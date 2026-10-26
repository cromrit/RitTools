# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
import math
from mathutils import Vector, Matrix
from .helpers import ensure_object_mode, move_modifier, set_active_mode
from .zone import _smoothstep, zone_body_changed
from .mesh_utils import mesh_is_closed, mesh_shape_coords
from .naming import get_proxy_type, proxy_body
from .presets import _cloth_mod, reset_cloth_cache
from .manager import _add_to_proxy_manager, prune_proxy_list
from .proxy_core import find_armature_for_obj, transfer_weights_to_proxy
from .bind import _HeldReports
from .i18n import tr
COLLIDER_COLLECTION = 'RCT_Colliders'
COLLIDER_THICKNESS = 0.005
PIT_DEPTH_DEFAULT = {'BREAST': 0.004, 'BELLY': 0.004, 'BUTT': 0.004, 'THIGHS': 0.004}
SHELF_THICKNESS = 0.003
SHELF_ROWS_DEFAULT = 2
SHELF_REACH_DEFAULT = {'BREAST': 0.03, 'BELLY': 0.03, 'BUTT': 0.05, 'THIGHS': 0.05}
SHELF_FACING_MIN = 0.2
SHELF_LENGTH_DEFAULT = {'BREAST': 30.0, 'BELLY': 30.0, 'BUTT': 25.0, 'THIGHS': 25.0}
SHELF_LENGTH_MAX = {'BREAST': 80.0, 'BELLY': 80.0, 'BUTT': 50.0, 'THIGHS': 50.0}
SHELF_BOUND_CHANGED_MSG = 'Сетка тела изменилась — задайте нижнюю границу заново'

def _pit_get(self):
    if 'rct_pit_depth' in self:
        return float(self['rct_pit_depth'])
    return PIT_DEPTH_DEFAULT.get(self.get('rct_preset'), 0.004)

def _pit_set(self, value):
    self['rct_pit_depth'] = value

def _body_size_factor(obj):
    body = proxy_body(obj)
    if not body:
        return 1.0
    h = body.dimensions.z / max(abs(body.scale.z), 1e-06) * body.matrix_world.to_scale().z
    return max(1.0, h / 1.8)

def _shelf_prop(key, default):

    def get(self):
        if key in self:
            return float(self[key])
        d = default.get(self.get('rct_preset'), 0.03) if isinstance(default, dict) else default
        return d * _body_size_factor(self)

    def set_(self, value):
        self[key] = value
    return (get, set_)

def shelf_length_max(obj):
    return SHELF_LENGTH_MAX.get(obj.get('rct_preset'), 80.0)

def _shelf_len_get(self):
    if 'rct_shelf_length' in self:
        return min(float(self['rct_shelf_length']), shelf_length_max(self))
    return SHELF_LENGTH_DEFAULT.get(self.get('rct_preset'), 30.0)

def _shelf_len_set(self, value):
    self['rct_shelf_length'] = min(value, shelf_length_max(self))

def shelf_bound_changed(proxy):
    body = proxy_body(proxy)
    n = proxy.get('rct_shelf_bound_vcount')
    return bool(body and n is not None and (n != len(body.data.vertices)))

def _rigid_bone_meshes(arm):
    out = {}
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.parent == arm and (o.parent_type == 'BONE') and o.parent_bone and (not o.get('rct_type')) and o.users_scene and o.visible_get():
            out.setdefault(o.parent_bone, []).append(o)
    return out

