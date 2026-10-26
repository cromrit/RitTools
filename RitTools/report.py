# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import datetime
import os
import platform
import traceback
from collections import deque
import bpy
from .i18n import tr
ERRORS = deque(maxlen=10)
ACTIONS = deque(maxlen=40)

def _now():
    return datetime.datetime.now().strftime('%H:%M:%S')

def _short_tb():
    out = []
    for line in traceback.format_exc().splitlines():
        m = line.find('File "')
        if m >= 0:
            q = line.find('"', m + 6)
            path = line[m + 6:q]
            i = path.rfind('RitTools' + os.sep)
            line = line[:m + 6] + (path[i:] if i >= 0 else os.path.basename(path)) + line[q:]
        out.append(line)
    return '\n'.join(out)

def note_error(where, text):
    if ERRORS and ERRORS[-1][1:] == (where, text):
        return
    ERRORS.append((_now(), where, text))
    for a in bpy.context.window_manager.windows if bpy.context.window_manager else ():
        for ar in a.screen.areas:
            if ar.type == 'VIEW_3D':
                ar.tag_redraw()

def _wrap(fn, idname):

    def call(self, context, *ev):
        try:
            r = fn(self, context, *ev)
        except Exception:
            note_error(idname, _short_tb())
            raise
        if r not in ({'RUNNING_MODAL'}, {'PASS_THROUGH'}):
            ACTIONS.append((_now(), idname, ','.join(sorted(r)) if isinstance(r, set) else str(r)))
        return r
    if fn.__name__ == 'execute' or fn.__code__.co_argcount == 2:
        w = lambda self, context: call(self, context)
    else:
        w = lambda self, context, event: call(self, context, event)
    w._rct_wrapped = True
    return w

def report_error(op, message):
    op.report({'ERROR'}, message)
    import sys
    tb = '\n' + _short_tb() if sys.exc_info()[0] else ''
    note_error(getattr(type(op), 'bl_idname', '?'), str(message) + tb)

def instrument(classes):
    for cls in classes:
        if issubclass(cls, bpy.types.Operator):
            for name in ('execute', 'invoke', 'modal'):
                fn = cls.__dict__.get(name)
                if fn and (not getattr(fn, '_rct_wrapped', False)):
                    setattr(cls, name, _wrap(fn, cls.bl_idname))
        elif issubclass(cls, bpy.types.Panel) and 'draw' in cls.__dict__ and (not getattr(cls.draw, '_rct_wrapped', False)):
            cls.draw = _wrap_draw(cls.draw, cls.__name__)

def _wrap_draw(draw, name):

    def w(self, context):
        try:
            draw(self, context)
        except Exception:
            note_error(name + '.draw', _short_tb())
            raise
    w._rct_wrapped = True
    return w

def _val(v):
    if isinstance(v, bpy.types.ID):
        return v.name
    if hasattr(v, '__len__') and (not isinstance(v, str)):
        try:
            return '(' + ', '.join((f'{x:.4g}' if isinstance(x, float) else str(x) for x in v)) + ')'
        except TypeError:
            pass
    return f'{v:.4g}' if isinstance(v, float) else str(v)
_MOD_SKIP = {'rna_type', 'name', 'type', 'show_viewport', 'show_render', 'show_in_editmode', 'show_on_cage', 'show_expanded', 'is_active', 'use_pin_to_last', 'is_override_data', 'use_apply_on_spline', 'execution_time', 'persistent_uid', 'is_bound'}

def _rna_props(data, skip=()):
    out = []
    for p in data.bl_rna.properties:
        k = p.identifier
        if k in _MOD_SKIP or k in skip or (p.type in ('POINTER', 'COLLECTION') and k not in ('vertex_group_mass',)):
            continue
        try:
            out.append(f'{k}={_val(getattr(data, k))}')
        except Exception:
            pass
    return ', '.join(out)

def _obj_lines(ob, L):
    from .naming import get_proxy_type, proxy_body
    L.append(f"  [{ob.name}] type={ob.type} rct_type={get_proxy_type(ob)} parent={(ob.parent.name if ob.parent else '-')} hide={ob.hide_get()} body={(_val(proxy_body(ob)) if ob.type == 'MESH' else '-')}")
    if ob.type == 'MESH':
        me = ob.data
        L.append(f'    mesh: v={len(me.vertices)} e={len(me.edges)} f={len(me.polygons)} scale={_val(ob.scale)}')
        L.append('    groups: ' + ', '.join((g.name for g in ob.vertex_groups)))
        L.append('    attrs: ' + ', '.join((a.name for a in me.attributes if not a.name.startswith('.'))))
    keys = [k for k in ob.keys() if k.startswith('rct')]
    if keys:
        L.append('    props: ' + ', '.join((f'{k}={str(ob[k])[:60]}' for k in keys)))
    for m in ob.modifiers:
        L.append(f'    mod {m.type} «{m.name}» view={m.show_viewport} render={m.show_render}')
        if m.type == 'CLOTH':
            L.append('      settings: ' + _rna_props(m.settings, skip=('effector_weights',)))
            L.append('      collision: ' + _rna_props(m.collision_settings))
            pc = m.point_cache
            L.append(f'      cache: {pc.frame_start}-{pc.frame_end} baked={pc.is_baked}')
        elif m.type in ('SURFACE_DEFORM', 'SHRINKWRAP', 'DATA_TRANSFER', 'ARMATURE', 'VERTEX_WEIGHT_PROXIMITY', 'VERTEX_WEIGHT_EDIT', 'VERTEX_WEIGHT_MIX', 'CORRECTIVE_SMOOTH', 'SMOOTH', 'COLLISION'):
            L.append('      ' + _rna_props(m)[:600])

