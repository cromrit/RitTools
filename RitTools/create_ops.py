# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
import math
from mathutils import Vector, Matrix
from .helpers import apply_modifier, apply_modifiers_through, begin_fit_proportional, begin_fit_simplify, end_fit_session, end_fit_simplify, ensure_object_mode, hide_weight_overlay, move_modifier, set_active_mode
from .zone import apply_pin_from_cast_distance, bake_shape_key_mix, bake_world_scale, bake_world_transform, create_auto_body_mask, mirror_body_mask, not_a_body, NOT_BODY_MSG, selected_body_verts, store_cast_distance, strip_inherited_animation, zone_body_changed
from .topology import clean_region_topology, relax_on_cast, self_intersections, split_concave_quads
from .mesh_utils import ensure_outward_normals, find_surface_deform, NORMALS_FLIPPED_MSG, orient_patch_outward, PATCH_FLIPPED_MSG, vertex_group_has_weights
from .naming import _proxy_side, auto_name_proxy, proxy_body
from .presets import _cloth_mod, cloth_pin_group, reset_cloth_cache
from .manager import _add_to_proxy_manager, add_to_physics_collection, delete_proxy_fully, detect_proxy_part, get_setup_proxy, NO_SURFDEF_PARTS
from .proxy_core import bind_body_to_proxy, find_armature_for_obj, transfer_weights_to_proxy
from .i18n import tr
from .report import report_error

class OBJECT_OT_DataTransferBind(bpy.types.Operator):
    bl_idname = 'object.data_transfer_bind'
    bl_label = 'Привязать: Прокси <-> Тело'
    bl_description = 'Связывает прокси с телом для симуляции (Data Transfer + Surface Deform)'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_SpawnProxyPreset(bpy.types.Operator):
    bl_idname = 'object.spawn_proxy_preset'
    bl_label = 'Заспавнить Пресет'
    bl_options = {'REGISTER', 'UNDO'}
    preset_name: bpy.props.StringProperty()
_DENSE_OFF = False

class OBJECT_OT_GenerateVertexProxy(bpy.types.Operator):
    bl_idname = 'object.generate_vertex_proxy'
    bl_label = 'Создать Прокси из Вершин'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromClosePit(bpy.types.Operator):
    bl_idname = 'object.rct_close_pit'
    bl_label = 'Закрыть углубление'
    bl_description = 'Выделенные вершины прокси (Edit Mode) — углубление: их грани удаляются, дыра закрывается заплаткой по форме тела, прокси привязывается заново. Край прокси не меняется'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return bool(o and o.type == 'MESH' and (context.mode == 'EDIT_MESH'))

class OBJECT_OT_RitCromFlattenBump(bpy.types.Operator):
    bl_idname = 'object.rct_flatten_bump'
    bl_label = 'Выровнять выпуклость (устаревшее)'
    bl_description = 'Устаревшее, запасной вариант для готового прокси. Выделенные вершины прокси (Edit Mode) и полоса в одно ребро вокруг выравниваются по окружающей поверхности, прокси привязывается заново. Край и закреплённое не двигаются, тело не меняется. При создании прокси для этого есть «Заменять области плотной сетки»'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return bool(o and o.type == 'MESH' and (context.mode == 'EDIT_MESH'))

