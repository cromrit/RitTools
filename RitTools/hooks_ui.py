# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
from .helpers import set_active_mode
from .mesh_utils import gn_value_owner
from .naming import proxy_body
from .proxy_core import find_armature_for_obj, HOOK_MAX_SLOTS
from .hooks import _has_hook_data, _hook_target, hook_mesh_changed, HOOK_MESH_CHANGED_KEY, hook_slot_settings, HOOK_ZONE_SHOWN_KEY
from .i18n import tr

def hook_list(obj):
    arm_obj = find_armature_for_obj(obj)
    hooks = []
    for i in range(1, HOOK_MAX_SLOTS + 1):
        mod = obj.modifiers.get(f'Hook_{i}')
        if not mod:
            continue
        bone_name = mod.bone_to if mod.type == 'WARP' else mod.subtarget if mod.type == 'HOOK' else None
        if bone_name and arm_obj and (bone_name in arm_obj.data.bones):
            hooks.append((i, bone_name))
    return hooks

def _hook_strength_owner(obj, arm_obj, slot, bone_name):
    pb = arm_obj.pose.bones.get(bone_name) if arm_obj and bone_name else None
    if pb and 'Strength' in pb:
        return (pb, '["Strength"]')
    mod = obj.modifiers.get(f'Hook_{slot}')
    return (mod, 'strength') if mod else (None, '')

def _hook_open_slot(scn, hooks):
    slots = [s for s, _ in hooks]
    if scn.rct_ui_hook_open in slots and len(hooks) <= scn.rct_ui_hook_seen:
        return scn.rct_ui_hook_open
    return slots[-1] if slots else 0

class OBJECT_OT_RitCromUiOpenHook(bpy.types.Operator):
    bl_idname = 'object.rct_ui_open_hook'
    bl_label = 'Раскрыть хук'
    bl_description = 'Показать настройки этого хука (остальные свернутся в строку)'
    bl_options = {'INTERNAL'}
    hook_index: bpy.props.IntProperty()
    obj_name: bpy.props.StringProperty()

class OBJECT_OT_RitCromHookEditProxy(bpy.types.Operator):
    bl_idname = 'object.rct_hook_edit_proxy'
    bl_label = 'Edit Mode на прокси'
    bl_description = 'Сделать выбранный в менеджере прокси активным и перейти в Edit Mode, чтобы выделить точки хука'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromHookPickProxy(bpy.types.Operator):
    bl_idname = 'object.rct_hook_pick_proxy'
    bl_label = 'Перейти к прокси'
    bl_description = 'Выбрать этот прокси в менеджере и на сцене — вкладка «Хуки» переключится на него'
    bl_options = {'REGISTER', 'UNDO'}
    obj_name: bpy.props.StringProperty()

def _hook_add_state(context, obj, n_hooks):
    if n_hooks >= HOOK_MAX_SLOTS:
        return (False, f'Заняты все {HOOK_MAX_SLOTS} слотов — удалите ненужный хук ниже', '')
    if not find_armature_for_obj(obj):
        return (False, 'Нет скелета: прокси не привязан к телу (Armature)', 'BIND')
    act = context.active_object
    if act != obj or obj.mode != 'EDIT':
        return (False, 'Хук ставится на выделенные точки прокси в Edit Mode', 'EDIT')
    if not obj.data.total_vert_sel:
        return (True, 'Выделите точки прокси, за которые тянуть', '')
    return (True, '', '')

