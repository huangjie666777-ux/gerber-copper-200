"""FastAPI request handling: upload, rebuild, stats, SVG download."""
from __future__ import annotations

import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from gerber_parser import GerberError, parse_gerber
from geometry import build_copper, copper_stats
from svg_export import geometry_to_svg

app = FastAPI(title="Gerber Copper Rebuilder")

_JOBS: dict[str, str] = {}  # job id -> svg text


@app.post("/api/rebuild")
async def rebuild(file: UploadFile = File(...),
                  tolerance: float = Form(0.01)):
    if tolerance <= 0:
        raise HTTPException(
            status_code=422,
            detail={"error": "tolerance must be a positive number of "
                             "millimetres", "line": None, "text": None})
    raw = await file.read()
    try:
        source = raw.decode("ascii")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422,
            detail={"error": "file is not ASCII Gerber", "line": None,
                    "text": None})
    try:
        ops, apertures = parse_gerber(source, tolerance)
        copper = build_copper(ops, apertures, tolerance)
    except GerberError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict())
    svg = geometry_to_svg(copper)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = svg
    stats = copper_stats(copper)
    return {
        "job_id": job_id,
        "filename": file.filename,
        "tolerance_mm": tolerance,
        **stats,
        "svg_url": f"/api/rebuild/{job_id}/svg",
    }


@app.get("/api/rebuild/{job_id}/svg")
async def download_svg(job_id: str):
    svg = _JOBS.get(job_id)
    if svg is None:
        raise HTTPException(status_code=404, detail="job not found")
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition":
                 f'attachment; filename="copper_{job_id}.svg"'},
    )

