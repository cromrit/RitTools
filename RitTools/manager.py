# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
from .helpers import _FIT_SIMPLIFY_KEY, end_fit_session, end_fit_simplify, ensure_object_mode
from .mesh_utils import mesh_is_closed
from .naming import auto_name_proxy, get_proxy_type, is_clothing, proxy_body, PROXY_TYPES
from .presets import _cloth_mod, apply_cloth_preset, check_proxy_scale, copy_cloth_to_mirror, DEFAULT_PRESET, mirror_partners, PRESETS
from .i18n import tr, wrap
from . import edition
_syncing_from_scene = False
_last_active = None

def sync_index_to_active(scene, view_layer):
    global _syncing_from_scene, _last_active
    act = view_layer.objects.active
    name = act.name if act else None
    if name == _last_active:
        return
    _last_active = name
    proxies = getattr(scene, 'rct_proxies', None)
    if not act or not proxies:
        return
    idx = next((i for i, it in enumerate(proxies) if it.obj_ptr == act and (not proxy_entry_is_dead(it))), -1)
    if idx < 0 or idx == scene.rct_proxy_index:
        return
    _syncing_from_scene = True
    try:
        scene.rct_proxy_index = idx
    finally:
        _syncing_from_scene = False

def _proxy_index_update(self, context):
    scn = self
    if not 0 <= scn.rct_proxy_index < len(scn.rct_proxies):
        return
    obj = scn.rct_proxies[scn.rct_proxy_index].obj_ptr
    if not obj or obj.name not in context.view_layer.objects:
        return
    body = proxy_body(obj)
    if body:
        scn.proxy_original_body = body
    if get_proxy_type(obj) == 'CLOTHING' and obj.type == 'MESH':
        scn.rct_clothing_obj = obj
    if context.mode != 'OBJECT' or _syncing_from_scene:
        return
    for o in context.selected_objects:
        o.select_set(False)
    try:
        obj.select_set(True)
        context.view_layer.objects.active = obj
    except RuntimeError:
        pass

class RitCromProxyItem(bpy.types.PropertyGroup):
    """Property group for storing references to generated proxies"""
    obj_ptr: bpy.props.PointerProperty(name='Proxy Object', type=bpy.types.Object, description='Reference to the proxy object')

def proxy_entry_is_dead(item):
    obj = item.obj_ptr
    return obj is None or obj.users == 0 or len(obj.users_scene) == 0

def prune_proxy_list(scene):
    proxies = scene.rct_proxies
    removed = 0
    for i in range(len(proxies) - 1, -1, -1):
        if proxy_entry_is_dead(proxies[i]):
            proxies.remove(i)
            removed += 1
    if scene.rct_proxy_index >= len(proxies):
        scene.rct_proxy_index = max(0, len(proxies) - 1)
    return removed

def migrate_clothing_entries(scene):
    n = 0
    for item in scene.rct_proxies:
        o = item.obj_ptr
        if o and o.get('rct_type') in ('VOLUME', 'SURFACE') and is_clothing(o):
            o['rct_type'] = 'CLOTHING'
            n += 1
    return n

def fit_simplify_orphaned(scene):
    if _FIT_SIMPLIFY_KEY not in scene:
        return False
    cast = getattr(scene, 'proxy_temp_cast', None)
    return not (cast and cast.users_scene)

@bpy.app.handlers.persistent
def _rct_load_post(_dummy):
    for scene in bpy.data.scenes:
        if hasattr(scene, 'rct_proxies'):
            prune_proxy_list(scene)
            migrate_clothing_entries(scene)
        if fit_simplify_orphaned(scene):
            end_fit_simplify(scene)

@bpy.app.handlers.persistent
def _rct_depsgraph_post(scene, _depsgraph=None):
    proxies = getattr(scene, 'rct_proxies', None)
    if proxies and any((proxy_entry_is_dead(i) for i in proxies)):
        try:
            prune_proxy_list(scene)
        except (AttributeError, RuntimeError):
            pass
    if fit_simplify_orphaned(scene):
        try:
            end_fit_simplify(scene)
        except (AttributeError, RuntimeError):
            pass
    vl = getattr(bpy.context, 'view_layer', None)
    if vl and bpy.context.scene == scene:
        try:
            sync_index_to_active(scene, vl)
        except (AttributeError, RuntimeError):
            pass