class OBJECT_OT_RitCromAutoFixProxy(bpy.types.Operator):
    bl_idname = 'object.rct_auto_fix_proxy'
    bl_label = 'Исправить автоматически'
    bl_description = 'Пересоздать прокси из того же выделения тела с исправлением сетки (очистка, заходы, выпуклости, вогнутые квады) и привязать заново. Тело не меняется'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ExtractAndCreateProxy(bpy.types.Operator):
    bl_idname = 'object.extract_and_create_proxy'
    bl_label = 'Создать слепок и Прокси-куб'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        orig_obj = context.active_object
        if not orig_obj or orig_obj.type != 'MESH' or context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, tr('Выберите Тело в Edit Mode и выделите нужные полигоны!'))
            return {'CANCELLED'}
        if not_a_body(context, orig_obj):
            self.report({'WARNING'}, tr(NOT_BODY_MSG))
            return {'CANCELLED'}
        self._simplify_was_on = False
        ok = False
        try:
            res = self._create(context, orig_obj)
            ok = 'FINISHED' in res
        finally:
            if not ok:
                end_fit_simplify(context.scene)
        if ok and self._simplify_was_on:
            self.report({'INFO'}, tr('Simplify в сцене выключен на время подгонки куба — вернётся на «Готово» или при отмене'))
        return res

    def _create(self, context, orig_obj):
        context.scene.proxy_original_body = orig_obj
        src_verts = selected_body_verts(orig_obj)
        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')
        new_objs = [o for o in context.selected_objects if o != orig_obj]
        if not new_objs:
            self.report({'WARNING'}, tr('Не удалось отделить полигоны!'))
            return {'CANCELLED'}
        temp_proxy = new_objs[0]
        temp_proxy.name = 'Temp_Proxy_Target'
        context.scene.proxy_temp_cast = temp_proxy
        strip_inherited_animation(temp_proxy)
        bake_shape_key_mix(context, temp_proxy)
        bake_world_transform(context, temp_proxy)
        cfix = clean_region_topology(temp_proxy)
        if cfix['doubles'] or cfix['extra_faces'] or cfix['smoothed']:
            self.report({'INFO'}, tr(f"Слепок (копия) очищен: дублей {cfix['doubles']}, лишних граней {cfix['extra_faces']}, разглажено вершин {cfix['smoothed']}"))
        if not temp_proxy.data.polygons:
            report_error(self, tr('Слепок пустой — выделите полигоны (грани), а не только точки'))
            bpy.data.objects.remove(temp_proxy)
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        temp_proxy.select_set(True)
        context.view_layer.objects.active = temp_proxy
        cc = [v.co for v in temp_proxy.data.vertices]
        lo = Vector((min((c.x for c in cc)), min((c.y for c in cc)), min((c.z for c in cc))))
        hi = Vector((max((c.x for c in cc)), max((c.y for c in cc)), max((c.z for c in cc))))
        center_loc = (lo + hi) / 2
        size = hi - lo
        size = Vector([max(s * 1.15, 0.05 * max(size)) for s in size])
        for obj in context.view_layer.objects:
            if obj == temp_proxy or obj.library:
                continue
            try:
                obj['was_hidden_before_proxy'] = obj.hide_get()
                obj.hide_set(True)
            except (RuntimeError, TypeError):
                pass
        if not context.scene.proxy_apply_subdiv:
            self._simplify_was_on = begin_fit_simplify(context.scene)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=center_loc)
        proxy_cube = context.active_object
        proxy_cube.data.transform(Matrix.Diagonal((size.x, size.y, size.z, 1.0)))
        proxy_cube.data.update()
        proxy_cube['rct_part'] = 'CUSTOM'
        proxy_cube['rct_body'] = orig_obj
        _add_to_proxy_manager(proxy_cube, context, 'VOLUME')
        mask_name = f'Mask_{proxy_cube.name}'
        create_auto_body_mask(orig_obj, src_verts, mask_name, context.scene.rct_zone_blur)
        proxy_cube['rct_mask'] = mask_name
        proxy_cube['rct_zone_verts'] = src_verts
        proxy_cube['rct_zone_body_vcount'] = len(orig_obj.data.vertices)
        proxy_cube.display_type = 'WIRE'
        proxy_cube.show_in_front = True
        context.view_layer.update()
        context.scene.proxy_active_cube = proxy_cube
        mod_sub = proxy_cube.modifiers.new('Subdivision', 'SUBSURF')
        mod_sub.levels = context.scene.proxy_cube_subdiv
        mod_sub.render_levels = context.scene.proxy_cube_subdiv
        mod_sub.show_in_editmode = True
        mod_sub.show_on_cage = False
        if context.scene.proxy_apply_subdiv:
            apply_modifier(context, proxy_cube, mod_sub.name)
        if 'Pin_Base' not in proxy_cube.vertex_groups:
            proxy_cube.vertex_groups.new(name='Pin_Base')
        add_to_physics_collection(proxy_cube, context)
        context.scene.proxy_custom_mesh = proxy_cube
        set_active_mode(context, proxy_cube, 'EDIT')
        hide_weight_overlay(context)
        context.tool_settings.mesh_select_mode = (True, False, False)
        begin_fit_proportional(context.scene, max(size) / 3)
        self.report({'INFO'}, tr('Слепок и куб созданы! Сцена изолирована. Куб в Edit Mode.'))
        return {'FINISHED'}

