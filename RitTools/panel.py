# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import time
from .helpers import ensure_object_mode, fit_session_alive, set_active_mode
from .zone import apply_pin_from_cast_distance, apply_pin_from_edge_distance, CAST_DIST_ATTR, EDGE_DIST_ATTR, recompute_zone_mask, zone_body_changed, ZONE_BODY_CHANGED_MSG
from .mesh_utils import find_surface_deform, vertex_group_has_weights
from .naming import addon_created, get_proxy_type, proxy_body, PROXY_TYPES
from .presets import _cloth_mod, breast_auto_applied, CLOTH_PRO_FIELDS, CLOTH_QUICK_BY_TYPE, DEFAULT_PRESET, draw_ps_limited, draw_shelf_fields, mirror_cloth_diff, mirror_partners, PRESETS, reset_cloth_cache
from .manager import detect_proxy_part, get_setup_proxy, NO_SURFDEF_PARTS, proxy_entry_is_dead
from .bind import triangulate_above_cloth
from .hooks_ui import draw_hooks_tab, draw_shrinkwrap_block
from .clothing import draw_clothing_tab, draw_collision_warning
from .colliders import _BodyWeights, _collider_body_and_arm, _finish_colliders, _RestPose, _scene_proxies, classify_skeleton, OBJECT_OT_RitCromCollidersFromSkeleton, backwall_of, build_backwall, remove_backwall, remove_colliders
from .i18n import draw_language_switch, enum_default, enum_items, tr, wrap
from . import edition
from .edition import beta, draw_beta_banner, draw_dev_banner, draw_full_version_links, draw_pro_banner

def _step_header(layout, num, text, icon, done=None):
    row = layout.row()
    mark = '  ✓' if done else ''
    row.label(text=f'{num}. {tr(text)}{mark}', translate=False, icon=icon)
    return row

def _wrap_text(text, width):
    lines, cur = ([], '')
    for word in tr(str(text)).split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f'{cur} {word}'.strip()
    return lines + ([cur] if cur else [])
_PART_LABELS = {'TitsPhys': 'Грудь', 'AssPhys': 'Ягодицы', 'ThighsPhys': 'Бёдра', 'HAIR': 'Волосы', 'HANDS': 'Руки'}
_UI_TABS = [('PROXY', 'Прокси', 'Создание и настройка прокси', 'MESH_UVSPHERE', 0), ('HOOKS', 'Хуки', 'Зацепы прокси за кости', 'HOOK', 1), ('CLOTHING', 'Одежда', 'Динамика одежды', 'MOD_CLOTH', 2), ('MORE', 'Ещё', 'Коллизии, советы, прочее', 'PREFERENCES', 3)]
_UI_FILTERS = [('ALL', 'Все', 'Показать всё'), ('PROXY', 'Прокси', 'Только прокси тела и волос'), ('CLOTHING', 'Одежда', 'Только одежда'), ('COLLISION', 'Коллайдеры', 'Только коллайдеры')]

def proxy_kind_label(obj):
    ptype = get_proxy_type(obj)
    label, icon = PROXY_TYPES.get(ptype, ('?', 'QUESTION'))
    if ptype in ('VOLUME', 'SURFACE', 'HAIR'):
        label = _PART_LABELS.get(detect_proxy_part(obj), label)
    return (label, icon)

def _proxy_filter_ok(obj, flt):
    if flt == 'ALL':
        return True
    ptype = get_proxy_type(obj)
    if flt == 'PROXY':
        return ptype not in ('CLOTHING', 'COLLISION')
    return ptype == flt

def _fold_header(layout, scn, prop, text, icon='NONE', alert=False):
    row = layout.row(align=True)
    row.alert = alert
    is_open = getattr(scn, prop)
    row.prop(scn, prop, icon='TRIA_DOWN' if is_open else 'TRIA_RIGHT', icon_only=True, emboss=False)
    row.label(text=tr(text), translate=False, icon=icon)
    return (is_open, row)

def draw_proxy_manager(layout, context):
    scn = context.scene
    box = layout.box()
    proxy = get_setup_proxy(context)
    is_open, row = _fold_header(box, scn, 'rct_ui_mgr_open', 'Менеджер прокси', 'OUTLINER')
    if not is_open:
        sub = row.row()
        sub.alignment = 'RIGHT'
        if proxy:
            label, icon = proxy_kind_label(proxy)
            sub.label(text=f'{proxy.name}  ({tr(label)})', translate=False, icon=icon)
        else:
            sub.label(text='пусто')
        return
    box.row().prop(scn, 'rct_ui_filter', expand=True)
    box.template_list('RCT_UL_ProxyList', '', scn, 'rct_proxies', scn, 'rct_proxy_index', rows=4)
    row = box.row(align=True)
    row.operator('object.rct_proxy_remove', icon='REMOVE', text='Удалить выбранный')
    row.operator('object.rct_proxy_clear_all', icon='TRASH', text='Очистить всё')
    box.operator('object.rct_add_own_proxy', icon='ADD', text='Добавить свой прокси')

