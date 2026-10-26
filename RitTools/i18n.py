# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import re
import bpy
from .i18n_en import EN
_PKG = __package__
_CYR = re.compile('[А-Яа-яЁё]')
_EXACT = {ru: en for ru, en in EN.items() if '{}' not in ru}
_TEMPLATES = []
for _ru, _en in sorted(((r, e) for r, e in EN.items() if '{}' in r), key=lambda x: -len(x[0].replace('{}', ''))):
    _TEMPLATES.append((re.compile('(.+?)'.join((re.escape(p) for p in _ru.split('{}'))), re.S), _en))
_STATIC = set()
_CACHE = {}
_registered = False

def _pref_language():
    try:
        return bpy.context.preferences.addons[_PKG].preferences.language
    except (KeyError, AttributeError):
        return 'AUTO'

def use_english():
    lang = _pref_language()
    if lang == 'AUTO':
        return not (bpy.app.translations.locale.startswith('ru') and bpy.context.preferences.view.use_translate_interface)
    return lang == 'EN'

def _tr(s):
    if not _CYR.search(s):
        return s
    r = _EXACT.get(s)
    if r is not None:
        return r
    best = None
    for rx, en in _TEMPLATES:
        m = rx.fullmatch(s)
        if m:
            r = en.format(*(_tr(g) for g in m.groups()))
            if not _CYR.search(r):
                return r
            if best is None:
                best = r
    core = s.strip()
    if core and core != s:
        i = s.index(core)
        return s[:i] + _tr(core) + s[i + len(core):]
    for sep in ('\n', '; '):
        if sep in s:
            return sep.join((_tr(p) for p in s.split(sep)))
    return best if best is not None else s

def tr(s):
    if not isinstance(s, str) or not _CYR.search(s) or (not use_english()):
        return s
    r = _CACHE.get(s)
    if r is None:
        if len(_CACHE) > 5000:
            _CACHE.clear()
        r = _CACHE[s] = _tr(s)
    return r

def enum_items(items):
    cache = {}

    def _items(self, context):
        en = use_english()
        if en not in cache:
            cache[en] = [(it[0], tr(it[1]), tr(it[2])) + tuple(it[3:]) for it in items]
        return cache[en]
    return _items

def enum_default(items, ident):
    for i, it in enumerate(items):
        if it[0] == ident:
            return it[4] if len(it) > 4 else i
    return 0
_SUB = {'row', 'column', 'box', 'split', 'grid_flow', 'column_flow', 'menu_pie'}
_OP_NAMES = {}

def _op_name(idname):
    n = _OP_NAMES.get(idname)
    if n is None:
        m, o = idname.split('.')
        try:
            n = getattr(getattr(bpy.ops, m), o).get_rna_type().name
        except (AttributeError, KeyError):
            n = ''
        _OP_NAMES[idname] = n
    return n

class _TrLayout:
    """UILayout, который сам переводит надписи на английский (для wrap)."""
    __slots__ = ('_l',)

    def __init__(self, layout):
        object.__setattr__(self, '_l', layout)

    def __getattr__(self, name):
        a = getattr(self._l, name)
        if name in _SUB:

            def sub(*args, **kw):
                if kw.get('heading'):
                    kw['heading'] = tr(kw['heading'])
                    kw['translate'] = False
                return _TrLayout(a(*args, **kw))
            return sub
        return a

    def __setattr__(self, name, value):
        setattr(self._l, name, value)

    @staticmethod
    def _text(kw, default=None):
        if 'text' in kw:
            kw['text'] = tr(kw['text'])
        elif default:
            kw['text'] = tr(default)
        kw['translate'] = False
        return kw

    def label(self, *args, **kw):
        return self._l.label(*args, **self._text(kw))

    def operator(self, idname, **kw):
        kw = self._text(kw, None if 'text' in kw else _op_name(idname))
        if _is_dev(idname):
            r = self._l.row(align=True)
            r.active = False
            kw['icon'] = 'TIME'
            if kw.get('text'):
                kw['text'] += tr('  · в разработке')
            return r.operator(idname, **kw)
        if _is_paid(idname):
            r = self._l.row(align=True)
            r.active = False
            kw['icon'] = 'LOCKED'
            if kw.get('text'):
                kw['text'] += '  · PRO'
            return r.operator(idname, **kw)
        return self._l.operator(idname, **kw)

    def operator_menu_enum(self, idname, prop, **kw):
        return self._l.operator_menu_enum(idname, prop, **self._text(kw))

    def prop_enum(self, data, prop, value, **kw):
        return self._l.prop_enum(data, prop, value, **self._text(kw))

    def menu(self, menu, **kw):
        return self._l.menu(menu, **self._text(kw))

    def prop(self, data, prop, **kw):
        p = None if prop.startswith('[') else data.bl_rna.properties.get(prop)
        if p is not None and p.type == 'ENUM' and kw.get('expand') and ('text' not in kw) and (not p.is_enum_flag):
            row = self._l.row(align=True)
            for it in p.enum_items:
                row.prop_enum(data, prop, it.identifier, text=tr(it.name), translate=False, icon=it.icon)
            return None
        if 'text' not in kw and (not kw.get('icon_only')) and (p is not None):
            kw['text'] = tr(p.name)
        return self._l.prop(data, prop, **self._text(kw))

def _is_paid(idname):
    from . import edition
    return idname in edition.PAID_OPS

def _is_dev(idname):
    from . import edition
    return idname in edition.DEV_LOCKED

def wrap(layout):
    if isinstance(layout, _TrLayout):
        return layout
    from . import edition
    return _TrLayout(layout)

def static_text(s):
    _STATIC.add(s)
    return s

def apply_language():
    global _registered
    if _registered:
        bpy.app.translations.unregister(_PKG)
        _registered = False
    _CACHE.clear()
    lang = _pref_language()
    if lang == 'RU':
        return
    msgs = {}
    pairs = dict(_EXACT)
    pairs.update(((s, _tr(s)) for s in _STATIC))
    for ru, en in pairs.items():
        msgs['*', ru] = en
        msgs['Operator', ru] = en
    locales = set(bpy.app.translations.locales) | {'en_US'}
    if lang == 'AUTO':
        locales = {loc for loc in locales if not loc.startswith('ru')}
    bpy.app.translations.register(_PKG, {loc: msgs for loc in locales})
    _registered = True

def unregister_language():
    global _registered
    if _registered:
        bpy.app.translations.unregister(_PKG)
        _registered = False

def _language_update(self, context):
    apply_language()
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()

def draw_language_switch(layout, context):
    addon = context.preferences.addons.get(_PKG)
    if not addon or not addon.preferences:
        return
    row = layout.box().row(align=True)
    row.label(text='Язык / Language', translate=False, icon='WORLD')
    row.prop(addon.preferences, 'language', text='')

class RitCromPreferences(bpy.types.AddonPreferences):
    bl_idname = _PKG
    language: bpy.props.EnumProperty(name='Язык / Language', items=[('AUTO', 'Как в Blender / As in Blender', "Russian if Blender's interface is Russian, otherwise English / Русский при русском интерфейсе Blender, иначе English"), ('RU', 'Русский', ''), ('EN', 'English', '')], default='AUTO', update=_language_update)

    def draw(self, context):
        self.layout.prop(self, 'language')
