# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
bl_info = {'name': 'RitTools Free', 'author': 'RitCrom', 'version': (1, 37, 3), 'blender': (4, 0, 0), 'location': 'View3D > Sidebar > RitTools', 'description': 'Автопроксирование, Dynamic binding (Vertex/Custom) + Автосоздание ткани + Пресеты', 'category': 'Rigging'}
if 'bpy' in locals():
    import sys
    for _m in [m for m in sys.modules if m.startswith(__name__ + '.')]:
        del sys.modules[_m]
        globals().pop(_m.rpartition('.')[2], None)
import bpy
from . import i18n, edition, helpers, zone, topology, pits_bumps, dense, mesh_utils, naming, presets, manager, proxy_core, create_ops, mirror, bind, hooks, shrink_hair, hooks_ui, clothing, colliders, panel, autophys, report, bake
from .i18n import RitCromPreferences, apply_language, enum_default, enum_items, unregister_language
from .zone import _edge_pin_width_update, _pin_transition_update, _zone_blur_update
from .presets import _PRESET_ENUMS, DEFAULT_PRESET, register_cloth_ui_props, unregister_cloth_ui_props
from .manager import _rct_depsgraph_post, _rct_load_post, _proxy_index_update, RCT_UL_ProxyList, RitCromProxyItem, OBJECT_OT_RitCromAddOwnProxy, OBJECT_OT_RitCromApplyPreset, OBJECT_OT_RitCromAutoBreastPhys, OBJECT_OT_RitCromSyncMirrorPhys, OBJECT_OT_RitCromProxyClearAll, OBJECT_OT_RitCromProxyRemove
from .create_ops import OBJECT_OT_AddShrinkwrapLive, OBJECT_OT_ApplyShrinkwrapAndRestore, OBJECT_OT_RitCromAutoFixProxy, OBJECT_OT_RitCromClosePit, OBJECT_OT_RitCromCubeCancel, OBJECT_OT_RitCromFlattenBump, OBJECT_OT_DataTransferBind, OBJECT_OT_ExtractAndCreateProxy, OBJECT_OT_GenerateVertexProxy, OBJECT_OT_PrepareBodyMask, OBJECT_OT_PreparePinGroup, OBJECT_OT_SmartMirrorProxy, OBJECT_OT_SpawnProxyPreset
from .mirror import OBJECT_OT_RitCromMirrorVertexProxy
from .bind import OBJECT_OT_ApplyBreastClothPreset, OBJECT_OT_ApplyCollision, OBJECT_OT_ApplyGluteClothPreset, OBJECT_OT_ApplyThighClothPreset, OBJECT_OT_CreateBaseGroup, OBJECT_OT_TransferAndBind
from .hooks import RitCromHookSlot, OBJECT_OT_RitCromHookShowZone, OBJECT_OT_ClearHooks, OBJECT_OT_ClearSingleHook, OBJECT_OT_DynamicGrab, OBJECT_OT_SelectHookBone, OBJECT_OT_SnapHookToVertex
from .shrink_hair import OBJECT_OT_ApplyShrinkwrap, OBJECT_OT_ClearHairBindings, OBJECT_OT_CreateShrinkGroup, OBJECT_OT_GenerateHairProxy, OBJECT_OT_PaintProxyInfluence
from .hooks_ui import OBJECT_OT_RitCromHookEditProxy, OBJECT_OT_RitCromHookPickProxy, OBJECT_OT_RitCromUiOpenHook
from .clothing import OBJECT_OT_AddArtificialImpact, OBJECT_OT_ApplyClothPresetElastic, OBJECT_OT_ApplyClothPresetMedium, OBJECT_OT_ApplyClothPresetSilk, OBJECT_OT_ApplySubdivision, OBJECT_OT_MakeClothingDynamic, OBJECT_OT_PaintDynamicClothing
from .colliders import _pit_get, _pit_set, _shelf_len_get, _shelf_len_set, _shelf_prop, _support_get, _support_set, shelf_live_rebuild, shelf_prop_update, _thickness_get, _thickness_set, OBJECT_OT_RitCromCollidersFromSelectedBones, OBJECT_OT_RitCromCollidersFromSkeleton, OBJECT_OT_RitCromShelfClearBound, OBJECT_OT_RitCromShelfSetBound, OBJECT_OT_RitCromUpdateTorsoCollider, SHELF_REACH_DEFAULT, SHELF_ROWS_DEFAULT
from .panel import _PART_ITEMS, _part_ui_get, _part_ui_set, _UI_FILTERS, _UI_TABS, OBJECT_OT_RitCromFixSetupStep, OBJECT_OT_RitCromSetPart, OBJECT_OT_RitCromToggleSupport, OBJECT_OT_RitCromToggleJerkGuard, VIEW3D_PT_RitTools_Tabs
from .autophys import RitCromAutoPhysChain, OBJECT_OT_RitCromAutoPhysApplySettings, OBJECT_OT_RitCromAutoPhysClear, OBJECT_OT_RitCromAutoPhysGenerate, OBJECT_OT_RitCromAutoPhysRemoveChain, OBJECT_OT_RitCromAutoPhysToggleExpand
from .edition import lock_paid_operators
from .report import instrument, OBJECT_OT_RitCromDismissErrors, OBJECT_OT_RitCromSaveReport
from .bake import bake_classes, register_bake_props, unregister_bake_props
for _mod in (helpers, zone, topology, pits_bumps, dense, mesh_utils, naming, presets, manager, proxy_core, create_ops, mirror, bind, hooks, shrink_hair, hooks_ui, clothing, colliders, panel, autophys, bake):
    globals().update({_k: _v for _k, _v in vars(_mod).items() if not _k.startswith('__')})
