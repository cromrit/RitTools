# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bpy
from .i18n import tr
FREE = True
PRO = False
URL_SHOP = 'https://app.lava.top/ritcrom?sort=archive'
URL_DISCORD = 'https://discord.gg/2WrpvUDMrC'
FREE_OPS = {'object.extract_and_create_proxy', 'object.add_shrinkwrap_live', 'object.apply_shrinkwrap_and_restore', 'object.rct_cube_cancel', 'object.rct_mirror_vertex_proxy', 'object.smart_mirror_proxy', 'object.rct_set_part', 'object.rct_apply_preset', 'object.rct_toggle_support', 'object.rct_toggle_jerk_guard', 'object.rct_sync_mirror_phys', 'object.rct_fix_setup_step', 'object.prepare_pin_group', 'object.transfer_and_bind', 'object.prepare_body_mask', 'object.rct_proxy_remove', 'object.rct_proxy_clear_all', 'object.rct_save_report', 'object.rct_dismiss_errors', 'object.rct_bake', 'object.rct_bake_free', 'object.rct_bake_pause'}
DEV_OPS = {'object.make_clothing_dynamic', 'object.paint_dynamic_clothing', 'object.apply_cloth_preset_silk', 'object.apply_cloth_preset_medium', 'object.apply_cloth_preset_elastic', 'object.apply_subdivision_cloth'}
DEV_LOCKED = set()

def shop_build():
    return FREE or PRO

def edition_name():
    return 'Free' if FREE else 'PRO' if PRO else 'Full'

def beta(text):
    return tr(text) + (tr(' (бета)') if shop_build() else '')

def draw_dev_banner(layout):
    b = layout.box()
    b.label(text=tr('В разработке — появится в следующих обновлениях'), icon='TIME')
    b.label(text=tr('Следите за новостями в Discord'), icon='DOT')
    b.operator('wm.url_open', text=tr('Discord'), icon='COMMUNITY').url = URL_DISCORD

def draw_beta_banner(layout):
    b = layout.box()
    b.label(text=tr('Бета-тест: эта вкладка ещё дорабатывается'), icon='EXPERIMENTAL')
    b.label(text=tr('Нашли ошибку — «Сохранить отчёт» внизу и пришлите в Discord'), icon='DOT')

def _draw_dev(menu, _context):
    col = menu.layout.column()
    col.label(text=tr('Динамика одежды ещё в разработке — появится в обновлении.'))
    col.separator()
    col.operator('wm.url_open', text=tr('Discord'), icon='COMMUNITY').url = URL_DISCORD

def _dev_invoke(self, context, _event=None):
    context.window_manager.popup_menu(_draw_dev, title=tr('В разработке'), icon='TIME')
    return {'CANCELLED'}

def _dev_execute(self, context):
    self.report({'WARNING'}, tr('Динамика одежды ещё в разработке — появится в обновлении.'))
    return {'CANCELLED'}
PAID_OPS = set()

def draw_pro_banner(layout, what):
    b = layout.box()
    b.label(text=tr('Только в полной версии:'), icon='LOCKED')
    for line in what:
        b.label(text=tr(line), icon='DOT')
    draw_full_version_links(b.row(align=True))

def draw_full_version_links(layout):
    layout.operator('wm.url_open', text=tr('Полная версия'), icon='URL').url = URL_SHOP
    layout.operator('wm.url_open', text=tr('Discord'), icon='COMMUNITY').url = URL_DISCORD

def _draw_locked(menu, _context):
    col = menu.layout.column()
    col.label(text=tr('Эта функция есть в полной версии RitTools.'))
    col.separator()
    draw_full_version_links(col)

def _locked_invoke(self, context, _event=None):
    context.window_manager.popup_menu(_draw_locked, title=tr('RitTools Free'), icon='LOCKED')
    return {'CANCELLED'}

def _locked_execute(self, context):
    self.report({'WARNING'}, tr('Эта функция есть в полной версии RitTools: ') + URL_SHOP)
    return {'CANCELLED'}

def lock_paid_operators(classes):
    if not shop_build():
        return
    for cls in classes:
        if issubclass(cls, bpy.types.Operator) and cls.bl_idname in DEV_OPS:
            DEV_LOCKED.add(cls.bl_idname)
            cls.invoke = _dev_invoke
            cls.execute = _dev_execute
    if not FREE:
        return
    for cls in classes:
        if issubclass(cls, bpy.types.Operator) and cls.bl_idname not in FREE_OPS | DEV_OPS:
            PAID_OPS.add(cls.bl_idname)
            cls.invoke = _locked_invoke
            cls.execute = _locked_execute
            if hasattr(cls, 'modal'):
                cls.modal = lambda self, context, event: {'CANCELLED'}
