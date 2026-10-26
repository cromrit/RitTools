# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
from .helpers import ensure_object_mode, place_modifier_before
from .naming import drives_body, get_proxy_type
from .manager import get_setup_proxy
from .proxy_core import find_armature_for_obj
from .i18n import tr

class OBJECT_OT_MakeClothingDynamic(bpy.types.Operator):
    bl_idname = 'object.make_clothing_dynamic'
    bl_label = 'Применить Cloth-Динамику'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_PaintDynamicClothing(bpy.types.Operator):
    bl_idname = 'object.paint_dynamic_clothing'
    bl_label = 'Рисовать Свободный Край'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ApplyClothPresetSilk(bpy.types.Operator):
    bl_idname = 'object.apply_cloth_preset_silk'
    bl_label = 'Шёлк'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ApplyClothPresetMedium(bpy.types.Operator):
    bl_idname = 'object.apply_cloth_preset_medium'
    bl_label = 'Плотная'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ApplyClothPresetElastic(bpy.types.Operator):
    bl_idname = 'object.apply_cloth_preset_elastic'
    bl_label = 'Упругая'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ApplySubdivision(bpy.types.Operator):
    bl_idname = 'object.apply_subdivision_cloth'
    bl_label = 'Добавить Subdivision (Мягкие углы)'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_AddArtificialImpact(bpy.types.Operator):
    bl_idname = 'object.add_artificial_impact'
    bl_label = 'Добавить физический импакт (Forcefield)'
    bl_description = 'Создает силовое поле для резкого физического воздействия на прокси-ткань (Artificial Impact)'
    bl_options = {'REGISTER', 'UNDO'}

def draw_collision_warning(layout):
    w = layout.box().column(align=True)
    w.alert = True
    w.label(text='ОЧЕНЬ ВАЖНО:', icon='ERROR')
    w.label(text='Если тело проваливается сквозь одежду,')
    w.label(text='выделите ЕГО и нажмите эту кнопку:')
    w.operator('object.apply_collision', text='Сделать Активный Объект Коллизией!', icon='MOD_PHYSICS')

def _manager_clothing(context):
    obj = get_setup_proxy(context)
    return obj if obj and obj.type == 'MESH' and (get_proxy_type(obj) == 'CLOTHING') else None

def draw_clothing_tab(layout, context):
    scn = context.scene
    box = layout.box()
    box.label(text='Одежда (Поверх тела):', icon='OUTLINER_OB_MESH')
    box.prop(scn, 'rct_clothing_obj', text='')
    man = _manager_clothing(context)
    if man and man != scn.rct_clothing_obj:
        c = box.column(align=True)
        c.label(text=tr(f'В менеджере выбрана {man.name}'), translate=False, icon='INFO')
        op = c.operator('wm.context_set_id', text='Взять из менеджера', icon='EYEDROPPER')
        op.data_path, op.value = ('scene.rct_clothing_obj', man.name)
    elif not man and (not scn.rct_clothing_obj):
        box.label(text='Выберите одежду в менеджере (фильтр', icon='INFO')
        box.label(text='«Одежда») или активный меш и нажмите')
        box.label(text='«Активировать Динамику».')
    layout.separator()
    col = layout.column(align=True)
    col.label(text='ШАГ 1: Динамика', icon='MOD_CLOTH')
    act = context.active_object
    can = bool(act and act.type == 'MESH')
    r = col.row()
    r.enabled = can
    r.operator('object.make_clothing_dynamic', icon='PLAY', text=tr(f'Активировать Динамику: {act.name}' if can else 'Активировать Динамику'), translate=False)
    if not can:
        col.label(text='Выделите меш одежды в сцене', icon='INFO')
    cloth_obj = scn.rct_clothing_obj
    if not (cloth_obj and cloth_obj.type == 'MESH'):
        return
    mod_vw = cloth_obj.modifiers.get('DynCloth_FadeVW')
    mod_cloth = cloth_obj.modifiers.get('Cloth')
    if not (mod_vw and mod_cloth):
        col.label(text=tr(f'У {cloth_obj.name} ещё нет динамики:'), translate=False, icon='INFO')
        col.label(text='выделите её и «Активировать Динамику».')
        return
    layout.separator()
    col = layout.column(align=True)
    col.label(text='Пресеты материала Ткани:', icon='MATERIAL')
    row_pres = col.row(align=True)
    row_pres.operator('object.apply_cloth_preset_silk')
    row_pres.operator('object.apply_cloth_preset_medium')
    row_pres.operator('object.apply_cloth_preset_elastic')
    layout.separator()
    col = layout.column(align=True)
    col.label(text='ШАГ 2: Рисовать Свободу', icon='BRUSH_DATA')
    col.operator('object.paint_dynamic_clothing', text='Рисовать свободный край')
    b = col.box()
    b.label(text='Красный (Вес 1.0): Привязка (Sticking)', icon='INFO')
    b.label(text='Темно-синий (Вес 0.0): Физика (Cloth)', icon='INFO')
    b.label(text='Отстаёт от хука — закрасьте СИНИМ сильнее', icon='INFO')
    layout.separator()
    col = layout.column(align=True)
    col.label(text='Анимация свободы:', icon='KEYINGSET')
    row = col.row()
    arm_obj = None
    for mod in cloth_obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            arm_obj = mod.object
            break
    target_prop_obj = arm_obj if arm_obj and 'Freedom' in arm_obj else cloth_obj
    if 'Freedom' in target_prop_obj:
        row.prop(target_prop_obj, '["Freedom"]', text='Освободить от Прокси')
    c_box = col.box()
    c_box.label(text='Если = 0.0 : Строго держится за Прокси (Прилегает)')
    c_box.label(text='Если = 1.0 : Отрывается и полностью симулируется')
    layout.separator()
    col = layout.column(align=True)
    col.label(text="Удаление 'квадратности':", icon='MOD_SMOOTH')
    mod_corr = cloth_obj.modifiers.get('DynCloth_Corrective')
    if mod_corr:
        col.row(align=True).prop(mod_corr, 'factor', text='Сила сглаживания (Corrective)')
    col.operator('object.apply_subdivision_cloth', icon='MOD_SUBSURF')
    col.label(text='* Corrective: сильно съедает объем мягких тканей!', icon='INFO')
    col.label(text='* Subdivision: сглаживает углы без потери объема', icon='INFO')
    layout.separator()
    draw_collision_warning(layout)
    op = layout.operator('wm.context_set_enum', text='Forcefield (импакт) — во вкладке «Ещё»', icon='FORCE_WIND')
    op.data_path, op.value = ('scene.rct_ui_tab', 'MORE')
    layout.separator()
    layout.label(text='Заметка: на свободный край можно')
    layout.label(text='вешать ХУКИ из вкладки «Хуки»!')
from . import colliders
