"""Receita de edição (spec JSON): carregamento, validação e expansão.

Veja docs/RECEITA.md para a referência completa dos campos.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .analyze import speech_ranges
from .ff import ClipadorError, parse_time, probe
from .presets import PRESETS, get_preset

TOP_KEYS = {"source", "output", "preset", "width", "height", "fps", "reframe", "segments", "transition",
            "overlays", "texts", "captions", "audio", "fade_in", "fade_out", "remove_silence", "quality",
            "title", "notes", "background_color", "color", "$schema"}
SEG_KEYS = {"source", "start", "end", "speed", "reframe", "zooms", "remove_silence", "label", "mute", "volume"}


def load_spec(path: str) -> dict:
    p = Path(path)
    try:
        spec = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ClipadorError(f"JSON inválido em {path}: {e}") from e
    spec["_base"] = str(p.resolve().parent)
    return spec


def resolve_path(spec: dict, value: str) -> str:
    """Caminhos relativos são procurados a partir da raiz do repo (cwd) e depois da pasta da receita."""
    p = Path(value)
    if p.is_absolute() or p.exists():
        return str(p)
    alt = Path(spec.get("_base", ".")) / value
    if alt.exists():
        return str(alt)
    return str(p)


def validate(spec: dict) -> list[str]:
    """Retorna lista de avisos; levanta ClipadorError em erros fatais."""
    warns: list[str] = []
    unknown = set(spec) - TOP_KEYS - {"_base"}
    if unknown:
        warns.append(f"campos desconhecidos ignorados: {sorted(unknown)}")
    if "preset" in spec and spec["preset"] not in PRESETS:
        raise ClipadorError(f"preset desconhecido: {spec['preset']}")
    if not spec.get("segments"):
        raise ClipadorError("a receita precisa de pelo menos um item em 'segments'")
    if not spec.get("output"):
        raise ClipadorError("faltou 'output'")
    for i, seg in enumerate(spec["segments"]):
        src = seg.get("source") or spec.get("source")
        if not src:
            raise ClipadorError(f"segments[{i}]: sem 'source' (nem global)")
        src = resolve_path(spec, src)
        if not Path(src).exists():
            raise ClipadorError(f"segments[{i}]: arquivo não encontrado: {src}")
        info = probe(src)
        bad = set(seg) - SEG_KEYS
        if bad:
            warns.append(f"segments[{i}]: campos desconhecidos {sorted(bad)}")
        is_image = info.get("is_image")
        start = parse_time(seg.get("start", 0))
        if "end" not in seg and not is_image:
            end = info["duration"]
        elif "end" not in seg:
            raise ClipadorError(f"segments[{i}]: imagem precisa de 'end' (duração)")
        else:
            end = parse_time(seg["end"])
        if end <= start:
            raise ClipadorError(f"segments[{i}]: end ({end}) <= start ({start})")
        if not is_image and end > info["duration"] + 0.05:
            raise ClipadorError(f"segments[{i}]: end {end:.2f}s passa da duração do arquivo ({info['duration']:.2f}s)")
        sp = float(seg.get("speed", 1.0))
        if not 0.25 <= sp <= 4.0:
            raise ClipadorError(f"segments[{i}]: speed deve estar entre 0.25 e 4")
    for i, ov in enumerate(spec.get("overlays", [])):
        f = resolve_path(spec, ov.get("file", ""))
        if not Path(f).exists():
            raise ClipadorError(f"overlays[{i}]: arquivo não encontrado: {f}")
    music = (spec.get("audio") or {}).get("music")
    if music and not Path(resolve_path(spec, music["file"])).exists():
        raise ClipadorError(f"audio.music: arquivo não encontrado: {music['file']}")
    cap = spec.get("captions")
    if cap and cap.get("transcript") and not Path(resolve_path(spec, cap["transcript"])).exists():
        raise ClipadorError(f"captions.transcript não encontrado: {cap['transcript']}")
    return warns


def output_format(spec: dict) -> dict:
    fmt = get_preset(spec.get("preset", "shorts"))
    for k in ("width", "height", "fps"):
        if k in spec:
            fmt[k] = spec[k]
    return fmt


def expand_segments(spec: dict) -> list[dict]:
    """Normaliza segmentos: resolve fonte/tempos, aplica remove_silence (jump cuts) e distribui zooms."""
    out: list[dict] = []
    global_rs = spec.get("remove_silence")
    for i, seg in enumerate(spec["segments"]):
        seg = copy.deepcopy(seg)
        src = resolve_path(spec, seg.get("source") or spec["source"])
        info = probe(src)
        start = parse_time(seg.get("start", 0))
        end = parse_time(seg["end"]) if "end" in seg else info["duration"]
        base = {
            "index": i,
            "label": seg.get("label", f"seg{i}"),
            "source": src,
            "is_image": bool(info.get("is_image")),
            "has_audio": info["has_audio"] and not seg.get("mute", False),
            "src_w": info.get("width"), "src_h": info.get("height"),
            "speed": float(seg.get("speed", 1.0)),
            "volume": float(seg.get("volume", 1.0)),
            "reframe": seg.get("reframe", spec.get("reframe", {"mode": "crop"})),
            "zooms": [dict(z, start=parse_time(z["start"]), end=parse_time(z["end"])) for z in seg.get("zooms", [])],
        }
        rs = seg.get("remove_silence", global_rs)
        if rs and not base["is_image"] and info["has_audio"]:
            rs = {} if rs is True else rs
            ranges = speech_ranges(src, start, end,
                                   threshold_db=rs.get("threshold_db", -35),
                                   min_silence=rs.get("min_silence", 0.45),
                                   pad=rs.get("pad", 0.12))
            if not ranges:
                ranges = [(start, end)]
        else:
            ranges = [(start, end)]
        for a, b in ranges:
            s = dict(base, start=a, end=b)
            s["zooms"] = [z for z in base["zooms"] if z["end"] > a and z["start"] < b]
            out.append(s)
    return out


def source_to_output_map(segments: list[dict], transition: float = 0.0):
    """Retorna função (source, t) -> tempo na saída (ou None se t foi cortado)."""
    offsets = []
    acc = 0.0
    for k, s in enumerate(segments):
        offsets.append(acc)
        acc += (s["end"] - s["start"]) / s["speed"] - (transition if k + 1 < len(segments) else 0)

    def f(source: str, t: float):
        for s, off in zip(segments, offsets):
            if Path(s["source"]).resolve() == Path(source).resolve() and s["start"] <= t < s["end"]:
                return off + (t - s["start"]) / s["speed"]
        return None

    return f, offsets
