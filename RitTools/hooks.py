# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
from mathutils import Vector, Matrix
from .helpers import _MODE_MAP, ensure_object_mode, place_modifier_before, set_active_mode
from .zone import _assign_weights
from .mesh_utils import gn_value_owner
from .naming import get_proxy_type
from .presets import apply_cloth_preset, DEFAULT_PRESET, PRESETS
from .manager import proxy_entry_is_dead
from .proxy_core import find_armature_for_obj, HOOK_MAX_SLOTS
from .i18n import tr
from .report import report_error

def _hook_bone_names(obj, slot_idx):
    mod = obj.modifiers.get(f'Hook_{slot_idx}')
    if not mod:
        return []
    if mod.type == 'WARP':
        return [mod.bone_to, mod.bone_from]
    if mod.type == 'HOOK':
        return [mod.subtarget]
    return []

def _action_fcurve_lists(action, slot):
    layers = getattr(action, 'layers', None)
    if layers:
        for layer in layers:
            for strip in layer.strips:
                cb = strip.channelbag(slot) if slot and hasattr(strip, 'channelbag') else None
                bags = [cb] if cb else [] if slot else list(getattr(strip, 'channelbags', []))
                for bag in bags:
                    yield bag
    elif hasattr(action, 'fcurves'):
        yield action

def purge_bone_animation(arm_obj, names):
    ad = arm_obj.animation_data if arm_obj else None
    names = [n for n in names if n]
    if not ad or not names:
        return 0
    prefixes = tuple((f'pose.bones["{bpy.utils.escape_identifier(n)}"]' for n in names))
    pairs = [(ad.action, getattr(ad, 'action_slot', None))]
    pairs += [(s.action, getattr(s, 'action_slot', None)) for t in ad.nla_tracks for s in t.strips]
    removed = 0
    for action, slot in pairs:
        if not action:
            continue
        for owner in _action_fcurve_lists(action, slot):
            for fc in [fc for fc in owner.fcurves if fc.data_path.startswith(prefixes)]:
                owner.fcurves.remove(fc)
                removed += 1
            groups = getattr(owner, 'groups', None)
            if groups is not None:
                for g in [g for g in groups if g.name in names and (not g.channels)]:
                    groups.remove(g)
    return removed

def delete_bones(context, arm_obj, names):
    purge_bone_animation(arm_obj, names)
    names = [n for n in names if n and n in arm_obj.data.bones]
    if not names:
        return
    ensure_object_mode(context)
    prev_active = context.view_layer.objects.active
    was_hidden = arm_obj.hide_get()
    if was_hidden:
        arm_obj.hide_set(False)
    context.view_layer.objects.active = arm_obj
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        for n in names:
            eb = arm_obj.data.edit_bones.get(n)
            if eb:
                arm_obj.data.edit_bones.remove(eb)
    finally:
        if arm_obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if was_hidden:
            arm_obj.hide_set(True)
        context.view_layer.objects.active = prev_active
_HOOK_BONE_COLLECTIONS = ('RCT_Hooks', 'RCT_Hidden_Hooks')

def armature_has_hooks(arm_obj):
    return any((m.type == 'WARP' and m.name.startswith('Hook_') and (arm_obj in (m.object_from, m.object_to)) for o in bpy.data.objects if o.type == 'MESH' for m in o.modifiers))

def cleanup_hook_rig(arm_obj):
    if not arm_obj or arm_obj.type != 'ARMATURE':
        return
    if hasattr(arm_obj.data, 'collections'):
        for name in _HOOK_BONE_COLLECTIONS:
            col = arm_obj.data.collections.get(name)
            if col and (not col.bones) and (not col.children):
                arm_obj.data.collections.remove(col)
    if 'Hold_Strength' in arm_obj and (not armature_has_hooks(arm_obj)):
        del arm_obj['Hold_Strength']
HOOK_RADIUS_DEFAULT = 3.0
HOOK_BLUR_DEFAULT = 0.5
HOOK_DIST_KEY = '_rct_hook_dist_{}'
HOOK_CENTER_KEY = '_rct_hook_center_{}'
HOOK_MESH_CHANGED_KEY = '_rct_hook_remeshed_{}'
HOOK_PIN_GROUP = 'Pin_Base'

def hook_slot_settings(obj, slot_idx):
    return next((s for s in obj.rct_hook_slots if s.slot == slot_idx), None) if obj else None

