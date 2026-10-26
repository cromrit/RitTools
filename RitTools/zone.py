# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
from mathutils import Vector, Matrix

def _smoothstep(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)

def _mesh_adjacency(me):
    adj = [[] for _ in range(len(me.vertices))]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    return adj

def _assign_weights(obj, vg_name, weights, clear=True):
    vg = obj.vertex_groups.get(vg_name) or obj.vertex_groups.new(name=vg_name)
    if clear:
        vg.remove(list(range(len(obj.data.vertices))))
    by_w = {}
    for i, w in weights.items():
        if w > 0.0:
            by_w.setdefault(round(w, 4), []).append(i)
    for w, idx in by_w.items():
        vg.add(idx, w, 'REPLACE')
    return vg

def mask_holes(me, inside, adj=None):
    if not inside:
        return []
    adj = adj or _mesh_adjacency(me)
    vs = me.vertices
    lo = [min((vs[i].co[k] for i in inside)) for k in range(3)]
    hi = [max((vs[i].co[k] for i in inside)) for k in range(3)]
    tol = max((hi[k] - lo[k] for k in range(3))) * 0.02
    limit = max(50, len(inside) // 4)
    seen, leaked, out = (set(), set(), [])
    for s in sorted({j for i in inside for j in adj[i] if j not in inside}):
        if s in seen:
            continue
        comp, stack, leak = ([], [s], False)
        seen.add(s)
        while stack:
            v = stack.pop()
            comp.append(v)
            co = vs[v].co
            if len(comp) > limit or any((co[k] < lo[k] - tol or co[k] > hi[k] + tol for k in range(3))):
                leak = True
                if len(comp) > limit:
                    break
            for j in adj[v]:
                if j in inside:
                    continue
                if j in leaked:
                    leak = True
                elif j not in seen:
                    seen.add(j)
                    stack.append(j)
        if leak:
            leaked.update(comp)
            leaked.update(stack)
        else:
            out.append(comp)
    return out

def fill_mask_holes(me, weights, adj=None):
    adj = adj or _mesh_adjacency(me)
    filled = 0
    w_min = 5e-05
    for comp in mask_holes(me, {i for i, w in weights.items() if w >= w_min}, adj):
        rest = set(comp)
        while rest:
            layer = {}
            for v in rest:
                ws = [weights[j] for j in adj[v] if weights.get(j, 0.0) >= w_min]
                if ws:
                    layer[v] = sum(ws) / len(ws)
            if not layer:
                break
            weights.update(layer)
            rest -= layer.keys()
            filled += len(layer)
    return (weights, filled)

def selected_body_verts(body):
    if body.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(body.data)
        bm.verts.index_update()
        return [v.index for v in bm.verts if v.select]
    return [v.index for v in body.data.vertices if v.select]
NOT_BODY_MSG = 'Это слепок или прокси, а не тело — выделите вершины на самом теле'

def not_a_body(context, obj):
    return obj == context.scene.proxy_temp_cast or obj.name.startswith('Temp_Proxy_Target') or 'rct_part' in obj

def _world_kdtree(points):
    from mathutils.kdtree import KDTree
    kd = KDTree(max(1, len(points)))
    for i, co in enumerate(points):
        kd.insert(co, i)
    kd.balance()
    return kd
ZONE_AUTO_BLUR_FRAC = 0.5

def create_auto_body_mask(body, vert_indices, mask_name, blur):
    sel = set(vert_indices)
    if not sel:
        return None
    me = body.data
    adj = _mesh_adjacency(me)
    for comp in mask_holes(me, sel, adj):
        sel.update(comp)
    mw = body.matrix_world
    edge = [i for i in sel if any((n not in sel for n in adj[i]))]
    weights = {i: 1.0 for i in sel}
    if edge:
        kd = _world_kdtree([mw @ me.vertices[i].co for i in sorted({n for i in edge for n in adj[i] if n not in sel})])
        edge_set = set(edge)
        seen = set()
        for s in sel:
            if s in seen:
                continue
            comp, stack = ([], [s])
            seen.add(s)
            while stack:
                v = stack.pop()
                comp.append(v)
                for j in adj[v]:
                    if j in sel and j not in seen:
                        seen.add(j)
                        stack.append(j)
            if edge_set.isdisjoint(comp):
                continue
            dist = {i: kd.find(mw @ me.vertices[i].co)[2] for i in comp}
            b = max(blur, ZONE_AUTO_BLUR_FRAC * max(dist.values()))
            for i, d in dist.items():
                weights[i] = _smoothstep(d / b)
        weights = {i: w for i, w in weights.items() if w > 0.0}
    fill_mask_holes(me, weights, adj)
    return _assign_weights(body, mask_name, weights)

def mirror_body_mask(body, mask_name):
    vg = body.vertex_groups.get(mask_name)
    if not vg:
        return
    me = body.data
    kd = _world_kdtree([v.co for v in me.vertices])
    gi = vg.index
    weights = {}
    for v in me.vertices:
        for g in v.groups:
            if g.group == gi and g.weight > 0.0:
                weights[v.index] = g.weight
    tol = max(body.dimensions) / max(max(body.scale), 1e-06) * 0.01 if me.vertices else 0.001
    merged = dict(weights)
    for i, w in weights.items():
        co = me.vertices[i].co
        _co, j, d = kd.find(Vector((-co.x, co.y, co.z)))
        if j is not None and d <= tol:
            merged[j] = max(merged.get(j, 0.0), w)
    fill_mask_holes(me, merged)
    _assign_weights(body, mask_name, merged)
ZONE_BODY_CHANGED_MSG = 'Сетка тела изменилась — создайте зону заново или докрасьте вручную'

def zone_body_changed(proxy):
    body = proxy_body(proxy)
    n = proxy.get('rct_zone_body_vcount')
    return bool(body and n is not None and (n != len(body.data.vertices)))

def recompute_zone_mask(proxy, blur):
    body = proxy_body(proxy)
    verts = proxy.get('rct_zone_verts')
    mask = proxy.get('rct_mask')
    if not (body and verts is not None and mask):
        return False
    if zone_body_changed(proxy):
        print(f'[RitTools] {proxy.name}: {ZONE_BODY_CHANGED_MSG}')
        return False
    create_auto_body_mask(body, list(verts), mask, blur)
    if proxy.get('rct_zone_mirrored'):
        mirror_body_mask(body, mask)
    if proxy.get('rct_sparse_bind'):
        rebind_sparse(proxy, body)
    return True

def rebind_sparse(proxy, body):
    sd = find_surface_deform(body, proxy)
    if not sd or not sd.use_sparse_bind:
        return False
    arm = body.find_armature() or find_armature_for_obj(body)
    old = arm.data.pose_position if arm else None
    try:
        if arm:
            arm.data.pose_position = 'REST'
        bpy.context.view_layer.update()
        with bpy.context.temp_override(object=body, active_object=body):
            if sd.is_bound:
                bpy.ops.object.surfacedeform_bind(modifier=sd.name)
            bpy.ops.object.surfacedeform_bind(modifier=sd.name)
        bpy.context.view_layer.update()
        body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    finally:
        if arm:
            arm.data.pose_position = old
    if not sd.is_bound:
        print(f'[RitTools] {proxy.name}: после изменения маски привязка не прошла — нажмите «Привязать» заново')
    return sd.is_bound

def _zone_blur_update(self, context):
    proxy = get_setup_proxy(context)
    if proxy and proxy.type == 'MESH':
        recompute_zone_mask(proxy, self.rct_zone_blur)
CAST_DIST_ATTR = 'rct_cast_dist'

def store_cast_distance(proxy, cast):
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(cast.data)
    bm.transform(cast.matrix_world)
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    mw = proxy.matrix_world
    me = proxy.data
    attr = me.attributes.get(CAST_DIST_ATTR) or me.attributes.new(CAST_DIST_ATTR, 'FLOAT', 'POINT')
    for v in me.vertices:
        hit = tree.find_nearest(mw @ v.co)
        attr.data[v.index].value = hit[3] if hit[0] is not None else 1000000.0
    proxy[CAST_ON_KEY] = CAST_ON_FRAC * (max(cast.dimensions) or 1.0)
CAST_ON_KEY = 'rct_cast_on'
CAST_ON_FRAC = 0.002
PIN_MIN_WEIGHT = 0.05
EDGE_DIST_ATTR = 'rct_pin_dist'

def _surface_distance(me, sources, scale=1.0):
    import heapq
    co = [v.co for v in me.vertices]
    adj = _mesh_adjacency(me)
    dist = [float('inf')] * len(co)
    heap = []
    for i in sources:
        dist[i] = 0.0
        heap.append((0.0, i))
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist[i]:
            continue
        for j in adj[i]:
            nd = d + (co[i] - co[j]).length * scale
            if nd < dist[j]:
                dist[j] = nd
                heapq.heappush(heap, (nd, j))
    return dist
PIN_FULL_DEPTH_FRAC = 0.75
PIN_BACK_FACING = (0.4, 0.8)
PIN_DOWN_FACING = (0.3, 0.7)
PIN_DOWN_DEPTH_FRAC = 0.1

def apply_pin_from_cast_distance(proxy, width):
    me = proxy.data
    attr = me.attributes.get(CAST_DIST_ATTR)
    if not attr or proxy.mode == 'EDIT':
        return None
    width = max(width, 1e-05)
    on = proxy.get(CAST_ON_KEY) or 0.001
    dist = [attr.data[i].value for i in range(len(me.vertices))]
    back = [i for i, d in enumerate(dist) if d >= on]
    full = PIN_FULL_DEPTH_FRAC * max((dist[i] for i in back), default=0.0)
    from mathutils import Vector
    mw = proxy.matrix_world
    m3 = mw.to_3x3()
    co = [mw @ v.co for v in me.vertices]
    front = [i for i, d in enumerate(dist) if d < on]
    axis = Vector()
    if front and back:
        axis = (sum((co[i] for i in front), Vector()) / len(front) - sum((co[i] for i in back), Vector()) / len(back)).normalized()
    nrm = [(m3 @ v.normal).normalized() for v in me.vertices]
    center = sum(co, Vector()) / max(1, len(co))
    if sum((n.dot(co[i] - center) for i, n in enumerate(nrm))) < 0:
        nrm = [-n for n in nrm]
    down = Vector(bpy.context.scene.gravity)
    down = down.normalized() if down.length > 1e-06 else Vector((0.0, 0.0, -1.0))
    w = [0.0] * len(dist)
    for i in back:
        by_depth = _smoothstep(dist[i] / full) if full > 0 else 1.0
        facing_back = _smoothstep((-nrm[i].dot(axis) - PIN_BACK_FACING[0]) / (PIN_BACK_FACING[1] - PIN_BACK_FACING[0]))
        facing_down = _smoothstep((nrm[i].dot(down) - PIN_DOWN_FACING[0]) / (PIN_DOWN_FACING[1] - PIN_DOWN_FACING[0]))
        bottom = facing_down * (_smoothstep(dist[i] / (PIN_DOWN_DEPTH_FRAC * full / PIN_FULL_DEPTH_FRAC)) if full > 0 else 1.0)
        w[i] = max(by_depth, facing_back, bottom)
    adj = _mesh_adjacency(me)
    scale = max(proxy.matrix_world.to_scale())
    in_back = set(back)
    for i in back:
        if w[i] <= 0.0 or all((j in in_back for j in adj[i])):
            continue
        for j, g in enumerate(_surface_distance(me, [i], scale)):
            if j not in in_back and g < width:
                w[j] = max(w[j], w[i] * (1.0 - _smoothstep(g / width)))
    w = [0.0 if x < PIN_MIN_WEIGHT else x for x in w]
    _assign_weights(proxy, 'Pin_Base', dict(enumerate(w)))
    return sum((1 for x in w if x > 0.5)) / max(1, len(w))

def apply_pin_from_edge_distance(proxy, width):
    me = proxy.data
    attr = me.attributes.get(EDGE_DIST_ATTR)
    if not attr:
        return None
    width = max(width, 1e-05)
    w = [1.0 - _smoothstep(attr.data[i].value / width) for i in range(len(me.vertices))]
    w = [0.0 if x < PIN_MIN_WEIGHT else x for x in w]
    _assign_weights(proxy, 'Pin_Base', dict(enumerate(w)))
    return sum((1 for x in w if x > 0.5)) / max(1, len(w))

def _pin_transition_update(self, context):
    proxy = get_setup_proxy(context)
    if proxy and proxy.type == 'MESH' and proxy.data.attributes.get(CAST_DIST_ATTR):
        apply_pin_from_cast_distance(proxy, self.rct_pin_transition)

def _edge_pin_width_update(self, context):
    proxy = get_setup_proxy(context)
    if proxy and proxy.type == 'MESH' and proxy.data.attributes.get(EDGE_DIST_ATTR):
        apply_pin_from_edge_distance(proxy, self.rct_edge_pin_width)

def bake_shape_key_mix(context, obj):
    if not obj.data.shape_keys:
        return
    with context.temp_override(object=obj, active_object=obj):
        try:
            bpy.ops.object.shape_key_remove(all=True, apply_mix=True)
            return
        except Exception:
            pass
    obj.shape_key_clear()

def _scale_is_one(m, tol=0.0001):
    return all((abs(x - 1.0) < tol for x in m.to_scale()))

def bake_world_scale(context, obj):
    context.view_layer.update()
    mw = obj.matrix_world.copy()
    if _scale_is_one(mw) and mw.to_3x3().determinant() > 0:
        return False
    mirrored = mw.to_3x3().determinant() < 0
    loc, rot, sca = mw.decompose()
    obj.delta_location = (0.0, 0.0, 0.0)
    obj.delta_rotation_euler = (0.0, 0.0, 0.0)
    obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.delta_scale = (1.0, 1.0, 1.0)
    try:
        obj.data.transform(Matrix.Diagonal((sca.x, sca.y, sca.z, 1.0)), shape_keys=True)
    except TypeError:
        obj.data.transform(Matrix.Diagonal((sca.x, sca.y, sca.z, 1.0)))
    if mirrored:
        obj.data.flip_normals()
    obj.data.update()
    obj.matrix_world = Matrix.LocRotScale(loc, rot, None)
    context.view_layer.update()
    return True
_TRANSFORM_PATHS = {'location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale', 'delta_location', 'delta_rotation_euler', 'delta_rotation_quaternion', 'delta_scale'}

def strip_inherited_animation(obj):
    if obj.animation_data:
        obj.animation_data_clear()

def bake_world_transform(context, obj):
    context.view_layer.update()
    mw = obj.matrix_world.copy()
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.parent = None
    obj.delta_location = (0.0, 0.0, 0.0)
    obj.delta_rotation_euler = (0.0, 0.0, 0.0)
    obj.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.data.transform(mw)
    obj.data.update()
    obj.matrix_world = Matrix.Identity(4)
    context.view_layer.update()
from . import topology
from .mesh_utils import find_surface_deform, mesh_is_closed
from .naming import proxy_body
from .manager import get_setup_proxy
from .proxy_core import find_armature_for_obj
