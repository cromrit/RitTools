# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import json
import time
import zlib
import bpy
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ExportHelper
from .helpers import ensure_object_mode
from .zone import _scale_is_one
from .naming import proxy_body
from .presets import _cloth_mod, _cloth_plain_props, clamp_pressure_scale, reset_cloth_cache
from .manager import get_setup_proxy
from .panel import _fold_header
from .i18n import tr
from . import edition
from .report import report_error
_SCOPES = [('SCENE', 'Все в сцене', 'Все прокси с физикой разом: они сталкиваются с общими коллайдерами'), ('CHARACTER', 'Персонаж', 'Все прокси того же тела, что и выбранный в менеджере'), ('ACTIVE', 'Выбранный', 'Только прокси, выбранный в менеджере')]
_QUALITY_MULT = [('1', '×1', 'Как в настройках'), ('2', '×2', 'Качество Cloth ×2 только на время запекания — меньше проскоков, вдвое дольше'), ('4', '×4', 'Качество Cloth ×4 только на время запекания — для быстрых движений, вчетверо дольше')]
LONG_SHOT = 1000
_PAUSE_KEY = 'rct_phys_paused'
_BAKE_KEY = 'rct_bake'
_JOB = {}

def phys_proxies(context):
    out = []
    for it in context.scene.rct_proxies:
        o = it.obj_ptr
        if o and o.users_scene and (o.type == 'MESH') and _cloth_mod(o) and (o not in out):
            out.append(o)
    return out

def bake_targets(context):
    allp = phys_proxies(context)
    scope = context.scene.rct_bake_scope
    if scope == 'SCENE':
        return allp
    cur = get_setup_proxy(context)
    if cur not in allp:
        return []
    body = proxy_body(cur)
    if scope == 'CHARACTER' and body:
        return [o for o in allp if proxy_body(o) == body]
    return [cur]

def timeline_range(scn):
    if scn.use_preview_range:
        return (scn.frame_preview_start, scn.frame_preview_end)
    return (scn.frame_start, scn.frame_end)

def bake_range(scn):
    if not scn.rct_bake_timeline:
        return (scn.rct_bake_start, max(scn.rct_bake_end, scn.rct_bake_start + 1))
    return timeline_range(scn)

def _settings_snapshot(m):
    d = {}
    for part in ('settings', 'collision_settings'):
        st = getattr(m, part)
        for p in _cloth_plain_props(st):
            v = getattr(st, p)
            d[f'{part}.{p}'] = round(v, 6) if isinstance(v, float) else v
    return d

def _sig(scn, m):
    a, b = bake_range(scn)
    raw = json.dumps([a, b, scn.rct_bake_preroll, _settings_snapshot(m)], sort_keys=True).encode()
    return zlib.crc32(raw) & 2147483647

def _take_info(obj, pc):
    return (obj.get(_BAKE_KEY) or {}).get(pc.name) or {}

def proxy_state(scn, obj):
    m = _cloth_mod(obj)
    pc = m.point_cache
    if pc.is_baking:
        return 'BAKING'
    if not pc.is_baked:
        return 'NONE'
    info = _take_info(obj, pc)
    if info.get('sig') != _sig(scn, m):
        return 'OTHER'
    return 'OK'

def summary(context, targets):
    scn = context.scene
    states = [proxy_state(scn, o) for o in targets]
    paused = [o for o in targets if o.get(_PAUSE_KEY)]
    rng = None
    for o in targets:
        pc = _cloth_mod(o).point_cache
        if pc.is_baked:
            rng = _take_info(o, pc).get('range') or (pc.frame_start, pc.frame_end)
            break
    return (states, paused, rng)

def _header_status(context, targets):
    if not targets:
        return (tr('нет физики'), False)
    states, paused, rng = summary(context, targets)
    pre = '⏸ ' if paused else ''
    if 'BAKING' in states:
        return (pre + tr('запекается…'), False)
    if all((s == 'NONE' for s in states)):
        return (pre + tr('не запечено'), False)
    a, b = rng
    if all((s == 'OK' for s in states)):
        return (pre + tr('запечено ') + f'{a}–{b} ✓', False)
    return (pre + tr('устарело — перезапеките'), True)