def _big(layout, op, icon, text):
    r = layout.row()
    r.scale_y = 1.5
    return r.operator(op, icon=icon, text=tr(text), translate=False)
_SHOP_TABS = {'MORE': (lambda: beta('Ещё'), None), 'CLOTHING': (lambda: tr('Одежда'), 'TIME'), 'HAIR': (lambda: beta('Волосы'), None)}

def _enum_tabs(row, data, prop, paid):
    r = row.row(align=True)
    for it in data.bl_rna.properties[prop].enum_items:
        text, icon = (tr(it.name), it.icon)
        if it.identifier in _SHOP_TABS:
            f, ic = _SHOP_TABS[it.identifier]
            text, icon = (f(), ic or icon)
        if True and it.identifier in paid and (it.identifier != 'CLOTHING'):
            icon = 'LOCKED'
        r.prop_enum(data, prop, it.identifier, text=text, translate=False, icon=icon)
_PRO_MODE_LINES = {'VERTEX': ('Прокси из любых вершин', 'Замена плотной сетки', 'Заплатка соска и пупка'), 'HAIR': ('Прокси волос по костям',)}
_PRO_TAB_LINES = {'HOOKS': ('Хуки: тянуть прокси костями',), 'CLOTHING': ('Динамика одежды',), 'MORE': ('Коллайдеры из скелета', 'Импакт, Shrinkwrap', 'Auto-Physics костей')}

def draw_create_block(layout, context):
    scn = context.scene
    box = layout.box()
    has_proxy = any((not proxy_entry_is_dead(it) for it in scn.rct_proxies))
    cube = scn.proxy_active_cube
    fitting_cube = bool(cube and scn.proxy_temp_cast)
    forced = not has_proxy or fitting_cube
    if forced:
        box.label(text='Создать прокси', icon='ADD')
    else:
        is_open, row = _fold_header(box, scn, 'rct_ui_create_open', 'Создать прокси', 'ADD')
        if not is_open:
            sub = row.row()
            sub.alignment = 'RIGHT'
            sub.label(text='+ ещё')
            return
    _enum_tabs(box.row(), scn, 'proxy_mode', {'VERTEX', 'HAIR'})
    locked = scn.proxy_mode != 'CUSTOM'
    if locked:
        draw_pro_banner(box, _PRO_MODE_LINES[scn.proxy_mode])
    elif scn.proxy_mode == 'HAIR':
        box.label(text='Бета-версия: пряди могут вести себя нестабильно', icon='EXPERIMENTAL')
    col = box.column(align=True)
    col.active = not locked
    if scn.proxy_mode == 'VERTEX':
        col.label(text='Выделите часть тела в Edit Mode и нажмите кнопку.', icon='INFO')
        r = col.row(align=True)
        r.prop(scn, 'rct_vertex_close_back')
        g = r.row(align=True)
        g.active = scn.rct_vertex_close_back
        g.prop(scn, 'rct_back_grid', text='Закрыть сеткой', icon='MESH_GRID', toggle=True)
        col.prop(scn, 'rct_auto_fix_mesh')
        if scn.rct_auto_fix_mesh:
            col.prop(scn, 'rct_dense_regions')
        col.separator()
        r = col.row(align=True)
        r.scale_y = 1.5
        r.operator('object.generate_vertex_proxy', icon='VERTEXSEL', text='Создать прокси')
        r.prop(scn, 'rct_vertex_mirror', icon='MOD_MIRROR')
        adv, _ = _fold_header(box, scn, 'rct_ui_create_adv', 'Дополнительно')
        if adv:
            a = box.column(align=True)
            a.active = not locked
            if scn.rct_vertex_close_back:
                a.prop(scn, 'rct_edge_pin_width')
            a.label(text='Скрипт сам: отделит сетку с ригом, закрепит края,', icon='NONE')
            a.label(text='нарисует зону влияния и привяжет к телу.')
            if scn.rct_vertex_close_back:
                a.label(text='Закрыт сзади: объём, можно надувать.', icon='MESH_UVSPHERE')
            else:
                a.label(text='Поверхность: без надутия (Pressure).', icon='MESH_GRID')
            if get_setup_proxy(context):
                a.separator()
                a.operator('object.rct_mirror_vertex_proxy', icon='MOD_MIRROR', text='Отзеркалить выбранный прокси')
                a.operator('object.rct_close_pit', icon='FACESEL', text='Закрыть углубление (выделенное)')
                a.operator('object.rct_flatten_bump', icon='SMOOTHCURVE', text='Выровнять выпуклость (устаревшее)')
    elif scn.proxy_mode == 'CUSTOM':
        fitting = bool(cube and cube.modifiers.get('Shrinkwrap') and scn.proxy_temp_cast)
        if not fitting_cube:
            col.label(text='Шаг 1: выделите полигоны части тела (Edit Mode).', icon='INFO')
            r = col.row(align=True)
            r.scale_y = 1.5
            r.operator('object.extract_and_create_proxy', icon='UV_ISLANDSEL', text='Создать прокси (слепок и куб)')
            r.prop(scn, 'proxy_apply_subdiv', text='Subdiv', icon='MOD_SUBSURF')
        elif not fitting:
            col.label(text='Шаг 2: двигайте точки куба (O включён),', icon='INFO')
            col.label(text='затем подгонка по форме тела.')
            _big(col, 'object.add_shrinkwrap_live', 'MOD_SHRINKWRAP', 'Подогнать по форме (Shrinkwrap)')
        else:
            col.label(text='Нравится, как облегает? Поправить — Tab,', icon='INFO')
            col.label(text='форма обновляется на лету. Затем:')
            r = col.row(align=True)
            r.scale_y = 1.5
            r.operator('object.apply_shrinkwrap_and_restore', icon='CHECKMARK', text='Готово: применить форму')
            r.prop(scn, 'rct_vertex_mirror', icon='MOD_MIRROR')
        if fitting_cube:
            col.operator('object.rct_cube_cancel', icon='CANCEL', text='Отменить куб')
        elif get_setup_proxy(context):
            col.operator('object.rct_mirror_vertex_proxy', icon='MOD_MIRROR', text='Отзеркалить выбранный прокси')
        adv, _ = _fold_header(box, scn, 'rct_ui_create_adv', 'Дополнительно')
        if adv:
            a = box.column(align=True)
            a.prop(scn, 'proxy_cube_subdiv', text='Уровень Subdiv')
            a.prop(scn, 'rct_pin_transition')
    elif scn.proxy_mode == 'HAIR':
        col.label(text='Выделите кости прядей (Edit/Pose Mode).', icon='INFO')
        col.prop(scn, 'rct_preset_hair', text='Пресет')
        col.separator()
        _big(col, 'object.generate_hair_proxy', 'OUTLINER_OB_CURVE', 'Создать прокси')
        adv, _ = _fold_header(box, scn, 'rct_ui_create_adv', 'Дополнительно')
        if adv:
            a = box.column(align=True)
            a.active = not locked
            a.prop(scn, 'hair_pin_root')
            a.prop(scn, 'hair_bending_stiffness', text='Начальная жесткость (Изгиб)')
            a.separator()
            a.label(text='Отмена привязки:', icon='ERROR')
            a.operator('object.clear_hair_bindings', icon='TRASH', text='Снять привязку с выделенных костей')