def build_report(context):
    from . import bl_info
    from .edition import edition_name
    from .manager import get_setup_proxy
    from .panel import fine_tune_problems
    scn = context.scene
    L = ['RitTools — отчёт для разработчика (отправьте файл в Discord вместе со скриншотом)', f'Время: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}', f"RitTools: {edition_name()} {'.'.join(map(str, bl_info['version']))}", f'Blender: {bpy.app.version_string} ({(bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else bpy.app.build_hash)})', f'Система: {platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}', f"Файл: {os.path.basename(bpy.data.filepath) or '(не сохранён)'}", f'Язык интерфейса: {bpy.context.preferences.view.language}', '']
    L.append(f'== Ошибки ({len(ERRORS)})')
    for t, where, text in ERRORS:
        L += [f'-- {t} {where}', text, '']
    if not ERRORS:
        L.append('(ошибок не поймано)\n')
    L.append('== Последние действия')
    L += [f'  {t} {op} -> {r}' for t, op, r in ACTIONS] or ['  (нет)']
    L.append('')
    ob = context.object
    L.append('== Состояние')
    L.append(f'  mode={context.mode} frame={scn.frame_current} ({scn.frame_start}-{scn.frame_end}) fps={scn.render.fps} unit_scale={scn.unit_settings.scale_length:.4g}')
    L.append(f"  active={(ob.name if ob else '-')} selected={[o.name for o in context.selected_objects][:20]}")
    if ob and ob.type == 'MESH' and (ob.mode == 'EDIT'):
        me = ob.data
        me.update_from_editmode() if hasattr(me, 'update_from_editmode') else None
        L.append(f'  выделено вершин: {sum((v.select for v in me.vertices))} из {len(me.vertices)}')
    L.append('  scene: ' + ', '.join((f'{k}={_val(getattr(scn, k))}' for k in sorted(dir(scn)) if k.startswith(('rct_', 'proxy_', 'hair_', 'hook_', 'shrink_')) and (not callable(getattr(scn, k, None))) and (k not in ('rct_proxies',)))))
    L.append('')
    sp = get_setup_proxy(context)
    L.append(f"== Прокси (выбран в менеджере: {(sp.name if sp else '-')})")
    for it in scn.rct_proxies:
        o = it.obj_ptr
        if o:
            _obj_lines(o, L)
            try:
                p = fine_tune_problems(context, o)
                if p:
                    L.append(f'    тонкая настройка, ошибки: {p}')
            except Exception as e:
                L.append(f'    fine_tune_problems: {e!r}')
    seen = {it.obj_ptr for it in scn.rct_proxies}
    bodies = {scn.proxy_original_body, scn.proxy_main_mesh} - {None} - seen
    if bodies:
        L.append('== Тело')
        for b in bodies:
            _obj_lines(b, L)
    return '\n'.join(L) + '\n'

class OBJECT_OT_RitCromSaveReport(bpy.types.Operator):
    bl_idname = 'object.rct_save_report'
    bl_label = 'Сохранить отчёт'
    bl_description = 'Сохранить файл с ошибками и настройками сцены — отправьте его в Discord, так мы быстрее поймём, что сломалось'
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default='*.txt', options={'HIDDEN'})

    def invoke(self, context, event):
        d = os.path.dirname(bpy.data.filepath) or os.path.expanduser('~')
        self.filepath = os.path.join(d, f'RitTools_report_{datetime.datetime.now():%Y%m%d_%H%M}.txt')
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            text = build_report(context)
        except Exception:
            text = 'build_report упал:\n' + traceback.format_exc()
            text += '\n\n== Ошибки\n' + '\n\n'.join((f'{t} {w}\n{x}' for t, w, x in ERRORS))
        path = bpy.path.ensure_ext(bpy.path.abspath(self.filepath), '.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        self.report({'INFO'}, tr('Отчёт сохранён: ') + path)
        return {'FINISHED'}

class OBJECT_OT_RitCromDismissErrors(bpy.types.Operator):
    bl_idname = 'object.rct_dismiss_errors'
    bl_label = 'Скрыть'
    bl_description = 'Убрать сообщение об ошибке (в отчёт она всё равно попадёт, пока Blender открыт)'

    def execute(self, context):
        _SEEN[0] = ERRORS[-1] if ERRORS else None
        return {'FINISHED'}
_SEEN = [None]

def errors_unseen():
    return bool(ERRORS) and _SEEN[0] is not ERRORS[-1]

def draw_error_box(layout, context):
    if not errors_unseen():
        return
    from .edition import URL_DISCORD
    b = layout.box()
    c = b.column(align=True)
    c.alert = True
    c.label(text='Произошла ошибка', icon='ERROR')
    last = ERRORS[-1][2].strip().splitlines()[-1][:60]
    c.label(text=last, translate=False)
    b.label(text='Сохраните отчёт и отправьте в Discord')
    b.operator('object.rct_save_report', icon='FILE_TEXT')
    r = b.row(align=True)
    r.operator('wm.url_open', text=tr('Discord'), icon='COMMUNITY').url = URL_DISCORD
    r.operator('object.rct_dismiss_errors', text='', icon='X')