classes = (RitCromPreferences, OBJECT_OT_SpawnProxyPreset, OBJECT_OT_GenerateVertexProxy, OBJECT_OT_RitCromClosePit, OBJECT_OT_RitCromFlattenBump, OBJECT_OT_RitCromAutoFixProxy, OBJECT_OT_RitCromHookShowZone, OBJECT_OT_ExtractAndCreateProxy, OBJECT_OT_AddShrinkwrapLive, OBJECT_OT_ApplyShrinkwrapAndRestore, OBJECT_OT_RitCromCubeCancel, OBJECT_OT_PreparePinGroup, OBJECT_OT_SmartMirrorProxy, OBJECT_OT_RitCromMirrorVertexProxy, OBJECT_OT_PrepareBodyMask, OBJECT_OT_TransferAndBind, OBJECT_OT_ApplyCollision, OBJECT_OT_ApplyBreastClothPreset, OBJECT_OT_ApplyThighClothPreset, OBJECT_OT_ApplyGluteClothPreset, OBJECT_OT_CreateBaseGroup, RitCromHookSlot, OBJECT_OT_DynamicGrab, OBJECT_OT_SnapHookToVertex, OBJECT_OT_SelectHookBone, OBJECT_OT_RitCromAddOwnProxy, OBJECT_OT_ClearHooks, OBJECT_OT_ClearSingleHook, OBJECT_OT_CreateShrinkGroup, OBJECT_OT_ApplyShrinkwrap, OBJECT_OT_DataTransferBind, OBJECT_OT_PaintProxyInfluence, OBJECT_OT_ClearHairBindings, OBJECT_OT_GenerateHairProxy, OBJECT_OT_MakeClothingDynamic, OBJECT_OT_PaintDynamicClothing, OBJECT_OT_ApplyClothPresetSilk, OBJECT_OT_ApplyClothPresetMedium, OBJECT_OT_ApplyClothPresetElastic, OBJECT_OT_ApplySubdivision, OBJECT_OT_AddArtificialImpact, RitCromAutoPhysChain, OBJECT_OT_RitCromAutoPhysToggleExpand, OBJECT_OT_RitCromAutoPhysRemoveChain, OBJECT_OT_RitCromAutoPhysGenerate, OBJECT_OT_RitCromAutoPhysApplySettings, OBJECT_OT_RitCromAutoPhysClear, RitCromProxyItem, RCT_UL_ProxyList, OBJECT_OT_RitCromProxyRemove, OBJECT_OT_RitCromProxyClearAll, OBJECT_OT_RitCromApplyPreset, OBJECT_OT_RitCromAutoBreastPhys, OBJECT_OT_RitCromSyncMirrorPhys, OBJECT_OT_RitCromCollidersFromSkeleton, OBJECT_OT_RitCromUpdateTorsoCollider, OBJECT_OT_RitCromShelfSetBound, OBJECT_OT_RitCromShelfClearBound, OBJECT_OT_RitCromCollidersFromSelectedBones, OBJECT_OT_RitCromFixSetupStep, OBJECT_OT_RitCromToggleSupport, OBJECT_OT_RitCromToggleJerkGuard, OBJECT_OT_RitCromSetPart, OBJECT_OT_RitCromUiOpenHook, OBJECT_OT_RitCromHookEditProxy, OBJECT_OT_RitCromHookPickProxy, OBJECT_OT_RitCromSaveReport, OBJECT_OT_RitCromDismissErrors, VIEW3D_PT_RitTools_Tabs) + bake_classes