_PART_ITEMS = [('NONE', 'не определено', 'Часть тела не определена — выберите вручную', 'QUESTION', 0), ('TitsPhys', 'Грудь', '', 'NONE', 1), ('AssPhys', 'Ягодицы', '', 'NONE', 2), ('BellyPhys', 'Живот', '', 'NONE', 3), ('ThighsPhys', 'Бёдра', '', 'NONE', 4)]
_PART_INDEX = {k: i for k, _l, _d, _ic, i in _PART_ITEMS}

def _part_ui_get(self):
    return _PART_INDEX.get(detect_proxy_part(self), 0)
PART_PRESET = {'TitsPhys': 'BREAST', 'AssPhys': 'BUTT', 'ThighsPhys': 'THIGHS', 'BellyPhys': 'BELLY'}

def set_proxy_part(scn, obj, key):
    if key not in PART_PRESET:
        return
    if not obj.get('rct_part_manual') and addon_created(obj):
        obj['rct_created'] = True
    obj['rct_part'] = key
    obj['rct_part_manual'] = True
    pid = PART_PRESET[key]
    ptype = get_proxy_type(obj)
    if PRESETS[pid]['type'] == ptype:
        setattr(scn, f'rct_preset_{ptype.lower()}', pid)

def _part_ui_set(self, value):
    key = next((k for k, _l, _d, _ic, i in _PART_ITEMS if i == value))
    set_proxy_part(bpy.context.scene, self, key)

