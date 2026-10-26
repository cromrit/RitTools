# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bmesh
import bpy
import math
from mathutils import Vector
from .helpers import ensure_object_mode, move_modifier, place_cloth_modifier
from .zone import _scale_is_one, bake_world_scale
from .mesh_utils import ensure_outward_normals, mesh_is_closed, NORMALS_FLIPPED_MSG
from .naming import auto_name_proxy, get_proxy_type, proxy_body
from .i18n import static_text, tr
PRESET_VERSION = 4
OPEN_VERTEX_MASS = 0.1
BREAST_PRESSURE = 0.0
BUTT_PRESSURE = 0.0
PRESSURE_SAFE_K = 3.0
PS_LIMITED_KEY = 'rct_ps_limited'
PS_LIMITED_MSG = '{}: прокси крупный — Упругость объёма снижена {} → {}, иначе физика взрывается'
PS_LIMITED_LABEL = 'Упругость объёма ограничена {}: прокси крупный, больше — взрыв'
PROXY_SMOOTH_NAME = 'RCT_ProxySmooth'
PROXY_SMOOTH = {'BREAST': dict(factor=0.15, iterations=5, smooth_type='SIMPLE', rest_source='ORCO')}
_VOLUME_BASE = {'quality': 5, 'time_scale': 1.0, 'air_damping': 1.0, 'bending_stiffness': 0.5, 'bending_damping': 0.5, 'shear_damping': 5.0, 'use_internal_springs': False, 'use_dynamic_mesh': True, 'use_pressure': True, 'uniform_pressure_force': 0.0, 'fluid_density': 0.0, 'shrink_min': 0.0, 'pin_stiffness': 1.0}
_SURFACE_BASE = {'quality': 5, 'time_scale': 1.0, 'air_damping': 1.0, 'shear_damping': 5.0, 'bending_damping': 0.5, 'use_internal_springs': False, 'use_dynamic_mesh': True, 'use_pressure': False, 'fluid_density': 0.0, 'shrink_min': 0.0}
_HAIR_BASE = {'quality': 5, 'time_scale': 1.0, 'air_damping': 0.5, 'tension_stiffness': 1.0, 'compression_stiffness': 1.0, 'shear_stiffness': 1.0, 'tension_damping': 0.5, 'compression_damping': 0.5, 'shear_damping': 0.5, 'use_internal_springs': False, 'use_dynamic_mesh': True, 'use_pressure': False, 'pin_stiffness': 1.0}
_VOLUME_COLLISION = {'use_collision': True, 'collision_quality': 3, 'distance_min': 0.003, 'use_self_collision': False}
_SURFACE_COLLISION = {'use_collision': True, 'collision_quality': 3, 'distance_min': 0.003, 'use_self_collision': False}
_HAIR_COLLISION = {'use_collision': True, 'collision_quality': 3, 'distance_min': 0.005, 'use_self_collision': False}

def _stiff(v):
    return {'tension_stiffness': v, 'compression_stiffness': v, 'shear_stiffness': v}

def _damp(v):
    return {'tension_damping': v, 'compression_damping': v}
