import math

import pytest
from fastapi.testclient import TestClient

from app import app
from gerber_parser import GerberError, parse_gerber
from geometry import build_copper, copper_stats

client = TestClient(app)

HEADER = "%FSLAX24Y24*%\n%MOMM*%\n"


def build(src, tol=0.01):
    ops, aps = parse_gerber(src, tol)
    return build_copper(ops, aps, tol)


def test_line_trace_area():
    src = HEADER + "%ADD10C,1.0*%\nD10*\nX0Y0D02*\nX100000Y0D01*\nM02*\n"
    g = build(src)
    # 10mm stroke of width 1 + two round caps
    assert g.area == pytest.approx(10 * 1 + math.pi * 0.25, rel=0.02)
    assert copper_stats(g)["components"] == 1


def test_rect_flash_only():
    src = HEADER + "%ADD11R,2.0X1.0*%\nD11*\nX5000Y5000D03*\nM02*\n"
    g = build(src)
    assert g.area == pytest.approx(2.0)
    assert g.bounds == pytest.approx((-0.5, 0.0, 1.5, 1.0))


def test_rect_draw_rejected():
    src = HEADER + "%ADD11R,2.0X1.0*%\nD11*\nX0Y0D02*\nX1000Y0D01*\nM02*\n"
    with pytest.raises(GerberError, match="only be flashed"):
        build(src)


def test_ccw_quarter_arc():
    src = (HEADER + "%ADD10C,0.1*%\nD10*\nG75*\n"
           "X10000Y0D02*\nG03*\nX0Y10000I-10000J0D01*\nM02*\n")
    g = build(src)
    assert not g.is_empty
    assert g.bounds[2] == pytest.approx(1.0, abs=0.1)
    assert g.bounds[3] == pytest.approx(1.0, abs=0.1)


def test_cw_full_circle():
    src = (HEADER + "%ADD10C,0.1*%\nD10*\nG75*\nG02*\n"
           "X10000Y0D02*\nX10000Y0I-10000J0D01*\nM02*\n")
    g = build(src)
    # annulus: outer r=1.05 inner r=0.95
    expect = math.pi * (1.05 ** 2 - 0.95 ** 2)
    assert g.area == pytest.approx(expect, rel=0.05)
    assert copper_stats(g)["holes"] == 1


def test_arc_off_circle_rejected():
    src = (HEADER + "%ADD10C,0.1*%\nD10*\nG75*\nG03*\n"
           "X0Y0D02*\nX20000Y0I-10000J0D01*\nM02*\n")
    with pytest.raises(GerberError, match="not on circle"):
        build(src)


def test_region_fill_and_unclosed():
    src = (HEADER + "G36*\nX0Y0D02*\nX40000Y0D01*\nX40000Y30000D01*\n"
           "X0Y30000D01*\nX0Y0D01*\nG37*\nM02*\n")
    g = build(src)
    assert g.area == pytest.approx(12.0)
    bad = src.replace("G37*", "")
    with pytest.raises(GerberError, match="not closed"):
        build(bad)


def test_region_self_intersect():
    src = (HEADER + "G36*\nX0Y0D02*\nX20000Y20000D01*\nX20000Y0D01*\n"
           "X0Y20000D01*\nX0Y0D01*\nG37*\nM02*\n")
    with pytest.raises(GerberError, match="self-intersecting"):
        build(src)


def test_polarity_clear_then_restore():
    src = (HEADER + "%ADD10C,4.0*%\n%ADD11C,2.0*%\n%ADD12C,1.0*%\n"
           "D10*\nX0Y0D03*\n%LPC*%\nD11*\nX0Y0D03*\n%LPD*%\n"
           "D12*\nX0Y0D03*\nM02*\n")
    g = build(src)
    expect = math.pi * (4 - 1 + 0.25)
    assert g.area == pytest.approx(expect, rel=0.05)
    assert copper_stats(g)["holes"] == 1


def test_inches():
    src = ("%FSLAX24Y24*%\n%MOIN*%\n%ADD10C,0.04*%\nD10*\n"
           "X0Y0D02*\nX10000Y0D01*\nM02*\n")
    g = build(src)
    assert g.bounds[2] == pytest.approx(25.4 + 0.508, abs=0.05)


def test_modal_coords_and_missing_axis():
    src = HEADER + "%ADD10C,0.5*%\nD10*\nX0Y0D02*\nX50000*\nY50000*\nM02*\n"
    g = build(src)
    assert g.bounds[2] == pytest.approx(5.0, abs=0.3)
    assert g.bounds[3] == pytest.approx(5.0, abs=0.3)


def test_undefined_aperture():
    src = HEADER + "D10*\nX0Y0D03*\nM02*\n"
    with pytest.raises(GerberError) as e:
        build(src)
    assert e.value.line == 3
    assert "D10" in e.value.text


def test_unsupported_code():
    src = HEADER + "G04 hi *\nG54D10*\nM02*\n"
    with pytest.raises(GerberError, match="unsupported"):
        build(src)


def test_truncated_file():
    src = HEADER + "%ADD10C,1.0*%\nD10*\nX0Y0D03*\n"
    with pytest.raises(GerberError, match="M02"):
        build(src)


def test_empty_copper_ok():
    src = HEADER + "G04 nothing *\nM02*\n"
    g = build(src)
    stats = copper_stats(g)
    assert stats["area_mm2"] == 0.0
    assert stats["components"] == 0


def test_api_upload_and_svg():
    src = HEADER + "%ADD10C,1.0*%\nD10*\nX0Y0D02*\nX100000Y0D01*\nM02*\n"
    r = client.post("/api/rebuild",
                    files={"file": ("t.gbr", src, "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert body["area_mm2"] > 0
    assert body["bbox_mm"][2] > 10
    r2 = client.get(body["svg_url"])
    assert r2.status_code == 200
    assert "evenodd" in r2.text
    assert "scale(1,-1)" in r2.text


def test_api_error_has_position():
    src = HEADER + "D99*\nM02*\n"
    r = client.post("/api/rebuild",
                    files={"file": ("bad.gbr", src, "text/plain")})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["line"] == 3
    assert detail["text"] == "D99"


def test_api_bad_tolerance():
    r = client.post("/api/rebuild", data={"tolerance": "0"},
                    files={"file": ("t.gbr", "M02*\n", "text/plain")})
    assert r.status_code == 422