class OBJECT_OT_RitCromSetPart(bpy.types.Operator):
    bl_idname = 'object.rct_set_part'
    bl_label = 'Часть тела'
    bl_description = 'Сменить часть тела выбранного прокси: подставляется пресет этой части. Ягодицы — сразу строится опора снизу'
    bl_options = {'REGISTER', 'UNDO'}
    part: bpy.props.EnumProperty(items=enum_items([it for it in _PART_ITEMS if it[0] != 'NONE']), default=enum_default(_PART_ITEMS, 'TitsPhys'))

    def execute(self, context):
        scn = context.scene
        proxy = get_setup_proxy(context)
        if not proxy or get_proxy_type(proxy) not in ('VOLUME', 'SURFACE'):
            self.report({'WARNING'}, tr('Выберите прокси в менеджере'))
            return {'CANCELLED'}
        set_proxy_part(scn, proxy, self.part)
        if self.part == 'AssPhys':
            proxy.rct_support = True
            t = time.perf_counter()
            if _rebuild_support(context, proxy, self):
                self.report({'INFO'}, tr(f'Опора снизу построена за {time.perf_counter() - t:.2f} с'))
        return {'FINISHED'}

def fine_tune_problems(context, proxy):
    scn = context.scene
    probs = {}
    if not vertex_group_has_weights(proxy, 'Pin_Base'):
        auto = bool(proxy.data.attributes.get(CAST_DIST_ATTR) or proxy.data.attributes.get(EDGE_DIST_ATTR))
        probs[1] = ('Точка крепления пустая (Pin_Base) — прокси не держится за скелет', auto)
    if detect_proxy_part(proxy) in NO_SURFDEF_PARTS:
        return probs
    body = proxy_body(proxy) or scn.proxy_original_body or scn.proxy_main_mesh
    mod_surf = find_surface_deform(body, proxy) if body else None
    if not body:
        probs[2] = ('Не найдено тело — выберите «Тело» ниже и нажмите «Привязать»', False)
    elif not mod_surf:
        probs[2] = ('Нет привязки к телу (Surface Deform)', True)
    elif not mod_surf.is_bound:
        probs[2] = (proxy.get('rct_bind_fail') or 'Привязка не удалась (is_bound = False)', True)
    elif proxy.get('rct_bound_vcount') not in (None, len(proxy.data.vertices)):
        probs[2] = ('Сетка прокси изменилась после привязки — привяжите заново', True)
    elif triangulate_above_cloth(proxy):
        probs[2] = ('SurfDef_Triangulate выше Cloth — в стеке модификаторов прокси (Properties → Modifiers) перетащите SurfDef_Triangulate ниже Cloth', False)
    if body and mod_surf:
        mask = mod_surf.vertex_group or proxy.get('rct_mask', '')
        zone_auto = proxy.get('rct_zone_verts') is not None and (not zone_body_changed(proxy))
        if not mod_surf.vertex_group:
            probs[3] = ('Маски нет — за прокси двигается ВСЁ тело', zone_auto or bool(mask and vertex_group_has_weights(body, mask)))
        elif not vertex_group_has_weights(body, mask):
            probs[3] = ('Зона влияния пустая — тело не двигается за прокси', zone_auto)
        elif zone_body_changed(proxy):
            probs[3] = (ZONE_BODY_CHANGED_MSG, False)
    return probs

class OBJECT_OT_RitCromFixSetupStep(bpy.types.Operator):
    bl_idname = 'object.rct_fix_setup_step'
    bl_label = 'Исправить автоматически'
    bl_description = 'Повторить автоматический шаг для выбранного прокси без пересоздания: точка крепления — по форме прокси, зона влияния — из запомненного выделения тела'
    bl_options = {'REGISTER', 'UNDO'}
    step: bpy.props.IntProperty()

    def execute(self, context):
        proxy = get_setup_proxy(context)
        scn = context.scene
        if not proxy or proxy.type != 'MESH':
            self.report({'WARNING'}, tr('Выберите прокси в менеджере'))
            return {'CANCELLED'}
        ensure_object_mode(context)
        if self.step == 1:
            if proxy.data.attributes.get(CAST_DIST_ATTR):
                apply_pin_from_cast_distance(proxy, scn.rct_pin_transition)
            elif proxy.data.attributes.get(EDGE_DIST_ATTR):
                apply_pin_from_edge_distance(proxy, scn.rct_edge_pin_width)
            else:
                self.report({'WARNING'}, tr('Нет данных для авто-крепления — нарисуйте точку крепления вручную'))
                return {'CANCELLED'}
        elif self.step == 3:
            body = proxy_body(proxy)
            mod_surf = find_surface_deform(body, proxy) if body else None
            if not mod_surf:
                self.report({'WARNING'}, tr('Сначала привяжите прокси к телу'))
                return {'CANCELLED'}
            mask = proxy.get('rct_mask') or f'Mask_{proxy.name}'
            if not vertex_group_has_weights(body, mask):
                if not proxy.get('rct_mask'):
                    proxy['rct_mask'] = mask
                if mask not in body.vertex_groups:
                    body.vertex_groups.new(name=mask)
                if not recompute_zone_mask(proxy, scn.rct_zone_blur):
                    self.report({'WARNING'}, tr('Нет запомненного выделения тела — нарисуйте зону влияния вручную'))
                    return {'CANCELLED'}
            mod_surf.vertex_group = mask
        else:
            return {'CANCELLED'}
        left = fine_tune_problems(context, proxy).get(self.step)
        if left:
            self.report({'WARNING'}, tr(f'Не помогло: {left[0]}'))
        else:
            self.report({'INFO'}, tr('Исправлено'))
        return {'FINISHED'}

