# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
from mathutils import Vector
from .panel import _fold_header
from .i18n import tr
from .report import report_error
_AUTOPHYS_TRACK_ITEMS = [('TRACK_X', 'X', 'Ось X'), ('TRACK_Y', 'Y', 'Ось Y (по умолчанию для костей)'), ('TRACK_Z', 'Z', 'Ось Z'), ('TRACK_NEGATIVE_X', '-X', 'Ось -X'), ('TRACK_NEGATIVE_Y', '-Y', 'Ось -Y'), ('TRACK_NEGATIVE_Z', '-Z', 'Ось -Z')]

def _autophys_chain_update(self, context):
    pass

class RitCromAutoPhysChain(bpy.types.PropertyGroup):
    """Запись об одной сгенерированной Auto-Physics цепи."""
    name: bpy.props.StringProperty(name='Имя цепи')
    expanded: bpy.props.BoolProperty(name='Развернуть', default=True)
    ctrl_bone: bpy.props.StringProperty(name='CTRL')
    root_bone: bpy.props.StringProperty(name='Root')
    deform_bones: bpy.props.StringProperty(name='Deform CSV')
    tgt_bones: bpy.props.StringProperty(name='TGT CSV')
    track_axis: bpy.props.EnumProperty(name='Track Axis', items=_AUTOPHYS_TRACK_ITEMS, default='TRACK_Y', update=_autophys_chain_update)
    influence_chain: bpy.props.FloatProperty(name='Chain Influence', description='Сила Damped Track для всех костей цепи КРОМЕ корневой', default=1.0, min=0.0, max=1.0, subtype='FACTOR', update=_autophys_chain_update)
    influence_root: bpy.props.FloatProperty(name='Root Influence', description='Сила Damped Track НА КОРНЕ — оставьте < 1.0, чтобы Copy Rotation от CTRL подмешивалась без блокировки', default=0.85, min=0.0, max=1.0, subtype='FACTOR', update=_autophys_chain_update)

class OBJECT_OT_RitCromAutoPhysToggleExpand(bpy.types.Operator):
    """Свернуть/развернуть группу настроек цепи в UI"""
    bl_idname = 'object.rct_autophys_toggle_expand'
    bl_label = 'Свернуть/развернуть цепь'
    bl_options = {'INTERNAL'}
    chain_index: bpy.props.IntProperty()

class OBJECT_OT_RitCromAutoPhysRemoveChain(bpy.types.Operator):
    """Удалить одну Auto-Physics цепь (констрейнты + кости + запись из реестра)"""
    bl_idname = 'object.rct_autophys_remove_chain'
    bl_label = 'Удалить цепь'
    bl_options = {'REGISTER', 'UNDO'}
    chain_index: bpy.props.IntProperty()

class OBJECT_OT_RitCromAutoPhysGenerate(bpy.types.Operator):
    """Создать Auto-Physics риг (sequential Damped Track + Copy Rotation Add-mix) из выделенных костей"""
    bl_idname = 'object.rct_autophys_generate'
    bl_label = 'Создать Auto-Physics риг'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromAutoPhysApplySettings(bpy.types.Operator):
    """Применить scene-настройки (Track Axis / Influence) ко ВСЕМ зарегистрированным цепям"""
    bl_idname = 'object.rct_autophys_apply_settings'
    bl_label = 'Применить scene-настройки ко всем цепям'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_RitCromAutoPhysClear(bpy.types.Operator):
    """Удалить ВСЕ Auto-Physics риги с активной арматуры (констрейнты + кости + реестр)"""
    bl_idname = 'object.rct_autophys_clear'
    bl_label = 'Очистить ВСЕ Auto-Physics'
    bl_options = {'REGISTER', 'UNDO'}