PRESETS = {'BREAST': dict(type='VOLUME', label='Грудь (мягкий объём)', name='Breast', vertex_mass=5.0, settings={**_VOLUME_BASE, **_stiff(15.0), **_damp(5.0), 'pressure_factor': 10000.0, 'uniform_pressure_force': BREAST_PRESSURE}, collision=_VOLUME_COLLISION), 'BUTT': dict(type='VOLUME', label='Ягодицы (упругий объём)', name='Butt', vertex_mass=2.0, settings={**_VOLUME_BASE, **_stiff(20.0), **_damp(5.0), 'pressure_factor': 10000.0, 'uniform_pressure_force': BUTT_PRESSURE}, collision=_VOLUME_COLLISION), 'THIGHS': dict(type='VOLUME', label='Бёдра (плотный объём)', name='Thighs', vertex_mass=3.0, settings={**_VOLUME_BASE, **_stiff(30.0), **_damp(8.0), 'pressure_factor': 100.0}, collision=_VOLUME_COLLISION), 'BELLY': dict(type='VOLUME', label='Живот (мягкий объём)', name='Belly', vertex_mass=5.0, settings={**_VOLUME_BASE, **_stiff(10.0), **_damp(5.0), 'pressure_factor': 10000.0}, collision=_VOLUME_COLLISION), 'SKIN_SOFT': dict(type='SURFACE', label='Мягкая кожа', name='Surface', vertex_mass=None, settings={**_SURFACE_BASE, **_stiff(10.0), **_damp(5.0), 'bending_stiffness': 0.3, 'pin_stiffness': 1.0}, collision=_SURFACE_COLLISION), 'SKIN_FIRM': dict(type='SURFACE', label='Упругая кожа', name='Surface', vertex_mass=None, settings={**_SURFACE_BASE, **_stiff(30.0), **_damp(8.0), 'bending_stiffness': 1.0, 'pin_stiffness': 3.0}, collision=_SURFACE_COLLISION), 'HAIR_SOFT': dict(type='HAIR', label='Мягкие волосы', name='Hair', vertex_mass=0.1, settings={**_HAIR_BASE, 'bending_stiffness': 0.05, 'bending_damping': 0.05}, collision=_HAIR_COLLISION), 'HAIR_STIFF': dict(type='HAIR', label='Жёсткие волосы', name='Hair', vertex_mass=0.1, settings={**_HAIR_BASE, 'bending_stiffness': 0.5, 'bending_damping': 0.2}, collision=_HAIR_COLLISION)}
DEFAULT_PRESET = {'VOLUME': 'BREAST', 'SURFACE': 'SKIN_SOFT', 'HAIR': 'HAIR_SOFT'}

def _preset_items(ptype):
    return [(k, v['label'], static_text(f"{v['label']}: Vertex Mass {(v['vertex_mass'] if v['vertex_mass'] is not None else OPEN_VERTEX_MASS)} кг на вершину")) for k, v in PRESETS.items() if v['type'] == ptype]
_PRESET_ENUMS = {t: _preset_items(t) for t in ('VOLUME', 'SURFACE', 'HAIR')}

def _apply_values(target, values, where, log):
    for key, val in values.items():
        if not hasattr(target, key):
            log.append(f'{where}.{key}: свойства нет в этой версии Blender')
            continue
        try:
            setattr(target, key, val)
        except Exception as e:
            log.append(f'{where}.{key}: не удалось записать ({e})')
            continue
        got = getattr(target, key)
        if isinstance(val, float) and abs(got - val) > 0.0001 * max(1.0, abs(val)):
            log.append(f'{where}.{key}: записано {val}, а стало {got} (ограничение диапазона?)')
        elif not isinstance(val, float) and got != val:
            log.append(f'{where}.{key}: записано {val!r}, а стало {got!r}')

def cloth_pin_group(obj):
    if obj.modifiers.get('DynamicPin_Geo') and 'Pin_Final' in obj.vertex_groups:
        return 'Pin_Final'
    for name in ('Pin_Base', 'DynCloth_Pin', 'Pin'):
        if name in obj.vertex_groups:
            return name
    return ''

def reset_cloth_cache(context, mod_cloth):
    pc = mod_cloth.point_cache
    if pc.is_baked:
        try:
            with context.temp_override(point_cache=pc):
                bpy.ops.ptcache.free_bake()
        except Exception:
            pass
    pc.frame_start = context.scene.frame_start
    pc.frame_end = context.scene.frame_end

def proxy_is_bound(obj):
    return any((m.type == 'SURFACE_DEFORM' and m.target == obj for o in bpy.data.objects if o.type == 'MESH' for m in o.modifiers)) or any((m.name.startswith('Hook_') for m in obj.modifiers))

