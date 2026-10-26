# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
import os
from .helpers import apply_modifier, ensure_object_mode, move_modifier, place_modifier_after_deform_base, place_modifier_before, set_active_mode
from .topology import split_concave_quads
from .mesh_utils import find_surface_deform, vertex_group_has_weights
from .manager import add_to_physics_collection
from .i18n import tr
from .report import report_error

def find_armature_for_obj(obj):
    for mod in obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            return mod.object
    for mod in obj.modifiers:
        if mod.type == 'SURFACE_DEFORM' and mod.target:
            for t_mod in mod.target.modifiers:
                if t_mod.type == 'ARMATURE' and t_mod.object:
                    return t_mod.object
    return None
HOOK_MAX_SLOTS = 16
HOOK_TREE_NAME = f'DynamicPin_{HOOK_MAX_SLOTS}Slots'

def transfer_weights_to_proxy(context, proxy, body, arm_obj):
    mod_arm = None
    if arm_obj:
        mod_arm = next((m for m in proxy.modifiers if m.type == 'ARMATURE'), None) or proxy.modifiers.new(name='Armature', type='ARMATURE')
        mod_arm.object = arm_obj
        for extra in [m for m in proxy.modifiers if m.type == 'ARMATURE' and m != mod_arm]:
            proxy.modifiers.remove(extra)
        move_modifier(proxy, mod_arm.name, 0)
    set_active_mode(context, proxy, 'OBJECT')
    mod_transfer = proxy.modifiers.get('DataTransfer') or proxy.modifiers.new(name='DataTransfer', type='DATA_TRANSFER')
    try:
        mod_transfer.object = body
        mod_transfer.use_vert_data = True
        mod_transfer.data_types_verts = {'VGROUP_WEIGHTS'}
        mod_transfer.vert_mapping = 'POLYINTERP_NEAREST'
        if hasattr(mod_transfer, 'layers_vgroup_select_src'):
            mod_transfer.layers_vgroup_select_src = 'ALL'
        if hasattr(mod_transfer, 'layers_vgroup_select_dst'):
            mod_transfer.layers_vgroup_select_dst = 'NAME'
        if hasattr(mod_transfer, 'use_object_transform'):
            mod_transfer.use_object_transform = True
        with context.temp_override(object=proxy, active_object=proxy):
            bpy.ops.object.datalayout_transfer(modifier=mod_transfer.name)
        apply_modifier(context, proxy, mod_transfer.name)
        if mod_arm:
            move_modifier(proxy, mod_arm.name, 0)
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_clean(group_select_mode='BONE_DEFORM', limit=0.002)
            bpy.ops.object.vertex_group_normalize_all(group_select_mode='BONE_DEFORM', lock_active=False)
            bpy.ops.object.mode_set(mode='OBJECT')
        return None
    except Exception as e:
        ensure_object_mode(context)
        if proxy.modifiers.get(mod_transfer.name):
            proxy.modifiers.remove(mod_transfer)
        return str(e)

