# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
from .helpers import _MODE_MAP, end_fit_simplify, ensure_object_mode, place_modifier_before, restore_isolation, set_active_mode
from .mesh_utils import find_surface_deform
from .naming import is_clothing, proxy_body
from .presets import apply_cloth_preset, PRESETS
from .manager import _add_to_proxy_manager, add_to_physics_collection, detect_proxy_part, get_setup_proxy, NO_SURFDEF_PARTS
from .proxy_core import bind_body_to_proxy, find_armature_for_obj, transfer_weights_to_proxy
from .i18n import static_text, tr

class _HeldReports:
    """Сообщения пробной привязки: покажем, только если она удалась (без ERROR)."""

    def __init__(self):
        self.items = []

    def report(self, kind, msg):
        self.items.append((kind, msg))

    def flush(self, operator):
        for kind, msg in self.items:
            if 'ERROR' not in kind:
                operator.report(kind, tr(msg))

def bind_proxy(context, proxy_obj, main_obj, operator):
    ensure_object_mode(context)
    end_fit_simplify(context.scene)
    restore_isolation(context)
    target_arm_obj = main_obj.find_armature() or find_armature_for_obj(main_obj)
    old_pose_pos = None
    try:
        if target_arm_obj:
            old_pose_pos = target_arm_obj.data.pose_position
            target_arm_obj.data.pose_position = 'REST'
            context.view_layer.update()
        err = transfer_weights_to_proxy(context, proxy_obj, main_obj, target_arm_obj)
        if err:
            operator.report({'WARNING'}, tr(f'Перенос весов не удался: {err}'))
        if target_arm_obj:
            mw = proxy_obj.matrix_world.copy()
            proxy_obj.parent = target_arm_obj
            proxy_obj.parent_type = 'OBJECT'
            proxy_obj.matrix_parent_inverse = target_arm_obj.matrix_world.inverted()
            proxy_obj.matrix_world = mw
        elif proxy_obj.parent:
            mw = proxy_obj.matrix_world.copy()
            proxy_obj.parent = None
            proxy_obj.matrix_world = mw
        closed_back = bool(proxy_obj.get('rct_closed_back'))
        for attempt in (1, 2):
            if closed_back or not proxy_obj.get('rct_auto_fix', True):
                set_active_mode(context, proxy_obj, 'OBJECT')
            else:
                set_active_mode(context, proxy_obj, 'EDIT')
                bpy.ops.mesh.select_mode(type='VERT')
                bpy.ops.mesh.select_all(action='DESELECT')
                try:
                    bpy.ops.mesh.select_non_manifold(extend=False, use_wire=True, use_boundary=False, use_multi_face=True, use_non_contiguous=False, use_verts=True)
                    bpy.ops.mesh.delete(type='VERT')
                except Exception:
                    pass
                bpy.ops.object.mode_set(mode='OBJECT')
            proxy_obj['rct_body'] = main_obj
            if detect_proxy_part(proxy_obj) in NO_SURFDEF_PARTS:
                break
            masks = [m for m in (proxy_obj.get('rct_mask'), f'Mask_{proxy_obj.name}', 'Proxy_Bind_Mask') if m]
            last = attempt == 2 or closed_back
            rep = operator if last else _HeldReports()
            sd = bind_body_to_proxy(context, main_obj, proxy_obj, rep, masks)
            if last or sd.is_bound:
                if rep is not operator:
                    rep.flush(operator)
                break
    except Exception as e:
        ensure_object_mode(context)
        operator.report({'WARNING'}, tr(f'Сбой привязки: {e}'))
        return False
    finally:
        if target_arm_obj and old_pose_pos:
            target_arm_obj.data.pose_position = old_pose_pos
    proxy_obj.display_type = 'WIRE'
    proxy_obj.show_in_front = True
    proxy_obj['rct_bound_vcount'] = len(proxy_obj.data.vertices)
    sd = find_surface_deform(main_obj, proxy_obj)
    if sd:
        proxy_obj['rct_bound_stack_index'] = list(main_obj.modifiers).index(sd)
        proxy_obj['rct_bound_stack_pos'] = _sd_stack_pos(main_obj, sd)
    add_to_physics_collection(proxy_obj, context)
    _add_to_proxy_manager(proxy_obj, context)
    set_active_mode(context, proxy_obj, 'OBJECT')
    return True