def check_proxy_scale(context, obj, operator=None):
    context.view_layer.update()
    mirrored = obj.matrix_world.to_3x3().determinant() < 0
    if _scale_is_one(obj.matrix_world) and (not mirrored):
        return True
    if mirrored and obj.type == 'MESH' and (obj.data.users == 1):
        ensure_object_mode(context)
        bake_world_scale(context, obj)
        ensure_outward_normals(obj)
        body = proxy_body(obj) or context.scene.proxy_original_body
        rebound = False
        if proxy_is_bound(obj) and body and (body != obj):
            bind_proxy(context, obj, body, operator or _HeldReports())
            rebound = True
        if operator:
            operator.report({'INFO'}, tr(f'{obj.name}: масштаб с отражением применён, нормали пересчитаны наружу') + (tr(', прокси привязан заново') if rebound else ''))
        return True
    if not proxy_is_bound(obj) and obj.type == 'MESH' and (obj.data.users == 1):
        ensure_object_mode(context)
        bake_world_scale(context, obj)
        if operator:
            operator.report({'INFO'}, tr(f'{obj.name}: масштаб запечён в сетку (=1) для стабильной физики'))
        return True
    if operator:
        operator.report({'WARNING'}, tr(f'{obj.name}: масштаб {tuple((round(s, 3) for s in obj.matrix_world.to_scale()))} ≠ 1 — физика может взрываться. Примените масштаб (Ctrl+A → Scale) и привяжите прокси заново.'))
    return False

def pressure_scale_limit(obj, s):
    me = obj.data
    if not me.polygons:
        return None
    k = abs(obj.matrix_world.to_3x3().determinant()) ** (2.0 / 3.0)
    a_v = sum((p.area for p in me.polygons)) * k / len(me.vertices)
    if a_v <= 0.0:
        return None
    return PRESSURE_SAFE_K * s.mass * (s.quality / 5.0) ** 2 / a_v

def clamp_pressure_scale(obj):
    m = _cloth_mod(obj)
    if not m or not m.settings.use_pressure:
        return None
    s = m.settings
    lim = pressure_scale_limit(obj, s)
    if lim is None or s.pressure_factor <= lim:
        return None
    old = s.pressure_factor
    s.pressure_factor = float(max(1, int(lim)))
    obj[PS_LIMITED_KEY] = s.pressure_factor
    return (old, s.pressure_factor)

def draw_ps_limited(layout, obj):
    v, m = (obj.get(PS_LIMITED_KEY), _cloth_mod(obj))
    if v is not None and m and m.settings.use_pressure and (abs(m.settings.pressure_factor - v) < 0.5):
        layout.label(text=tr(PS_LIMITED_LABEL.format(int(v))), translate=False, icon='INFO')

def ensure_proxy_smooth(obj, preset_id, mod_cloth):
    sm = obj.modifiers.get(PROXY_SMOOTH_NAME)
    cfg = PROXY_SMOOTH.get(preset_id)
    if not cfg:
        if sm:
            obj.modifiers.remove(sm)
        return None
    if not sm and any((m.type == 'CORRECTIVE_SMOOTH' for m in obj.modifiers)):
        return None
    sm = sm or obj.modifiers.new(PROXY_SMOOTH_NAME, 'CORRECTIVE_SMOOTH')
    for k, v in cfg.items():
        setattr(sm, k, v)
    move_modifier(obj, sm.name, obj.modifiers.find(mod_cloth.name) + 1)
    return sm

