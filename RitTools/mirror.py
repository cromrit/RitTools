# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
import re
from mathutils import Vector, Matrix
from .helpers import ensure_object_mode, move_modifier, place_cloth_modifier, set_active_mode
from .zone import _assign_weights, _world_kdtree, bake_world_scale, fill_mask_holes, zone_body_changed
from .mesh_utils import ensure_outward_normals, find_surface_deform, NORMALS_FLIPPED_MSG
from .naming import SIDE_CROSS_FRAC, _proxy_side, _unique_object_name, get_proxy_type, proxy_body, proxy_center_cross
from .presets import _cloth_mod, cloth_pin_group, PROXY_SMOOTH_NAME, reset_cloth_cache
from .manager import _add_to_proxy_manager, get_setup_proxy
from .proxy_core import find_armature_for_obj
from .i18n import tr
_MIRROR_SKIP_KEYS = {'rct_mask', 'rct_zone_verts', 'rct_zone_body_vcount', 'rct_zone_mirrored', 'rct_bound_vcount', 'rct_bound_stack_index', 'rct_bound_stack_pos', 'rct_bind_fail', 'rct_col_collection', 'rct_autoname', 'rct_body', 'rct_shelf_bound_verts', 'rct_shelf_bound_vcount', 'rct_hook_slots', 'rct_hook_bone_back', 'rct_autophys_chains', 'rct_self_intersections', 'rct_mirror_of'}

def _copy_rna(src, dst, skip=()):
    for p in src.bl_rna.properties:
        k = p.identifier
        if k in skip or k == 'rna_type' or p.is_readonly:
            continue
        if p.type in ('BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'):
            try:
                setattr(dst, k, getattr(src, k))
            except (AttributeError, TypeError, ValueError):
                pass
    ew = getattr(src, 'effector_weights', None)
    if ew is not None:
        _copy_rna(ew, dst.effector_weights, ('collection',))

def body_mirror_map(body, verts):
    me = body.data
    kd = _world_kdtree([v.co for v in me.vertices])
    zs = [v.co.z for v in me.vertices]
    tol = max(max(zs) - min(zs), 1e-06) * 0.0001 if zs else 1e-06
    scale = max(body.matrix_world.to_scale())
    out, inexact, worst = ({}, 0, 0.0)
    for i in verts:
        co = me.vertices[i].co
        m = Vector((-co.x, co.y, co.z))
        near = [j for _co, j, _d in kd.find_range(m, tol)]
        if not near:
            _co, j, d = kd.find(m)
            near = [j]
            inexact += 1
            worst = max(worst, d * scale)
        out[i] = near
    return (out, inexact, worst * 1000.0)

def _mirror_name(src, side):
    base = re.sub('\\.\\d{3}$', '', src.name)
    base = re.sub('[_.][LRlr]$', '', base)
    return _unique_object_name(base + side)

def center_cross_msg(proxy, body):
    return f'Копия на другой стороне не сделана: {proxy.name} заходит за середину тела на {proxy_center_cross(proxy, body):.0f} мм (можно до {SIDE_CROSS_FRAC * 100:.0f}% ширины прокси). Выделите одну сторону или сдвиньте прокси и нажмите «Отзеркалить»'

