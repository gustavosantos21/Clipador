"""Utilitários de baixo nível: tempo, ffprobe, execução do ffmpeg, fontes."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class ClipadorError(Exception):
    pass


def require_binaries() -> None:
    for b in ("ffmpeg", "ffprobe"):
        if not shutil.which(b):
            raise ClipadorError(f"'{b}' não encontrado no PATH. Instale o ffmpeg.")


# ---------------------------------------------------------------- tempo

_TC = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:[.,]\d+)?)$")


def parse_time(value) -> float:
    """Aceita 83.5, "83.5", "01:23.5", "00:01:23.500", "1:02:03,25"."""
    if value is None:
        raise ClipadorError("tempo vazio")
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s.replace(",", "."))
    except ValueError:
        pass
    m = _TC.match(s)
    if not m:
        raise ClipadorError(f"tempo inválido: {value!r} (use segundos ou HH:MM:SS.ms)")
    h = int(m.group(1) or 0)
    return h * 3600 + int(m.group(2)) * 60 + float(m.group(3).replace(",", "."))


def fmt_time(t: float, ms: bool = True) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if ms else f"{h:02d}:{m:02d}:{int(s):02d}"


# ---------------------------------------------------------------- probe


@lru_cache(maxsize=64)
def _probe_cached(path: str, mtime: float) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise ClipadorError(f"ffprobe falhou em {path}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def probe(path: str | Path) -> dict:
    """Resumo útil de um arquivo de mídia."""
    p = Path(path)
    if not p.exists():
        raise ClipadorError(f"arquivo não encontrado: {p}")
    data = _probe_cached(str(p.resolve()), p.stat().st_mtime)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    info = {
        "path": str(p),
        "duration": float(data["format"].get("duration") or 0),
        "has_video": v is not None,
        "has_audio": a is not None,
    }
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        if abs(rot) in (90, 270):
            w, h = h, w
        num, den = (v.get("avg_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        info.update(width=w, height=h, fps=round(fps, 3), vcodec=v.get("codec_name"),
                    is_image=v.get("codec_name") in ("png", "mjpeg", "webp", "bmp", "gif") and info["duration"] < 0.1)
    if a:
        info.update(sample_rate=int(a.get("sample_rate", 0)), channels=a.get("channels"),
                    acodec=a.get("codec_name"))
    return info


# ---------------------------------------------------------------- execução


def run_ffmpeg(args: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    cmd = ["ffmpeg", "-hide_banner", "-y"] + (["-loglevel", "error", "-nostats"] if quiet else []) + args
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise ClipadorError("ffmpeg falhou:\n" + " ".join(cmd) + "\n\n" + res.stderr[-4000:])
    return res


def run_ffmpeg_stderr(args: list[str]) -> str:
    """Roda ffmpeg e devolve o stderr (para filtros de análise que logam lá)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats"] + args
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise ClipadorError("ffmpeg falhou:\n" + " ".join(cmd) + "\n\n" + res.stderr[-4000:])
    return res.stderr


# ---------------------------------------------------------------- fontes

REPO_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = REPO_ROOT / "assets" / "fonts"


@lru_cache(maxsize=32)
def font_file(name: str) -> str:
    """Resolve um nome de fonte ("Inter Black", "Inter:style=Bold") ou caminho para um arquivo."""
    p = Path(name)
    if p.suffix.lower() in (".ttf", ".otf") and p.exists():
        return str(p)
    local = FONTS_DIR / name
    if local.exists():
        return str(local)
    if shutil.which("fc-match"):
        r = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    raise ClipadorError(f"fonte não encontrada: {name}")


def escape_filter_path(path: str | Path) -> str:
    """Escapa um caminho para uso como valor de opção dentro de um filtergraph."""
    s = str(Path(path).resolve())
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")
