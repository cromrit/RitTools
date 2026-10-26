# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh

def mesh_shape_coords(context, obj):
    if not obj.data.shape_keys:
        mw = obj.matrix_world
        return [mw @ v.co for v in obj.data.vertices]
    tmp = bpy.data.objects.new('_rct_shape_eval', obj.data)
    tmp.matrix_world = obj.matrix_world
    context.scene.collection.objects.link(tmp)
    try:
        context.view_layer.update()
        dg = context.evaluated_depsgraph_get()
        ev = tmp.evaluated_get(dg)
        me = ev.to_mesh()
        mw = obj.matrix_world
        co = [mw @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
    return co

def vertex_group_has_weights(obj, vg_name):
    vg = obj.vertex_groups.get(vg_name)
    if not vg:
        return False
    gi = vg.index
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gi and g.weight > 0.0:
                return True
    return False

def mesh_is_closed(obj):
    me = obj.data
    if not me.polygons:
        return False
    edge_faces = [0] * len(me.edges)
    for p in me.polygons:
        for li in p.loop_indices:
            edge_faces[me.loops[li].edge_index] += 1
    return all((c >= 2 for c in edge_faces))
NORMALS_FLIPPED_MSG = 'нормали были внутрь (объём отрицательный) — развёрнуты наружу'

def ensure_outward_normals(obj):
    if obj.type != 'MESH' or not mesh_is_closed(obj):
        return False
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    vol = bm.calc_volume(signed=True) * (1.0 if obj.matrix_world.to_3x3().determinant() >= 0 else -1.0)
    if vol >= 0:
        bm.free()
        return False
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return True
PATCH_FLIPPED_MSG = 'Нормали тела смотрят внутрь — у копии выделения развёрнуты наружу (тело не менялось)'

def orient_patch_outward(context, proxy, body):
    from mathutils.bvhtree import BVHTree
    polys = proxy.data.polygons
    if not polys or not body or body.type != 'MESH' or (not body.data.polygons):
        return False
    tree = BVHTree.FromPolygons(mesh_shape_coords(context, body), [p.vertices[:] for p in body.data.polygons])
    mw = proxy.matrix_world
    nm = mw.inverted_safe().transposed().to_3x3()
    sgn = 1.0 if mw.to_3x3().determinant() >= 0 else -1.0
    eps = 0.0001
    out = inn = 0
    for i in range(0, len(polys), max(1, len(polys) // 400)):
        p = polys[i]
        c = mw @ p.center
        n = nm @ p.normal * sgn
        if n.length < 1e-12:
            continue
        n.normalize()
        fwd = tree.ray_cast(c + n * eps, n)[0] is not None
        back = tree.ray_cast(c - n * eps, -n)[0] is not None
        if back and (not fwd):
            out += 1
        elif fwd and (not back):
            inn += 1
    if inn <= out:
        return False
    bm = bmesh.new()
    bm.from_mesh(proxy.data)
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    bm.to_mesh(proxy.data)
    bm.free()
    cn = proxy.data.attributes.get('custom_normal')
    if cn:
        proxy.data.attributes.remove(cn)
    proxy.data.update()
    return True

def find_surface_deform(body, proxy):
    for m in body.modifiers:
        if m.type == 'SURFACE_DEFORM' and m.target == proxy:
            return m
    return None

def _gn_new_api_input(mod_geo, sid):
    props = getattr(mod_geo, 'properties', None)
    inputs = getattr(props, 'inputs', None) if props is not None else None
    if inputs is None:
        return None
    return getattr(inputs, sid, None)

def gn_value_owner(mod_geo, sid):
    sock = _gn_new_api_input(mod_geo, sid)
    if sock is not None:
        return (sock, 'value')
    return (mod_geo, f'["{sid}"]')
from . import naming
