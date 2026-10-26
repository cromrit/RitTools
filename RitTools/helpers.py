# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
_MODE_MAP = {'EDIT_MESH': 'EDIT', 'EDIT_ARMATURE': 'EDIT', 'EDIT_CURVE': 'EDIT', 'EDIT_SURFACE': 'EDIT', 'EDIT_TEXT': 'EDIT', 'EDIT_METABALL': 'EDIT', 'EDIT_LATTICE': 'EDIT', 'PAINT_WEIGHT': 'WEIGHT_PAINT', 'PAINT_VERTEX': 'VERTEX_PAINT', 'PAINT_TEXTURE': 'TEXTURE_PAINT', 'SCULPT': 'SCULPT', 'POSE': 'POSE', 'OBJECT': 'OBJECT'}

def ensure_object_mode(context):
    obj = context.view_layer.objects.active
    if obj and obj.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass
    for o in context.view_layer.objects:
        if o.mode == 'EDIT' and o.type == 'MESH':
            prev = context.view_layer.objects.active
            context.view_layer.objects.active = o
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except RuntimeError:
                pass
            context.view_layer.objects.active = prev

def set_active_mode(context, obj, mode):
    ensure_object_mode(context)
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode=mode)
        except RuntimeError:
            pass

def hide_weight_overlay(context):
    screen = getattr(context, 'screen', None)
    for a in screen.areas if screen else []:
        if a.type == 'VIEW_3D' and a.spaces.active:
            a.spaces.active.overlay.show_weight = False

def move_modifier(obj, name, index):
    mods = obj.modifiers
    cur = mods.find(name)
    if cur < 0:
        return
    index = max(0, min(index, len(mods) - 1))
    if cur == index:
        return
    if hasattr(mods, 'move'):
        mods.move(cur, index)
    else:
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_move_to_index(modifier=name, index=index)

def place_modifier_before(obj, name, other_name):
    i, j = (obj.modifiers.find(name), obj.modifiers.find(other_name))
    if i >= 0 and j >= 0 and (i > j):
        move_modifier(obj, name, j)

def place_modifier_after_deform_base(obj, name):
    idx = -1
    for i, m in enumerate(obj.modifiers):
        if m.type == 'ARMATURE' and m.name != name:
            idx = i
    cur = obj.modifiers.find(name)
    if cur < 0:
        return
    target = idx + 1 if cur > idx else idx
    move_modifier(obj, name, target)
_PRE_SIM_TYPES = {'ARMATURE', 'NODES', 'WARP', 'HOOK', 'VERTEX_WEIGHT_MIX', 'VERTEX_WEIGHT_EDIT', 'VERTEX_WEIGHT_PROXIMITY', 'SHRINKWRAP', 'DATA_TRANSFER', 'SURFACE_DEFORM'}

def place_cloth_modifier(obj, name):
    cur = obj.modifiers.find(name)
    if cur < 0:
        return
    last_pre = -1
    for i, m in enumerate(obj.modifiers):
        if m.name != name and m.type in _PRE_SIM_TYPES:
            last_pre = i
    target = last_pre + 1 if cur > last_pre else last_pre
    move_modifier(obj, name, target)

def apply_modifier(context, obj, name):
    if obj.modifiers.find(name) < 0:
        return False
    move_modifier(obj, name, 0)
    render = context.scene.render
    simplify = render.use_simplify if obj.modifiers[name].type == 'SUBSURF' else False
    if simplify:
        render.use_simplify = False
    try:
        with context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_apply(modifier=name)
    finally:
        if simplify:
            render.use_simplify = True
    return True

def apply_modifiers_through(context, obj, name, types=('SUBSURF', 'MIRROR', 'SHRINKWRAP')):
    while True:
        idx = obj.modifiers.find(name)
        if idx < 0:
            return False
        above = [m.name for m in obj.modifiers[:idx] if m.type in types]
        if not above:
            break
        apply_modifier(context, obj, above[0])
    return apply_modifier(context, obj, name)

def restore_isolation(context):
    for obj in context.scene.objects:
        if obj.get('was_hidden_before_proxy') is not None:
            try:
                obj.hide_set(bool(obj['was_hidden_before_proxy']))
            except RuntimeError:
                pass
            del obj['was_hidden_before_proxy']
_FIT_SIMPLIFY_KEY = 'rct_fit_simplify'

def begin_fit_simplify(scene):
    if _FIT_SIMPLIFY_KEY not in scene:
        scene[_FIT_SIMPLIFY_KEY] = int(scene.render.use_simplify)
    was_on = scene.render.use_simplify
    scene.render.use_simplify = False
    return was_on

def end_fit_simplify(scene):
    if _FIT_SIMPLIFY_KEY not in scene:
        return False
    scene.render.use_simplify = bool(scene[_FIT_SIMPLIFY_KEY])
    del scene[_FIT_SIMPLIFY_KEY]
    return True
_FIT_PROP_KEY = 'rct_fit_proportional'

def begin_fit_proportional(scene, size):
    ts = scene.tool_settings
    if _FIT_PROP_KEY not in scene:
        scene[_FIT_PROP_KEY] = [int(ts.use_proportional_edit), ts.proportional_size]
    ts.use_proportional_edit = True
    ts.proportional_size = size

def end_fit_proportional(scene):
    if _FIT_PROP_KEY not in scene:
        return
    use, size = scene[_FIT_PROP_KEY]
    ts = scene.tool_settings
    ts.use_proportional_edit = bool(use)
    ts.proportional_size = size
    del scene[_FIT_PROP_KEY]

def fit_session_alive(scene):
    cube, cast = (scene.proxy_active_cube, scene.proxy_temp_cast)
    return bool(cube and cube.users_scene and cast and cast.users_scene)

def end_fit_session(context):
    scn = context.scene
    cast = scn.proxy_temp_cast
    if cast:
        scn.proxy_temp_cast = None
        try:
            bpy.data.objects.remove(cast, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    end_fit_simplify(scn)
    restore_isolation(context)
    end_fit_proportional(scn)
from . import zone