def _shrinkwrap_effect(context, obj, mod):

    def ev():
        context.view_layer.update()
        e = obj.evaluated_get(context.evaluated_depsgraph_get())
        m = e.to_mesh()
        out = [v.co.copy() for v in m.vertices]
        e.to_mesh_clear()
        return out
    mod.show_viewport = False
    a = ev()
    mod.show_viewport = True
    b = ev()
    if len(a) != len(b):
        return (len(b), len(b))
    return (sum((1 for x, y in zip(a, b) if (x - y).length > 1e-06)), len(b))

class OBJECT_OT_AddShrinkwrapLive(bpy.types.Operator):
    bl_idname = 'object.add_shrinkwrap_live'
    bl_label = 'Добавить Shrinkwrap (Живой режим)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        proxy = context.scene.proxy_active_cube
        temp_target = context.scene.proxy_temp_cast
        if not proxy or not temp_target:
            self.report({'WARNING'}, tr('Не найден прокси или слепок! Сначала создайте их на Шаге 1.'))
            return {'CANCELLED'}
        mod_shrink = proxy.modifiers.get('Shrinkwrap')
        if not mod_shrink:
            mod_shrink = proxy.modifiers.new('Shrinkwrap', 'SHRINKWRAP')
        if orient_patch_outward(context, temp_target, context.scene.proxy_original_body):
            self.report({'INFO'}, tr(PATCH_FLIPPED_MSG))
        mod_shrink.target = temp_target
        mod_shrink.wrap_method = 'PROJECT'
        mod_shrink.wrap_mode = 'INSIDE'
        mod_shrink.use_negative_direction = True
        mod_shrink.use_positive_direction = True
        mod_shrink.cull_face = 'OFF'
        mod_shrink.use_invert_cull = False
        mod_shrink.offset = 0.0
        mod_shrink.project_limit = 0.0
        mod_shrink.subsurf_levels = 0
        mod_shrink.use_project_x = mod_shrink.use_project_y = mod_shrink.use_project_z = False
        mod_shrink.vertex_group = ''
        mod_shrink.show_in_editmode = True
        mod_shrink.show_on_cage = False
        move_modifier(proxy, mod_shrink.name, len(proxy.modifiers) - 1)
        if context.scene.render.use_simplify and any((m.type == 'SUBSURF' for m in proxy.modifiers)):
            begin_fit_simplify(context.scene)
            self.report({'INFO'}, tr('Simplify выключен на время подгонки — вернётся на «Готово»'))
        set_active_mode(context, proxy, 'OBJECT')
        moved, total = _shrinkwrap_effect(context, proxy, mod_shrink)
        if moved == 0:
            self.report({'WARNING'}, tr('Shrinkwrap не притянул ни одной вершины: куб целиком за кожей или слепок пустой. Вытяните вершины куба наружу (перед кожей)'))
        elif moved < 0.1 * total:
            self.report({'WARNING'}, tr(f'Shrinkwrap притянул мало: {moved} из {total} вершин. Подвиньте вершины куба ближе к коже — притянутых станет больше'))
        else:
            self.report({'INFO'}, tr(f'Shrinkwrap: притянуто {moved} из {total} вершин. Посмотрите, как облегает; поправить — Tab (Edit Mode)'))
        return {'FINISHED'}

