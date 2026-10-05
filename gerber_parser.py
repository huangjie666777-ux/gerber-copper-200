"""ASCII Gerber subset parser.

Supports: FSLA (absolute, leading-zero omitted), MO MM/IN, AD (C, R apertures),
Dnn select, D01/D02/D03, G01/G02/G03 (G75 multi-quadrant), G36/G37 regions,
G04 comments, LP D/C, M02 EOF.
Produces a list of ops consumed by geometry.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class GerberError(Exception):
    def __init__(self, message: str, line: int, text: str):
        super().__init__(message)
        self.message = message
        self.line = line
        self.text = text.strip()

    def to_dict(self) -> dict:
        return {"error": self.message, "line": self.line, "text": self.text}


@dataclass
class Aperture:
    kind: str  # "C" or "R"
    params: tuple  # C: (diameter_mm,)  R: (w_mm, h_mm)


@dataclass
class Op:
    kind: str
    line: int
    text: str
    data: dict = field(default_factory=dict)


@dataclass
class _State:
    x_dec: int = 0
    y_dec: int = 0
    unit: float = 1.0  # multiplier to mm
    apertures: dict = field(default_factory=dict)
    current_ap: int | None = None
    cx: float | None = None  # current point, mm
    cy: float | None = None
    interp: str = "G01"
    in_region: bool = False
    polarity: str = "D"
    region_pts: list = field(default_factory=list)
    region_line: int = 0
    region_text: str = ""
    got_mo: bool = False
    got_fs: bool = False
    got_m02: bool = False


def parse_gerber(source: str, tolerance: float) -> tuple[list[Op], dict]:
    lines = source.splitlines()
    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln) + 1)

    def line_of(offset: int) -> int:
        lo, hi = 0, len(lines) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    # split into blocks terminated by '*'; '%' wraps extended commands
    blocks = []  # (text, line)
    i, n = 0, len(source)
    in_ext = False
    buf = ""
    buf_line = 1
    while i < n:
        ch = source[i]
        if ch == "%":
            if in_ext:
                if buf.strip():
                    blocks.append((buf.strip(), buf_line))
                buf = ""
                in_ext = False
            else:
                if buf.strip():
                    blocks.append((buf.strip(), buf_line))
                buf = ""
                in_ext = True
            buf_line = line_of(i + 1)
            i += 1
            continue
        if ch == "*":
            if not in_ext:
                blocks.append((buf.strip(), buf_line))
                buf = ""
                buf_line = line_of(i + 1)
            i += 1
            continue
        if ch in "\r\n":
            i += 1
            continue
        if not buf:
            buf_line = line_of(i)
        buf += ch
        i += 1
    if buf.strip():
        blocks.append((buf.strip(), buf_line))

    st = _State()
    ops: list[Op] = []

    def err(msg, line, text):
        raise GerberError(msg, line, text)

    coord_re = re.compile(
        r"^(?:G0?([123]))?(?:X([+-]?\d+))?(?:Y([+-]?\d+))?"
        r"(?:I([+-]?\d+))?(?:J([+-]?\d+))?(?:D0?([123]))?$"
    )

    def to_mm(raw: str, dec: int) -> float:
        return int(raw) / (10 ** dec) * st.unit

    def require_pos(line, text):
        if st.cx is None or st.cy is None:
            err("first coordinate has no previous position to inherit", line, text)

    def emit_draw(g, x, y, ii, jj, line, text):
        require_pos(line, text)
        nx = st.cx if x is None else to_mm(x, st.x_dec)
        ny = st.cy if y is None else to_mm(y, st.y_dec)
        mode = g or st.interp
        if st.in_region:
            if mode != "G01":
                err("only G01 linear segments allowed inside G36/G37 region", line, text)
            if ii is not None or jj is not None:
                err("I/J not allowed inside region", line, text)
            st.region_pts.append((nx, ny))
        else:
            if mode == "G01":
                if ii is not None or jj is not None:
                    err("I/J given for linear G01 draw", line, text)
                ops.append(Op("line", line, text,
                              {"x1": st.cx, "y1": st.cy, "x2": nx, "y2": ny}))
            elif mode in ("G02", "G03"):
                if ii is None and jj is None:
                    err("arc missing I/J center offset", line, text)
                ci = to_mm(ii, st.x_dec) if ii is not None else 0.0
                cj = to_mm(jj, st.y_dec) if jj is not None else 0.0
                ops.append(Op("arc", line, text, {
                    "x1": st.cx, "y1": st.cy, "x2": nx, "y2": ny,
                    "i": ci, "j": cj, "cw": mode == "G02"}))
            else:
                err(f"unsupported interpolation {mode}", line, text)
        st.cx, st.cy = nx, ny

    for text, line in blocks:
        if not text:
            continue
        if st.got_m02:
            err("content after M02 end of file", line, text)

        if text.startswith("FS"):
            m = re.fullmatch(r"FS([LT])([AI])X(\d)(\d)Y(\d)(\d)", text)
            if not m:
                err("malformed FS statement", line, text)
            if m.group(1) != "L":
                err("only leading-zero omission (FSLx) supported", line, text)
            if m.group(2) != "A":
                err("only absolute coordinates (FSxA) supported", line, text)
            if m.group(3) != m.group(5) or m.group(4) != m.group(6):
                err("X and Y format must match", line, text)
            st.x_dec = int(m.group(4))
            st.y_dec = int(m.group(6))
            st.got_fs = True
            continue
        if text.startswith("MO"):
            u = text[2:]
            if u == "MM":
                st.unit = 1.0
            elif u == "IN":
                st.unit = 25.4
            else:
                err(f"unsupported unit MO{u}", line, text)
            st.got_mo = True
            continue
        if text.startswith("AD"):
            m = re.fullmatch(r"ADD(\d+)([CR])(.*)", text)
            if not m:
                err("only C and R aperture macros supported", line, text)
            num = int(m.group(1))
            if num < 10:
                err("aperture D-code must be >= 10", line, text)
            args = m.group(3)
            if args.startswith(","):
                args = args[1:]
            if m.group(2) == "C":
                parts = args.split("X")
                try:
                    d = float(parts[0]) * st.unit
                except ValueError:
                    err("invalid C aperture diameter", line, text)
                if len(parts) > 1 and parts[1] not in ("", "0"):
                    err("C aperture with hole not supported", line, text)
                if d <= 0:
                    err("aperture diameter must be positive", line, text)
                st.apertures[num] = Aperture("C", (d,))
            else:
                parts = args.split("X")
                if len(parts) < 2:
                    err("R aperture needs widthXheight", line, text)
                try:
                    w = float(parts[0]) * st.unit
                    h = float(parts[1]) * st.unit
                except ValueError:
                    err("invalid R aperture size", line, text)
                if len(parts) > 2 and parts[2] not in ("", "0"):
                    err("R aperture with hole not supported", line, text)
                if w <= 0 or h <= 0:
                    err("aperture size must be positive", line, text)
                st.apertures[num] = Aperture("R", (w, h))
            continue
        if text.startswith("LP"):
            p = text[2:]
            if p not in ("D", "C"):
                err(f"unsupported polarity LP{p}", line, text)
            if st.in_region:
                err("LP not allowed inside region", line, text)
            st.polarity = p
            ops.append(Op("polarity", line, text, {"polarity": p}))
            continue
        if text.startswith("G04") or text.startswith("G4"):
            continue
        if text in ("G01", "G1", "G02", "G2", "G03", "G3"):
            st.interp = "G0" + text[-1]
            continue
        if text == "G75":
            continue
        if text == "G74":
            err("G74 single-quadrant arcs not supported (use G75)", line, text)
        if text == "G36":
            if st.in_region:
                err("nested G36 region", line, text)
            st.in_region = True
            st.region_pts = []
            st.region_line = line
            st.region_text = text
            continue
        if text == "G37":
            if not st.in_region:
                err("G37 without matching G36", line, text)
            st.in_region = False
            ops.append(Op("region", st.region_line, st.region_text,
                          {"points": list(st.region_pts)}))
            st.region_pts = []
            continue
        if text in ("M02", "M2"):
            if st.in_region:
                err("region not closed with G37 before M02", line, text)
            st.got_m02 = True
            ops.append(Op("eof", line, text, {}))
            continue

        m = re.fullmatch(r"D(\d+)", text)
        if m:
            code = int(m.group(1))
            if code < 10:
                err(f"unsupported D-code D{code:02d}", line, text)
            if code not in st.apertures:
                err(f"aperture D{code} not defined", line, text)
            st.current_ap = code
            continue

        m = coord_re.match(text)
        if m and any(g is not None for g in m.groups()):
            g = "G0" + m.group(1) if m.group(1) else None
            x, y, ii, jj, d = (m.group(2), m.group(3), m.group(4),
                               m.group(5), m.group(6))
            if not st.got_fs or not st.got_mo:
                err("coordinate used before FS/MO header", line, text)
            if d == "3":
                nx = st.cx if x is None else to_mm(x, st.x_dec)
                ny = st.cy if y is None else to_mm(y, st.y_dec)
                if nx is None or ny is None:
                    err("flash before any coordinate established", line, text)
                if st.in_region:
                    err("D03 flash not allowed inside region", line, text)
                if st.current_ap is None:
                    err("no aperture selected for flash", line, text)
                ops.append(Op("flash", line, text,
                              {"x": nx, "y": ny, "ap": st.current_ap,
                               "polarity": st.polarity}))
                st.cx, st.cy = nx, ny
            elif d == "2":
                nx = st.cx if x is None else to_mm(x, st.x_dec)
                ny = st.cy if y is None else to_mm(y, st.y_dec)
                if st.in_region:
                    if st.region_pts:
                        err("D02 move inside region must be the first point only",
                            line, text)
                    st.region_pts.append((nx, ny))
                st.cx, st.cy = nx, ny
            else:
                # D01 draw (explicit or modal bare coordinate)
                if not st.in_region and st.current_ap is None:
                    err("no aperture selected for draw", line, text)
                emit_draw(g, x, y, ii, jj, line, text)
                if not st.in_region:
                    ops[-1].data["ap"] = st.current_ap
                    ops[-1].data["polarity"] = st.polarity
            continue

        err(f"unsupported or unrecognized statement: {text!r}", line, text)

    if st.in_region:
        err("file truncated: region not closed with G37",
            st.region_line, st.region_text)
    if not st.got_m02:
        err("file truncated: missing M02 end of file",
            len(lines), lines[-1] if lines else "")
    return ops, st.apertures