def apply_cloth_preset(context, obj, preset_id, operator=None):
    preset = PRESETS[preset_id]
    ensure_object_mode(context)
    check_proxy_scale(context, obj, operator)
    if preset['type'] != 'HAIR' and ensure_outward_normals(obj):
        body = proxy_body(obj) or context.scene.proxy_original_body
        rebound = proxy_is_bound(obj) and body and (body != obj)
        if rebound:
            bind_proxy(context, obj, body, operator or _HeldReports())
        if operator:
            operator.report({'INFO'}, tr(f'{obj.name}: {NORMALS_FLIPPED_MSG}' + (', прокси привязан заново' if rebound else '')))
    mod_cloth = next((m for m in obj.modifiers if m.type == 'CLOTH'), None)
    if not mod_cloth:
        mod_cloth = obj.modifiers.new(name='Cloth', type='CLOTH')
    place_cloth_modifier(obj, mod_cloth.name)
    log = []
    settings = dict(preset['settings'])
    is_open = preset['type'] == 'SURFACE' or (preset['type'] == 'VOLUME' and (not mesh_is_closed(obj)))
    if is_open:
        if preset['type'] == 'VOLUME':
            log.append('use_pressure: сетка не замкнута — Pressure выключен (иначе взрыв)')
        settings['use_pressure'] = False
    _apply_values(mod_cloth.settings, settings, 'settings', log)
    _apply_values(mod_cloth.collision_settings, preset['collision'], 'collision', log)
    _apply_values(mod_cloth.settings, {'mass': OPEN_VERTEX_MASS if is_open else preset['vertex_mass']}, 'settings', log)
    pin = cloth_pin_group(obj)
    mod_cloth.settings.vertex_group_mass = pin
    if not pin:
        log.append('vertex_group_mass: нет группы закрепления (Pin_Base) — прокси упадёт под гравитацией')
    ensure_proxy_smooth(obj, preset_id, mod_cloth)
    if obj.get(PS_LIMITED_KEY) is not None:
        del obj[PS_LIMITED_KEY]
    cut = clamp_pressure_scale(obj)
    if cut and operator:
        operator.report({'INFO'}, tr(PS_LIMITED_MSG.format(obj.name, int(cut[0]), int(cut[1]))))
    obj['rct_preset'] = preset_id
    obj['rct_preset_version'] = PRESET_VERSION
    if not obj.get('rct_type'):
        obj['rct_type'] = get_proxy_type(obj)
    auto_name_proxy(obj, preset['name'] if preset['type'] != 'HAIR' else None)
    if preset['type'] == 'HAIR':
        col = _collider_collection(context)
    else:
        col = proxy_collision_collection(context, obj)
        fill_proxy_collision_collection(obj, col)
    mod_cloth.collision_settings.collection = col
    reset_cloth_cache(context, mod_cloth)
    for line in log:
        print(f'[RitTools] пресет {preset_id} → {obj.name}: {line}')
    if operator and log:
        operator.report({'WARNING'}, tr(f"Пресет {preset['label']}: {len(log)} замечаний — см. консоль. {log[0]}"))
    return mod_cloth

def _cloth_mod(obj):
    return next((m for m in obj.modifiers if m.type == 'CLOTH'), None) if obj and obj.type == 'MESH' else None

def _cloth_getter(attr, default=0.0, part='settings'):

    def get(self):
        m = _cloth_mod(self)
        return getattr(getattr(m, part), attr) if m else default
    return get

def mirror_partners(obj):
    out = []
    src = obj.get('rct_mirror_of')
    if isinstance(src, bpy.types.Object) and src != obj:
        out.append(src)
    for o in bpy.data.objects:
        if o != obj and o not in out and (o.get('rct_mirror_of') == obj):
            out.append(o)
    return [o for o in out if o.users_scene]

def _cloth_plain_props(struct):
    return [p.identifier for p in struct.bl_rna.properties if not p.is_readonly and p.type in ('BOOLEAN', 'INT', 'FLOAT', 'ENUM') and (getattr(p, 'array_length', 0) == 0) and (not p.identifier.startswith('vertex_group'))]