def triangulate_above_cloth(proxy):
    tri = proxy.modifiers.find('SurfDef_Triangulate')
    cloth = next((i for i, m in enumerate(proxy.modifiers) if m.type == 'CLOTH'), -1)
    return tri >= 0 and cloth >= 0 and (tri < cloth)

def proxy_binding_ok(proxy):
    body = proxy_body(proxy)
    sd = find_surface_deform(body, proxy) if body else None
    if not (sd and sd.is_bound and (proxy.get('rct_bound_vcount') == len(proxy.data.vertices))):
        return False
    pos = proxy.get('rct_bound_stack_pos')
    if pos is not None:
        return _sd_stack_pos(body, sd) == pos
    idx = proxy.get('rct_bound_stack_index')
    return idx is None or list(body.modifiers).index(sd) == idx

def _sd_stack_pos(body, sd):
    mods = list(body.modifiers)
    return sum((1 for m in mods[:mods.index(sd)] if m.type != 'SURFACE_DEFORM'))

class OBJECT_OT_TransferAndBind(bpy.types.Operator):
    bl_idname = 'object.transfer_and_bind'
    bl_label = 'Перенос весов и Авто-Bind (Surface Deform)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        proxy_obj = get_setup_proxy(context)
        main_obj = context.scene.proxy_original_body or context.scene.proxy_main_mesh or (proxy_body(proxy_obj) if proxy_obj else None)
        if not main_obj or not proxy_obj:
            self.report({'WARNING'}, tr('Тело или Прокси потерялись из памяти! Выделите их в панели выше.'))
            return {'CANCELLED'}
        if main_obj.type != 'MESH' or proxy_obj.type != 'MESH':
            self.report({'WARNING'}, tr('Оба объекта должны быть геометрией (Mesh)!'))
            return {'CANCELLED'}
        if not bind_proxy(context, proxy_obj, main_obj, self):
            return {'CANCELLED'}
        self.report({'INFO'}, tr(f"Кастомный прокси '{proxy_obj.name}' перенял веса и привязан!"))
        return {'FINISHED'}

class OBJECT_OT_ApplyCollision(bpy.types.Operator):
    bl_idname = 'object.apply_collision'
    bl_label = 'Применить Коллизию'
    bl_options = {'REGISTER', 'UNDO'}

def _make_part_preset_op(cls_name, idname, label, preset_id):

    def execute(self, context):
        obj = context.scene.rct_cloth_obj or context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, tr('Не выбран Mesh-объект (Одежда/Прокси) для применения пресета!'))
            return {'CANCELLED'}
        apply_cloth_preset(context, obj, preset_id, self)
        _add_to_proxy_manager(obj, context, 'CLOTHING' if is_clothing(obj) else 'VOLUME')
        self.report({'INFO'}, tr(f"Пресет «{PRESETS[preset_id]['label']}» применён к {obj.name}"))
        return {'FINISHED'}
    return type(cls_name, (bpy.types.Operator,), {'bl_idname': idname, 'bl_label': label, 'bl_options': {'REGISTER', 'UNDO'}, 'bl_description': static_text(f"Пресет физики: {PRESETS[preset_id]['label']}"), 'execute': execute})
OBJECT_OT_ApplyBreastClothPreset = _make_part_preset_op('OBJECT_OT_ApplyBreastClothPreset', 'object.apply_breast_cloth', 'Грудь', 'BREAST')
OBJECT_OT_ApplyThighClothPreset = _make_part_preset_op('OBJECT_OT_ApplyThighClothPreset', 'object.apply_thigh_cloth', 'Бёдра', 'THIGHS')
OBJECT_OT_ApplyGluteClothPreset = _make_part_preset_op('OBJECT_OT_ApplyGluteClothPreset', 'object.apply_glute_cloth', 'Ягодицы', 'BUTT')

class OBJECT_OT_CreateBaseGroup(bpy.types.Operator):
    bl_idname = 'object.create_base_group'
    bl_label = '1. Залить синим (Pin_Base)'
    bl_options = {'REGISTER', 'UNDO'}
from . import hooks