def classify_skeleton(arm, body):
    warnings = []
    mw_a = arm.matrix_world
    mw_b = body.matrix_world
    co = mesh_shape_coords(bpy.context, body)
    if not co:
        return ({}, {}, ['У тела нет вершин'])
    zmin = min((p.z for p in co))
    zmax = max((p.z for p in co))
    H = max(zmax - zmin, 0.001)
    cx = sum((p.x for p in co)) / len(co)
    tol = max(0.01, 0.012 * H)
    names = {g.index: g.name for g in body.vertex_groups}
    deform = [b for b in arm.data.bones if b.use_deform]
    dset = {b.name for b in deform}
    verts = {b.name: [] for b in deform}
    for v in body.data.vertices:
        for g in v.groups:
            bn = names.get(g.group)
            if bn in dset and g.weight > 0.5:
                verts[bn].append(v.index)
    nodes = []
    node_of = {}
    for b in deform:
        h, t = (mw_a @ b.head_local, mw_a @ b.tail_local)
        for n in nodes:
            if (n['h'] - h).length < tol * 0.8 and (n['t'] - t).length < tol * 0.8:
                n['bones'].append(b.name)
                node_of[b.name] = n['id']
                break
        else:
            nodes.append({'id': len(nodes), 'h': h, 't': t, 'bones': [b.name]})
            node_of[b.name] = len(nodes) - 1
    rigid = _rigid_bone_meshes(arm)
    for n in nodes:
        idx = [i for bn in n['bones'] for i in verts[bn]]
        n['n'] = len(idx)
        n['rigid'] = sum((len(o.data.vertices) for bn in n['bones'] for o in rigid.get(bn, [])))
        n['c'] = sum((co[i] for i in idx), Vector()) / len(idx) if idx else (n['h'] + n['t']) / 2
    adj = {n['id']: set() for n in nodes}

    def link(a, b):
        if a != b:
            adj[a].add(b)
            adj[b].add(a)
    has_parent = set()
    for b in deform:
        p = b.parent
        while p and (not p.use_deform):
            p = p.parent
        if p:
            link(node_of[b.name], node_of[p.name])
            has_parent.add(node_of[b.name])
    for b in nodes:
        if b['id'] in has_parent:
            continue
        cands = [a for a in nodes if a is not b and (a['t'] - b['h']).length < tol]
        if cands:
            link(b['id'], max(cands, key=lambda a: (a['n'], -(a['t'] - b['h']).length))['id'])

    def central(n):
        return abs(n['c'].x - cx) < 0.05 * H
    mids = [n for n in nodes if central(n) and zmin + 0.2 * H < n['c'].z < zmin + 0.85 * H and (n['n'] > 0)]
    if not mids:
        return ({}, {}, ['Не найден таз (центральная кость середины тела) — выделите кости вручную'])
    root = max(mids, key=lambda n: n['n'])['id']

    def comp_of(start):
        seen, st = ({start}, [start])
        while st:
            x = st.pop()
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    st.append(y)
        return seen
    main = comp_of(root)
    for _ in range(len(nodes)):
        rest = [n for n in nodes if n['id'] not in main]
        if not rest:
            break
        best = None
        body_main = [m for m in main if nodes[m]['n'] > 0] or list(main)
        for n in rest:
            for m in body_main:
                mm = nodes[m]
                d = min(_point_segment_dist(n['h'], mm['h'], mm['t']), (n['h'] - mm['t']).length)
                if d < 0.06 * H and (best is None or d < best[0]):
                    best = (d, n['id'], m)
        if not best:
            break
        link(best[1], best[2])
        main = comp_of(root)
    parent = {root: None}
    order = [root]
    for x in order:
        for y in sorted(adj[x]):
            if y not in parent:
                parent[y] = x
                order.append(y)
    children = {i: [] for i in parent}
    for i, p in parent.items():
        if p is not None:
            children[p].append(i)

    def subtree(i):
        out, st = ([], [i])
        while st:
            x = st.pop()
            out.append(x)
            st.extend(children[x])
        return out
    sub_n = {}
    for i in reversed(order):
        sub_n[i] = nodes[i]['n'] + nodes[i]['rigid'] + sum((sub_n[c] for c in children[i]))
    for i in list(children):
        children[i] = [c for c in children[i] if sub_n[c] >= 5]
    alive, st = (set(), [root])
    while st:
        x = st.pop()
        alive.add(x)
        st.extend(children[x])
    parent = {i: p for i, p in parent.items() if i in alive}

    def pts(ids):
        return [nodes[i]['h'] for i in ids] + [nodes[i]['t'] for i in ids]
    spine = [root]
    while True:
        up = [c for c in children[spine[-1]] if max((p.z for p in pts(subtree(c)))) > nodes[spine[-1]]['t'].z - tol and abs(nodes[c]['c'].x - cx) < 0.06 * H]
        if not up:
            break
        spine.append(max(up, key=lambda c: max((p.z for p in pts(subtree(c))))))
    spine_set = set(spine)
    kinds_node = {}
    legs = []
    for sn in spine:
        for c in children[sn]:
            if c not in spine_set:
                sub = subtree(c)
                if min((p.z for p in pts(sub))) < zmin + 0.25 * H:
                    legs.append(sub)
                    for i in sub:
                        kinds_node[i] = 'LEG'
    arms = []
    for side in (1.0, -1.0):
        cand = [n for n in nodes if n['id'] in parent and n['id'] not in spine_set and (n['n'] > 0) and (kinds_node.get(n['id']) != 'LEG') and (n['c'].z > zmin + 0.3 * H)]
        if not cand:
            continue
        ext = max(cand, key=lambda n: side * (n['c'].x - cx))
        if side * (ext['c'].x - cx) < 0.12 * H:
            continue
        path = []
        x = ext['id']
        while x is not None and x not in spine_set:
            path.append(x)
            x = parent[x]
        path.reverse()
        if not path:
            continue
        arms.append(path)
    shoulder_z = None
    if arms:
        shoulder_z = sum((nodes[p[0]]['h'].z for p in arms)) / len(arms)
    else:
        shoulder_z = zmin + 0.8 * H
        warnings.append('Руки не найдены по структуре')
    if len(arms) != 2:
        warnings.append(f'Найдено рук: {len(arms)} (ожидалось 2)')
    for path in arms:
        start = 0
        first = nodes[path[0]]
        d = first['t'] - first['h']
        if len(path) > 2 and abs(first['h'].x - cx) < 0.12 * H and (abs(d.x) > 0.5 * d.length):
            kinds_node[path[0]] = 'SHOULDER'
            start = 1
        hand_k = next((k for k in range(start, len(path)) if len(children[path[k]]) >= 3), None)
        stop = hand_k if hand_k is not None else len(path) - 1
        for k in range(start, stop + 1):
            kinds_node[path[k]] = 'ARM'
        if hand_k is not None:
            for f in children[path[hand_k]]:
                chain, x = ([], f)
                while True:
                    chain.append(x)
                    if len(children[x]) != 1:
                        break
                    x = children[x][0]
                for k, i in enumerate(chain):
                    kinds_node[i] = 'ARM' if k == 0 and len(chain) >= 4 else 'FINGER'
                for i in subtree(f):
                    kinds_node.setdefault(i, 'FINGER')
        for i in subtree(path[0]):
            kinds_node.setdefault(i, 'OTHER')

    def head_n(i):
        return nodes[i]['n'] + nodes[i]['rigid']
    above = [i for i in spine if nodes[i]['c'].z > shoulder_z and head_n(i) > 0]
    head = None
    if above:
        top_n = max((head_n(i) for i in above))
        head = max((i for i in above if head_n(i) >= 0.25 * top_n), key=lambda i: nodes[i]['c'].z)
    if head is None:
        warnings.append('Голова не найдена (нет кости с вершинами выше плеч на конце позвоночника)')
    else:
        for i in subtree(head):
            kinds_node[i] = 'HEAD' if i == head else 'HEAD_PART'
        for i in spine[spine.index(head) - 1::-1] if head in spine else []:
            if nodes[i]['c'].z > shoulder_z:
                kinds_node.setdefault(i, 'NECK')
    for i in parent:
        kinds_node.setdefault(i, 'TORSO')
    kinds = {}
    for n in nodes:
        k = kinds_node.get(n['id'])
        if k:
            for bn in n['bones']:
                kinds[bn] = k
    spine_bones = {bn for i in spine for bn in nodes[i]['bones']}
    info = {'shoulder_z': shoulder_z, 'zmin': zmin, 'H': H, 'cx': cx, 'arms': len(arms), 'legs': len(legs), 'spine_bones': spine_bones, 'head': nodes[head]['bones'][0] if head is not None else None, 'nodes': nodes, 'node_of': node_of}
    return (kinds, info, warnings)