def mirror_cloth_diff(obj):
    m = _cloth_mod(obj)
    if not m:
        return []
    out = []
    for o in mirror_partners(obj):
        pm = _cloth_mod(o)
        if not pm:
            continue
        for part in ('settings', 'collision_settings'):
            a, b = (getattr(m, part), getattr(pm, part))
            for k in _cloth_plain_props(a):
                va, vb = (getattr(a, k), getattr(b, k))
                if abs(va - vb) > 1e-05 * max(1.0, abs(va)) if isinstance(va, float) else va != vb:
                    name = a.bl_rna.properties[k].name
                    if name not in out:
                        out.append(name)
    return out

def copy_cloth_to_mirror(obj):
    m = _cloth_mod(obj)
    done = []
    for o in mirror_partners(obj) if m else []:
        pm = _cloth_mod(o)
        if not pm:
            continue
        for part in ('settings', 'collision_settings'):
            a, b = (getattr(m, part), getattr(pm, part))
            for k in _cloth_plain_props(a):
                setattr(b, k, getattr(a, k))
        done.append(o.name)
    return done
AUTO_BREAST_SMALL_H = 0.05
AUTO_BREAST_SMALL = (2.0, 10.0)
AUTO_BREAST_BIG = (5.0, 15.0)
AUTO_BREAST_P = (0.0477, -0.0515, 0.2597)
AUTO_BREAST_P_STEP, AUTO_BREAST_P_MAX = (0.05, 0.2)
AUTO_BREAST_KEY = 'rct_auto_breast'

def breast_auto_applied(obj):
    vals, cm = (obj.get(AUTO_BREAST_KEY), _cloth_mod(obj))
    if not vals or not cm:
        return False
    s = cm.settings
    return all((abs(a - b) < 0.0001 for a, b in zip((s.mass, s.tension_stiffness, s.uniform_pressure_force if s.use_pressure else -1.0), vals)))

def _cloth_setter(*attrs, clamp=None, part='settings'):

    def set_(self, value):
        if clamp:
            value = min(max(value, clamp[0]), clamp[1])
        objs = [self]
        if getattr(bpy.context.scene, 'rct_phys_both', False):
            objs += mirror_partners(self)
        for o in objs:
            m = _cloth_mod(o)
            if m:
                for a in attrs:
                    setattr(getattr(m, part), a, value)
                if part == 'settings' and _PS_DEPS.intersection(attrs):
                    clamp_pressure_scale(o)
    return set_