def rebuild_torso_collider(context, op):
    body, arm = _collider_body_and_arm(context, op)
    if not body:
        return False
    ensure_object_mode(context)
    remove_colliders(context, {'TORSO', 'SHOULDER', 'SHELF'})
    report = []
    with _RestPose(context, arm):
        kinds_map, info, warn = classify_skeleton(arm, body)
        report.extend(warn)
        bw = _BodyWeights(body, arm, kinds_map)
        bw.spine = info.get('spine_bones', set()) if info else set()
        created = OBJECT_OT_RitCromCollidersFromSkeleton._torso(context, arm, bw, report)
    set_active_mode(context, body, 'OBJECT')
    _finish_colliders(context, op, created, report)
    return True

class OBJECT_OT_RitCromToggleSupport(bpy.types.Operator):
    bl_idname = 'object.rct_toggle_support'
    bl_label = 'Опора снизу'
    bl_description = 'Включите для крупной груди или живота, если они провисают и плохо держатся. Полка строится сразу при включении и удаляется при выключении'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scn = context.scene
        proxy = get_setup_proxy(context)
        if not proxy or get_proxy_type(proxy) not in ('VOLUME', 'SURFACE'):
            self.report({'WARNING'}, tr('Выберите прокси в менеджере'))
            return {'CANCELLED'}
        proxy.rct_support = not proxy.rct_support
        t = time.perf_counter()
        if _rebuild_support(context, proxy, self):
            self.report({'INFO'}, tr(f'Коллайдер тела пересобран за {time.perf_counter() - t:.2f} с'))
        return {'FINISHED'}

class OBJECT_OT_RitCromToggleJerkGuard(bpy.types.Operator):
    bl_idname = 'object.rct_toggle_jerk_guard'
    bl_label = 'Резкие рывки'
    bl_description = 'Для очень резких движений (прыжок, рывок, реактивное): за задней стенкой ставится невидимая стенка-коллайдер, перед не проходит сквозь неё и прокси не выворачивается. Обычно не нужна'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        proxy = get_setup_proxy(context)
        if not proxy or get_proxy_type(proxy) != 'VOLUME':
            self.report({'WARNING'}, tr('Выберите в менеджере прокси-объём (закрытый сзади)'))
            return {'CANCELLED'}
        ensure_object_mode(context)
        idx = context.scene.rct_proxy_index
        if backwall_of(proxy):
            remove_backwall(proxy)
            m = _cloth_mod(proxy)
            if m:
                reset_cloth_cache(context, m)
            self.report({'INFO'}, tr(f'{proxy.name}: стенка для резких рывков убрана'))
        else:
            w, why = build_backwall(context, proxy)
            if not w:
                self.report({'WARNING'}, tr(f'{proxy.name}: стенка не построена — {tr(why)}'))
                return {'CANCELLED'}
            self.report({'INFO'}, tr(f'{proxy.name}: стенка для резких рывков — {w.name}'))
        set_active_mode(context, proxy, 'OBJECT')
        if context.scene.rct_proxy_index != idx:
            context.scene.rct_proxy_index = idx
        return {'FINISHED'}

def _rebuild_support(context, proxy, op):
    scn = context.scene
    body = proxy_body(proxy)
    if body and (not scn.proxy_original_body):
        scn.proxy_original_body = body
    if body and scn.proxy_original_body != body:
        op.report({'WARNING'}, tr(f'«Тело» в сцене не {body.name} — флаг запомнен, полка не перестроена'))
        return False
    idx = scn.rct_proxy_index
    ok = rebuild_torso_collider(context, op)
    if scn.rct_proxy_index != idx:
        scn.rct_proxy_index = idx
    return ok

