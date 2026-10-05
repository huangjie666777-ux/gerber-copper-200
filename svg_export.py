"""SVG export of the final copper geometry (holes + Y-up orientation)."""
from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon


def _ring_path(coords) -> str:
    pts = list(coords)
    parts = [f"M{pts[0][0]:.6f},{pts[0][1]:.6f}"]
    parts += [f"L{x:.6f},{y:.6f}" for x, y in pts[1:]]
    parts.append("Z")
    return "".join(parts)


def _poly_path(poly: Polygon) -> str:
    d = _ring_path(poly.exterior.coords)
    for interior in poly.interiors:
        d += _ring_path(interior.coords)
    return d


def geometry_to_svg(geom, margin: float = 1.0) -> str:
    if geom.is_empty:
        return ('<svg xmlns="http://www.w3.org/2000/svg" '
                'viewBox="0 0 1 1" width="100" height="100"></svg>\n')
    polys = []
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        polys = [g for g in getattr(geom, "geoms", [])
                 if isinstance(g, Polygon)]
    minx, miny, maxx, maxy = geom.bounds
    x0, y0 = minx - margin, miny - margin
    w = (maxx - minx) + 2 * margin
    h = (maxy - miny) + 2 * margin
    d = "".join(_poly_path(p) for p in polys)
    # flip Y so Gerber's Y-up coordinates render correctly in SVG (Y-down)
    flip = f"translate(0,{miny + maxy:.6f}) scale(1,-1)"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{x0:.6f} {y0:.6f} {w:.6f} {h:.6f}" '
        f'width="{w * 20:.2f}" height="{h * 20:.2f}">\n'
        f'  <g transform="{flip}">\n'
        f'    <path d="{d}" fill="#c8862a" fill-rule="evenodd" '
        f'stroke="none"/>\n'
        f'  </g>\n'
        f'</svg>\n'
    )