_PS_DEPS = {'mass', 'quality', 'pressure_factor'}
CLOTH_UI_PROPS = {'rct_mass_total': ('Масса вершины (Vertex Mass), кг', 'Vertex Mass: масса КАЖДОЙ вершины, как в панели Cloth (без пересчёта от числа вершин). Больше — тяжелее и инертнее', _cloth_getter('mass'), _cloth_setter('mass'), 0.001, 20.0, 'FLOAT'), 'rct_mass_quick': ('Вес, кг', 'Vertex Mass: масса КАЖДОЙ вершины, кг (число как есть, без пересчёта). 1–10; больше 5 — тяжёлая, может провисать', _cloth_getter('mass'), _cloth_setter('mass', clamp=(1.0, 10.0)), 1.0, 10.0, 'FLOAT_HARD'), 'rct_pressure_quick': ('Надутие', 'Pressure: давление изнутри. Обычно 0, максимум 0.2 — больше грудь начинает раздуваться', _cloth_getter('uniform_pressure_force'), _cloth_setter('uniform_pressure_force'), 0.0, 0.5, 'FLOAT_FINE'), 'rct_pressure': ('Надутие', 'Давление изнутри (Pressure): насколько прокси «надут». 0 — держит исходный объём, больше — раздувается', _cloth_getter('uniform_pressure_force'), _cloth_setter('uniform_pressure_force'), -100.0, 300.0, 'FLOAT'), 'rct_volume_stiffness': ('Упругость объёма', 'Насколько сильно прокси сопротивляется сплющиванию (Pressure Scale). Больше — упругий мячик, меньше — мягко проминается. Не путать с «Надутием»: оно раздувает, а это держит объём', _cloth_getter('pressure_factor'), _cloth_setter('pressure_factor'), 0.0, 10000.0, 'FLOAT'), 'rct_fluid': ('Ощущение жидкости внутри', 'Fluid Density: имитирует жидкость внутри объёма — низ становится тяжелее и «переливается». 0 — выключено. Большие значения могут взорвать симуляцию', _cloth_getter('fluid_density'), _cloth_setter('fluid_density'), -1000.0, 50.0, 'FLOAT'), 'rct_stiffness': ('Упругость', 'Tension: сопротивление растяжению. Больше — твёрже и быстрее возвращается, меньше — мягче и тянется', _cloth_getter('tension_stiffness'), _cloth_setter('tension_stiffness', 'compression_stiffness', 'shear_stiffness'), 0.0, 100.0, 'FLOAT'), 'rct_bending': ('Изгиб', 'Сопротивление сгибанию: больше — держит форму, меньше — мнётся складками', _cloth_getter('bending_stiffness'), _cloth_setter('bending_stiffness'), 0.0, 10.0, 'FLOAT'), 'rct_damping': ('Затухание (сколько трясётся)', 'Damping: больше — колебания быстро успокаиваются, меньше — дольше трясётся', _cloth_getter('tension_damping'), _cloth_setter('tension_damping', 'compression_damping'), 0.0, 50.0, 'FLOAT'), 'rct_pin_stiffness': ('Сила крепления', 'Pin Stiffness: насколько жёстко закреплённая часть (Pin_Base) держится за скелет. Больше — меньше болтается у основания', _cloth_getter('pin_stiffness'), _cloth_setter('pin_stiffness'), 0.0, 50.0, 'FLOAT'), 'rct_shrink': ('Сжатие', 'Shrinking: больше 0 — ткань стягивается, меньше 0 — раздувается', _cloth_getter('shrink_min'), _cloth_setter('shrink_min'), -1.0, 1.0, 'FLOAT'), 'rct_hair_bending': ('Жёсткость на изгиб', 'Насколько пряди сопротивляются сгибанию: больше — пружинят и держат форму', _cloth_getter('bending_stiffness'), _cloth_setter('bending_stiffness'), 0.0, 10.0, 'FLOAT'), 'rct_hair_damping': ('Затухание (сколько трясётся)', 'Bending Damping: больше — пряди быстрее успокаиваются после движения', _cloth_getter('bending_damping'), _cloth_setter('bending_damping'), 0.0, 5.0, 'FLOAT'), 'rct_air': ('Сопротивление воздуха', 'Air Viscosity: воздух тормозит всё движение прокси — больше, и движения плавнее и медленнее, как в воде. При большом весе действует слабо', _cloth_getter('air_damping'), _cloth_setter('air_damping'), 0.0, 10.0, 'FLOAT'), 'rct_col_quality': ('Точность столкновений', 'Collision Quality: сколько раз за шаг проверяются столкновения с телом и опорой. Больше — реже проходит насквозь, но медленнее', _cloth_getter('collision_quality', 2, part='collision_settings'), _cloth_setter('collision_quality', clamp=(1, 20), part='collision_settings'), 1, 20, 'INT'), 'rct_impulse_clamp': ('Гасить дрожание от касаний', 'Impulse Clamping: ограничивает толчок от столкновения. Дрожит, когда касается тела или опоры, — поставьте совсем немного (0.01–0.05). 0 — без ограничения', _cloth_getter('impulse_clamp', part='collision_settings'), _cloth_setter('impulse_clamp', part='collision_settings'), 0.0, 0.5, 'FLOAT_FINE'), 'rct_quality': ('Качество (повысить, если симуляция взрывается)', 'Quality Steps: шагов симуляции на кадр. Больше — стабильнее, но медленнее', _cloth_getter('quality', 5), _cloth_setter('quality'), 1, 20, 'INT')}
CLOTH_FIELDS_BY_TYPE = {'VOLUME': ['rct_mass_total', 'rct_pressure', 'rct_volume_stiffness', 'rct_stiffness', 'rct_quality'], 'SURFACE': ['rct_mass_total', 'rct_stiffness', 'rct_bending', 'rct_quality'], 'HAIR': ['rct_hair_bending', 'rct_hair_damping', 'rct_quality']}
CLOTH_PRO_FIELDS = ['rct_pin_stiffness', 'rct_air', 'rct_col_quality', 'rct_impulse_clamp']
CLOTH_ADVANCED_BY_TYPE = {'VOLUME': ['rct_fluid', 'rct_shrink']}
CLOTH_QUICK_BY_TYPE = {'VOLUME': [('rct_mass_quick', 'Вес, кг'), ('rct_stiffness', 'Упругость'), ('rct_pressure_quick', 'Надутие'), ('rct_quality', 'Качество')], 'SURFACE': [('rct_stiffness', 'Упругость'), ('rct_quality', 'Качество')]}