def draw_physics_block(layout, context, proxy):
    scn = context.scene
    ptype = get_proxy_type(proxy)
    box = layout.box()
    box.label(text=tr('Физика') + ('  ✓' if _cloth_mod(proxy) else ''), translate=False, icon='PHYSICS')
    if ptype == 'CLOTHING':
        box.label(text='Одежда: динамика — во вкладке «Одежда».', icon='INFO')
        return
    if ptype == 'COLLISION':
        box.prop(proxy, 'rct_col_thickness')
        box.label(text='Коллайдер: настраивается во вкладке «Ещё».', icon='INFO')
        return
    col = box.column(align=True)
    is_open = True
    if _cloth_mod(proxy) and proxy.get('rct_preset'):
        p = PRESETS.get(proxy['rct_preset'], {})
        is_open, _ = _fold_header(col, scn, 'rct_ui_phys_preset', f"Сейчас: {p.get('label', proxy['rct_preset'])} (v{proxy.get('rct_preset_version', '?')})", 'PRESET')
    if is_open:
        if ptype != 'HAIR':
            r = col.row(align=True)
            r.alert = _part_ui_get(proxy) == 0
            r.label(text='Часть тела:')
            cur = next((it for it in _PART_ITEMS if it[4] == _part_ui_get(proxy)))
            r.operator_menu_enum('object.rct_set_part', 'part', text=tr(cur[1]), translate=False, icon=cur[3])
        row = col.row(align=True)
        row.prop(scn, f'rct_preset_{ptype.lower()}', text='')
        r = col.row()
        r.scale_y = 1.4
        r.operator('object.rct_apply_preset', icon='CHECKMARK', text='Применить физику')
    if ptype in ('VOLUME', 'SURFACE'):
        col.separator()
        col.operator('object.rct_toggle_support', text='Опора снизу', emboss=False, icon='CHECKBOX_HLT' if proxy.rct_support else 'CHECKBOX_DEHLT')
    quick = CLOTH_QUICK_BY_TYPE.get(ptype)
    if quick and _cloth_mod(proxy):
        q = box.box()
        q.label(text='Быстрая настройка', icon='OPTIONS')
        if proxy.get('rct_preset') == 'BREAST':
            q.operator('object.rct_auto_breast_phys', icon='CHECKBOX_HLT' if breast_auto_applied(proxy) else 'CHECKBOX_DEHLT')
        qc = q.column(align=True)
        for name, text in quick:
            qc.prop(proxy, name, text=tr(text), translate=False)
            if name == 'rct_mass_quick' and proxy.rct_mass_quick > 5.0:
                qc.label(text='Больше 5 кг — тяжёлая, может провисать', icon='ERROR')
            if name == 'rct_pressure_quick':
                if not _cloth_mod(proxy).settings.use_pressure:
                    qc.label(text='Надутие выключено (Pressure) — значение не действует', icon='INFO')
                elif proxy.rct_pressure_quick > 0.2:
                    qc.label(text='Больше 0.2 — начинает раздуваться', icon='ERROR')
        draw_ps_limited(qc, proxy)
        if mirror_partners(proxy):
            q.prop(scn, 'rct_phys_both')
            diff = mirror_cloth_diff(proxy)
            if diff:
                w = q.column(align=True)
                w.alert = True
                w.label(text=tr('Вторая сторона отличается: ') + ', '.join(diff[:3]) + (f' +{len(diff) - 3}' if len(diff) > 3 else ''), translate=False, icon='ERROR')
                w.operator('object.rct_sync_mirror_phys', icon='MOD_MIRROR')
    is_open, _ = _fold_header(box, scn, 'rct_ui_phys_custom', 'Для опытных', 'MODIFIER')
    if is_open:
        c = box.column(align=True)
        if not _cloth_mod(proxy):
            c.label(text='Физики ещё нет — примените пресет', icon='INFO')
        else:
            if ptype == 'VOLUME':
                c.prop(proxy, 'rct_volume_stiffness', text=tr('Упругость объёма (Pressure Scale)'), translate=False)
                draw_ps_limited(c, proxy)
            for name in CLOTH_PRO_FIELDS:
                c.prop(proxy, name)
        if ptype in ('VOLUME', 'SURFACE') and proxy.rct_support:
            s = box.column()
            s.label(text='Полка «Опоры снизу»:', icon='MOD_SOLIDIFY')
            draw_shelf_fields(s, proxy)
        if ptype == 'VOLUME':
            box.operator('object.rct_toggle_jerk_guard', text='Резкие рывки', emboss=False, icon='CHECKBOX_HLT' if backwall_of(proxy) else 'CHECKBOX_DEHLT')
    draw_bake_block(box, context)