def hook_mesh_changed(obj, slot_idx):
    dist = obj.get(HOOK_DIST_KEY.format(slot_idx))
    if dist is None:
        return False
    n = len(bmesh.from_edit_mesh(obj.data).verts) if obj.mode == 'EDIT' else len(obj.data.vertices)
    return len(dist) != n

def _hook_slot_update(self, context):
    pass
HOOK_ZONE_SHOWN_KEY = '_rct_zone_shown'
HOOK_ZONE_BACK_KEY = '_rct_zone_back'

class OBJECT_OT_RitCromHookShowZone(bpy.types.Operator):
    bl_idname = 'object.rct_hook_show_zone'
    bl_label = 'Показать зону'
    bl_description = 'Показать веса зоны хука (Grp_Slot) поверх сетки в Edit Mode. Повторное нажатие возвращает прежнюю активную группу и оверлей'
    bl_options = {'REGISTER'}
    hook_index: bpy.props.IntProperty()
    obj_name: bpy.props.StringProperty()

class RitCromHookSlot(bpy.types.PropertyGroup):
    """Настройки зоны одного хука (Hook_N / Grp_Slot_N)."""
    slot: bpy.props.IntProperty()
    radius: bpy.props.FloatProperty(name='Радиус хватки (рядов)', description='Сколько рядов прокси вокруг точки идёт за хуком. Считается по поверхности сетки, через воздух на заднюю стенку или соседнюю грудь не перескакивает. Закреплённое основание (Pin_Base) хук не двигает', default=HOOK_RADIUS_DEFAULT, min=0.5, soft_max=15.0, max=100.0, step=10, precision=1, update=_hook_slot_update)
    blur: bpy.props.FloatProperty(name='Размытие края', description='0 — резкий край зоны, 1 — плавный спад от самой точки к краю радиуса', default=HOOK_BLUR_DEFAULT, min=0.0, max=1.0, subtype='FACTOR', update=_hook_slot_update)

class OBJECT_OT_DynamicGrab(bpy.types.Operator):
    bl_idname = 'object.dynamic_grab'
    bl_label = 'Создать зацеп (Хук)'
    bl_options = {'REGISTER', 'UNDO'}

def _hook_target(context, obj_name):
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    scn = context.scene
    if not obj:
        act = context.active_object
        if act and act.type == 'MESH' and any((it.obj_ptr == act and (not proxy_entry_is_dead(it)) for it in scn.rct_proxies)):
            obj = act
    if not obj:
        if 0 <= scn.rct_proxy_index < len(scn.rct_proxies):
            item = scn.rct_proxies[scn.rct_proxy_index]
            if not proxy_entry_is_dead(item):
                obj = item.obj_ptr
    return obj

def _has_hook_data(obj):
    return obj and obj.type == 'MESH' and (obj.modifiers.get('DynamicPin_Geo') or any((m.name.startswith('Hook_') for m in obj.modifiers)) or any((g.name.startswith('Grp_Slot_') for g in obj.vertex_groups)))

class OBJECT_OT_SnapHookToVertex(bpy.types.Operator):
    bl_idname = 'object.snap_hook_to_vertex'
    bl_label = 'Примагнитить кость к сетке'
    bl_description = 'Возвращает управляющую кость хука в нулевое положение (на Base): зона хука встаёт на место на теле'
    bl_options = {'REGISTER', 'UNDO'}
    hook_index: bpy.props.IntProperty()
    obj_name: bpy.props.StringProperty()

class OBJECT_OT_SelectHookBone(bpy.types.Operator):
    bl_idname = 'object.rct_select_hook_bone'
    bl_label = 'Выбрать кость'
    bl_description = 'Выделить управляющую кость хука и перейти в Pose Mode. Повторное нажатие — вернуться в прежний объект и режим'
    bl_options = {'REGISTER', 'UNDO'}
    hook_index: bpy.props.IntProperty()
    obj_name: bpy.props.StringProperty()

class OBJECT_OT_ClearHooks(bpy.types.Operator):
    bl_idname = 'object.clear_hooks'
    bl_label = 'Удалить все Хуки и Слоты'
    bl_description = 'Очищает хуки выбранного прокси из менеджера'
    bl_options = {'REGISTER', 'UNDO'}
    obj_name: bpy.props.StringProperty(options={'SKIP_SAVE'})

class OBJECT_OT_ClearSingleHook(bpy.types.Operator):
    bl_idname = 'object.clear_single_hook'
    bl_label = 'Удалить конкретный Хук'
    bl_options = {'REGISTER', 'UNDO'}
    hook_index: bpy.props.IntProperty()
    obj_name: bpy.props.StringProperty()
from . import shrink_hair
