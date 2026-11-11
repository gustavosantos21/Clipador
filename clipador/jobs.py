"""Fila de trabalhos persistente (SQLite) + workers.

Vários workers (processos/threads) podem consumir a mesma fila: `python -m clipador worker -n 3`.
Para escalar em várias máquinas troque o SQLite por Postgres/Redis mantendo a mesma interface
(enqueue / claim / finish) — veja docs/ESCALA.md.
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
import traceback
from pathlib import Path

from .workspace import ROOT

DB_PATH = Path(os.environ.get("CLIPADOR_DB", ROOT / ".cache" / "jobs.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  args TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error
  priority INTEGER NOT NULL DEFAULT 0,
  progress REAL NOT NULL DEFAULT 0,
  message TEXT DEFAULT '',
  result TEXT,
  worker TEXT,
  created REAL NOT NULL,
  started REAL,
  finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, priority, id);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def enqueue(kind: str, args: dict, priority: int = 0) -> int:
    con = connect()
    cur = con.execute("INSERT INTO jobs(kind,args,priority,created) VALUES (?,?,?,?)",
                      (kind, json.dumps(args, ensure_ascii=False), priority, time.time()))
    return int(cur.lastrowid)


def claim(worker: str) -> dict | None:
    con = connect()
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC, id LIMIT 1").fetchone()
    if not row:
        con.execute("COMMIT")
        return None
    con.execute("UPDATE jobs SET status='running', worker=?, started=? WHERE id=?", (worker, time.time(), row["id"]))
    con.execute("COMMIT")
    return _row(row)


def update(job_id: int, **kw) -> None:
    if "result" in kw:
        kw["result"] = json.dumps(kw["result"], ensure_ascii=False)
    sets = ", ".join(f"{k}=?" for k in kw)
    connect().execute(f"UPDATE jobs SET {sets} WHERE id=?", (*kw.values(), job_id))


def get(job_id: int) -> dict | None:
    row = connect().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(row) if row else None


def list_jobs(limit: int = 100) -> list[dict]:
    return [_row(r) for r in connect().execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def requeue_stale() -> int:
    """Jobs 'running' de um worker que morreu voltam para a fila (chamado na inicialização)."""
    host = socket.gethostname()
    cur = connect().execute("UPDATE jobs SET status='queued', worker=NULL WHERE status='running' AND worker LIKE ?",
                            (f"{host}:%",))
    return cur.rowcount


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["args"] = json.loads(d["args"])
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    return d


# ---------------------------------------------------------------- handlers


def _h_scan(job, prog):
    from .faces import detect_facecam
    from .highlights import scan
    from .workspace import RAW, find_chat, project_name, work
    f = RAW / job["args"]["file"]
    name = project_name(f)
    w = work(name)
    chat = job["args"].get("chat") or (str(find_chat(f)) if find_chat(f) else None)
    prog(0.05, "procurando picos de áudio/chat")
    res = scan(str(f), chat, top=int(job["args"].get("top", 30)))
    (w / "candidates.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    prog(0.6, "procurando facecam")
    fc = None
    try:
        fc = detect_facecam(str(f), debug_image=str(w / "facecam.jpg"))
    except Exception as e:  # sem OpenCV, por exemplo
        prog(0.6, f"facecam ignorada: {e}")
    if fc:
        (w / "facecam.json").write_text(json.dumps(fc, indent=1))
    elif (w / "facecam.json").exists():
        (w / "facecam.json").unlink()
    return {"project": name, "candidates": len(res["candidates"]), "facecam": fc}


def _h_transcribe(job, prog):
    from .transcript import transcribe_ranges
    from .workspace import RAW, project_name, work
    f = RAW / job["args"]["file"]
    name = project_name(f)
    w = work(name)
    ranges = job["args"].get("ranges")
    if not ranges:
        cands = json.loads((w / "candidates.json").read_text())["candidates"]
        ranges = [(c["start"] - 5, c["end"] + 5) for c in cands]
    transcribe_ranges(str(f), ranges, str(w / "transcript.json"), model=job["args"].get("model", "small"),
                      language=job["args"].get("language", "pt"), progress=lambda p: prog(p, "transcrevendo"))
    return {"project": name, "ranges": len(ranges)}


def _h_autospec(job, prog):
    from .workspace import make_spec_from_candidate, rel
    a = job["args"]
    from .workspace import work
    cands = json.loads((work(a["project"]) / "candidates.json").read_text())["candidates"]
    ids = a.get("ids") or [c["id"] for c in cands[: int(a.get("top", 5))]]
    made = []
    for c in cands:
        if c["id"] in ids:
            for preset in a.get("presets", ["shorts"]):
                made.append(rel(make_spec_from_candidate(a["project"], a["file"], c, preset, a.get("layout", "auto"))))
    return {"specs": made}


def _h_render(job, prog):
    from .render import render
    prog(0.1, "renderizando")
    meta = render(job["args"]["spec"], draft=job["args"].get("draft", False), preview=True)
    meta.pop("command", None)
    return meta


def _h_pipeline(job, prog):
    """Tudo de uma vez para uma stream: scan -> receitas dos top N -> render rascunho."""
    a = job["args"]
    r = _h_scan(job, lambda p, m="": prog(p * 0.4, m))
    sub = {"args": {"project": r["project"], "file": a["file"], "top": a.get("top_render", 5),
                    "presets": a.get("presets", ["shorts"])}}
    specs = _h_autospec(sub, prog)["specs"]
    ids = []
    for s in specs:
        ids.append(enqueue("render", {"spec": s, "draft": a.get("draft", True)}))
    return {**r, "specs": specs, "render_jobs": ids}


def _h_compile(job, prog):
    from .workspace import make_compilation_spec, rel, work
    a = job["args"]
    cands = json.loads((work(a["project"]) / "candidates.json").read_text())["candidates"]
    p = make_compilation_spec(a["project"], a["file"], cands, n=int(a.get("n", 10)), preset=a.get("preset", "youtube"))
    rid = None
    if a.get("render", True):
        rid = enqueue("render", {"spec": rel(p), "draft": a.get("draft", True)})
    return {"spec": rel(p), "render_job": rid}


def _h_package(job, prog):
    from .deliver import package
    from .workspace import PROJECTS
    a = job["args"]
    specs = a.get("specs")
    if not specs:  # todas as receitas renderizadas do projeto
        from .spec import load_spec, resolve_path
        specs = []
        for sp in sorted((PROJECTS / a["project"] / "specs").glob("*.json")):
            spec = load_spec(str(sp))
            if Path(resolve_path(spec, spec["output"])).exists():
                specs.append(str(sp))
    return package(specs, a.get("dest"))


def _h_publish(job, prog):
    from .publish import youtube_upload
    a = job["args"]
    return youtube_upload(a["spec"], privacy=a.get("privacy", "private"), publish_at=a.get("publish_at"),
                          thumbnail=a.get("thumbnail"), progress=lambda p: prog(p, "enviando"))


HANDLERS = {"compile": _h_compile, "package": _h_package, "publish": _h_publish,"scan": _h_scan, "transcribe": _h_transcribe, "autospec": _h_autospec,
            "render": _h_render, "pipeline": _h_pipeline}


def run_one(job: dict) -> None:
    def prog(p: float, msg: str = "") -> None:
        update(job["id"], progress=round(min(max(p, 0), 1), 3), message=msg[:500])

    try:
        res = HANDLERS[job["kind"]](job, prog)
        update(job["id"], status="done", progress=1.0, result=res, finished=time.time(), message="ok")
    except Exception as e:
        update(job["id"], status="error", message=f"{e}"[-1500:], finished=time.time(),
               result={"traceback": traceback.format_exc()[-4000:]})


def worker_loop(stop: threading.Event | None = None, name: str | None = None, poll: float = 1.0) -> None:
    name = name or f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident() % 10000}"
    while not (stop and stop.is_set()):
        job = claim(name)
        if job is None:
            time.sleep(poll)
            continue
        run_one(job)


def start_workers(n: int) -> threading.Event:
    requeue_stale()
    stop = threading.Event()
    for i in range(n):
        threading.Thread(target=worker_loop, args=(stop,), daemon=True, name=f"worker{i}").start()
    return stop