class _RestPose:
    """Временно переключить риг в REST — коллайдеры строятся по позе покоя."""

    def __init__(self, context, arm):
        self.context, self.arm, self.old = (context, arm, None)

    def __enter__(self):
        self.old = self.arm.data.pose_position
        self.arm.data.pose_position = 'REST'
        self.context.view_layer.update()
        return self

    def __exit__(self, *exc):
        self.arm.data.pose_position = self.old
        self.context.view_layer.update()
        return False

def _collider_collection(context):
    col = bpy.data.collections.get(COLLIDER_COLLECTION)
    if not col:
        col = bpy.data.collections.new(COLLIDER_COLLECTION)
        context.scene.collection.children.link(col)
    elif col.name not in context.scene.collection.children and (not any((col in c.children_recursive for c in [context.scene.collection]))):
        context.scene.collection.children.link(col)
    return col

def _support_default(obj):
    return obj.get('rct_preset') == 'BUTT' or obj.get('rct_part') == 'AssPhys'

def _support_get(self):
    if 'rct_support' in self:
        return bool(self['rct_support'])
    return _support_default(self)

def _support_set(self, value):
    self['rct_support'] = bool(value)

def _thickness_get(self):
    return self.collision.thickness_outer if getattr(self, 'collision', None) else 0.0

