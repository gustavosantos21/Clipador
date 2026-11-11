"""Varredura de streams longas: encontra candidatos a clipe sem transcrever tudo.

Sinais (baratos, escalam para VODs de muitas horas):
  - áudio: pico de volume relativo à linha de base móvel (grito, risada, explosão, empolgação)
  - chat (opcional): explosão de mensagens + palavras de "hype" (KEKW, KKKK, CLIP, ????, LUL...)
Depois só os candidatos são transcritos e editados.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np

from .analyze import audio_energy, detect_silences
from .ff import fmt_time, parse_time, probe

HYPE = re.compile(
    r"\b(kekw|omegalul|lul|lol|lmao|lmfao|k{4,}|(?:ha){3,}|rsrs\w*|clip\w*|pog\w*|monkas|wtf|ez|w+|l+|holy|"
    r"insane|absurdo|caraca|mds|meu deus|nossa)\b|\?{3,}|!{3,}", re.I)


# ---------------------------------------------------------------- chat


def load_chat(path: str) -> list[tuple[float, str]]:
    """Lê chat em vários formatos: TwitchDownloader JSON, chat-downloader JSON, yt-dlp live_chat (jsonl),
    CSV/TSV (tempo,mensagem) ou texto "[HH:MM:SS] usuario: mensagem"."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    out: list[tuple[float, str]] = []
    stripped = text.lstrip()
    if stripped.startswith("{") and '"comments"' in text[:5000]:
        data = json.loads(text)
        for c in data["comments"]:
            msg = c.get("message", {})
            body = msg.get("body") if isinstance(msg, dict) else str(msg)
            out.append((float(c["content_offset_seconds"]), body or ""))
    elif stripped.startswith("["):
        for c in json.loads(text):
            t = c.get("time_in_seconds", c.get("time", c.get("offset")))
            out.append((parse_time(t), c.get("message") or c.get("text") or ""))
    elif stripped.startswith("{"):  # jsonl (yt-dlp live_chat)
        for line in text.splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            r = o.get("replayChatItemAction")
            if not r:
                continue
            t = int(r.get("videoOffsetTimeMsec", 0)) / 1000
            for a in r.get("actions", []):
                item = a.get("addChatItemAction", {}).get("item", {})
                rend = item.get("liveChatTextMessageRenderer")
                if rend:
                    out.append((t, "".join(x.get("text", "") for x in rend.get("message", {}).get("runs", []))))
    else:
        m_re = re.compile(r"^\[?(\d+:\d{2}(?::\d{2})?(?:\.\d+)?)\]?\s*(.*)$")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = m_re.match(line)
            if m:
                out.append((parse_time(m.group(1)), m.group(2)))
                continue
            row = next(csv.reader([line], delimiter="\t" if "\t" in line else ","))
            if len(row) >= 2:
                try:
                    out.append((parse_time(row[0]), row[-1]))
                except Exception:
                    pass
    return sorted(out)


# ---------------------------------------------------------------- sinais