def mirror_proxy_copy(context, src, operator):
    body = proxy_body(src) or context.scene.proxy_original_body
    if not body or body.type != 'MESH':
        operator.report({'WARNING'}, tr(f'{src.name}: не найдено тело — укажите его в «Привязке»'))
        return None
    side = _proxy_side(src, body)
    if not side:
        operator.report({'WARNING'}, tr(f'{src.name} заходит на обе стороны тела — зеркалить нечего'))
        operator.report({'WARNING'}, tr(center_cross_msg(src, body)))
        return None
    if src.get('rct_zone_mirrored'):
        operator.report({'WARNING'}, tr(f'{src.name} уже отзеркален на обе стороны (Mirror)'))
        return None
    ensure_object_mode(context)
    context.view_layer.update()
    bw = body.matrix_world
    world = bw @ Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0)) @ bw.inverted() @ src.matrix_world
    flip = world.to_3x3().determinant() < 0
    if flip:
        world = world @ Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
    me = src.data.copy()
    me.name = src.data.name + '_mirror'
    if flip:
        bm = bmesh.new()
        bm.from_mesh(me)
        for v in bm.verts:
            v.co.x = -v.co.x
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(me)
        bm.free()
        me.update()
    dst = bpy.data.objects.new(_mirror_name(src, '_R' if side == '_L' else '_L'), me)
    for col in src.users_collection:
        col.objects.link(dst)
    dst.matrix_world = world
    context.view_layer.update()
    for g in src.vertex_groups:
        dst.vertex_groups.new(name=g.name)
    arm = body.find_armature() or find_armature_for_obj(body)
    bones = {b.name for b in arm.data.bones} if arm else set()
    for g in list(dst.vertex_groups):
        if g.name in bones or g.name.startswith('Grp_Slot') or g.name == 'Pin_Final':
            dst.vertex_groups.remove(g)
    for k in src.keys():
        if k.startswith('rct_') and k not in _MIRROR_SKIP_KEYS:
            try:
                dst[k] = src[k]
            except (TypeError, ValueError):
                pass
    dst.display_type = src.display_type
    dst.show_in_front = src.show_in_front
    scaled = bake_world_scale(context, dst)
    flipped = ensure_outward_normals(dst)
    dst['rct_body'] = body
    zone = _proxy_zone(src, body) or set()
    sd = find_surface_deform(body, src)
    src_mask = (sd.vertex_group if sd and sd.vertex_group else '') or src.get('rct_mask') or ''
    bound = [] if shelf_bound_changed(src) else [int(i) for i in src.get('rct_shelf_bound_verts') or []]
    zone_verts = [] if zone_body_changed(src) else [int(i) for i in src.get('rct_zone_verts') or []]
    vmap, inexact, worst = body_mirror_map(body, zone | set(zone_verts) | set(bound))
    weights, src_w = ({}, {})
    vg = body.vertex_groups.get(src_mask)
    if vg:
        for v in body.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0.0:
                    src_w[v.index] = g.weight
                    for j in vmap.get(v.index, ()):
                        weights[j] = max(weights.get(j, 0.0), g.weight)
    else:
        weights = {j: 1.0 for i in zone for j in vmap[i]}
    fill_mask_holes(body.data, weights)
    sgn = 1.0 if side == '_L' else -1.0
    shared = [j for j in weights if j in src_w]
    to_copy = [j for j in shared if body.data.vertices[j].co.x * sgn < -1e-06]
    for j in shared:
        if j not in to_copy:
            del weights[j]
    if to_copy and vg:
        vg.remove(to_copy)
    mask = f'Mask_{dst.name}'
    _assign_weights(body, mask, weights)
    dst['rct_mask'] = mask
    if zone_verts:
        dst['rct_zone_verts'] = sorted({j for i in zone_verts for j in vmap[i]})
        dst['rct_zone_body_vcount'] = len(body.data.vertices)
    if bound:
        dst['rct_shelf_bound_verts'] = sorted({j for i in bound for j in vmap[i]})
        dst['rct_shelf_bound_vcount'] = len(body.data.vertices)
    bound_ok = bind_proxy(context, dst, body, operator)
    sd_new = find_surface_deform(body, dst)
    c_src = _cloth_mod(src)
    if c_src:
        c = _cloth_mod(dst) or dst.modifiers.new(name=c_src.name, type='CLOTH')
        _copy_rna(c_src.settings, c.settings, ('vertex_group_mass',))
        _copy_rna(c_src.collision_settings, c.collision_settings, ('collection',))
        c.settings.vertex_group_mass = cloth_pin_group(dst)
        place_cloth_modifier(dst, c.name)
        col = proxy_collision_collection(context, dst)
        fill_proxy_collision_collection(dst, col)
        c.collision_settings.collection = col
        reset_cloth_cache(context, c)
        sm_src = src.modifiers.get(PROXY_SMOOTH_NAME)
        if sm_src and (not dst.modifiers.get(PROXY_SMOOTH_NAME)):
            sm = dst.modifiers.new(PROXY_SMOOTH_NAME, 'CORRECTIVE_SMOOTH')
            _copy_rna(sm_src, sm, ('name',))
            move_modifier(dst, sm.name, dst.modifiers.find(c.name) + 1)
    if dst.get('rct_created') and (not dst.get('rct_user_proxy')):
        dst['rct_autoname'] = dst.name
    dst['rct_mirror_of'] = src
    _add_to_proxy_manager(dst, context)
    set_active_mode(context, dst, 'OBJECT')
    pin = dst.vertex_groups.get('Pin_Base')
    n_pin = sum((1 for v in dst.data.vertices for g in v.groups if pin and g.group == pin.index and (g.weight > 0)))
    ok = bool(bound_ok and sd_new and sd_new.is_bound)
    msg = tr(f"{dst.name}: копия {src.name} на другой стороне, {('привязана' if ok else 'НЕ привязана')}. Зона {len(weights)} верш. тела, крепление {n_pin} верш.")
    if inexact:
        msg += tr(f'; без точной зеркальной вершины {inexact} (взята ближайшая, до {worst:.1f} мм)')
    if shared:
        msg += tr(f'; источник доходит до середины тела — общие вершины зоны ({len(shared)}) поделены по сторонам')
    if scaled:
        msg += tr('; масштаб применён')
    msg += tr(f". У источника {NORMALS_FLIPPED_MSG.split(' —')[0]} — у копии развёрнуты наружу" if flipped else '. Нормали наружу') + (tr(', Cloth скопирован') if c_src else '')
    if backwall_of(src):
        build_backwall(context, dst)
        set_active_mode(context, dst, 'OBJECT')
    operator.report({'INFO'} if ok else {'WARNING'}, tr(msg))
    return dst

class OBJECT_OT_RitCromMirrorVertexProxy(bpy.types.Operator):
    """Копия выбранного прокси на другой стороне тела: своя зона влияния (зеркальные вершины тела),
    своя привязка, настройки Cloth — копия. Без отрицательного масштаба"""
    bl_idname = 'object.rct_mirror_vertex_proxy'
    bl_label = 'Отзеркалить на другую сторону'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = get_setup_proxy(context)
        return bool(p and p.type == 'MESH' and (get_proxy_type(p) in ('VOLUME', 'SURFACE')))

    def execute(self, context):
        src = get_setup_proxy(context)
        return {'FINISHED'} if mirror_proxy_copy(context, src, self) else {'CANCELLED'}
from . import bind
from .bind import bind_proxy
from .colliders import _proxy_zone, backwall_of, build_backwall, fill_proxy_collision_collection, proxy_collision_collection, shelf_bound_changed