def draw_fine_tune_block(layout, context, proxy):
    scn = context.scene
    ptype = get_proxy_type(proxy)
    if ptype in ('CLOTHING', 'COLLISION'):
        return
    box = layout.box()
    if ptype == 'HAIR':
        box.label(text='Тонкая настройка: крепление к костям — авто', icon='CHECKMARK')
        return
    probs = fine_tune_problems(context, proxy)
    if probs:
        r = box.row()
        r.alert = True
        r.label(text=tr(f'Тонкая настройка: ошибка ({len(probs)})'), translate=False, icon='ERROR')
        is_open = True
    else:
        is_open, r = _fold_header(box, scn, 'rct_ui_fine_open', 'Тонкая настройка')
        sub = r.row()
        sub.alignment = 'RIGHT'
        sub.label(text='авто, всё готово', icon='CHECKMARK')
    if not is_open:
        return
    from_vertex = proxy.get('rct_zone_verts') is not None
    body = proxy_body(proxy) or scn.proxy_original_body or scn.proxy_main_mesh
    steps = ((1, 'Точка крепления (на прокси)', 'PINNED'), (2, 'Привязка к скелету и телу', 'ARMATURE_DATA'), (3, 'Зона влияния (маска на теле)', 'MOD_VERTEX_WEIGHT'))
    for num, text, icon in steps:
        b = box.box()
        prob = probs.get(num)
        _step_header(b, num, text, icon, done=not prob)
        if prob:
            w = b.column(align=True)
            w.alert = True
            for line in _wrap_text(prob[0], 44):
                w.label(text=tr(line), translate=False)
            if num == 1:
                if prob[1]:
                    w.operator('object.rct_fix_setup_step', icon='TOOL_SETTINGS', text='Исправить автоматически').step = 1
                else:
                    w.operator('object.prepare_pin_group', icon='BRUSH_DATA', text='Рисовать вручную')
            elif num == 2:
                if not body:
                    w.prop(scn, 'proxy_original_body', text='Тело')
                    w.operator('object.transfer_and_bind', icon='LINKED', text='Привязать')
                elif prob[1]:
                    w.operator('object.transfer_and_bind', icon='TOOL_SETTINGS', text='Исправить автоматически')
                if proxy.get('rct_bind_fail'):
                    if from_vertex:
                        w.operator('object.rct_auto_fix_proxy', icon='FILE_REFRESH', text='Пересоздать (физика сбросится)')
                    else:
                        w.label(text='Не помогло: создайте прокси заново')
                        w.label(text='(вкладка «Прокси» → «Создать»).')
            elif prob[1]:
                w.operator('object.rct_fix_setup_step', icon='TOOL_SETTINGS', text='Исправить автоматически').step = 3
            else:
                r = w.row()
                r.enabled = bool(body)
                r.operator('object.prepare_body_mask', icon='BRUSH_DATA', text='Рисовать вручную')
            continue
        if num == 1:
            if proxy.data.attributes.get(CAST_DIST_ATTR):
                b.prop(scn, 'rct_pin_transition')
            elif proxy.data.attributes.get(EDGE_DIST_ATTR):
                b.prop(scn, 'rct_edge_pin_width')
            b.operator('object.prepare_pin_group', icon='BRUSH_DATA', text='Рисовать точку крепления')
        elif num == 2:
            b.prop(scn, 'proxy_original_body', text='Тело')
            b.operator('object.transfer_and_bind', icon='LINKED', text='Привязать заново')
        else:
            if from_vertex and (not zone_body_changed(proxy)):
                b.prop(scn, 'rct_zone_blur')
            b.operator('object.prepare_body_mask', icon='BRUSH_DATA', text='Рисовать зону влияния')

