"""Interface web local: `python -m clipador serve --port 8765`."""
from __future__ import annotations

import json
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from . import jobs
from .ff import ClipadorError
from .workspace import OUT, PROJECTS, RAW, ROOT, VIDEO_EXT, list_raw, make_spec_from_candidate, rel, slug, work

WEB = Path(__file__).parent / "web"


def _safe(base: Path, sub: str) -> Path:
    p = (base / sub).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise PermissionError("caminho inválido")
    return p


def _err(e: Exception, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(e)}, status_code=code)


async def index(_: Request):
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"))


async def files(_: Request):
    return JSONResponse(list_raw())


async def upload(req: Request):
    name = Path(req.query_params.get("name", "")).name
    if not name:
        return _err(ValueError("faltou ?name="))
    is_video = Path(name).suffix.lower() in VIDEO_EXT
    is_chat = any(name.endswith(x) for x in (".chat.json", ".chat.jsonl", ".chat.csv", ".chat.txt", ".live_chat.json"))
    is_asset = req.query_params.get("asset")
    if not (is_video or is_chat or is_asset):
        return _err(ValueError("envie um vídeo, um chat (<nome>.chat.json/.csv/.txt) ou um asset"))
    dest_dir = ROOT / "assets" / slug(is_asset) if is_asset else RAW
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / (name + ".part")
    with open(tmp, "wb") as f:
        async for chunk in req.stream():  # streaming: não carrega o arquivo na memória
            f.write(chunk)
    tmp.rename(dest_dir / name)
    return JSONResponse({"ok": True, "path": rel(dest_dir / name)})


async def media(req: Request):
    sub = req.path_params["path"]
    for base in (RAW, OUT, PROJECTS):
        prefix = base.name + "/"
        if sub.startswith(prefix):
            p = _safe(base, sub[len(prefix):])
            if p.exists():
                return FileResponse(p)  # suporta Range (seek no player)
    return Response(status_code=404)


async def project(req: Request):
    name = slug(req.path_params["name"])
    w = PROJECTS / name / "work"
    data: dict = {"name": name}
    for key, fn in (("candidates", "candidates.json"), ("facecam", "facecam.json")):
        p = w / fn
        data[key] = json.loads(p.read_text()) if p.exists() else None
    data["facecam_image"] = f"/media/projects/{name}/work/facecam.jpg" if (w / "facecam.jpg").exists() else None
    tp = w / "transcript.json"
    if tp.exists():
        t = json.loads(tp.read_text())
        data["transcript_ranges"] = t.get("ranges")
    sd = PROJECTS / name / "specs"
    data["specs"] = []
    for s in sorted(sd.glob("*.json")) if sd.exists() else []:
        try:
            spec = json.loads(s.read_text())
            out = ROOT / spec.get("output", "")
        except Exception:
            spec, out = {}, Path("/nonexistent")
        item = {"file": s.name, "path": rel(s), "output": spec.get("output"), "rendered": out.exists()}
        if out.exists():
            item["video"] = "/media/" + rel(out)
            pv = out.with_suffix(".preview.jpg")
            item["preview"] = "/media/" + rel(pv) if pv.exists() else None
        data["specs"].append(item)
    return JSONResponse(data)


async def spec_rw(req: Request):
    name = slug(req.path_params["name"])
    p = _safe(PROJECTS / name / "specs", req.path_params["file"])
    if req.method == "GET":
        return Response(p.read_text(encoding="utf-8"), media_type="application/json") if p.exists() else Response(status_code=404)
    body = (await req.body()).decode("utf-8")
    try:
        json.loads(body)
    except json.JSONDecodeError as e:
        return _err(e)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return JSONResponse({"ok": True, "path": rel(p)})


async def validate(req: Request):
    from .spec import expand_segments, load_spec, output_format, validate as v
    body = await req.json()
    try:
        spec = load_spec(body["path"])
        warns = v(spec)
        segs = expand_segments(spec)
        fmt = output_format(spec)
        dur = sum((s["end"] - s["start"]) / s["speed"] for s in segs)
        return JSONResponse({"ok": True, "warnings": warns, "segments": len(segs), "duration": round(dur, 2),
                             "format": f"{fmt['width']}x{fmt['height']}",
                             "reframes": [s["reframe"] for s in segs[:3]]})
    except (ClipadorError, Exception) as e:
        return _err(e)


async def autospec(req: Request):
    b = await req.json()
    name = slug(b["project"])
    cands = json.loads((work(name) / "candidates.json").read_text())["candidates"]
    c = next(x for x in cands if x["id"] == b["id"])
    p = make_spec_from_candidate(name, b["file"], c, b.get("preset", "shorts"), b.get("layout", "auto"))
    return JSONResponse({"ok": True, "file": p.name, "path": rel(p)})


async def jobs_api(req: Request):
    if req.method == "POST":
        b = await req.json()
        if b.get("kind") not in jobs.HANDLERS:
            return _err(ValueError(f"tipo de job inválido: {b.get('kind')}"))
        return JSONResponse({"id": jobs.enqueue(b["kind"], b.get("args", {}), int(b.get("priority", 0)))})
    return JSONResponse(jobs.list_jobs(int(req.query_params.get("limit", 60))))


async def energy(req: Request):
    name = slug(req.path_params["name"])
    p = work(name) / "candidates.json"
    if not p.exists():
        return JSONResponse({"curve": []})
    return JSONResponse({"curve": json.loads(p.read_text()).get("curve", [])})


def make_app() -> Starlette:
    return Starlette(routes=[
        Route("/", index),
        Route("/api/files", files),
        Route("/api/upload", upload, methods=["POST", "PUT"]),
        Route("/api/project/{name}", project),
        Route("/api/project/{name}/energy", energy),
        Route("/api/spec/{name}/{file}", spec_rw, methods=["GET", "PUT"]),
        Route("/api/validate", validate, methods=["POST"]),
        Route("/api/autospec", autospec, methods=["POST"]),
        Route("/api/jobs", jobs_api, methods=["GET", "POST"]),
        Route("/media/{path:path}", media),
    ])


def serve(host: str = "127.0.0.1", port: int = 8765, workers: int = 2) -> None:
    import uvicorn
    for d in (RAW, OUT, PROJECTS):
        d.mkdir(exist_ok=True)
    jobs.start_workers(workers)
    print(f"Clipador em http://{host}:{port}  ({workers} workers)")
    uvicorn.run(make_app(), host=host, port=port, log_level="warning")