def bake_problems(context, targets):
    scn = context.scene
    out = []
    a, b = bake_range(scn)
    if not targets:
        out.append(('ERROR', 'Нет прокси с физикой — сначала «Применить физику»'))
        return out
    if b - a < 1:
        out.append(('ERROR', 'Диапазон меньше двух кадров'))
    if context.mode != 'OBJECT':
        out.append(('INFO', 'Сейчас режим редактирования — перед запеканием выйду в Object Mode сам'))
    bad = [o.name for o in targets if not _scale_is_one(o.matrix_world)]
    if bad:
        out.append(('WARNING', tr('Масштаб прокси не применён (физика будет другой): ') + ', '.join(bad[:3])))
    stale = [o for o in targets if not _cloth_mod(o).point_cache.is_baked and _cloth_mod(o).point_cache.frame_start != scn.frame_start]
    if stale:
        out.append(('WARNING', 'Кэш начинается не с начала сцены — вживую физика не считается'))
    if any((o.get(_PAUSE_KEY) for o in targets)):
        out.append(('INFO', 'Физика на паузе — при запекании включится сама'))
    disk = any((_cloth_mod(o).point_cache.use_disk_cache for o in targets))
    if not bpy.data.filepath:
        out.append(('ERROR' if disk else 'WARNING', 'Файл ещё не сохранён — если Blender вылетит при запекании, работа пропадёт'))
    if not disk and b - a + scn.rct_bake_preroll > LONG_SHOT:
        out.append(('INFO', 'Длинный шот: кэш в памяти раздует .blend — лучше «Кэш на диск»'))
    return out

def _all_scene_caches(scn):
    out = []
    for o in scn.objects:
        for m in o.modifiers:
            if m.type in ('CLOTH', 'SOFT_BODY'):
                out.append((o, m, m.point_cache))
        for ps in getattr(o, 'particle_systems', ()):
            out.append((o, None, ps.point_cache))
    rbw = scn.rigidbody_world
    if rbw and rbw.point_cache:
        out.append((scn, None, rbw.point_cache))
    return out

def _free_cache(pc):
    wm = bpy.context.window_manager
    win = bpy.context.window or (wm.windows[0] if wm.windows else None)
    kw = {'window': win} if win else {}
    with bpy.context.temp_override(point_cache=pc, **kw):
        bpy.ops.ptcache.free_bake()

def set_live_range(context, m):
    pc = m.point_cache
    if not pc.is_baked:
        pc.frame_start = context.scene.frame_start
        pc.frame_end = context.scene.frame_end
_LIVE_SEEN = {}

@persistent
def _live_guard(scn, depsgraph=None):
    if _JOB:
        return
    for o in scn.objects:
        if o.type != 'MESH' or not o.get('rct_type'):
            continue
        m = _cloth_mod(o)
        if not m:
            continue
        pc = m.point_cache
        if pc.is_baked or pc.is_baking:
            continue
        if pc.frame_start != scn.frame_start:
            pc.frame_start = scn.frame_start
        if pc.frame_end < scn.frame_end:
            pc.frame_end = scn.frame_end
        s = m.settings
        key = (len(o.data.vertices), s.mass, s.quality, s.pressure_factor, s.use_pressure)
        if _LIVE_SEEN.get(o.as_pointer()) != key:
            clamp_pressure_scale(o)
            _LIVE_SEEN[o.as_pointer()] = (len(o.data.vertices), s.mass, s.quality, s.pressure_factor, s.use_pressure)

def free_targets(context, targets):
    for o in targets:
        m = _cloth_mod(o)
        name = m.point_cache.name
        reset_cloth_cache(context, m)
        d = o.get(_BAKE_KEY)
        if d and name in d:
            del d[name]