class VIEW3D_PT_RitTools_Tabs(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'RitTools'
    bl_label = 'RitTools'
    bl_order = 0

    def draw(self, context):
        layout = wrap(self.layout)
        scn = context.scene
        draw_error_box(layout, context)
        b = layout.box()
        b.label(text='RitTools Free', icon='LOCKED')
        draw_full_version_links(b.row(align=True))
        draw_proxy_manager(layout, context)
        row = layout.row()
        row.scale_y = 1.2
        _enum_tabs(row, scn, 'rct_ui_tab', {'HOOKS', 'CLOTHING', 'MORE'})
        tab = scn.rct_ui_tab
        if tab == 'PROXY':
            draw_create_block(layout, context)
            if not get_setup_proxy(context):
                for name in ('Физика', 'Тонкая настройка'):
                    r = layout.box().row()
                    r.enabled = False
                    r.label(text=tr(f'{name}: появится после создания'), translate=False, icon='RIGHTARROW')
            elif fit_session_alive(scn) and get_setup_proxy(context) == scn.proxy_active_cube:
                for name in ('Физика', 'Тонкая настройка'):
                    r = layout.box().row()
                    r.enabled = False
                    r.label(text=tr(f'{name}: после «Готово»'), translate=False, icon='RIGHTARROW')
            else:
                proxy = get_setup_proxy(context)
                draw_physics_block(layout, context, proxy)
                draw_fine_tune_block(layout, context, proxy)
        else:
            tl = layout
            if tab == 'CLOTHING':
                draw_dev_banner(layout)
                tl = layout.column()
                tl.active = False
            else:
                draw_pro_banner(layout, _PRO_TAB_LINES[tab])
                tl = layout.column()
                tl.active = False
            if tab == 'HOOKS':
                draw_hooks_tab(tl, context)
            elif tab == 'CLOTHING':
                draw_clothing_tab(tl, context)
            else:
                draw_colliders_block(tl, context)
                draw_shrinkwrap_block(tl, context)
                b = tl.box()
                b.label(text='Импакт (Forcefield): прокси/одежда активны', icon='FORCE_WIND')
                b.operator('object.add_artificial_impact', icon='FORCE_WIND')
                draw_tips_block(tl, context)
                draw_autophys_block(tl, context)
                draw_language_switch(layout, context)
                layout.operator('object.rct_save_report', icon='FILE_TEXT')

def draw_tips_block(layout, context):
    scn = context.scene
    box = layout.box()
    is_open, _ = _fold_header(box, scn, 'show_proxy_help', 'Советы', 'HELP')
    if not is_open:
        return
    h_col = box.column(align=True)
    h_col.label(text='Точка крепления vs Зона влияния:', icon='QUESTION')
    h_col.label(text='• Точка крепления — НА ПРОКСИ (Pin_Base):')
    h_col.label(text='  где прокси держится за скелет.')
    h_col.label(text='• Зона влияния — НА ТЕЛЕ (Mask_<прокси>):')
    h_col.label(text='  какая кожа повторяет движение прокси.')
    h_col.separator()
    h_col = box.column(align=True)
    h_col.label(text='Голова и Тело:', icon='USER')
    h_col.label(text='• Делайте из обычного шарика (сферы).')
    h_col.label(text='• Много вершин не надо, нужны крупные квадраты.')
    h_col.separator()
    h_col = box.column(align=True)
    h_col.label(text='Анатомия (пупки, отверстия):', icon='MESH_DATA')
    h_col.label(text='• Обязательно запаивайте (заполняйте) глубокие')
    h_col.label(text='  отверстия, чтобы ткань не застревала внутри.')

def draw_colliders_block(layout, context):
    scn = context.scene
    outer = layout.box()
    is_open, _ = _fold_header(outer, scn, 'rct_ui_more_col', beta('Коллизии'), 'MOD_PHYSICS')
    if not is_open:
        return
    col = outer.column(align=True)
    col.prop(scn, 'proxy_original_body', text='Тело')
    col.label(text='Строится в REST-позе (поза анимации неважна).', icon='ARMATURE_DATA')
    box = outer.box()
    box.label(text='Что создать:', icon='MOD_PHYSICS')
    row = box.row(align=True)
    row.prop(scn, 'rct_col_head', toggle=True)
    row.prop(scn, 'rct_col_torso', toggle=True)
    row = box.row(align=True)
    row.prop(scn, 'rct_col_arms', toggle=True)
    row.prop(scn, 'rct_col_fingers', toggle=True)
    box.prop(scn, 'rct_col_segments')
    if scn.rct_col_torso:
        t = box.box()
        t.label(text='Туловище = только опоры:', icon='INFO')
        t.label(text='«полка» под прокси с «Опорой снизу» (менеджер)')
        t.label(text='+ плечи/спина для длинных волос.')
        off = [p.name for p in _scene_proxies(context) if not p.rct_support]
        if off:
            w = t.column(align=True)
            w.label(text=tr(f"Без опоры: {', '.join(off[:3])}{('…' if len(off) > 3 else '')}"), translate=False, icon='ERROR')
            w.label(text='Провисает — включите «Опора снизу» → «Обновить»')
        if any((get_proxy_type(o) == 'HAIR' for o in context.scene.objects)):
            t.label(text='Плечи/спина для волос:')
            t.prop(scn, 'rct_col_torso_segments')
            t.prop(scn, 'rct_col_reach')
    r = box.row()
    r.scale_y = 1.3
    r.operator('object.rct_colliders_from_skeleton', icon='BONE_DATA', text=beta('Коллизии из скелета'), translate=False)
    box.operator('object.rct_update_torso_collider', icon='FILE_REFRESH')
    man = outer.box()
    man.label(text='Если части тела определились неверно:', icon='QUESTION')
    man.label(text='выделите кости в Pose Mode →')
    man.operator('object.rct_colliders_from_selected_bones', icon='BONE_DATA')
    other = outer.box()
    other.label(text='Прочее:', icon='OBJECT_DATA')
    other.prop(scn, 'shrink_target', text='Тело (Коллизия)')
    draw_collision_warning(other)
from . import autophys
from .autophys import draw_autophys_block
from .report import draw_error_box
from . import bake
from .bake import draw_bake_block