def register():
    lock_paid_operators(classes)
    instrument(classes)
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.rct_proxies = bpy.props.CollectionProperty(type=RitCromProxyItem)
    bpy.types.Scene.rct_proxy_index = bpy.props.IntProperty(name='Index для Proxy списка', default=0, update=_proxy_index_update)
    register_cloth_ui_props()
    bpy.types.Object.rct_support = bpy.props.BoolProperty(name='Опора снизу', description='Включите для крупной груди или живота, если они провисают и плохо держатся. Маленьким и средним не нужно', get=_support_get, set=_support_set)
    bpy.types.Object.rct_pit_depth = bpy.props.FloatProperty(name='Запас', description='Зазор полки до прокси сверх Collision Distance. Мало — прокси сразу лежит на полке (может мелко дрожать в покое); много — сначала свободно проседает. Полка пересобирается сразу', get=_pit_get, set=_pit_set, update=shelf_prop_update, min=0.0, max=0.06, unit='LENGTH')
    bpy.types.Object.rct_shelf_rows = bpy.props.IntProperty(name='Ряды опоры', description='Минимум рядов полигонов тела под нижним краем прокси, даже если «Длина полки» короче. Считается в рядах сетки, поэтому одинаково работает на густой и редкой сетке', default=SHELF_ROWS_DEFAULT, min=1, soft_max=6, update=shelf_prop_update)
    _len_desc = 'На сколько полка уходит вниз от нижнего края прокси, в процентах его высоты (не меньше «Рядов опоры»). Не действует, пока задана нижняя граница. Полка пересобирается сразу'
    bpy.types.Object.rct_shelf_length = bpy.props.FloatProperty(name='Длина полки', description=_len_desc, get=_shelf_len_get, set=_shelf_len_set, update=shelf_prop_update, min=0.0, max=80.0, subtype='PERCENTAGE')
    bpy.types.Object.rct_shelf_length_low = bpy.props.FloatProperty(name='Длина полки', description=_len_desc, get=_shelf_len_get, set=_shelf_len_set, update=shelf_prop_update, min=0.0, max=50.0, subtype='PERCENTAGE')
    _g, _s = _shelf_prop('rct_shelf_reach', SHELF_REACH_DEFAULT)
    bpy.types.Object.rct_shelf_reach = bpy.props.FloatProperty(name='Вылет', description='Какая часть полки подтягивается к прокси: кожа ближе этого расстояния встаёт на зазор под прокси, дальше — остаётся на коже (плавный переход). Длину и ширину полки не ограничивает', get=_g, set=_s, update=shelf_prop_update, min=0.005, soft_max=0.3, unit='LENGTH')
    bpy.types.Object.rct_col_thickness = bpy.props.FloatProperty(name='Толщина', description='Толщина коллайдера (Collision → Thickness Outer)', get=_thickness_get, set=_thickness_set, min=0.001, soft_max=0.05, unit='LENGTH')
    bpy.types.Scene.rct_col_head = bpy.props.BoolProperty(name='Голова', default=True)
    bpy.types.Scene.rct_col_torso = bpy.props.BoolProperty(name='Туловище', default=True)
    bpy.types.Scene.rct_col_arms = bpy.props.BoolProperty(name='Руки', default=True)
    bpy.types.Scene.rct_col_fingers = bpy.props.BoolProperty(name='Пальцы', default=False)
    bpy.types.Scene.rct_col_segments = bpy.props.IntProperty(name='Сегменты капсул', description='Сегментов по окружности капсул рук/пальцев', default=8, min=8, max=12)
    bpy.types.Scene.rct_col_torso_segments = bpy.props.IntProperty(name='Сегменты', description='Сегментов по окружности цилиндра туловища', default=24, min=8, max=64)
    bpy.types.Scene.rct_col_reach = bpy.props.FloatProperty(name='Охват', description='Только для коллайдера плеч/спины под длинные волосы: кожу ближе этого расстояния к прокси в него не берём. На полки под прокси не влияет. Применяется при «Обновить коллайдер тела»', default=0.05, min=0.01, max=0.3, unit='LENGTH')
    bpy.types.Scene.rct_phys_mode = bpy.props.EnumProperty(name='Физика', items=[('PRESET', 'Пресет', 'Готовые проверенные настройки'), ('CUSTOM', 'Своя настройка', 'Только нужные для этого типа прокси параметры')], default='PRESET')
    for _t in ('VOLUME', 'SURFACE', 'HAIR'):
        setattr(bpy.types.Scene, f'rct_preset_{_t.lower()}', bpy.props.EnumProperty(name='Пресет', items=enum_items(_PRESET_ENUMS[_t]), default=enum_default(_PRESET_ENUMS[_t], DEFAULT_PRESET[_t])))
    bpy.types.Scene.rct_show_cloth_adv = bpy.props.BoolProperty(name='Дополнительно', default=False)
    bpy.types.Scene.rct_ui_tab = bpy.props.EnumProperty(name='Вкладка', items=_UI_TABS, default='PROXY')
    bpy.types.Scene.rct_ui_filter = bpy.props.EnumProperty(name='Фильтр', items=_UI_FILTERS, default='ALL')
    bpy.types.Scene.rct_ui_mgr_open = bpy.props.BoolProperty(name='Менеджер прокси', default=True)
    bpy.types.Scene.rct_ui_create_open = bpy.props.BoolProperty(name='Создать прокси', default=True)
    bpy.types.Scene.rct_ui_create_adv = bpy.props.BoolProperty(name='Дополнительно', default=False)
    bpy.types.Scene.rct_ui_phys_custom = bpy.props.BoolProperty(name='Для опытных', default=False)
    bpy.types.Scene.rct_ui_phys_preset = bpy.props.BoolProperty(name='Часть тела и пресет', default=False)
    bpy.types.Scene.rct_ui_fine_open = bpy.props.BoolProperty(name='Тонкая настройка', default=False)
    bpy.types.Scene.rct_ui_hook_open = bpy.props.IntProperty(name='Раскрытый хук', default=0)
    bpy.types.Scene.rct_ui_hook_seen = bpy.props.IntProperty(name='Хуков при раскрытии', default=0)
    bpy.types.Scene.rct_ui_more_col = bpy.props.BoolProperty(name='Коллизии', default=False)
    bpy.types.Scene.rct_ui_more_shrink = bpy.props.BoolProperty(name='Защита кожи (Shrinkwrap)', default=False)
    bpy.types.Scene.rct_ui_more_anime = bpy.props.BoolProperty(name='Аниме (временно)', default=False)
    bpy.types.Object.rct_part_ui = bpy.props.EnumProperty(name='Часть тела', items=_PART_ITEMS, get=_part_ui_get, set=_part_ui_set, description='Определена при создании; можно сменить (пишется в rct_part)')
    bpy.types.Scene.rct_back_grid = bpy.props.BoolProperty(name='Задняя стенка сеткой', description='«Закрыть сзади» сеткой квадов, как задняя грань куба, вместо веера к одной точке. Выключите — старый веер. От выворота при резких рывках сетка не спасает — для этого «Резкие рывки» у прокси', default=True)
    bpy.types.Scene.rct_vertex_close_back = bpy.props.BoolProperty(name='Закрыть сзади (объём)', description='Заливает край выделения гранью: получается замкнутый объём, можно надувать (Pressure). Задняя грань и край автоматически закрепляются. Без галочки — открытая поверхность без Pressure', default=True)
    bpy.types.Scene.rct_vertex_mirror = bpy.props.BoolProperty(name='Зеркало', description='После создания сразу сделать копию на другой стороне тела (своя зона влияния и привязка). Прокси посередине тела (заходит на обе стороны) не зеркалится', default=False)
    bpy.types.Scene.rct_phys_both = bpy.props.BoolProperty(name='Обе стороны (L и R)', description='Физика и быстрая настройка меняются сразу у прокси и его зеркальной копии', default=True)
    bpy.types.Scene.rct_auto_fix_mesh = bpy.props.BoolProperty(name='Исправлять сетку автоматически', description='Чинит копию выделения, тело не меняется: склеивает дубли вершин, убирает лишние грани на рёбрах с 3+ гранями, висячие рёбра и вершины, разглаживает вывернутые внутрь вершины, закрывает узкие заходы внутрь сетки (мелкие впадины с плотной сеткой вроде пупка не трогает — их убирает «Заменять области плотной сетки»). При привязке режет вогнутые квады и n-угольники, не помогло — привязывает через Triangulate. Выключено — прокси ровно по выделению, вершина в вершину; если привязка не удастся, будет кнопка «Исправить автоматически»', default=True)
    bpy.types.Scene.rct_dense_regions = bpy.props.BoolProperty(name='Заменять области плотной сетки', description='Экспериментально. Убирает участки плотной сетки (выпуклые детали, мелкие впадины вроде пупка): внутри ровного кольца квадов всё удаляется и заливается кольцами квадов к центру с плотностью как у сетки вокруг: сосок вместе с густой ареолой становится не плотнее остальной груди (масса Cloth на вершину одинакова — густой сосок тяжелее). Только квады, без треугольников и звёзд: в вершине сходятся не больше 5 квадов. Впадина (пупок) заливается сеткой квадов по уровню поверхности вокруг, как раньше. Пятна меньше 20 граней не трогает, кроме впадин. Работает только при включённой «Исправлять сетку автоматически». Тело не меняется. Выключено по умолчанию: вершин в прокси меньше, с сильным Pressure он может стать неустойчивым', default=False)
    bpy.types.Scene.rct_pin_transition = bpy.props.FloatProperty(name='Ширина перехода', description='Авто-точка крепления куба: задник закреплён целиком, боковые стенки под кожей — слабее к коже, часть на коже свободна, у её края — плавный спад на эту ширину. ВНИМАНИЕ: слайдер ПЕРЕЗАПИСЫВАЕТ Pin_Base — ручная докраска точки крепления пропадёт', default=0.015, min=0.001, max=0.5, unit='LENGTH', update=_pin_transition_update)
    bpy.types.Scene.rct_edge_pin_width = bpy.props.FloatProperty(name='Ширина крепления от края', description='«Закрыть сзади»: край выделения и задняя грань закреплены, внутрь — плавный спад на эту ширину. ВНИМАНИЕ: слайдер ПЕРЕЗАПИСЫВАЕТ Pin_Base — ручная докраска точки крепления пропадёт', default=0.015, min=0.001, max=0.3, unit='LENGTH', update=_edge_pin_width_update)
    bpy.types.Scene.rct_zone_blur = bpy.props.FloatProperty(name='Размытие края зоны', description='Авто-зона влияния: насколько размывать маску ВНУТРЬ от края выделения (снаружи выделения вес всегда 0). Ширина размытия подбирается сама по размеру зоны, слайдер — наименьшая ширина. ВНИМАНИЕ: слайдер ПЕРЕЗАПИСЫВАЕТ маску — ручная докраска зоны пропадёт', default=0.03, min=0.0, max=0.3, unit='LENGTH', update=_zone_blur_update)
    if _rct_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_rct_load_post)
    if _rct_depsgraph_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_rct_depsgraph_post)
    bpy.types.Scene.hook_falloff_radius = bpy.props.FloatProperty(name='Радиус хука', description='Радиус охвата соседних вершин', default=0.08, min=0.001, max=2.0, step=1)
    bpy.types.Scene.proxy_mode = bpy.props.EnumProperty(items=[('VERTEX', 'Из вершин', 'Поверхность: кусок тела из выделенных вершин', 'VERTEXSEL', 2), ('CUSTOM', 'Объём (куб)', 'Замкнутый объём из куба, подогнанного по форме тела', 'MESH_CUBE', 3), ('HAIR', 'Волосы (кости)', 'Пряди волос по выделенным костям', 'STRANDS', 4)], name='Режим создания', default='VERTEX')
    bpy.types.Scene.proxy_main_mesh = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.proxy_custom_mesh = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.proxy_cube_subdiv = bpy.props.IntProperty(name='Уровень Subdivision', description='Уровень сглаживания для квадросферы', default=2, min=1, max=4)
    bpy.types.Scene.proxy_original_body = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.proxy_temp_cast = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.proxy_active_cube = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.proxy_apply_subdiv = bpy.props.BoolProperty(name='Сразу применить Subdiv', default=True, description='Куб сразу сглажен в сетку: её точки тянутся областью (O). Выключено — Subdivision остаётся модификатором, двигаются 8 вершин куба')
    bpy.types.Scene.proxy_decimate_ratio = bpy.props.FloatProperty(name='Decimate Ratio', description='Коэффициент полигонажа прокси-тела', default=0.15, min=0.01, max=1.0, step=0.01)
    bpy.types.Scene.proxy_smooth_iters = bpy.props.IntProperty(name='Smooth Iterations', description='Количество итераций сглаживания после Decimate', default=5, min=0, max=50)
    bpy.types.Scene.hair_pin_root = bpy.props.BoolProperty(name='Закрепить корень пряди', description='Включено: первая кость каждой пряди остаётся жёсткой (держится за голову), качаются остальные. Выключено: первая кость тоже качается от физики — прядь может «отрываться» у основания', default=True)
    bpy.types.Scene.hair_bending_stiffness = bpy.props.FloatProperty(name='Жёсткость изгиба (Для новых)', description='Задает начальную жесткость изгиба волос перед созданием прокси (больше = тверже)', default=0.05, min=0.001, max=5.0, step=1)
    bpy.types.Scene.show_hair_phys = bpy.props.BoolProperty(name='Настройки физики волос', default=False)
    bpy.types.Scene.show_proxy_help = bpy.props.BoolProperty(name='Справка по Прокси Объектам', default=False)
    bpy.types.Scene.shrink_target = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.rct_cloth_obj = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.rct_clothing_obj = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.rct_autophys_track_axis = bpy.props.EnumProperty(name='Track Axis', description='Локальная ось кости, которая будет направлена на target', items=[('TRACK_X', 'X', 'Ось X'), ('TRACK_Y', 'Y', 'Ось Y (по умолчанию для костей)'), ('TRACK_Z', 'Z', 'Ось Z'), ('TRACK_NEGATIVE_X', '-X', 'Ось -X'), ('TRACK_NEGATIVE_Y', '-Y', 'Ось -Y'), ('TRACK_NEGATIVE_Z', '-Z', 'Ось -Z')], default='TRACK_Y')
    bpy.types.Scene.rct_autophys_influence = bpy.props.FloatProperty(name='Chain Influence', description='Сила Damped Track для НЕ-корневых костей цепи (по умолчанию для новых ригов)', default=1.0, min=0.0, max=1.0, subtype='FACTOR')
    bpy.types.Scene.rct_autophys_root_influence = bpy.props.FloatProperty(name='Root Influence', description='Сила Damped Track НА КОРНЕ цепи. Оставьте < 1.0 (по умолчанию 0.85), чтобы Copy Rotation Add-mix от CTRL могла подмешивать ручную позу', default=0.85, min=0.0, max=1.0, subtype='FACTOR')
    bpy.types.Scene.rct_autophys_ctrl_size = bpy.props.FloatProperty(name='CTRL Size ×', description='Множитель длины генерируемой CTRL-кости относительно корня цепи (для удобства селекта)', default=1.5, min=1.0, max=4.0, subtype='FACTOR')
    bpy.types.Scene.rct_autophys_ctrl_suffix = bpy.props.StringProperty(name='CTRL Suffix', description='Суффикс независимой управляющей кости', default='_CTRL')
    bpy.types.Scene.rct_autophys_tgt_suffix = bpy.props.StringProperty(name='TGT Suffix', description='Суффикс tip-target костей для Damped Track', default='_TGT_TIP')
    bpy.types.Object.rct_autophys_chains = bpy.props.CollectionProperty(type=RitCromAutoPhysChain)
    bpy.types.Object.rct_hook_slots = bpy.props.CollectionProperty(type=RitCromHookSlot)
    register_bake_props()
    apply_language()

