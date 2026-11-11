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
            "reframe": resolve_reframe(spec, src, info, start, end, seg.get("reframe", spec.get("reframe", {"mode": "crop"}))),
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


def resolve_reframe(spec: dict, src: str, info: dict, start: float, end: float, rf: dict) -> dict:
    """Resolve enquadramentos automáticos ("x": "auto", "mode": "stream") em crop/split concretos."""
    rf = dict(rf)
    if info.get("is_image") or not info.get("width"):
        return rf if rf.get("mode") != "stream" else {"mode": "blur"}
    fmt = output_format(spec)
    out_aspect = fmt["width"] / fmt["height"]
    mode = rf.get("mode", "crop")
    if mode == "crop" and rf.get("x") == "auto":
        from .faces import auto_crop_keyframes
        r = auto_crop_keyframes(src, start, end, out_aspect / float(rf.get("scale", 1.0)),
                                step=float(rf.get("step", 0.5)), deadzone=float(rf.get("deadzone", 0.07)))
        rf["x"] = r["x"]
        rf["_auto"] = {"hits": r["hits"], "samples": r["samples"]}
    elif mode == "stream":
        rf = resolve_stream_layout(spec, src, info, rf, out_aspect, fmt)
    return rf


def resolve_stream_layout(spec: dict, src: str, info: dict, rf: dict, out_aspect: float, fmt: dict) -> dict:
    """Layout de stream: facecam em cima, gameplay embaixo. Sem facecam -> fallback."""
    cam = rf.get("facecam", "auto")
    if cam == "auto":
        from .faces import detect_facecam
        det = detect_facecam(src)
        cam = det["rect"] if det else None
    if not cam:
        fb = rf.get("fallback", "crop")
        return {"mode": "crop", "x": rf.get("game_x", 0.5)} if fb == "crop" else {"mode": fb}
    ratio = float(rf.get("ratio", 0.38))
    zoom = float(rf.get("game_zoom", 1.0))
    src_aspect = info["width"] / info["height"]
    panel_aspect = fmt["width"] / (fmt["height"] * (1 - ratio))
    w = min(1.0, panel_aspect / src_aspect / zoom)
    h = min(1.0, w * src_aspect / panel_aspect) if w >= 1.0 else 1.0 / zoom
    gx = float(rf.get("game_x", 0.5))
    gy = float(rf.get("game_y", 0.5))
    x = min(max(gx - w / 2, 0.0), 1 - w)
    y = min(max(gy - h / 2, 0.0), 1 - h)
    # evita mostrar a webcam de novo dentro do recorte do jogo
    cx, cy, cw, ch = cam
    if rf.get("avoid_facecam", True) and "game_x" not in rf and cy < y + h and cy + ch > y and cx < x + w and cx + cw > x:
        if cx + cw / 2 < 0.5:
            x = min(cx + cw, 1 - w)
        else:
            x = max(cx - w, 0.0)
    return {"mode": "split", "top": list(cam), "bottom": [round(x, 4), round(y, 4), round(w, 4), round(h, 4)],
            "ratio": ratio, "_facecam": list(cam)}