def start_bake(context, targets, rebake=False):
    scn = context.scene
    ensure_object_mode(context)
    if scn.rct_bake_save and bpy.data.filepath and bpy.data.is_dirty:
        bpy.ops.wm.save_mainfile()
    if rebake:
        free_targets(context, targets)
    a, b = bake_range(scn)
    mult = 1
    job = {'targets': [o.name for o in targets], 'quality': {}, 'hidden': [], 'start': a, 't0': time.time(), 'seen': False}
    for o in targets:
        m = _cloth_mod(o)
        if o.get(_PAUSE_KEY):
            m.show_viewport = True
            del o[_PAUSE_KEY]
        pc = m.point_cache
        if pc.is_baked:
            continue
        pc.frame_start = a - scn.rct_bake_preroll
        pc.frame_end = b
        d = o.get(_BAKE_KEY)
        if d is None:
            o[_BAKE_KEY] = {}
            d = o[_BAKE_KEY]
        d[pc.name] = {'sig': _sig(scn, m), 'set': json.dumps(_settings_snapshot(m)), 'range': [a, b]}
        if mult > 1:
            job['quality'][o.name] = m.settings.quality
            m.settings.quality = m.settings.quality * mult
    tset = set(targets)
    job['was_baked'] = [(o.name, getattr(mm, 'name', None), i) for i, (o, mm, pc) in enumerate(_all_scene_caches(scn)) if pc.is_baked]
    for o, m, pc in _all_scene_caches(scn):
        if m is not None and o not in tset and (not pc.is_baked) and m.show_viewport:
            m.show_viewport = False
            job['hidden'].append((o.name, m.name))
    _JOB.clear()
    _JOB.update(job)
    if bpy.app.background or not context.window:
        bpy.ops.ptcache.bake_all(bake=True)
        return finish_bake(bpy.context)
    bpy.ops.ptcache.bake_all('INVOKE_DEFAULT', bake=True)
    if not bpy.app.timers.is_registered(_poll_bake):
        bpy.app.timers.register(_poll_bake, first_interval=0.3)
    return 'RUNNING'

def _job_caches():
    out = []
    for n in _JOB.get('targets', ()):
        o = bpy.data.objects.get(n)
        m = _cloth_mod(o)
        if m:
            out.append(m.point_cache)
    return out

def _poll_bake():
    if not _JOB:
        return None
    baking = any((pc.is_baking for pc in _job_caches()))
    if baking:
        _JOB['seen'] = True
        return 0.3
    if not _JOB['seen'] and time.time() - _JOB['t0'] < 5.0 and (not all((pc.is_baked for pc in _job_caches()))):
        return 0.3
    finish_bake(bpy.context)
    return None

def finish_bake(context):
    scn = context.scene
    job = dict(_JOB)
    _JOB.clear()
    for n, q in job.get('quality', {}).items():
        m = _cloth_mod(bpy.data.objects.get(n))
        if m:
            m.settings.quality = q
    was = {(o, mm) for o, mm, _i in job.get('was_baked', ())}
    tnames = set(job.get('targets', ()))
    for o, m, pc in _all_scene_caches(scn):
        key = (o.name, getattr(m, 'name', None))
        if o.name not in tnames and key not in was and pc.is_baked:
            try:
                _free_cache(pc)
            except Exception:
                pass
    for on, mn in job.get('hidden', ()):
        o = bpy.data.objects.get(on)
        m = o.modifiers.get(mn) if o else None
        if m:
            m.show_viewport = True
    ok = True
    for n in tnames:
        o = bpy.data.objects.get(n)
        m = _cloth_mod(o)
        if m and (not m.point_cache.is_baked):
            ok = False
            set_live_range(context, m)
            d = o.get(_BAKE_KEY)
            if d and m.point_cache.name in d:
                del d[m.point_cache.name]
    if 'start' in job:
        scn.frame_set(job['start'])
    for area in getattr(context.screen, 'areas', ()):
        area.tag_redraw()
    return 'DONE' if ok else 'CANCELLED'