def unregister():
    unregister_language()
    unregister_bake_props()
    if bpy.app.timers.is_registered(shelf_live_rebuild):
        bpy.app.timers.unregister(shelf_live_rebuild)
    props_to_remove = ['hook_falloff_radius', 'proxy_mode', 'proxy_main_mesh', 'proxy_custom_mesh', 'proxy_cube_subdiv', 'proxy_decimate_ratio', 'proxy_smooth_iters', 'hair_pin_root', 'rct_phys_mode', 'rct_preset_volume', 'rct_preset_surface', 'rct_preset_hair', 'rct_show_cloth_adv', 'rct_ui_tab', 'rct_ui_filter', 'rct_ui_mgr_open', 'rct_ui_create_open', 'rct_ui_create_adv', 'rct_ui_phys_custom', 'rct_ui_phys_preset', 'rct_ui_fine_open', 'rct_ui_hook_open', 'rct_ui_hook_seen', 'rct_ui_more_col', 'rct_ui_more_shrink', 'rct_ui_more_anime', 'rct_col_head', 'rct_col_torso', 'rct_col_arms', 'rct_col_fingers', 'rct_col_segments', 'rct_col_torso_segments', 'rct_col_reach', 'rct_vertex_close_back', 'rct_back_grid', 'rct_vertex_mirror', 'rct_phys_both', 'rct_auto_fix_mesh', 'rct_dense_regions', 'rct_pin_transition', 'rct_edge_pin_width', 'rct_zone_blur', 'hair_bending_stiffness', 'show_hair_phys', 'show_proxy_help', 'shrink_target', 'rct_cloth_obj', 'rct_clothing_obj', 'rct_proxies', 'rct_proxy_index', 'proxy_active_cube', 'proxy_temp_cast', 'proxy_original_body', 'proxy_apply_subdiv', 'rct_autophys_track_axis', 'rct_autophys_influence', 'rct_autophys_root_influence', 'rct_autophys_ctrl_size', 'rct_autophys_ctrl_suffix', 'rct_autophys_tgt_suffix']
    for prop in props_to_remove:
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass
    unregister_cloth_ui_props()
    for _p in ('rct_support', 'rct_part_ui', 'rct_col_thickness', 'rct_pit_depth', 'rct_shelf_rows', 'rct_shelf_length', 'rct_shelf_length_low', 'rct_shelf_reach'):
        try:
            delattr(bpy.types.Object, _p)
        except AttributeError:
            pass
    if _rct_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_rct_load_post)
    if _rct_depsgraph_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_rct_depsgraph_post)
    for _p in ('rct_autophys_chains', 'rct_hook_slots'):
        try:
            delattr(bpy.types.Object, _p)
        except AttributeError:
            pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
if __name__ == '__main__':
    register()