class OBJECT_OT_ApplyShrinkwrapAndRestore(bpy.types.Operator):
    bl_idname = 'object.apply_shrinkwrap_and_restore'
    bl_label = 'Применить Shrinkwrap и вернуть сцену'
    bl_description = 'Применить форму, сгладить складки, разрезать вогнутые квады, вернуть сцену и привязать прокси к телу (2–8 с)'
    bl_options = {'REGISTER', 'UNDO'}
    WAIT_TEXT = 'Привязка, подождите…'

    def invoke(self, context, event):
        if not (context.scene.proxy_active_cube and context.scene.proxy_temp_cast) or not context.window:
            return self.execute(context)
        self._area = context.area
        self._ticks = 0
        context.window.cursor_modal_set('WAIT')
        context.workspace.status_text_set(self.WAIT_TEXT)
        if self._area:
            self._area.header_text_set(self.WAIT_TEXT)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        self._ticks += 1
        if self._ticks < 2:
            return {'RUNNING_MODAL'}
        context.window_manager.event_timer_remove(self._timer)
        try:
            return self.execute(context)
        finally:
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            if self._area:
                self._area.header_text_set(None)

    def execute(self, context):
        proxy = context.scene.proxy_active_cube
        temp_target = context.scene.proxy_temp_cast
        if not proxy or not temp_target:
            self.report({'WARNING'}, tr('Временные объекты не найдены!'))
            return {'CANCELLED'}
        self._notes = []
        try:
            self._apply(context, proxy, temp_target)
        finally:
            end_fit_session(context)
        for obj in context.scene.objects:
            if obj.type == 'ARMATURE':
                if hasattr(obj.data, 'collections'):
                    b_col = obj.data.collections.get('RCT_Hidden_Hooks')
                    if b_col:
                        b_col.is_visible = False
        self._bind(context, proxy)
        body = proxy_body(proxy)
        sd = find_surface_deform(body, proxy) if body else None
        if context.scene.rct_vertex_mirror and sd and sd.is_bound and (not _proxy_side(proxy, body)):
            self._note(center_cross_msg(proxy, body), True)
        elif context.scene.rct_vertex_mirror and sd and sd.is_bound:
            held = _HeldReports()
            copy = mirror_proxy_copy(context, proxy, held)
            for kind, msg in held.items:
                if 'INFO' not in kind:
                    self._note(msg, True)
            if copy:
                self._note(f'копия {copy.name} на другой стороне')
                _add_to_proxy_manager(proxy, context)
        set_active_mode(context, proxy, 'OBJECT')
        warn = any((w for w, _ in self._notes))
        text = '; '.join((t for _, t in self._notes))
        self.report({'WARNING'} if warn else {'INFO'}, tr(f'Готово: {text}'))
        return {'FINISHED'}

    def _note(self, text, warn=False):
        self._notes.append((warn, text))

    def _apply(self, context, proxy, temp_target):
        set_active_mode(context, proxy, 'OBJECT')
        mod_shrink = proxy.modifiers.get('Shrinkwrap')
        if mod_shrink:
            try:
                apply_modifiers_through(context, proxy, mod_shrink.name)
            except Exception as e:
                self._note(f'ошибка применения Shrinkwrap: {e}', True)
        from mathutils.bvhtree import BVHTree
        tb = bmesh.new()
        tb.from_mesh(temp_target.data)
        tb.transform(temp_target.matrix_world)
        tt = BVHTree.FromBMesh(tb)
        tb.free()
        ref = max(temp_target.dimensions) or 1.0
        on_dist = 0.002 * ref
        mw = proxy.matrix_world.copy()
        ds = [tt.find_nearest(mw @ v.co)[3] for v in proxy.data.vertices]
        on = sum((1 for d in ds if d is not None and d < on_dist))
        if on == 0:
            self._note('ни одна вершина куба не легла на слепок — проверьте подгонку', True)
        elif on < 0.15 * len(ds):
            self._note(f'на слепок легло мало: {on} из {len(ds)} вершин — форма почти не подогнана. В следующий раз перед «Готово» подвиньте вершины куба ближе к коже', True)
        else:
            self._note(f'на слепок легло {on} из {len(ds)} вершин')
        bm = bmesh.new()
        bm.from_mesh(proxy.data)
        bm.transform(mw)
        before, left, _it = relax_on_cast(bm, tt, on_dist)
        cut = split_concave_quads(bm)
        bm.transform(mw.inverted())
        bm.to_mesh(proxy.data)
        bm.free()
        proxy.data.update()
        if before:
            self._note(f'сглажены складки (пересечений было {before})')
        if cut:
            self._note(f'разрезано вогнутых квадов: {cut}')
        try:
            store_cast_distance(proxy, temp_target)
            frac = apply_pin_from_cast_distance(proxy, context.scene.rct_pin_transition)
            if frac is not None and frac < 0.05:
                self._note(f'закреплено только {frac * 100:.0f}% вершин — прокси может провиснуть. Уменьшите «Ширину перехода» или дорисуйте точку крепления', True)
        except Exception as e:
            self._note(f'авто-точка крепления не посчиталась: {e}', True)
        if ensure_outward_normals(proxy):
            self._note(NORMALS_FLIPPED_MSG)

    def _bind(self, context, proxy):
        body = proxy_body(proxy) or context.scene.proxy_original_body
        if not body or body == proxy:
            self._note('тело не выбрано — привяжите прокси кнопкой «Привязать к скелету и телу»', True)
            return
        held = _HeldReports()
        nv = len(proxy.data.vertices)
        bind_proxy(context, proxy, body, held)
        if len(proxy.data.vertices) != nv:
            self._note(f'при привязке склеено вершин: {nv - len(proxy.data.vertices)}')
        bm = bmesh.new()
        bm.from_mesh(proxy.data)
        left = self_intersections(bm)
        bm.free()
        proxy['rct_self_intersections'] = left
        if left:
            self._note(f'самопересечений осталось {left} — подвиньте вершины прокси в Edit Mode и нажмите «Привязать к скелету и телу»', True)
        for kind, msg in held.items:
            self._note(msg, 'INFO' not in kind)
        sd = find_surface_deform(body, proxy)
        if sd and sd.is_bound:
            tri = proxy.modifiers.get('SurfDef_Triangulate')
            self._note(tr('привязан к телу') + (tr(' через Triangulate') if tri else ''), bool(tri))
        elif detect_proxy_part(proxy) not in NO_SURFDEF_PARTS:
            self._note('к телу НЕ привязан', True)