def _thickness_set(self, value):
    if getattr(self, 'collision', None):
        self.collision.thickness_outer = value

def _point_segment_dist(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return (p - (a + ab * t)).length

def _bvh_world(obj):
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    bm.free()
    return tree

def _inside(tree, p):
    d = Vector((0.5773, 0.5774, 0.5774))
    origin, count = (p.copy(), 0)
    for _ in range(64):
        hit = tree.ray_cast(origin, d)
        if hit[0] is None:
            break
        count += 1
        origin = hit[0] + d * 1e-05
    return count % 2 == 1

def _scene_proxies(context):
    out = []
    for item in context.scene.rct_proxies:
        o = item.obj_ptr
        if o and o.users_scene and (o.type == 'MESH') and (get_proxy_type(o) in ('VOLUME', 'SURFACE')):
            out.append(o)
    return out

def _hair_proxies(arm):
    objs = set()
    for pb in arm.pose.bones:
        for c in pb.constraints:
            if c.name == 'Hair_Track' and getattr(c, 'target', None):
                objs.add(c.target)
    return objs

class _BodyWeights:

    def __init__(self, body, arm, kinds):
        self.body, self.arm, self.kind = (body, arm, kinds)
        self.co = mesh_shape_coords(bpy.context, body)
        names = {g.index: g.name for g in body.vertex_groups}
        self.by_bone = {}
        self.torso_w = [0.0] * len(self.co)
        deform = {b.name for b in arm.data.bones if b.use_deform}
        for v in body.data.vertices:
            for g in v.groups:
                bn = names.get(g.group)
                if bn in deform and g.weight > 0.0:
                    if g.weight > 0.5:
                        self.by_bone.setdefault(bn, []).append(v.index)
                    if kinds.get(bn) in ('TORSO', 'SHOULDER'):
                        self.torso_w[v.index] += g.weight

def _proxy_zone(proxy, body):
    if proxy_body(proxy) not in (None, body):
        return None
    zone = set()
    verts = proxy.get('rct_zone_verts')
    if verts is not None and (not zone_body_changed(proxy)):
        zone |= {int(i) for i in verts}
    vg = body.vertex_groups.get(proxy.get('rct_mask') or '')
    if vg:
        for v in body.data.vertices:
            for g in v.groups:
                if g.group == vg.index and g.weight > 0.01:
                    zone.add(v.index)
    return zone or None

def proxy_collision_collection(context, proxy):
    col = proxy.get('rct_col_collection')
    if not isinstance(col, bpy.types.Collection) or col.name not in bpy.data.collections:
        parent = _collider_collection(context)
        col = bpy.data.collections.new(f'RCT_Col_{proxy.name}')
        col['rct_proxy_collision'] = True
        parent.children.link(col)
        proxy['rct_col_collection'] = col
    return col
_NOT_FOR_PROXY_KINDS = ('SHELF', 'TORSO', 'SHOULDER', 'BACKWALL')

def fill_proxy_collision_collection(p, col):
    main = bpy.data.collections.get(COLLIDER_COLLECTION)
    if not main:
        return
    want = {o for o in main.objects if o.get('rct_col_kind') not in _NOT_FOR_PROXY_KINDS or (o.get('rct_col_kind') == 'SHELF' and o.get('rct_shelf_of') == p) or (o.get('rct_col_kind') == 'BACKWALL' and o.get('rct_backwall_of') == p)}
    for o in list(col.objects):
        if o not in want:
            col.objects.unlink(o)
    for o in want:
        if o.name not in col.objects:
            col.objects.link(o)

def sync_collision_collections(context):
    main = bpy.data.collections.get(COLLIDER_COLLECTION)
    if not main:
        return
    used = set()
    proxies = _scene_proxies(context)
    proxies += [o for o in context.scene.objects if o not in proxies and o.type == 'MESH' and isinstance(o.get('rct_col_collection'), bpy.types.Collection) and (get_proxy_type(o) in ('VOLUME', 'SURFACE', 'CLOTHING'))]
    for p in proxies:
        col = proxy_collision_collection(context, p)
        used.add(col.name)
        fill_proxy_collision_collection(p, col)
        m = _cloth_mod(p)
        if m:
            m.collision_settings.collection = col
    for c in list(main.children):
        if c.get('rct_proxy_collision') and c.name not in used:
            bpy.data.collections.remove(c)
BACKWALL_THICKNESS = 0.03
BACKWALL_GAP = 0.005
BACKWALL_GROW = 1.15
BACKWALL_FACING = 0.5

def backwall_of(proxy):
    return next((o for o in bpy.data.objects if o.get('rct_col_kind') == 'BACKWALL' and o.get('rct_backwall_of') == proxy), None)

def remove_backwall(proxy):
    for o in list(bpy.data.objects):
        if o.get('rct_col_kind') == 'BACKWALL' and o.get('rct_backwall_of') in (proxy, None):
            mesh = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)

