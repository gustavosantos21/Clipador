"""Análise do material bruto: silêncios, cortes de cena, picos de energia e folhas de contato.

Tudo aqui existe para o agente "enxergar" o vídeo antes de decidir onde cortar.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from .ff import ClipadorError, fmt_time, probe, run_ffmpeg, run_ffmpeg_stderr


def _range_args(start: float | None, end: float | None) -> list[str]:
    a: list[str] = []
    if start:
        a += ["-ss", f"{start:.3f}"]
    if end is not None:
        a += ["-to", f"{end:.3f}"]
    return a


# ---------------------------------------------------------------- silêncio


def detect_silences(path: str, threshold_db: float = -35.0, min_duration: float = 0.4,
                    start: float | None = None, end: float | None = None) -> list[tuple[float, float]]:
    """Retorna [(inicio, fim)] de trechos silenciosos, em tempo absoluto do arquivo."""
    info = probe(path)
    if not info["has_audio"]:
        return []
    offset = start or 0.0
    # -ss/-to como opção de input: os timestamps saem relativos ao início do trecho
    args = (["-ss", f"{offset:.3f}"] if offset else []) + (["-to", f"{end:.3f}"] if end is not None else [])
    err = run_ffmpeg_stderr(args + ["-i", path, "-vn", "-af",
                                    f"silencedetect=noise={threshold_db}dB:d={min_duration}", "-f", "null", "-"])
    limit = (end if end is not None else info["duration"])
    out: list[tuple[float, float]] = []
    cur = None
    for line in err.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            cur = float(m.group(1)) + offset
            continue
        m = re.search(r"silence_end: (-?[\d.]+)", line)
        if m and cur is not None:
            out.append((max(cur, offset), float(m.group(1)) + offset))
            cur = None
    if cur is not None:
        out.append((cur, limit))
    return out


def speech_ranges(path: str, start: float, end: float, threshold_db: float = -35.0,
                  min_silence: float = 0.4, pad: float = 0.12, min_keep: float = 0.25) -> list[tuple[float, float]]:
    """Inverso de detect_silences dentro de [start,end]: trechos com fala, com margem."""
    sil = detect_silences(path, threshold_db, min_silence, start, end)
    keep: list[tuple[float, float]] = []
    cur = start
    for s0, s1 in sil:
        a, b = cur, s0 + pad
        if b - a >= min_keep:
            keep.append((max(start, a), min(end, b)))
        cur = max(cur, s1 - pad)
    if end - cur >= min_keep:
        keep.append((cur, end))
    # junta trechos que se sobrepõem por causa do pad
    merged: list[tuple[float, float]] = []
    for a, b in keep:
        if merged and a <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


# ---------------------------------------------------------------- cenas


def detect_scenes(path: str, threshold: float = 0.3, start: float | None = None,
                  end: float | None = None) -> list[float]:
    info = probe(path)
    if not info["has_video"]:
        return []
    offset = start or 0.0
    args = (["-ss", f"{offset:.3f}"] if offset else []) + (["-to", f"{end:.3f}"] if end is not None else [])
    err = run_ffmpeg_stderr(args + ["-i", path, "-an", "-vf",
                                    f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return [round(float(m.group(1)) + offset, 3) for m in re.finditer(r"pts_time:([\d.]+)", err)]


# ---------------------------------------------------------------- energia


def audio_energy(path: str, window: float = 0.5, start: float | None = None,
                 end: float | None = None, sr: int = 8000) -> tuple[np.ndarray, np.ndarray]:
    """RMS em dB por janela. Lê o áudio em blocos via pipe — memória constante mesmo em VODs de 10 h.
    Retorna (tempos, db)."""
    cmd = ["ffmpeg", "-v", "error"] + _range_args(start, end) + ["-i", path, "-vn", "-ac", "1", "-ar", str(sr),
                                                                  "-f", "s16le", "-"]
    n = int(sr * window)
    block = n * 2 * 240  # ~2 min de áudio por leitura
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    vals: list[np.ndarray] = []
    rest = b""
    try:
        while True:
            buf = proc.stdout.read(block)
            if not buf:
                break
            buf = rest + buf
            usable = (len(buf) // (n * 2)) * n * 2
            rest = buf[usable:]
            if usable:
                x = np.frombuffer(buf[:usable], dtype=np.int16).astype(np.float32) / 32768.0
                vals.append(np.sqrt(np.mean(x.reshape(-1, n) ** 2, axis=1) + 1e-12))
    finally:
        proc.stdout.close()
        proc.wait()
    if not vals:
        return np.array([]), np.array([])
    rms = np.concatenate(vals)
    db = 20 * np.log10(rms)
    t = np.arange(len(db)) * window + (start or 0.0)
    return t, db


def energy_peaks(path: str, top: int = 15, window: float = 0.5, min_gap: float = 20.0) -> list[dict]:
    """Momentos de maior energia sonora (risadas, gritos, empolgação) — bons candidatos a highlight."""
    t, db = audio_energy(path, window)
    if len(db) == 0:
        return []
    # suaviza ~3 s para achar "trechos quentes", não estalos isolados
    k = max(1, int(3.0 / window))
    smooth = np.convolve(db, np.ones(k) / k, mode="same")
    median = float(np.median(db))
    order = np.argsort(smooth)[::-1]
    picked: list[dict] = []
    for i in order:
        ti = float(t[i])
        if any(abs(ti - p["time"]) < min_gap for p in picked):
            continue
        picked.append({"time": round(ti, 2), "tc": fmt_time(ti), "db": round(float(smooth[i]), 1),
                       "above_median_db": round(float(smooth[i]) - median, 1)})
        if len(picked) >= top:
            break
    return sorted(picked, key=lambda p: p["time"])


def analyze(path: str, silence_db: float = -35.0, scene_threshold: float = 0.3) -> dict:
    info = probe(path)
    silences = detect_silences(path, silence_db, 0.6)
    total_sil = sum(b - a for a, b in silences)
    report = {
        "file": path,
        "duration": info["duration"],
        "duration_tc": fmt_time(info["duration"]),
        "video": {k: info.get(k) for k in ("width", "height", "fps", "vcodec")},
        "audio": {k: info.get(k) for k in ("sample_rate", "channels", "acodec")},
        "silence_ratio": round(total_sil / info["duration"], 3) if info["duration"] else 0,
        "silences": [{"start": round(a, 2), "end": round(b, 2), "dur": round(b - a, 2)} for a, b in silences],
        "scenes": detect_scenes(path, scene_threshold),
        "energy_peaks": energy_peaks(path),
    }
    return report


# ---------------------------------------------------------------- folha de contato


def contact_sheet(path: str, out: str, times: list[float] | None = None, every: float | None = None,
                  start: float = 0.0, end: float | None = None, cols: int = 4, thumb_w: int = 384,
                  max_frames: int = 24) -> str:
    """Gera uma imagem em grade com frames + timecode, para o agente ver o conteúdo."""
    from PIL import Image, ImageDraw, ImageFont

    info = probe(path)
    dur = info["duration"]
    end = dur if end is None else min(end, dur)
    if not times:
        if not every:
            every = max((end - start) / max_frames, 0.5)
        times = list(np.arange(start, end, every))[:max_frames]
    times = [t for t in times if t < dur]
    if not times:
        raise ClipadorError("nenhum tempo válido para a folha de contato")

    tmpdir = Path(out).with_suffix("")
    tmpdir = tmpdir.parent / (tmpdir.name + "_frames")
    tmpdir.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for i, t in enumerate(times):
        fp = tmpdir / f"f{i:03d}.jpg"
        run_ffmpeg(["-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", f"scale={thumb_w}:-2", "-q:v", "4", str(fp)])
        if fp.exists():
            thumbs.append((t, Image.open(fp).convert("RGB")))
    if not thumbs:
        raise ClipadorError("não foi possível extrair frames")
    tw, th = thumbs[0][1].size
    rows = (len(thumbs) + cols - 1) // cols
    label_h = 26
    sheet = Image.new("RGB", (cols * tw, rows * (th + label_h)), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, (t, im) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * (th + label_h)
        sheet.paste(im, (x, y + label_h))
        draw.text((x + 6, y + 3), f"#{i}  {fmt_time(t)}", fill=(255, 220, 0), font=font)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    for f in tmpdir.glob("*.jpg"):
        f.unlink()
    tmpdir.rmdir()
    return out
