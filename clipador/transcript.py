"""Transcrição (faster-whisper, opcional), importação de SRT e leitura de transcrições.

Formato padrão da transcrição (JSON):
{
  "source": "raw/video.mp4",
  "language": "pt",
  "segments": [
    {"start": 1.2, "end": 4.8, "text": "frase completa",
     "words": [{"start": 1.2, "end": 1.5, "word": "frase"}, ...]}
  ]
}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .ff import ClipadorError, fmt_time, parse_time


def transcribe(path: str, out: str, model: str = "small", language: str | None = "pt",
               device: str = "auto", compute_type: str = "auto") -> dict:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise ClipadorError(
            "faster-whisper não está instalado. Rode: pip install faster-whisper\n"
            "Alternativa: gere um .srt em outra ferramenta e use `clipador import-srt`."
        ) from e
    if compute_type == "auto":
        compute_type = "int8" if device in ("cpu", "auto") else "float16"
    wm = WhisperModel(model, device=device, compute_type=compute_type)
    segments, info = wm.transcribe(path, language=language, word_timestamps=True, vad_filter=True)
    data = {"source": path, "language": info.language, "segments": []}
    for s in segments:
        words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                 for w in (s.words or []) if w.word.strip()]
        data["segments"].append({"start": round(s.start, 3), "end": round(s.end, 3),
                                 "text": s.text.strip(), "words": words})
    save(data, out)
    return data


def import_srt(srt_path: str, out: str, source: str | None = None) -> dict:
    """Converte SRT em transcrição. Tempos de palavra são estimados proporcionalmente ao tamanho."""
    text = Path(srt_path).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.strip())
    data = {"source": source, "language": None, "segments": []}
    for b in blocks:
        lines = [l for l in b.strip().splitlines() if l.strip()]
        tl = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if tl is None:
            continue
        a, b2 = [x.strip() for x in lines[tl].split("-->")]
        start, end = parse_time(a), parse_time(b2.split()[0])
        content = " ".join(lines[tl + 1:])
        content = re.sub(r"<[^>]+>", "", content).strip()
        data["segments"].append({"start": start, "end": end, "text": content,
                                 "words": estimate_words(content, start, end)})
    save(data, out)
    return data


def estimate_words(text: str, start: float, end: float) -> list[dict]:
    toks = text.split()
    if not toks:
        return []
    weights = [len(t) + 2 for t in toks]
    total = sum(weights)
    out, cur = [], start
    for tok, w in zip(toks, weights):
        d = (end - start) * w / total
        out.append({"start": round(cur, 3), "end": round(cur + d, 3), "word": tok})
        cur += d
    return out


def load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for s in data.get("segments", []):
        if not s.get("words"):
            s["words"] = estimate_words(s.get("text", ""), s["start"], s["end"])
    return data


def save(data: dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def all_words(data: dict) -> list[dict]:
    return [w for s in data.get("segments", []) for w in s.get("words", [])]


def render_text(data: dict, start: float | None = None, end: float | None = None) -> str:
    """Transcrição legível com timecodes — é o que o agente lê para escolher os cortes."""
    lines = []
    for s in data.get("segments", []):
        if start is not None and s["end"] < start:
            continue
        if end is not None and s["start"] > end:
            continue
        lines.append(f"[{fmt_time(s['start'])} → {fmt_time(s['end'])}] {s['text']}")
    return "\n".join(lines)