def build_backwall(context, proxy):
    remove_backwall(proxy)
    pin = proxy.vertex_groups.get('Pin_Base')
    if not pin or not mesh_is_closed(proxy):
        return (None, 'нужен закрытый сзади прокси (объём) с Pin_Base')
    k = _body_size_factor(proxy)
    th, off = (BACKWALL_THICKNESS * k, (BACKWALL_THICKNESS + BACKWALL_GAP) * k)
    w = proxy.copy()
    w.data = proxy.data.copy()
    w.name = w.data.name = f'Col_BackWall_{proxy.name}'
    for key in list(w.keys()):
        del w[key]
    w.animation_data_clear()
    for c in list(w.constraints):
        w.constraints.remove(c)
    for m in list(w.modifiers):
        if m.type != 'ARMATURE':
            w.modifiers.remove(m)
    for c in list(w.users_collection):
        c.objects.unlink(w)
    _collider_collection(context).objects.link(w)
    bm = bmesh.new()
    bm.from_mesh(w.data)
    dl = bm.verts.layers.deform.active
    pinned = {v for v in bm.verts if dl and v[dl].get(pin.index, 0.0) > 0.99}
    keep = [f for f in bm.faces if all((v in pinned for v in f.verts))]
    back = sum((f.normal * f.calc_area() for f in keep), Vector())
    if not keep or back.length < 1e-09:
        bm.free()
        bpy.data.objects.remove(w, do_unlink=True)
        return (None, 'нет закреплённой задней стенки (Pin_Base 1)')
    back.normalize()
    keep = {f for f in keep if f.normal.dot(back) > BACKWALL_FACING}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in keep], context='FACES')
    c = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    for v in bm.verts:
        d = v.co - c
        depth = d.dot(back)
        v.co = c + (d - back * depth) * BACKWALL_GROW + back * (depth + off)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(w.data)
    bm.free()
    w.data.update()
    w.display_type = 'WIRE'
    w.show_in_front = False
    w.hide_render = True
    w['rct_type'] = 'COLLISION'
    w['rct_col_kind'] = 'BACKWALL'
    w['rct_backwall_of'] = proxy
    w.modifiers.new('Collision', 'COLLISION')
    s = w.collision
    s.thickness_outer = th
    s.thickness_inner = 0.2 * k
    s.use_culling = True
    s.use_normal = True
    s.damping = 0.0
    s.cloth_friction = 0.0
    sync_collision_collections(context)
    m = _cloth_mod(proxy)
    if m:
        col = proxy_collision_collection(context, proxy)
        fill_proxy_collision_collection(proxy, col)
        m.collision_settings.collection = col
        reset_cloth_cache(context, m)
    return (w, '')

