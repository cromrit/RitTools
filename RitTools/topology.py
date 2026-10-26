# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bmesh
from mathutils import Vector

def _weld_and_prune(bm, stats):
    tm = bmesh.ops.find_doubles(bm, verts=bm.verts, dist=0.0001)['targetmap']
    stats['doubles'] += len(tm)
    if tm:
        bmesh.ops.weld_verts(bm, targetmap=tm)
    extra = set()
    for e in bm.edges:
        if len(e.link_faces) > 2:
            fs = sorted(e.link_faces, key=lambda f: f.calc_area(), reverse=True)
            extra.update(fs[2:])
    if extra:
        stats['extra_faces'] += len(extra)
        bmesh.ops.delete(bm, geom=list(extra), context='FACES_ONLY')
    degenerate = [f for f in bm.faces if f.calc_area() < 1e-12]
    if degenerate:
        bmesh.ops.delete(bm, geom=degenerate, context='FACES_ONLY')
    wire = [e for e in bm.edges if not e.link_faces]
    if wire:
        bmesh.ops.delete(bm, geom=wire, context='EDGES')
    loose = [v for v in bm.verts if not v.link_faces]
    stats['loose'] += len(loose) + len(wire) + len(degenerate)
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')

def clean_region_topology(obj):
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    avg_before = sum((f.normal * f.calc_area() for f in bm.faces), Vector())
    stats = {'doubles': 0, 'extra_faces': 0, 'loose': 0, 'smoothed': 0, 'concave': 0}
    _weld_and_prune(bm, stats)
    smoothed = set()
    for _ in range(10):
        bm.normal_update()
        bad = set()
        for f in bm.faces:
            nb = {g for e in f.edges for g in e.link_faces if g is not f}
            if nb:
                avg = sum((g.normal for g in nb), Vector())
                if avg.length > 1e-09 and f.normal.dot(avg.normalized()) < 0.0:
                    bad.update(f.verts)
        if not bad:
            break
        new_co = {}
        for v in bad:
            nbv = [e.other_vert(v) for e in v.link_edges]
            if nbv:
                new_co[v] = sum((x.co for x in nbv), Vector()) / len(nbv)
        for v, c in new_co.items():
            v.co = c
        smoothed |= {v.index for v in bad}
    stats['smoothed'] = len(smoothed)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    avg_after = sum((f.normal * f.calc_area() for f in bm.faces), Vector())
    if avg_before.length > 0 and avg_after.dot(avg_before) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    stats['concave'] = split_concave_quads(bm)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return stats

def split_concave_quads(bm):
    bm.normal_update()
    n = 0
    ngons = []
    for f in [f for f in bm.faces if len(f.verts) >= 4]:
        vs = list(f.verts)
        k_ = len(vs)
        turn = [(vs[(i + 1) % k_].co - vs[i].co).cross(vs[(i + 2) % k_].co - vs[(i + 1) % k_].co).dot(f.normal) for i in range(k_)]
        if all((t > 0.0 for t in turn)):
            continue
        if k_ > 4:
            ngons.append(f)
            continue
        k = (min(range(4), key=lambda i: turn[i]) + 1) % 4
        try:
            bmesh.ops.connect_verts(bm, verts=[vs[k], vs[(k + 2) % 4]])
            n += 1
        except Exception:
            pass
    if ngons:
        try:
            bmesh.ops.triangulate(bm, faces=ngons, quad_method='BEAUTY', ngon_method='EAR_CLIP')
            n += len(ngons)
        except Exception:
            pass
    return n

def intersecting_faces(bm):
    from mathutils.bvhtree import BVHTree
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm)
    fv = [{v.index for v in f.verts} for f in bm.faces]
    return [(a, b) for a, b in tree.overlap(tree) if a < b and (not fv[a] & fv[b])]

def self_intersections(bm):
    return len(intersecting_faces(bm))
RELAX_RINGS = 2

def relax_on_cast(bm, cast_tree, on_dist, max_iter=60):
    bm.verts.ensure_lookup_table()
    pairs = intersecting_faces(bm)
    before = len(pairs)
    if not before:
        return (0, 0, 0)
    dist = [cast_tree.find_nearest(v.co)[3] for v in bm.verts]
    on = {i for i, d in enumerate(dist) if d is not None and d < on_dist}
    it = 0
    while pairs and it < max_iter:
        zone = {v for ab in pairs for i in ab for v in bm.faces[i].verts}
        for _ in range(RELAX_RINGS):
            zone |= {e.other_vert(v) for v in zone for e in v.link_edges}
        free = [v for v in zone if not v.is_boundary and v.link_edges]
        new = {v: v.co.lerp(sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges), 0.5) for v in free}
        for v, c in new.items():
            if v.index in on:
                p, n, _i, d = cast_tree.find_nearest(c)
                if d > 1e-09 * (1.0 + c.length) and abs((c - p).normalized().dot(n.normalized())) < 0.99:
                    on.discard(v.index)
                else:
                    c = p
            v.co = c
        it += 1
        pairs = intersecting_faces(bm)
    left = len(pairs)
    bm.normal_update()
    return (before, left, it)
from . import pits_bumps