def draw_hooks_tab(layout, context):
    scn = context.scene
    obj = _hook_target(context, '')
    if not obj or obj.type != 'MESH':
        b = layout.box()
        b.label(text='Выберите прокси или одежду в менеджере', icon='INFO')
        b.label(text='(список сверху) или выделите его на сцене.')
        return
    arm_obj = find_armature_for_obj(obj)
    hooks = hook_list(obj)
    head = layout.box()
    r = head.row(align=True)
    r.label(text=obj.name, translate=False, icon='ARMATURE_DATA')
    sub = r.row()
    sub.alignment = 'RIGHT'
    sub.label(text=tr(f'{len(hooks)} из {HOOK_MAX_SLOTS}'), translate=False)
    mod_geo = obj.modifiers.get('DynamicPin_Geo')
    if mod_geo and getattr(mod_geo, 'node_group', None):
        hold_id = next((i.identifier for i in mod_geo.node_group.interface.items_tree if i.name == 'Hold Strength'), None)
        if hold_id:
            if arm_obj and 'Hold_Strength' in arm_obj:
                head.prop(arm_obj, '["Hold_Strength"]', text='Общая привязка')
            else:
                owner, path = gn_value_owner(mod_geo, hold_id)
                head.prop(owner, path, text='Общая привязка')
    if _has_hook_data(obj):
        head.operator('object.clear_hooks', icon='TRASH', text='Очистить всё')
    ok, why, action = _hook_add_state(context, obj, len(hooks))
    col = layout.column(align=True)
    r = col.row()
    r.scale_y = 1.5
    r.enabled = ok
    r.operator('object.dynamic_grab', icon='ADD', text='Добавить хук')
    if why:
        for i, line in enumerate(_wrap_text(why, 44)):
            col.label(text=tr(line), translate=False, icon='INFO' if i == 0 else 'NONE')
    if action == 'EDIT':
        col.operator('object.rct_hook_edit_proxy', icon='EDITMODE_HLT', text='Edit Mode на прокси')
    elif action == 'BIND':
        if not (proxy_body(obj) or scn.proxy_original_body):
            col.prop(scn, 'proxy_original_body', text='Тело')
        col.operator('object.transfer_and_bind', icon='LINKED', text='Привязать')
    open_slot = _hook_open_slot(scn, hooks)
    for local_idx, (slot, bone_name) in enumerate(hooks, 1):
        b = layout.box()
        st = hook_slot_settings(obj, slot)
        owner, path = _hook_strength_owner(obj, arm_obj, slot, bone_name)
        if slot != open_slot:
            r = b.row(align=True)
            op = r.operator('object.rct_ui_open_hook', text=tr(f'Хук {local_idx}'), translate=False, icon='TRIA_RIGHT', emboss=False)
            op.hook_index, op.obj_name = (slot, obj.name)
            sub = r.row()
            sub.alignment = 'RIGHT'
            strength = owner.path_resolve(path) if owner else 0.0
            radius = tr(f'  ·  радиус {st.radius:g}') if st else ''
            sub.label(text=tr(f'сила {strength:.2f}') + radius, translate=False)
            continue
        b.row().label(text=tr(f'Хук {local_idx}  ({bone_name})'), translate=False, icon='TRIA_DOWN')
        r = b.row(align=True)
        in_pose = context.mode == 'POSE' and context.active_object == arm_obj and arm_obj.data.bones.active and (arm_obj.data.bones.active.name == bone_name)
        op = r.operator('object.rct_select_hook_bone', text=tr('Вернуться' if in_pose else 'Выбрать кость'), translate=False, icon='LOOP_BACK' if in_pose else 'BONE_DATA')
        op.hook_index, op.obj_name = (slot, obj.name)
        op = r.operator('object.snap_hook_to_vertex', text='Магнит', icon='SNAP_ON')
        op.hook_index, op.obj_name = (slot, obj.name)
        c = b.column(align=True)
        if st is None:
            c.label(text='Старый хук: радиус в метрах.', icon='INFO')
            c.label(text='Удалите и создайте заново, чтобы')
            c.label(text='настраивать радиус в рядах.')
        else:
            c.prop(st, 'radius', text='Радиус хватки (рядов)')
            c.prop(st, 'blur', text='Размытие края')
        if owner:
            c.prop(owner, path, text='Сила')
        changed = st is not None and (obj.get(HOOK_MESH_CHANGED_KEY.format(slot)) or hook_mesh_changed(obj, slot))
        if changed:
            w = b.box().column(align=True)
            w.label(text='Сетка прокси изменилась', icon='ERROR')
            w.label(text='Зона хука пересчитана — проверьте:')
            op = w.operator('object.rct_hook_show_zone', text='Показать зону', icon='GROUP_VERTEX', depress=obj.get(HOOK_ZONE_SHOWN_KEY) == slot)
            op.hook_index, op.obj_name = (slot, obj.name)
        r = b.row(align=True)
        if st is not None and (not changed):
            op = r.operator('object.rct_hook_show_zone', text='Показать зону', icon='GROUP_VERTEX', depress=obj.get(HOOK_ZONE_SHOWN_KEY) == slot)
            op.hook_index, op.obj_name = (slot, obj.name)
        op = r.operator('object.clear_single_hook', text='Удалить хук', icon='X')
        op.hook_index, op.obj_name = (slot, obj.name)
    others = [o for o in context.view_layer.objects if o != obj and o.type == 'MESH' and o.modifiers.get('DynamicPin_Geo') and hook_list(o)]
    if others:
        c = layout.column(align=True)
        c.label(text='Хуки есть и на:', icon='INFO')
        for o in others:
            idx = next((i for i, it in enumerate(scn.rct_proxies) if it.obj_ptr == o), -1)
            if idx >= 0:
                op = c.operator('object.rct_hook_pick_proxy', text=tr(f'{o.name} ({len(hook_list(o))})'), translate=False, icon='RESTRICT_SELECT_OFF')
                op.obj_name = o.name
            else:
                c.label(text=tr(f'{o.name} ({len(hook_list(o))}) — не в менеджере'), translate=False)

def draw_shrinkwrap_block(layout, context):
    scn = context.scene
    box = layout.box()
    is_open, _ = _fold_header(box, scn, 'rct_ui_more_shrink', 'Защита кожи (Shrinkwrap)', 'MOD_SHRINKWRAP')
    if not is_open:
        return
    col = box.column(align=True)
    col.operator('object.create_shrink_group', icon='BRUSH_DATA', text='1. Выделить зону')
    col.label(text='Тело (чтобы не проваливало ткань):')
    col.prop(scn, 'shrink_target', text='Тело (Коллизия)')
    col.operator('object.apply_shrinkwrap', icon='CHECKMARK', text='2. Применить Shrinkwrap')
    base_obj = context.active_object if context.active_object and context.active_object.type == 'MESH' else context.scene.rct_cloth_obj
    if base_obj and base_obj.type == 'MESH':
        mod_shrink = base_obj.modifiers.get('Shrinkwrap')
        if mod_shrink:
            col.separator()
            col.prop(mod_shrink, 'offset', text='Отступ (Offset)')
from . import clothing
from .panel import _fold_header, _wrap_text
