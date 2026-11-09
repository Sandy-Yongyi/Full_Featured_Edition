"""Convert existing BlockData and dictionary regions to line vertices."""

from collections.abc import Mapping
import numpy as np

REGION_COLORS = {"outside": (0.0, 1.0, 0.0), "inside": (1.0, 0.0, 0.0), "jig": (1.0, 1.0, 0.0)}


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def box_geometry(data, include: set[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    vertices, colors = [], []

    def add(bounds, color, layer):
        if include is not None and layer not in include:
            return
        if any(value is None for value in bounds):
            return
        values = np.asarray(bounds, dtype=np.float32)
        if not np.isfinite(values).all():
            return
        x0, x1, y0, y1, z0, z1 = values
        corners = np.array(((x0, y0, z0), (x0, y0, z1), (x0, y1, z0), (x0, y1, z1), (x1, y0, z0), (x1, y0, z1), (x1, y1, z0), (x1, y1, z1)), dtype=np.float32)
        edges = ((0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7))
        lines = corners[np.asarray(edges).ravel()]
        vertices.append(lines)
        colors.append(np.tile(color, (24, 1)))

    if isinstance(data, Mapping):
        for jig in data.get("jig_data", ()) or ():
            add([_get(jig, key) for key in ("x_min", "x_max", "y_min", "y_max", "z_start", "z_end")], REGION_COLORS["jig"], "jig")
        outside = data.get("outside_data") or {}
        if isinstance(outside, Mapping):
            add([outside.get(key) for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")], REGION_COLORS["outside"], "outside")
    else:
        outside = _get(data, "outside_data", ()) or ()
        for region in outside:
            add([_get(region, f"outside_{key}") for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")], REGION_COLORS["outside"], "outside")
        if outside:
            for jig in _get(data, "jig_data", ()) or ():
                add([_get(outside[0], "outside_x_min"), _get(outside[0], "outside_x_max"),
                     _get(jig, "jig_y_min"), _get(jig, "jig_y_max"),
                     _get(jig, "jig_z_min"), _get(jig, "jig_z_max")], REGION_COLORS["jig"], "jig")
    for inside in _get(data, "inside_data", ()) or ():
        for region in _get(inside, "subinside_datalist", ()) or ():
            add([_get(region, f"subinside_{key}") for key in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")], REGION_COLORS["inside"], "inside")
    if not vertices:
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.float32)
    return np.ascontiguousarray(np.vstack(vertices), dtype=np.float32), np.ascontiguousarray(np.vstack(colors), dtype=np.float32)
