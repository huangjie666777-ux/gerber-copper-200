"""Exposure geometry reconstruction from parsed Gerber ops (Shapely)."""
from __future__ import annotations

import math

from shapely.geometry import (
    GeometryCollection, LineString, MultiPolygon, Point, Polygon, box,
)
from shapely.ops import unary_union

from gerber_parser import Aperture, GerberError, Op


def _arc_points(x1, y1, x2, y2, ci, cj, cw, tol, line, text):
    """Sample a G75 arc. I/J are center offsets from the arc start."""
    cx, cy = x1 + ci, y1 + cj
    r = math.hypot(ci, cj)
    if r <= 0:
        raise GerberError("arc with zero radius (I=J=0)", line, text)
    r_end = math.hypot(x2 - cx, y2 - cy)
    if abs(r_end - r) > max(0.05 * r, 0.02):
        raise GerberError(
            f"arc endpoint not on circle (r={r:.6f} vs {r_end:.6f} mm)",
            line, text)
    a0 = math.atan2(y1 - cy, x1 - cx)
    a1 = math.atan2(y2 - cy, x2 - cx)
    full = abs(x2 - x1) < 1e-12 and abs(y2 - y1) < 1e-12
    if cw:
        sweep = (a0 - a1) % (2 * math.pi)
    else:
        sweep = (a1 - a0) % (2 * math.pi)
    if full:
        sweep = 2 * math.pi
    if sweep <= 0:
        raise GerberError("degenerate arc with zero sweep", line, text)
    # chord sagitta r*(1-cos(theta/2)) <= tol
    ratio = max(-1.0, 1.0 - tol / r)
    step = 2 * math.acos(ratio)
    step = min(step, math.pi / 2)
    n = max(1, math.ceil(sweep / step))
    pts = []
    for k in range(1, n + 1):
        if cw:
            a = a0 - sweep * k / n
        else:
            a = a0 + sweep * k / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts[-1] = (x2, y2)  # land exactly on the stated endpoint
    return pts


def _circle_polygon(x, y, radius, tol):
    ratio = max(-1.0, 1.0 - tol / radius)
    step = 2 * math.acos(ratio)
    step = min(step, math.pi / 4)
    n = max(8, math.ceil(2 * math.pi / step))
    return Polygon([
        (x + radius * math.cos(2 * math.pi * k / n),
         y + radius * math.sin(2 * math.pi * k / n))
        for k in range(n)
    ])


def _aperture_flash(ap: Aperture, x, y, tol):
    if ap.kind == "C":
        return _circle_polygon(x, y, ap.params[0] / 2, tol)
    w, h = ap.params
    return box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def _aperture_stroke(ap: Aperture, coords, tol, line, text):
    if ap.kind != "C":
        raise GerberError("R (rectangle) aperture may only be flashed (D03)",
                          line, text)
    radius = ap.params[0] / 2
    ratio = max(-1.0, 1.0 - tol / radius)
    step = 2 * math.acos(ratio)
    resolution = max(4, math.ceil(math.pi / step))
    line_geom = LineString(coords)
    return line_geom.buffer(radius, cap_style="round", join_style="round",
                            resolution=resolution)


def build_copper(ops: list[Op], apertures: dict, tolerance: float):
    """Compose the final copper geometry honoring LP order."""
    copper = GeometryCollection()
    for op in ops:
        if op.kind == "eof":
            break
        if op.kind == "polarity":
            continue
        d = op.data
        if op.kind == "flash":
            geom = _aperture_flash(apertures[d["ap"]], d["x"], d["y"], tolerance)
        elif op.kind == "line":
            if d["x1"] == d["x2"] and d["y1"] == d["y2"]:
                geom = _aperture_flash(apertures[d["ap"]], d["x1"], d["y1"],
                                       tolerance)
            else:
                geom = _aperture_stroke(apertures[d["ap"]],
                                        [(d["x1"], d["y1"]), (d["x2"], d["y2"])],
                                        tolerance, op.line, op.text)
        elif op.kind == "arc":
            pts = [(d["x1"], d["y1"])] + _arc_points(
                d["x1"], d["y1"], d["x2"], d["y2"], d["i"], d["j"], d["cw"],
                tolerance, op.line, op.text)
            geom = _aperture_stroke(apertures[d["ap"]], pts, tolerance,
                                    op.line, op.text)
        elif op.kind == "region":
            geom = _build_region(d["points"], op.line, op.text)
        else:
            continue
        if d.get("polarity") == "C":
            copper = copper.difference(geom)
        else:
            copper = unary_union([copper, geom])
    return copper


def _build_region(points, line, text):
    if len(points) < 4:
        raise GerberError("region contour has fewer than 3 distinct vertices",
                          line, text)
    if points[0] != points[-1]:
        raise GerberError("G36/G37 region contour is not closed", line, text)
    ring = LineString(points)
    if not ring.is_simple:
        raise GerberError("G36/G37 region contour is self-intersecting",
                          line, text)
    poly = Polygon(points)
    if not poly.is_valid or poly.area <= 0:
        raise GerberError("G36/G37 region is degenerate", line, text)
    return poly


def copper_stats(geom) -> dict:
    if geom.is_empty:
        return {"area_mm2": 0.0, "bbox_mm": None, "components": 0, "holes": 0}
    polys = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        polys = [g for g in getattr(geom, "geoms", []) if not g.is_empty]
    minx, miny, maxx, maxy = geom.bounds
    return {
        "area_mm2": round(geom.area, 6),
        "bbox_mm": [round(minx, 6), round(miny, 6),
                    round(maxx, 6), round(maxy, 6)],
        "components": len(polys),
        "holes": sum(len(p.interiors) for p in polys),
    }