def check_collider_intersections(context, colliders, report):
    for col in colliders:
        tree = _bvh_world(col)
        closed = mesh_is_closed(col)
        th = col.collision.thickness_outer if col.collision else COLLIDER_THICKNESS
        for p in _scene_proxies(context) + [h for h in context.scene.objects if get_proxy_type(h) == 'HAIR']:
            if p.type != 'MESH':
                continue
            bad = 0
            m = _cloth_mod(p)
            pin = p.vertex_groups.get(m.settings.vertex_group_mass) if m and m.settings.vertex_group_mass else None
            for v in p.data.vertices:
                if pin and any((g.group == pin.index and g.weight > 0.5 for g in v.groups)):
                    continue
                q = p.matrix_world @ v.co
                res = tree.find_nearest(q)
                if res[0] is None:
                    continue
                if closed and _inside(tree, q) or res[3] < th * 0.5:
                    bad += 1
            if bad:
                report.append(f'{col.name} пересекает {p.name} ({bad} верш.)')

def set_cloth_collision_collection(context, objs):
    col = bpy.data.collections.get(COLLIDER_COLLECTION)
    if not col:
        return
    for o in objs:
        m = _cloth_mod(o)
        if m:
            m.collision_settings.collection = col

def remove_colliders(context, kinds):
    for o in list(bpy.data.objects):
        if o.get('rct_type') == 'COLLISION' and o.get('rct_col_kind') in kinds:
            mesh = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    prune_proxy_list(context.scene)

def _collider_body_and_arm(context, op):
    body = context.scene.proxy_original_body
    if not body or body.type != 'MESH':
        op.report({'WARNING'}, tr('Укажите тело'))
        return (None, None)
    arm = body.find_armature() or find_armature_for_obj(body)
    if not arm:
        op.report({'WARNING'}, tr('У тела нет Armature — не из чего строить коллизии'))
        return (None, None)
    return (body, arm)