def bind_body_to_proxy(context, body, proxy, operator, mask_names=()):
    mod_surf = find_surface_deform(body, proxy) or body.modifiers.new(name=f'SurfDef_{proxy.name}', type='SURFACE_DEFORM')
    mod_surf.target = proxy
    place_modifier_after_deform_base(body, mod_surf.name)
    if body.modifiers.get('Collision'):
        place_modifier_before(body, mod_surf.name, 'Collision')
    mod_surf.vertex_group = ''
    for mname in mask_names:
        if mname in body.vertex_groups:
            mod_surf.vertex_group = mname
            if not vertex_group_has_weights(body, mname):
                operator.report({'WARNING'}, tr(f"Маска '{mname}' пустая — тело не будет реагировать на прокси. Закрасьте маску и привяжите снова."))
            break
    if proxy.get('rct_auto_fix', True):
        set_active_mode(context, proxy, 'EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.object.mode_set(mode='OBJECT')
    set_active_mode(context, body, 'OBJECT')
    if proxy.get('rct_sparse_bind'):
        mod_surf.use_sparse_bind = False
        del proxy['rct_sparse_bind']
    first_err = None
    try:
        if mod_surf.is_bound:
            bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
        bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
    except Exception as e:
        err_msg = str(e).lower()
        if 'more than two polygons' in err_msg:
            first_err = f'Surface Deform: у {proxy.name} внутренние грани (Non-Manifold). Сделайте Clean Up в Edit Mode!'
        elif 'concave' in err_msg:
            first_err = f'Surface Deform: у {proxy.name} вогнутые полигоны. Сгладьте сетку прокси (Smooth Vertices) или увеличьте Subdiv.'
        elif 'overlap' in err_msg or 'no vertices' in err_msg:
            first_err = f'Surface Deform: {e}. Проверьте маску на теле и что прокси не сплющен.'
        else:
            first_err = f'Не удалось привязать Surface Deform: {e}'
    context.view_layer.update()
    body.evaluated_get(context.evaluated_depsgraph_get())
    if not mod_surf.is_bound and mod_surf.vertex_group:
        mod_surf.use_sparse_bind = True
        try:
            bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
            bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
        except Exception:
            pass
        context.view_layer.update()
        body.evaluated_get(context.evaluated_depsgraph_get())
        if mod_surf.is_bound:
            proxy['rct_sparse_bind'] = True
            first_err = None
            print(f'[RitTools] {proxy.name}: привязано только по маске (Sparse Bind)')
        else:
            mod_surf.use_sparse_bind = False
    auto_fix = proxy.get('rct_auto_fix', True)
    if auto_fix and (not mod_surf.is_bound) and (not proxy.modifiers.get('SurfDef_Triangulate')):
        bm = bmesh.new()
        bm.from_mesh(proxy.data)
        cut = split_concave_quads(bm)
        if cut:
            bm.to_mesh(proxy.data)
            proxy.data.update()
        bm.free()
        if cut:
            set_active_mode(context, body, 'OBJECT')
            try:
                bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
                bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
            except Exception:
                pass
            context.view_layer.update()
            body.evaluated_get(context.evaluated_depsgraph_get())
            if mod_surf.is_bound:
                operator.report({'INFO'}, tr(f'{proxy.name}: разрезано вогнутых квадов {cut} — привязано'))
    if auto_fix and (not mod_surf.is_bound) and (not proxy.modifiers.get('SurfDef_Triangulate')):
        tri = proxy.modifiers.new('SurfDef_Triangulate', 'TRIANGULATE')
        tri.quad_method = 'FIXED'
        tri.ngon_method = 'CLIP'
        tri.min_vertices = 4
        move_modifier(proxy, tri.name, len(proxy.modifiers) - 1)
        set_active_mode(context, body, 'OBJECT')
        try:
            bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
            bpy.ops.object.surfacedeform_bind(modifier=mod_surf.name)
        except Exception:
            pass
        context.view_layer.update()
        body.evaluated_get(context.evaluated_depsgraph_get())
        if mod_surf.is_bound:
            operator.report({'WARNING'}, tr(f'{proxy.name}: привязано только через Triangulate (последняя мера: тело держится за треугольники, физика — на квадах). Сгладьте прокси (Smooth Vertices) и привяжите снова, чтобы обойтись без него'))
        else:
            proxy.modifiers.remove(tri)
    if 'rct_bind_fail' in proxy:
        del proxy['rct_bind_fail']
    if not mod_surf.is_bound and (not auto_fix):
        reason = first_err or f'Surface Deform не привязался к {proxy.name}: вогнутые или пересекающиеся полигоны, лишние грани или слипшиеся вершины в копии выделения'
        proxy['rct_bind_fail'] = reason
        operator.report({'WARNING'}, tr(reason) + tr('. Сетка не исправлялась (галочка выключена) — нажмите «Исправить автоматически» в настройке прокси'))
    elif not mod_surf.is_bound:
        if first_err:
            operator.report({'WARNING'}, tr(first_err))
        operator.report({'ERROR'}, tr(f'Surface Deform не привязался к {proxy.name}: у прокси вогнутые или пересекающиеся полигоны, либо вершины слиплись. Сгладьте прокси (Smooth Vertices) или поднимите уровень Subdiv и привяжите снова.'))
    return mod_surf
from . import create_ops
