# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 RitCrom. Assets (PROXY.blend, PROXYHANDS.obj, name RitTools): ASSETS_LICENSE.txt
import bmesh
import math
import os
from mathutils import Vector
from .i18n import tr
from .zone import _world_kdtree
PIT_RAY_EDGES = 2.0
PIT_MIN_VERTS = 3
PIT_MIN_DEPTH = 0.1
PIT_MAX_REMNANT = 0.25
PIT_GROW_TRIES = 3
BUMP_SCALES = (3.0, 4.0)
BUMP_MIN_HEIGHT = 0.3
BUMP_MIN_VERTS = 7
BUMP_MIN_ROUND = 0.35
BUMP_BAND = 1.0
BUMP_MAX_ZONE = 6.0
BUMP_FIT_RING = 2.5
BUMP_MAX_SHIFT = 0.1
BUMP_MAX_VOLUME_LOSS = 0.03
BUMP_MIN_EDGE_FLOOR = 0.00011
from . import dense
from .mesh_utils import mesh_shape_coords