class OBJECT_OT_RitCromCubeCancel(bpy.types.Operator):
    bl_idname = 'object.rct_cube_cancel'
    bl_label = 'Отменить куб'
    bl_description = 'Удалить куб и слепок, вернуть видимость сцены и Simplify'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scn = context.scene
        cube = scn.proxy_active_cube
        body = scn.proxy_original_body
        if cube and cube.users_scene:
            delete_proxy_fully(context, cube)
        ensure_object_mode(context)
        end_fit_session(context)
        if body and body.users_scene:
            set_active_mode(context, body, 'OBJECT')
        self.report({'INFO'}, tr('Куб отменён, сцена возвращена'))
        return {'FINISHED'}

class OBJECT_OT_PreparePinGroup(bpy.types.Operator):
    bl_idname = 'object.prepare_pin_group'
    bl_label = 'Точка крепления'
    bl_description = 'Рисуется НА ПРОКСИ (группа Pin_Base): красным (1.0) — где прокси держится за скелет, синим (0.0) — свободно качается'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        proxy = get_setup_proxy(context)
        if not proxy or proxy.type != 'MESH':
            proxy = context.active_object
            if not proxy or proxy.type != 'MESH':
                self.report({'WARNING'}, tr('Выберите Proxy объект!'))
                return {'CANCELLED'}
        if 'Pin_Base' not in proxy.vertex_groups:
            proxy.vertex_groups.new(name='Pin_Base')
        set_active_mode(context, proxy, 'WEIGHT_PAINT')
        proxy.vertex_groups.active_index = proxy.vertex_groups['Pin_Base'].index
        mod_cloth = _cloth_mod(proxy)
        if mod_cloth and (not mod_cloth.settings.vertex_group_mass):
            mod_cloth.settings.vertex_group_mass = cloth_pin_group(proxy)
        self.report({'INFO'}, tr('Точка крепления (Pin_Base на прокси): красным (1.0) — держится за скелет.'))
        return {'FINISHED'}