class OBJECT_OT_RitCromBake(bpy.types.Operator):
    bl_idname = 'object.rct_bake'
    bl_label = 'Запечь'
    bl_description = 'Просчитать физику прокси на весь диапазон и сохранить: проигрывание и рендер идут без пересчёта. Прогресс — внизу окна, Esc — отмена'
    bl_options = {'REGISTER'}
    rebake: bpy.props.BoolProperty(name='Перезапечь', default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        if _JOB:
            self.report({'WARNING'}, tr('Запекание уже идёт'))
            return {'CANCELLED'}
        targets = bake_targets(context)
        errs = [t for lvl, t in bake_problems(context, targets) if lvl == 'ERROR' and (not t.startswith('Файл'))]
        if errs:
            report_error(self, tr(errs[0]))
            return {'CANCELLED'}
        try:
            r = start_bake(context, targets, rebake=self.rebake)
        except Exception as e:
            finish_bake(context)
            report_error(self, tr('Запекание не удалось: ') + str(e))
            return {'CANCELLED'}
        if r == 'CANCELLED':
            self.report({'WARNING'}, tr('Запекание отменено'))
        elif r == 'DONE':
            self.report({'INFO'}, tr('Запечено прокси: ') + str(len(targets)))
        return {'FINISHED'}

class OBJECT_OT_RitCromBakeFree(bpy.types.Operator):
    bl_idname = 'object.rct_bake_free'
    bl_label = 'Удалить запекание'
    bl_description = 'Стереть запечённую физику — прокси снова считается на лету при проигрывании'
    bl_options = {'REGISTER'}

    def execute(self, context):
        targets = bake_targets(context)
        if not targets:
            self.report({'WARNING'}, tr('Нет прокси с физикой'))
            return {'CANCELLED'}
        free_targets(context, targets)
        return {'FINISHED'}

class OBJECT_OT_RitCromBakePause(bpy.types.Operator):
    bl_idname = 'object.rct_bake_pause'
    bl_label = 'Пауза физики'
    bl_description = 'Выключить физику во вьюпорте, пока ставите позы — анимация не тормозит, тело просто следует за скелетом. Нажмите ещё раз, чтобы включить. На рендер не влияет'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = bake_targets(context)
        if not targets:
            self.report({'WARNING'}, tr('Нет прокси с физикой'))
            return {'CANCELLED'}
        if any((o.get(_PAUSE_KEY) for o in targets)):
            for o in targets:
                if o.get(_PAUSE_KEY):
                    _cloth_mod(o).show_viewport = True
                    del o[_PAUSE_KEY]
        else:
            for o in targets:
                m = _cloth_mod(o)
                if m.show_viewport:
                    m.show_viewport = False
                    o[_PAUSE_KEY] = True
        return {'FINISHED'}

def _take_names(obj):
    return [c.name for c in _cloth_mod(obj).point_cache.point_caches]

class OBJECT_OT_RitCromBakeTakeAdd(bpy.types.Operator):
    bl_idname = 'object.rct_bake_take_add'
    bl_label = 'Новый дубль'
    bl_description = 'Добавить пустой дубль запекания: прошлый сохранится, его можно включить обратно и сравнить. Меняйте настройки и запекайте новый'
    bl_options = {'REGISTER'}

class OBJECT_OT_RitCromBakeTakeSet(bpy.types.Operator):
    bl_idname = 'object.rct_bake_take_set'
    bl_label = 'Включить дубль'
    bl_description = 'Проигрывать этот дубль запекания'
    bl_options = {'REGISTER'}
    name: bpy.props.StringProperty(options={'SKIP_SAVE'})

class OBJECT_OT_RitCromBakeTakeRemove(bpy.types.Operator):
    bl_idname = 'object.rct_bake_take_remove'
    bl_label = 'Удалить дубль'
    bl_description = 'Удалить включённый дубль (последний оставшийся не удаляется)'
    bl_options = {'REGISTER'}

class OBJECT_OT_RitCromBakeTakeSettings(bpy.types.Operator):
    bl_idname = 'object.rct_bake_take_settings'
    bl_label = 'Взять настройки дубля'
    bl_description = 'Вернуть в Cloth настройки, с которыми запечён включённый дубль — понравился старый вариант, берёте его значения'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromBakeDisk(bpy.types.Operator):
    bl_idname = 'object.rct_bake_disk'
    bl_label = 'Кэш на диск'
    bl_description = 'Хранить запекание в папке blendcache_ рядом с .blend, а не внутри файла: для длинных шотов и рендер-фермы. Нужен сохранённый файл'
    bl_options = {'REGISTER'}

class OBJECT_OT_RitCromBakeExportAbc(bpy.types.Operator, ExportHelper):
    bl_idname = 'object.rct_bake_export_abc'
    bl_label = 'Экспорт Alembic'
    bl_description = 'Сохранить движение тела с физикой в .abc — для другой программы, игрового движка или чтобы отдать файл без аддона. Сначала запеките'
    bl_options = {'REGISTER'}
    filename_ext = '.abc'
    filter_glob: bpy.props.StringProperty(default='*.abc', options={'HIDDEN'})

def draw_bake_block(box, context):
    scn = context.scene
    targets = bake_targets(context)
    is_open, row = _fold_header(box, scn, 'rct_ui_bake_open', 'Запекание анимации', 'RENDER_ANIMATION')
    text, alert = _header_status(context, targets)
    sub = row.row()
    sub.alignment = 'RIGHT'
    sub.alert = alert
    sub.label(text=text, translate=False)
    if not is_open:
        return
    c = box.column()
    c.row().prop(scn, 'rct_bake_scope', expand=True)
    col = c.column(align=True)
    col.prop(scn, 'rct_bake_timeline')
    r = col.row(align=True)
    if scn.rct_bake_timeline:
        r.enabled = False
        pre = 'frame_preview_' if scn.use_preview_range else 'frame_'
        r.prop(scn, pre + 'start', text=tr('С'), translate=False)
        r.prop(scn, pre + 'end', text=tr('По'), translate=False)
    else:
        r.prop(scn, 'rct_bake_start')
        r.prop(scn, 'rct_bake_end')
    col.prop(scn, 'rct_bake_preroll')
    r = col.row(align=True)
    r.active = False
    r.label(text='Качество для финала:', icon='LOCKED')
    r.prop(scn, 'rct_bake_quality', expand=True)
    for lvl, t in bake_problems(context, targets):
        w = c.row()
        w.alert = lvl == 'ERROR'
        w.label(text=tr(t), translate=False, icon={'ERROR': 'ERROR', 'WARNING': 'ERROR'}.get(lvl, 'INFO'))
        if t.startswith('Файл ещё не сохранён'):
            w.operator('wm.save_as_mainfile', text='', icon='FILE_TICK')
        elif t.startswith('Кэш начинается'):
            w.operator('object.rct_bake_free', text='', icon='FILE_REFRESH')
    if bpy.data.filepath:
        c.prop(scn, 'rct_bake_save')
    if not targets:
        return
    states, paused, _rng = summary(context, targets)
    r = c.row(align=True)
    r.scale_y = 1.4
    if all((s == 'NONE' for s in states)):
        r.operator('object.rct_bake', icon='RENDER_ANIMATION', text='Запечь')
    else:
        if 'NONE' in states:
            r.operator('object.rct_bake', icon='RENDER_ANIMATION', text='Допечь')
        r.operator('object.rct_bake', icon='FILE_REFRESH', text='Перезапечь').rebake = True
        r.operator('object.rct_bake_free', icon='TRASH', text='')
    c.operator('object.rct_bake_pause', icon='PLAY' if paused else 'PAUSE', text='Включить физику' if paused else 'Пауза физики', depress=bool(paused))
    t = box.box()
    t.label(text='Дубли запекания', icon='DUPLICATE')
    first = targets[0]
    m = _cloth_mod(first)
    names = _take_names(first)
    rr = t.row(align=True)
    if len(names) > 1:
        for i, n in enumerate(names):
            op = rr.operator('object.rct_bake_take_set', text=n or tr('Дубль ') + '1', translate=False, depress=i == m.point_cache.point_caches.active_index)
            op.name = n
        rr.operator('object.rct_bake_take_remove', text='', icon='REMOVE')
    rr.operator('object.rct_bake_take_add', text='' if len(names) > 1 else 'Новый дубль', icon='ADD')
    if len(names) > 1:
        if proxy_state(scn, first) == 'OTHER':
            t.label(text='Этот дубль запечён с другими настройками', icon='INFO')
        t.operator('object.rct_bake_take_settings', icon='IMPORT')
    r = box.row(align=True)
    disk = m.point_cache.use_disk_cache
    r.operator('object.rct_bake_disk', icon='CHECKBOX_HLT' if disk else 'CHECKBOX_DEHLT', emboss=False)
    r.operator('object.rct_bake_export_abc', icon='EXPORT')
bake_classes = (OBJECT_OT_RitCromBake, OBJECT_OT_RitCromBakeFree, OBJECT_OT_RitCromBakePause, OBJECT_OT_RitCromBakeTakeAdd, OBJECT_OT_RitCromBakeTakeSet, OBJECT_OT_RitCromBakeTakeRemove, OBJECT_OT_RitCromBakeTakeSettings, OBJECT_OT_RitCromBakeDisk, OBJECT_OT_RitCromBakeExportAbc)

def _timeline_toggled(scn, _context):
    if not scn.rct_bake_timeline:
        scn.rct_bake_start, scn.rct_bake_end = timeline_range(scn)
_SCENE_PROPS = ('rct_ui_bake_open', 'rct_bake_scope', 'rct_bake_timeline', 'rct_bake_start', 'rct_bake_end', 'rct_bake_preroll', 'rct_bake_quality', 'rct_bake_save')

def register_bake_props():
    S = bpy.types.Scene
    S.rct_ui_bake_open = bpy.props.BoolProperty(name='Запекание анимации', default=False)
    S.rct_bake_scope = bpy.props.EnumProperty(name='Что запекать', items=_SCOPES, default='SCENE')
    S.rct_bake_timeline = bpy.props.BoolProperty(name='Запекать на длину таймлайна', default=True, update=_timeline_toggled, description='Кадры берутся с таймлайна сами (90, 360 — сколько стоит; Preview Range, если включён). Выключите, чтобы задать свои С и По')
    S.rct_bake_start = bpy.props.IntProperty(name='С', default=1)
    S.rct_bake_end = bpy.props.IntProperty(name='По', default=250)
    S.rct_bake_preroll = bpy.props.IntProperty(name='Разгон, кадров', default=20, min=0, soft_max=100, description='Симуляция начинается раньше анимации: к первому кадру грудь уже успокоилась и не падает из позы покоя. 0 — без разгона')
    S.rct_bake_quality = bpy.props.EnumProperty(name='Качество для финала', items=_QUALITY_MULT, default='1')
    S.rct_bake_save = bpy.props.BoolProperty(name='Сохранять файл перед запеканием', default=True, description='Запекание может уронить Blender — файл сохранится до начала')
    if _live_guard not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(_live_guard)

def unregister_bake_props():
    if bpy.app.timers.is_registered(_poll_bake):
        bpy.app.timers.unregister(_poll_bake)
    for h in [h for h in bpy.app.handlers.frame_change_pre if getattr(h, '__name__', '') == '_live_guard']:
        bpy.app.handlers.frame_change_pre.remove(h)
    for p in _SCENE_PROPS:
        try:
            delattr(bpy.types.Scene, p)
        except AttributeError:
            pass