def _finish_colliders(context, op, created, report):
    for o in created:
        _add_to_proxy_manager(o, context, 'COLLISION')
    targets = []
    arm = None
    body = context.scene.proxy_original_body
    if body:
        arm = body.find_armature() or find_armature_for_obj(body)
    if arm:
        targets += list(_hair_proxies(arm))
    targets += [o for o in context.scene.objects if get_proxy_type(o) == 'HAIR']
    set_cloth_collision_collection(context, set(targets))
    sync_collision_collections(context)
    check_collider_intersections(context, created, report)
    for line in report:
        print(f'[RitTools] коллизии: {line}')
    polys = ', '.join((f'{o.name}: {len(o.data.polygons)}' for o in created))
    if polys:
        print(f'[RitTools] коллизии, полигонов: {polys}')
    if report:
        op.report({'WARNING'}, tr(f'Коллизии: {len(report)} замечаний — см. консоль. {report[0]}'))
    op.report({'INFO'}, tr(f'Создано коллайдеров: {len(created)}'))

class OBJECT_OT_RitCromCollidersFromSkeleton(bpy.types.Operator):
    """Коллайдеры по скелету в REST-позе: голова, руки, (пальцы), опоры туловища"""
    bl_idname = 'object.rct_colliders_from_skeleton'
    bl_label = 'Коллизии из скелета'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromCollidersFromSelectedBones(bpy.types.Operator):
    """Запасной вариант: капсулы на кости, выделенные в Pose Mode (bone parent, без Armature)"""
    bl_idname = 'object.rct_colliders_from_selected_bones'
    bl_label = 'Коллизия на выделенные кости'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.type == 'ARMATURE' and (context.mode == 'POSE')

class OBJECT_OT_RitCromUpdateTorsoCollider(bpy.types.Operator):
    """Пересобрать коллайдер туловища под текущий набор прокси и их галочки «Опора снизу»"""
    bl_idname = 'object.rct_update_torso_collider'
    bl_label = 'Обновить коллайдер тела'
    bl_options = {'REGISTER', 'UNDO'}
SHELF_LIVE_DELAY = 0.3
_shelf_live_pending = set()

def shelf_built(proxy):
    return any((o.get('rct_col_kind') == 'SHELF' and o.get('rct_shelf_of') == proxy for o in bpy.data.objects))

def shelf_prop_update(self, context):
    _shelf_live_pending.add(self.name)
    if bpy.app.timers.is_registered(shelf_live_rebuild):
        bpy.app.timers.unregister(shelf_live_rebuild)
    bpy.app.timers.register(shelf_live_rebuild, first_interval=SHELF_LIVE_DELAY)

def shelf_live_rebuild():
    context = bpy.context
    scn = context.scene
    if context.mode != 'OBJECT':
        return 1.0
    names, _ = (set(_shelf_live_pending), _shelf_live_pending.clear())
    if not any((p and p.rct_support and shelf_built(p) and (scn.proxy_original_body == proxy_body(p)) for p in map(bpy.data.objects.get, names))):
        return None
    idx = scn.rct_proxy_index
    win = context.window_manager.windows[0] if context.window_manager.windows else None
    if win:
        area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
        with context.temp_override(window=win, screen=win.screen, area=area):
            bpy.ops.object.rct_update_torso_collider()
    else:
        rebuild_torso_collider(context, _HeldReports())
    if scn.rct_proxy_index != idx:
        scn.rct_proxy_index = idx
    return None

class OBJECT_OT_RitCromShelfSetBound(bpy.types.Operator):
    """Полка тянется ровно до выделенной на теле петли/полигонов (вместо «Длины полки»).
    Выделите в Edit Mode тела и нажмите"""
    bl_idname = 'object.rct_shelf_set_bound'
    bl_label = 'Задать нижнюю границу'
    bl_options = {'REGISTER', 'UNDO'}
    proxy_name: bpy.props.StringProperty()

class OBJECT_OT_RitCromShelfClearBound(bpy.types.Operator):
    """Убрать нижнюю границу — длина полки снова по «Длине полки»"""
    bl_idname = 'object.rct_shelf_clear_bound'
    bl_label = 'Сбросить границу'
    bl_options = {'REGISTER', 'UNDO'}
    proxy_name: bpy.props.StringProperty()
from . import panel
from .panel import rebuild_torso_collider