class OBJECT_OT_PrepareBodyMask(bpy.types.Operator):
    bl_idname = 'object.prepare_body_mask'
    bl_label = 'Зона влияния (маска на теле)'
    bl_description = 'Рисуется НА ТЕЛЕ (группа Mask_<прокси>): какая кожа повторяет движение прокси. Красным — повторяет полностью, синим — не двигается за прокси'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        proxy = get_setup_proxy(context)
        body = (proxy_body(proxy) if proxy else None) or context.scene.proxy_original_body or context.scene.proxy_main_mesh
        if not body or body.type != 'MESH':
            self.report({'WARNING'}, tr('Не найдено оригинальное тело! Выделите его.'))
            return {'CANCELLED'}
        mask_name = f'Mask_{proxy.name}' if proxy else 'Proxy_Bind_Mask'
        if mask_name not in body.vertex_groups:
            body.vertex_groups.new(name=mask_name)
        if proxy:
            proxy['rct_mask'] = mask_name
            mod_surf = find_surface_deform(body, proxy)
            if mod_surf:
                mod_surf.vertex_group = mask_name
        set_active_mode(context, body, 'WEIGHT_PAINT')
        body.vertex_groups.active_index = body.vertex_groups[mask_name].index
        self.report({'INFO'}, tr(f'Маска {mask_name} подготовлена. Закрасьте красным зону реакции тела на прокси.'))
        return {'FINISHED'}

class OBJECT_OT_SmartMirrorProxy(bpy.types.Operator):
    bl_idname = 'object.smart_mirror_proxy'
    bl_label = 'Отзеркалить и Применить (Mirror)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        proxy = context.scene.proxy_active_cube or get_setup_proxy(context)
        center_obj = context.scene.proxy_original_body
        if not proxy or proxy.type != 'MESH':
            proxy = context.active_object
            if not proxy or proxy.type != 'MESH':
                self.report({'WARNING'}, tr('Выберите Proxy объект для отражения!'))
                return {'CANCELLED'}
        if not center_obj:
            self.report({'WARNING'}, tr('Объект центра (Оригинальное тело) не найден!'))
            return {'CANCELLED'}
        mod_mirror = proxy.modifiers.get('Mirror')
        if not mod_mirror:
            mod_mirror = proxy.modifiers.new('Mirror', 'MIRROR')
        mod_mirror.use_axis[0] = True
        mod_mirror.mirror_object = center_obj
        set_active_mode(context, proxy, 'OBJECT')
        try:
            apply_modifiers_through(context, proxy, mod_mirror.name)
        except Exception as e:
            self.report({'WARNING'}, tr(f'Не удалось применить Mirror: {e}'))
        for mod in list(proxy.modifiers):
            if mod.type in ['CLOTH', 'COLLISION', 'MIRROR']:
                proxy.modifiers.remove(mod)
        body = proxy_body(proxy) or center_obj
        mask = proxy.get('rct_mask') or f'Mask_{proxy.name}'
        if body and mask in body.vertex_groups:
            mirror_body_mask(body, mask)
            proxy['rct_zone_mirrored'] = True
        auto_name_proxy(proxy)
        if body and body != proxy and find_surface_deform(body, proxy):
            bind_proxy(context, proxy, body, self)
        self.report({'INFO'}, tr(f'Модификатор Mirror применен! Прокси: {proxy.name}'))
        return {'FINISHED'}
from . import mirror
from .bind import _HeldReports, bind_proxy
from .mirror import center_cross_msg, mirror_proxy_copy