def _rolling_median(x: np.ndarray, win: int) -> np.ndarray:
    if len(x) == 0:
        return x
    # mediana em blocos + interpolação: O(n), suficiente para linha de base
    step = max(1, win // 4)
    centers, meds = [], []
    for i in range(0, len(x), step):
        a, b = max(0, i - win // 2), min(len(x), i + win // 2)
        centers.append(i)
        meds.append(np.median(x[a:b]))
    return np.interp(np.arange(len(x)), centers, meds)


def _smooth(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or len(x) == 0:
        return x
    return np.convolve(x, np.ones(k) / k, mode="same")


def _robust_z(x: np.ndarray, base: np.ndarray) -> np.ndarray:
    d = x - base
    mad = np.median(np.abs(d - np.median(d))) * 1.4826 + 1e-6
    return d / mad


def signals(path: str, chat_path: str | None = None, chat_delay: float = 8.0) -> dict:
    """Séries por segundo: audio_z, chat_z, hype, score."""
    t, db = audio_energy(path, window=1.0)
    n = len(db)
    db = np.maximum(db, -70)
    base = _rolling_median(db, 180)
    audio_z = _smooth(_robust_z(db, base), 3)
    audio_db = _smooth(db - base, 3)  # dB acima da linha de base (legível para humanos)
    chat_z = np.zeros(n)
    hype = np.zeros(n)
    msgs = np.zeros(n)
    if chat_path:
        for ts, m in load_chat(chat_path):
            i = int(ts - chat_delay)  # o chat reage com atraso
            if 0 <= i < n:
                msgs[i] += 1
                if HYPE.search(m or ""):
                    hype[i] += 1
        rate = _smooth(msgs, 10)
        chat_z = _smooth(_robust_z(rate, _rolling_median(rate, 300)), 5) + 0.5 * _smooth(hype, 10)
    # compressão suave: um sinal enorme não domina tudo, e não há empate artificial no topo
    score = 8 * np.tanh(np.maximum(audio_z, -3) / 8) + (10 * np.tanh(np.maximum(chat_z, -3) / 10) if chat_path else 0)
    return {"t": t, "audio_z": audio_z, "audio_db": audio_db, "chat_z": chat_z, "msgs": msgs, "hype": hype, "score": score,
            "has_chat": bool(chat_path)}


def scan(path: str, chat_path: str | None = None, top: int = 30, pre: float = 22.0, post: float = 8.0,
         min_gap: float = 45.0, max_len: float = 58.0, min_len: float = 15.0) -> dict:
    """Lista ranqueada de candidatos a clipe."""
    info = probe(path)
    dur = info["duration"]
    sig = signals(path, chat_path)
    score = sig["score"]
    n = len(score)
    if n == 0:
        return {"file": path, "duration": dur, "candidates": [], "curve": []}
    silences = detect_silences(path, -38, 0.35)
    sil_starts = np.array([a for a, _ in silences]) if silences else np.array([])
    sil_ends = np.array([b for _, b in silences]) if silences else np.array([])

    def snap(t, arr, lo, hi):
        if len(arr) == 0:
            return t
        cand = arr[(arr >= lo) & (arr <= hi)]
        return float(cand[np.argmin(np.abs(cand - t))]) if len(cand) else t

    order = np.argsort(score)[::-1]
    picked: list[dict] = []
    thr = float(np.percentile(score, 75))
    for i in order:
        if len(picked) >= top or score[i] <= 1.0:
            break
        pk = float(i)
        if any(abs(pk - c["peak"]) < min_gap for c in picked):
            continue
        # estende o fim enquanto o "calor" continua (reação, risada que segue)
        j = i
        while j + 1 < n and score[j + 1] > thr and (j - i) < max_len - pre:
            j += 1
        start = max(0.0, pk - pre)
        end = min(dur, float(j) + post)
        if end - start > max_len:
            end = start + max_len
        if end - start < min_len:
            end = min(dur, start + min_len)
        start = snap(start, sil_ends, start - 3, start + 3)
        end = snap(end, sil_starts, end - 3, end + 2)
        reasons = []
        if sig["audio_z"][i] > 2.5:
            reasons.append(f"pico de áudio (+{sig['audio_db'][i]:.0f} dB acima do normal)")
        if sig["has_chat"]:
            w = slice(max(0, i - 5), min(n, i + 15))
            if sig["chat_z"][i] > 2:
                reasons.append(f"chat agitado ({int(sig['msgs'][w].sum())} msgs, {int(sig['hype'][w].sum())} de hype)")
        picked.append({"peak": pk, "start": round(start, 2), "end": round(end, 2),
                       "score": round(float(score[i]), 2), "audio_z": round(float(sig["audio_z"][i]), 2),
                       "chat_z": round(float(sig["chat_z"][i]), 2), "reasons": reasons})
    picked.sort(key=lambda c: -c["score"])
    for k, c in enumerate(picked):
        c["id"] = f"c{k + 1:02d}"
        c["tc"] = f"{fmt_time(c['start'], ms=False)} → {fmt_time(c['end'], ms=False)}"
        c["duration"] = round(c["end"] - c["start"], 1)
    # curva reduzida para a interface (1 ponto a cada ~5 s)
    step = max(1, n // 1500)
    curve = [[int(k), round(float(score[k]), 2)] for k in range(0, n, step)]
    return {"file": path, "duration": dur, "has_chat": sig["has_chat"], "candidates": picked, "curve": curve}
