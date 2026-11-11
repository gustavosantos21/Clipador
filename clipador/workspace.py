"""Organização de pastas por vídeo bruto e geração automática de receitas a partir de candidatos."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .ff import REPO_ROOT, probe

ROOT = Path.cwd() if (Path.cwd() / "clipador").exists() else REPO_ROOT
RAW = ROOT / "raw"
OUT = ROOT / "out"
PROJECTS = ROOT / "projects"
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm", ".flv", ".ts", ".m4v"}


def slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:80] or "video"


def project_name(raw_file: str | Path) -> str:
    return slug(Path(raw_file).stem)


def pdir(name: str) -> Path:
    return PROJECTS / name


def work(name: str) -> Path:
    d = pdir(name) / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def specs_dir(name: str) -> Path:
    d = pdir(name) / "specs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_chat(raw_file: Path) -> Path | None:
    for ext in (".chat.json", ".chat.jsonl", ".live_chat.json", ".chat.csv", ".chat.txt"):
        c = raw_file.with_name(raw_file.stem + ext)
        if c.exists():
            return c
    return None


def list_raw() -> list[dict]:
    RAW.mkdir(exist_ok=True)
    out = []
    for f in sorted(RAW.iterdir()):
        if f.suffix.lower() not in VIDEO_EXT:
            continue
        name = project_name(f)
        w = pdir(name) / "work"
        item = {"file": f.name, "project": name, "size_mb": round(f.stat().st_size / 1e6, 1),
                "chat": find_chat(f).name if find_chat(f) else None,
                "scanned": (w / "candidates.json").exists(),
                "facecam": (w / "facecam.json").exists(),
                "transcript": (w / "transcript.json").exists()}
        try:
            info = probe(f)
            item.update(duration=round(info["duration"], 1), width=info.get("width"), height=info.get("height"))
        except Exception as e:  # arquivo ainda sendo enviado, corrompido etc.
            item["error"] = str(e)[:200]
        out.append(item)
    return out


def rel(p: Path | str) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(p)


def make_spec_from_candidate(name: str, raw_file: str, cand: dict, preset: str = "shorts",
                             layout: str = "auto", caption_style: str = "bold_pop") -> Path:
    """Receita inicial automática para um candidato. O agente/humano refina depois (gancho, título, zooms)."""
    w = work(name)
    fc = w / "facecam.json"
    facecam = json.loads(fc.read_text()) if fc.exists() else None
    if layout == "auto":
        layout = "stream" if facecam else "face"
    if layout == "stream" and facecam:
        reframe = {"mode": "stream", "facecam": facecam["rect"], "ratio": 0.38}
    elif layout == "stream":
        reframe = {"mode": "stream", "facecam": "auto", "ratio": 0.38}
    elif layout == "face":
        reframe = {"mode": "crop", "x": "auto"}
    else:
        reframe = {"mode": layout}
    spec: dict = {
        "title": f"{name} {cand['id']} — {cand.get('tc', '')}",
        "notes": "Gerada automaticamente a partir do candidato. Revise: gancho, título, zooms, corte inicial/final.",
        "source": rel(RAW / raw_file),
        "output": rel(OUT / name / f"{cand['id']}_{preset}.mp4"),
        "preset": preset,
        "reframe": reframe,
        "segments": [{"start": cand["start"], "end": cand["end"], "label": cand["id"]}],
        "audio": {"normalize": True, "lufs": -14},
        "fade_out": 0.3,
    }
    tp = w / "transcript.json"
    if tp.exists():
        t = json.loads(tp.read_text())
        if any(cand["start"] <= s["start"] < cand["end"] for s in t.get("segments", [])):
            spec["captions"] = {"transcript": rel(tp), "style": caption_style}
    out = specs_dir(name) / f"{cand['id']}_{preset}.json"
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def make_compilation_spec(name: str, raw_file: str, cands: list[dict], n: int = 10, preset: str = "youtube",
                          transition: float = 0.5, min_score: float = 0.0) -> Path:
    """Vídeo longo: os N melhores momentos em ordem cronológica, com transição e capítulos."""
    from .ff import fmt_time
    chosen = sorted([c for c in cands if c["score"] >= min_score][:n], key=lambda c: c["start"])
    if not chosen:
        raise ValueError("nenhum candidato para a compilação")
    w = work(name)
    vertical = preset not in ("youtube", "youtube4k")
    fc = w / "facecam.json"
    if vertical:
        reframe = ({"mode": "stream", "facecam": json.loads(fc.read_text())["rect"]} if fc.exists()
                   else {"mode": "crop", "x": "auto"})
    else:
        reframe = {"mode": "crop", "x": 0.5}  # 16:9 -> 16:9 não corta nada
    chapters, acc = [], 0.0
    for i, c in enumerate(chosen):
        mm = fmt_time(acc, ms=False)
        chapters.append(f"{mm[3:] if mm.startswith('00:') else mm} Momento {i + 1}")
        acc += (c["end"] - c["start"]) - (transition if i + 1 < len(chosen) else 0)
    spec = {
        "title": f"{name} — melhores momentos",
        "notes": "Compilação automática. Revise a ordem, renomeie os capítulos e escreva título/descrição em `post`.",
        "source": rel(RAW / raw_file),
        "output": rel(OUT / name / f"compilacao_{preset}.mp4"),
        "preset": preset,
        "reframe": reframe,
        "segments": [{"start": c["start"], "end": c["end"], "label": c["id"]} for c in chosen],
        "transition": {"type": "fade", "duration": transition},
        "audio": {"normalize": True, "lufs": -14},
        "fade_in": 0.5,
        "fade_out": 1.0,
        "post": {"title": f"MELHORES MOMENTOS — {name}", "description": "", "hashtags": [],
                 "chapters": chapters},
    }
    tp = w / "transcript.json"
    if tp.exists():
        spec["captions"] = {"transcript": rel(tp), "style": "clean_box" if not vertical else "bold_pop"}
    out = specs_dir(name) / f"compilacao_{preset}.json"
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
