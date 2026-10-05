
"""FastAPI 请求处理层: 上传、铜层重建、SVG 下载。"""
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from gerber.errors import GerberError
from gerber.geometry import build_geometry, summarize
from gerber.parser import Parser
from gerber.svg_export import geometry_to_svg

app = FastAPI(title="Gerber 铜层重建服务")

# svg_id -> (svg_text, stats)
_results = {}


def _rebuild(text, tolerance):
    parser = Parser(text)
    events = parser.parse()
    geom = build_geometry(events, parser.apertures, tolerance)
    stats = summarize(geom)
    svg = geometry_to_svg(geom)
    return stats, svg


@app.post("/api/rebuild")
async def rebuild(file: UploadFile = File(...),
                  tolerance: float = Form(0.01)):
    if tolerance <= 0:
        raise HTTPException(422, "tolerance 必须为正数(毫米)")
    raw = await file.read()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(422, "仅支持 ASCII 编码的 Gerber 文件")
    try:
        stats, svg = _rebuild(text, tolerance)
    except GerberError as exc:
        raise HTTPException(422, {
            "error": exc.message, "line": exc.line, "source": exc.source})
    svg_id = uuid.uuid4().hex
    _results[svg_id] = svg
    stats["svg_id"] = svg_id
    stats["svg_url"] = "/api/rebuild/%s/svg" % svg_id
    return stats


@app.get("/api/rebuild/{svg_id}/svg")
async def download_svg(svg_id: str):
    svg = _results.get(svg_id)
    if svg is None:
        raise HTTPException(404, "结果不存在或已过期")
    return Response(
        svg, media_type="image/svg+xml",
        headers={"Content-Disposition":
                 'attachment; filename="copper_%s.svg"' % svg_id[:8]})