def draw_autophys_block(layout, context):
    scn = context.scene
    outer = layout.box()
    is_open, _ = _fold_header(outer, scn, 'rct_ui_more_anime', 'Аниме (временно)', 'CON_TRACKTO')
    if not is_open:
        return
    layout = outer.column()
    arm_obj = context.active_object
    is_arm = arm_obj and arm_obj.type == 'ARMATURE'
    box = layout.box()
    box.label(text='Активная арматура:', icon='ARMATURE_DATA')
    if is_arm:
        box.label(text=arm_obj.name, translate=False, icon='OUTLINER_DATA_ARMATURE')
        box.label(text=tr(f'Режим: {context.mode}'), translate=False, icon='EDITMODE_HLT' if context.mode == 'EDIT_ARMATURE' else 'POSE_HLT')
    else:
        box.label(text='Нет — выберите Armature', icon='ERROR')
    layout.separator()
    col = layout.column(align=True)
    col.label(text='Настройки для новых цепей:', icon='CON_TRACKTO')
    col.prop(scn, 'rct_autophys_track_axis', text='Track Axis')
    col.prop(scn, 'rct_autophys_influence', text='Chain Influence', slider=True)
    col.prop(scn, 'rct_autophys_root_influence', text='Root Influence', slider=True)
    col.prop(scn, 'rct_autophys_ctrl_size', text='CTRL Size ×', slider=True)
    col2 = layout.column(align=True)
    col2.label(text='Суффиксы:', icon='GREASEPENCIL')
    col2.prop(scn, 'rct_autophys_ctrl_suffix', text='CTRL')
    col2.prop(scn, 'rct_autophys_tgt_suffix', text='TGT')
    layout.separator()
    col = layout.column(align=True)
    col.label(text='Действия:', icon='MODIFIER')
    row = col.row(align=True)
    row.scale_y = 1.4
    row.operator('object.rct_autophys_generate', text='Создать Auto-Physics риг', icon='CON_TRACKTO')
    col.operator('object.rct_autophys_apply_settings', text='Применить scene-настройки ко всем', icon='FILE_REFRESH')
    col.operator('object.rct_autophys_clear', text='Очистить ВСЕ Auto-Physics', icon='TRASH')
    if is_arm and len(arm_obj.rct_autophys_chains) > 0:
        layout.separator()
        layout.label(text=tr(f'Зарегистрированные цепи: {len(arm_obj.rct_autophys_chains)}'), translate=False, icon='OUTLINER_OB_ARMATURE')
        for idx, ch in enumerate(arm_obj.rct_autophys_chains):
            cbox = layout.box()
            header = cbox.row(align=True)
            tri_icon = 'TRIA_DOWN' if ch.expanded else 'TRIA_RIGHT'
            op = header.operator('object.rct_autophys_toggle_expand', text=tr(f'Chain: {ch.name}'), translate=False, icon=tri_icon, emboss=False)
            op.chain_index = idx
            rm = header.operator('object.rct_autophys_remove_chain', text='', icon='X', emboss=False)
            rm.chain_index = idx
            if ch.expanded:
                body = cbox.column(align=True)
                body.label(text=tr(f'CTRL: {ch.ctrl_bone}'), translate=False, icon='BONE_DATA')
                n_deform = len([n for n in ch.deform_bones.split(',') if n])
                body.label(text=tr(f'Костей в цепи: {n_deform}'), translate=False, icon='GROUP_BONE')
                body.separator()
                body.prop(ch, 'track_axis', text='Track Axis')
                body.prop(ch, 'influence_chain', text='Chain Influence', slider=True)
                body.prop(ch, 'influence_root', text='Root Influence', slider=True)
    layout.separator()
    help_box = layout.box()
    help_box.label(text='Как пользоваться:', icon='HELP')
    h = help_box.column(align=True)
    h.label(text='1. Выберите Armature, зайдите в Edit/Pose Mode.')
    h.label(text='2. Выделите цепь костей (или одну кость).')
    h.label(text="3. Нажмите 'Создать Auto-Physics риг'.")
    h.label(text='4. Анимируйте крупную CTRL-кость у корня цепи —')
    h.label(text='   Add-mix Copy Rotation подмешает её ротацию,')
    h.label(text="   а Damped Track даст 'физический' look-at.")
    h.label(text='• Root Influence < 1.0 → CTRL не блокируется DT.')
    h.label(text='• Каждая цепь сворачивается в свой блок выше ↑')