def register_cloth_ui_props():
    for name, (label, desc, get, set_, mn, smax, kind) in CLOTH_UI_PROPS.items():
        if kind == 'INT':
            prop = bpy.props.IntProperty(name=label, description=desc, get=get, set=set_, min=int(mn), soft_max=int(smax), max=100)
        elif kind == 'FLOAT_FINE':
            prop = bpy.props.FloatProperty(name=label, description=desc, get=get, set=set_, min=mn, soft_max=smax, step=1, precision=3)
        elif kind == 'FLOAT_HARD':
            prop = bpy.props.FloatProperty(name=label, description=desc, get=get, set=set_, min=mn, max=smax)
        else:
            prop = bpy.props.FloatProperty(name=label, description=desc, get=get, set=set_, min=mn, soft_max=smax)
        setattr(bpy.types.Object, name, prop)

def unregister_cloth_ui_props():
    for name in CLOTH_UI_PROPS:
        try:
            delattr(bpy.types.Object, name)
        except AttributeError:
            pass

def draw_shelf_fields(layout, obj):
    sub = layout.column(align=True)
    sub.prop(obj, 'rct_shelf_rows')
    bound = obj.get('rct_shelf_bound_verts') is not None
    changed = bound and shelf_bound_changed(obj)
    r = sub.row(align=True)
    r.enabled = not bound or changed
    r.prop(obj, 'rct_shelf_length' if shelf_length_max(obj) > 50.0 else 'rct_shelf_length_low')
    sub.prop(obj, 'rct_shelf_reach')
    sub.prop(obj, 'rct_pit_depth')
    b = layout.column(align=True)
    if bound:
        if changed:
            w = b.column(align=True)
            w.alert = True
            w.label(text=tr(SHELF_BOUND_CHANGED_MSG), translate=False, icon='ERROR')
        else:
            b.label(text=tr(f"Нижняя граница: {len(obj['rct_shelf_bound_verts'])} верш. тела"), translate=False, icon='CHECKMARK')
    r = b.row(align=True)
    r.operator('object.rct_shelf_set_bound', icon='EDGESEL').proxy_name = obj.name
    if bound:
        r.operator('object.rct_shelf_clear_bound', icon='X', text='Сбросить границу').proxy_name = obj.name
    if _support_default(obj):
        layout.label(text='Если ягодицы упругие и не проваливаются, можно выключить', icon='INFO')
from . import manager
from .bind import _HeldReports, bind_proxy
from .colliders import _collider_collection, _support_default, fill_proxy_collision_collection, proxy_collision_collection, shelf_bound_changed, SHELF_BOUND_CHANGED_MSG, shelf_length_max