def get_setup_proxy(context):
    scn = context.scene
    if 0 <= scn.rct_proxy_index < len(scn.rct_proxies):
        item = scn.rct_proxies[scn.rct_proxy_index]
        if not proxy_entry_is_dead(item):
            return item.obj_ptr
    for obj in (scn.proxy_active_cube, scn.proxy_custom_mesh):
        if obj and obj.users_scene:
            return obj
    return None

class RCT_UL_ProxyList(bpy.types.UIList):
    """Список прокси: иконка типа, имя, кнопка удаления"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout = wrap(layout)
        obj = item.obj_ptr
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if obj is None or not obj.users_scene:
                layout.label(text='<удалён из сцены>', icon='ERROR')
            else:
                label, type_icon = proxy_kind_label(obj)
                row = layout.row(align=True)
                row.prop(obj, 'name', text='', emboss=False, icon=type_icon)
                sub = row.row()
                sub.alignment = 'RIGHT'
                sub.label(text=tr(label) + (' ⚙' if _cloth_mod(obj) else ''), translate=False)
            op = layout.operator('object.rct_proxy_remove', text='', icon='X', emboss=False)
            op.index = index
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text='', icon=PROXY_TYPES.get(get_proxy_type(obj), ('', 'QUESTION'))[1])

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt = context.scene.rct_ui_filter
        return ([0 if proxy_entry_is_dead(it) or not _proxy_filter_ok(it.obj_ptr, flt) else self.bitflag_filter_item for it in items], [])
_REMOVE_MODES = [('LIST', 'Убрать из списка', 'Прокси остаётся в сцене, просто пропадает из менеджера'), ('FULL', 'Удалить полностью', 'Удалить прокси-объект, его физику и хуки, а также Surface Deform / Data Transfer / Shrinkwrap и маски на теле и одежде, которые на него ссылались')]

def delete_proxy_fully(context, obj):
    ensure_object_mode(context)
    name = obj.name
    mask_names = {obj.get('rct_mask') or '', f'Mask_{name}'} - {''}
    fitting = context.scene.proxy_active_cube == obj and context.scene.proxy_temp_cast is not None
    arm_obj = find_armature_for_obj(obj)
    bones = []
    for i in range(1, HOOK_MAX_SLOTS + 1):
        bones.extend(_hook_bone_names(obj, i))
    if arm_obj and bones:
        delete_bones(context, arm_obj, bones)
    ref_attrs = ('target', 'object', 'object_from', 'object_to', 'mirror_object', 'offset_object')
    removable = {'SURFACE_DEFORM', 'DATA_TRANSFER', 'SHRINKWRAP', 'WARP', 'HOOK', 'VERTEX_WEIGHT_PROXIMITY'}
    for o in bpy.data.objects:
        if o == obj:
            continue
        if o.type == 'MESH':
            for m in list(o.modifiers):
                if m.type in removable and any((getattr(m, a, None) == obj for a in ref_attrs)):
                    o.modifiers.remove(m)
            for mn in mask_names:
                vg = o.vertex_groups.get(mn)
                if vg:
                    o.vertex_groups.remove(vg)
        for c in list(o.constraints):
            if getattr(c, 'target', None) == obj:
                o.constraints.remove(c)
        if o.type == 'ARMATURE' and o.pose:
            for pb in o.pose.bones:
                for c in list(pb.constraints):
                    if getattr(c, 'target', None) == obj:
                        pb.constraints.remove(c)
    for scn in bpy.data.scenes:
        for attr in ('proxy_active_cube', 'proxy_custom_mesh', 'proxy_temp_cast', 'rct_cloth_obj', 'shrink_target', 'rct_clothing_obj'):
            if getattr(scn, attr, None) == obj:
                setattr(scn, attr, None)
        proxies = scn.rct_proxies
        for i in range(len(proxies) - 1, -1, -1):
            if proxies[i].obj_ptr == obj:
                proxies.remove(i)
        if scn.rct_proxy_index >= len(proxies):
            scn.rct_proxy_index = max(0, len(proxies) - 1)
    for o in list(bpy.data.objects):
        if o.get('rct_col_kind') == 'BACKWALL' and o.get('rct_backwall_of') == obj:
            wm = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if wm and wm.users == 0:
                bpy.data.meshes.remove(wm)
    mesh = obj.data if obj.type == 'MESH' else None
    geo = obj.modifiers.get('DynamicPin_Geo') if obj.type == 'MESH' else None
    tree = geo.node_group if geo else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    if tree and tree.users == 0:
        bpy.data.node_groups.remove(tree)
    if arm_obj and bones:
        cleanup_hook_rig(arm_obj)
    if fitting:
        end_fit_session(context)

class OBJECT_OT_RitCromAddOwnProxy(bpy.types.Operator):
    """Сделать свой меш (не созданный аддоном) прокси: в менеджер, тип по сетке, пустая Pin_Base.
    Ничего существующего не меняет — дальше общий блок: точка крепления, привязка, пресет"""
    bl_idname = 'object.rct_add_own_proxy'
    bl_label = 'Добавить свой прокси'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromProxyRemove(bpy.types.Operator):
    """Удалить прокси: убрать из списка или удалить полностью вместе со всеми связями"""
    bl_idname = 'object.rct_proxy_remove'
    bl_label = 'Удалить прокси'
    bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE'})
    mode: bpy.props.EnumProperty(name='Как удалить', items=_REMOVE_MODES, default='LIST')

    def _target_index(self, context):
        return self.index if self.index >= 0 else context.scene.rct_proxy_index

    def invoke(self, context, event):
        prune_proxy_list(context.scene)
        if not context.scene.rct_proxies:
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=360, title=tr(self.bl_label), translate=False)

    def draw(self, context):
        proxies = context.scene.rct_proxies
        i = self._target_index(context)
        obj = proxies[i].obj_ptr if 0 <= i < len(proxies) else None
        layout = wrap(self.layout)
        layout.label(text=tr(f"Прокси: {(obj.name if obj else '?')}"), translate=False, icon='OUTLINER_OB_MESH')
        layout.prop(self, 'mode', expand=True)

    def execute(self, context):
        scn = context.scene
        proxies = scn.rct_proxies
        i = self._target_index(context)
        if not 0 <= i < len(proxies):
            return {'CANCELLED'}
        obj = proxies[i].obj_ptr
        if self.mode == 'FULL' and obj and obj.users_scene:
            name = obj.name
            delete_proxy_fully(context, obj)
            self.report({'INFO'}, tr(f'Прокси {name} удалён полностью'))
        else:
            proxies.remove(i)
            self.report({'INFO'}, tr('Убрано из списка'))
        if scn.rct_proxy_index >= len(proxies):
            scn.rct_proxy_index = max(0, len(proxies) - 1)
        prune_proxy_list(scn)
        return {'FINISHED'}

class OBJECT_OT_RitCromProxyClearAll(bpy.types.Operator):
    """Очистить весь менеджер прокси"""
    bl_idname = 'object.rct_proxy_clear_all'
    bl_label = 'Очистить всё'
    bl_options = {'REGISTER', 'UNDO'}
    mode: bpy.props.EnumProperty(name='Как удалить', items=_REMOVE_MODES, default='LIST')

    def invoke(self, context, event):
        prune_proxy_list(context.scene)
        if not context.scene.rct_proxies:
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(self, width=360, title=tr(self.bl_label), translate=False)

    def draw(self, context):
        n = len(context.scene.rct_proxies)
        layout = wrap(self.layout)
        layout.label(text=tr(f'Все прокси в списке: {n}'), translate=False, icon='ERROR')
        layout.prop(self, 'mode', expand=True)

    def execute(self, context):
        scn = context.scene
        proxies = scn.rct_proxies
        n = len(proxies)
        if self.mode == 'FULL':
            objs = [proxies[i].obj_ptr for i in range(n - 1, -1, -1)]
            for obj in objs:
                if obj and obj.users_scene:
                    delete_proxy_fully(context, obj)
        proxies.clear()
        scn.rct_proxy_index = 0
        self.report({'INFO'}, tr(f'Менеджер очищен ({n})'))
        return {'FINISHED'}

class OBJECT_OT_RitCromApplyPreset(bpy.types.Operator):
    """Применить выбранный пресет физики к прокси"""
    bl_idname = 'object.rct_apply_preset'
    bl_label = 'Применить пресет'
    bl_options = {'REGISTER', 'UNDO'}
    preset: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        obj = get_setup_proxy(context)
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, tr('Нет прокси — создайте его или выберите в менеджере'))
            return {'CANCELLED'}
        ptype = get_proxy_type(obj)
        if ptype == 'COLLISION':
            self.report({'WARNING'}, tr('Это коллайдер — пресеты физики к нему не применяются'))
            return {'CANCELLED'}
        if ptype == 'CLOTHING':
            self.report({'WARNING'}, tr(f'{obj.name} — одежда: физика настраивается во вкладке «Одежда»'))
            return {'CANCELLED'}
        pid = self.preset or getattr(context.scene, f'rct_preset_{ptype.lower()}', DEFAULT_PRESET[ptype])
        if PRESETS.get(pid, {}).get('type') != ptype:
            pid = DEFAULT_PRESET[ptype]
        objs = [obj]
        if context.scene.rct_phys_both:
            objs += [p for p in mirror_partners(obj) if p.type == 'MESH' and get_proxy_type(p) == ptype]
        auto = None
        for o in objs:
            check_proxy_scale(context, o, self)
            if ptype != 'HAIR' and (not proxy_binding_ok(o)):
                body = proxy_body(o) or context.scene.proxy_original_body
                if body and body != o:
                    bind_proxy(context, o, body, self)
                else:
                    self.report({'WARNING'}, tr('Тело не выбрано — физика без привязки к телу'))
            apply_cloth_preset(context, o, pid, self)
            if triangulate_above_cloth(o):
                self.report({'WARNING'}, tr(f'{o.name}: SurfDef_Triangulate стоит ВЫШЕ Cloth — физика считается на треугольниках. Переместите его под Cloth.'))
        _add_to_proxy_manager(obj, context)
        self.report({'INFO'}, tr(f"Пресет «{PRESETS[pid]['label']}» применён к {', '.join((o.name for o in objs))}") + (tr(', подобран по форме') if pid == 'BREAST' and auto else ''))
        return {'FINISHED'}

class OBJECT_OT_RitCromAutoBreastPhys(bpy.types.Operator):
    """Подобрать Вес, Упругость и Надутие по форме прокси груди (без запекания). Галочка «Обе стороны» — и паре"""
    bl_idname = 'object.rct_auto_breast_phys'
    bl_label = 'Подобрать по форме'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromSyncMirrorPhys(bpy.types.Operator):
    """Скопировать всю физику (Cloth) этого прокси его зеркальной паре"""
    bl_idname = 'object.rct_sync_mirror_phys'
    bl_label = 'Сделать вторую сторону такой же'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = get_setup_proxy(context)
        done = copy_cloth_to_mirror(obj) if obj else []
        if not done:
            self.report({'WARNING'}, tr('Нет зеркальной пары с физикой'))
            return {'CANCELLED'}
        self.report({'INFO'}, tr(f"Физика {obj.name} скопирована: {', '.join(done)}"))
        return {'FINISHED'}

def _add_to_proxy_manager(obj, context, ptype=None):
    if not obj:
        return
    if ptype:
        obj['rct_type'] = ptype
    elif not obj.get('rct_type'):
        obj['rct_type'] = get_proxy_type(obj)
    auto_name_proxy(obj)
    scn = context.scene
    for i, item in enumerate(scn.rct_proxies):
        if item.obj_ptr == obj:
            if scn.rct_proxy_index != i:
                scn.rct_proxy_index = i
            return
    proxy_item = scn.rct_proxies.add()
    proxy_item.obj_ptr = obj
    scn.rct_proxy_index = len(scn.rct_proxies) - 1
    scn.rct_ui_create_open = False

def add_to_physics_collection(obj, context):
    physics_col = bpy.data.collections.get('Physics')
    if not physics_col:
        physics_col = bpy.data.collections.new('Physics')
        context.scene.collection.children.link(physics_col)
    for col in list(obj.users_collection):
        if col.name not in ['Physics', 'ProxyHair']:
            try:
                col.objects.unlink(obj)
            except Exception:
                pass
    if obj.name not in physics_col.objects:
        physics_col.objects.link(obj)
NO_SURFDEF_PARTS = {'Body collision', 'Head collision', 'HANDS'}

def detect_proxy_part(obj):
    part = obj.get('rct_part')
    if part:
        return part
    n = obj.name.lower()
    if 'collision' in n:
        return 'Body collision'
    if 'hands' in n:
        return 'HANDS'
    if 'hair' in n:
        return 'HAIR'
    if 'ass' in n or 'glute' in n or 'ягодиц' in n:
        return 'AssPhys'
    if 'thigh' in n or 'ляжк' in n:
        return 'ThighsPhys'
    if 'tits' in n or 'soft' in n or 'breast' in n or ('груд' in n):
        return 'TitsPhys'
    if n.startswith('proxy_part'):
        return 'TitsPhys'
    return None
from . import proxy_core
from .proxy_core import find_armature_for_obj, HOOK_MAX_SLOTS
from .bind import bind_proxy, proxy_binding_ok, triangulate_above_cloth
from .hooks import _hook_bone_names, cleanup_hook_rig, delete_bones
from .panel import _proxy_filter_ok, proxy_kind_label
