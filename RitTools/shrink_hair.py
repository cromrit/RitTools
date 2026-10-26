# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
import bmesh
from .helpers import set_active_mode
from .presets import apply_cloth_preset
from .manager import _add_to_proxy_manager, add_to_physics_collection
from .i18n import tr

class OBJECT_OT_CreateShrinkGroup(bpy.types.Operator):
    bl_idname = 'object.create_shrink_group'
    bl_label = '1. Залить синим (Shrink)'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ApplyShrinkwrap(bpy.types.Operator):
    bl_idname = 'object.apply_shrinkwrap'
    bl_label = '2. Применить Shrinkwrap'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_PaintProxyInfluence(bpy.types.Operator):
    bl_idname = 'object.paint_proxy_influence'
    bl_label = 'Нарисовать маску (Proxy_Mask)'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_ClearHairBindings(bpy.types.Operator):
    bl_idname = 'object.clear_hair_bindings'
    bl_label = 'Снять привязку волос с выделенных костей'
    bl_description = 'Удаляет с выделенных костей констрейнты Hair_Track — кости перестают следовать за прокси-волосами. Сам прокси-объект не удаляется'
    bl_options = {'REGISTER', 'UNDO'}

class OBJECT_OT_GenerateHairProxy(bpy.types.Operator):
    bl_idname = 'object.generate_hair_proxy'
    bl_label = 'Создать Proxy-волосы по костям'
    bl_description = 'Создаёт физические цилиндры (прокси) вдоль выбранных костей'
    bl_options = {'REGISTER', 'UNDO'}
from . import hooks_ui
