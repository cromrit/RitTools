# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import re
from .mesh_utils import mesh_is_closed
PROXY_TYPES = {'VOLUME': ('Объём', 'MESH_UVSPHERE'), 'SURFACE': ('Поверхность', 'MESH_GRID'), 'HAIR': ('Волосы', 'STRANDS'), 'COLLISION': ('Коллизия', 'MOD_PHYSICS'), 'CLOTHING': ('Одежда', 'MOD_CLOTH')}

def drives_body(obj):
    return any((m.type == 'SURFACE_DEFORM' and m.target == obj for o in bpy.data.objects if o.type == 'MESH' for m in o.modifiers))

def is_clothing(obj):
    if not obj or obj.type != 'MESH':
        return False
    if obj.get('rct_type') == 'CLOTHING':
        return True
    return bool(obj.modifiers.get('DynCloth_FadeVW')) and (not drives_body(obj))

def get_proxy_type(obj):
    if not obj:
        return None
    t = obj.get('rct_type')
    if t in PROXY_TYPES:
        return t
    if 'hairproxy' in obj.name.lower() or obj.name.startswith('Proxy_Hair'):
        return 'HAIR'
    if obj.type == 'MESH' and obj.data.polygons:
        return 'VOLUME' if mesh_is_closed(obj) else 'SURFACE'
    return 'SURFACE'

def _unique_object_name(base, numbered=False):
    if not numbered and base not in bpy.data.objects:
        return base
    i = 1 if numbered else 2
    while f'{base}_{i:02d}' in bpy.data.objects:
        i += 1
    return f'{base}_{i:02d}'

def _proxy_side(obj, body=None):
    if obj.type != 'MESH' or not obj.data.vertices:
        return ''
    xs, scale = _x_in_body(obj, body)
    lo, hi = (min(xs), max(xs))
    eps = max(0.002 / scale, SIDE_CROSS_FRAC * (hi - lo))
    if lo > -eps and hi > eps:
        return '_L'
    if hi < eps and lo < -eps:
        return '_R'
    return ''
SIDE_CROSS_FRAC = 0.15

def _x_in_body(obj, body):
    if body:
        m = body.matrix_world.inverted() @ obj.matrix_world
        scale = max(max(body.matrix_world.to_scale()), 1e-06)
    else:
        m, scale = (obj.matrix_world, 1.0)
    return ([(m @ v.co).x for v in obj.data.vertices], scale)

def proxy_center_cross(obj, body):
    if obj.type != 'MESH' or not obj.data.vertices:
        return 0.0
    xs, scale = _x_in_body(obj, body)
    return max(min(-min(xs), max(xs)), 0.0) * scale * 1000.0

def proxy_body(obj):
    b = obj.get('rct_body') if obj else None
    if isinstance(b, bpy.types.Object) and b.name in bpy.data.objects:
        return b
    return None

def rename_proxy(obj, new_name):
    old = obj.name
    if new_name == old:
        return
    obj.name = new_name
    new = obj.name
    old_mask = obj.get('rct_mask') or f'Mask_{old}'
    new_mask = f'Mask_{new}'
    for body in [o for o in bpy.data.objects if o.type == 'MESH']:
        vg = body.vertex_groups.get(old_mask)
        if vg and new_mask not in body.vertex_groups:
            vg.name = new_mask
        for m in body.modifiers:
            if m.type == 'SURFACE_DEFORM' and m.target == obj:
                if m.vertex_group == old_mask:
                    m.vertex_group = new_mask
                if m.name == f'SurfDef_{old}':
                    m.name = f'SurfDef_{new}'
    if obj.get('rct_mask'):
        obj['rct_mask'] = new_mask
    if obj.get('rct_autoname') == old:
        obj['rct_autoname'] = new

def addon_created(obj):
    return bool(obj.get('rct_created') or (obj.get('rct_part') and (not obj.get('rct_part_manual'))) or (obj.get('rct_autoname') and obj.get('rct_autoname') == obj.name))

def auto_name_proxy(obj, label=None):
    ptype = get_proxy_type(obj)
    if ptype in ('COLLISION', 'CLOTHING'):
        return
    if obj.get('rct_user_proxy') or not addon_created(obj):
        return
    is_auto = obj.get('rct_autoname') == obj.name or not obj.name.startswith('Proxy_')
    if not is_auto:
        return
    if label is None and ptype != 'HAIR' and (obj.get('rct_preset') in PRESETS):
        label = PRESETS[obj['rct_preset']]['name']
        if label == 'Surface':
            label = None
    if ptype == 'HAIR':
        base, numbered = ('Proxy_Hair', True)
    else:
        base = 'Proxy_' + (label or {'VOLUME': 'Volume', 'SURFACE': 'Surface'}.get(ptype, 'Part'))
        base += _proxy_side(obj, proxy_body(obj))
        numbered = False
    if obj.name == base or re.fullmatch(re.escape(base) + '_\\d\\d', obj.name):
        obj['rct_autoname'] = obj.name
        return
    new = _unique_object_name(base, numbered)
    rename_proxy(obj, new)
    obj['rct_autoname'] = obj.name
from . import presets
from .presets import PRESETS
