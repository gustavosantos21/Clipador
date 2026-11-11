"""Gera legendas animadas (.ass) a partir de palavras com tempo na timeline de SAÍDA.

Os estilos ficam em styles/captions/*.json. Modos:
  highlight  – bloco de palavras, palavra falada muda de cor
  pop        – como highlight + palavra falada "pula" (escala)
  karaoke    – preenchimento progressivo (\\kf)
  word       – uma palavra por vez, grande
  static     – frase inteira, sem animação por palavra
"""
from __future__ import annotations

import json
from pathlib import Path

from .ff import REPO_ROOT, ClipadorError

STYLES_DIR = REPO_ROOT / "styles" / "captions"

DEFAULT_STYLE = {
    "font": "Inter Black",
    "size": 0.052,          # fração da altura do vídeo
    "uppercase": True,
    "mode": "pop",
    "primary": "#FFFFFF",
    "highlight": "#FFE600",
    "outline_color": "#000000",
    "outline": 0.10,        # fração do tamanho da fonte
    "shadow": 0.0,
    "shadow_color": "#00000080",
    "box": False,
    "box_color": "#000000B0",
    "position": "lower",    # top | center | lower | bottom
    "margin_v": None,       # fração da altura (sobrepõe position)
    "margin_h": 0.08,       # fração da largura
    "max_words": 3,
    "max_chars": 18,
    "pop_scale": 1.15,
    "gap_break": 0.6,       # pausa (s) que força quebra de bloco
    "linger": 0.25,         # quanto o bloco fica na tela após a última palavra
}

_POS = {"top": (8, 0.10), "center": (5, 0.0), "lower": (2, 0.24), "bottom": (2, 0.09)}


def list_styles() -> list[str]:
    return sorted(p.stem for p in STYLES_DIR.glob("*.json"))


def load_style(style: str | dict | None, overrides: dict | None = None) -> dict:
    st = dict(DEFAULT_STYLE)
    if isinstance(style, dict):
        st.update(style)
    elif style:
        p = Path(style)
        if not p.exists():
            p = STYLES_DIR / f"{style}.json"
        if not p.exists():
            raise ClipadorError(f"estilo de legenda não encontrado: {style}. Disponíveis: {', '.join(list_styles())}")
        st.update(json.loads(p.read_text(encoding="utf-8")))
    if overrides:
        st.update({k: v for k, v in overrides.items() if v is not None})
    return st


def ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 6:
        h += "FF"
    if len(h) != 8:
        raise ClipadorError(f"cor inválida: {hex_color}")
    r, g, b, a = h[0:2], h[2:4], h[4:6], h[6:8]
    inv = 255 - int(a, 16)
    return f"&H{inv:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(word: str, upper: bool) -> str:
    w = word.replace("\\", "").replace("{", "(").replace("}", ")").strip()
    return w.upper() if upper else w


def chunk_words(words: list[dict], st: dict) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            chars = sum(len(x["word"]) + 1 for x in cur) + len(w["word"])
            gap = w["start"] - cur[-1]["end"]
            ends_sentence = cur[-1]["word"].rstrip().endswith((".", "!", "?", "…"))
            if (len(cur) >= st["max_words"] or chars > st["max_chars"] or gap > st["gap_break"]
                    or ends_sentence or (st["mode"] == "word")):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[dict], width: int, height: int, style: dict) -> str:
    st = style
    fs = int(round(st["size"] * height))
    outline = round(st["outline"] * fs, 1)
    shadow = round(st["shadow"] * fs, 1)
    align, mv_default = _POS.get(st["position"], _POS["lower"])
    mv = int((st["margin_v"] if st["margin_v"] is not None else mv_default) * height)
    mh = int(st["margin_h"] * width)
    border_style = 3 if st["box"] else 1
    outline_col = ass_color(st["box_color"]) if st["box"] else ass_color(st["outline_color"])
    back_col = ass_color(st["box_color"]) if st["box"] else ass_color(st["shadow_color"])
    if st["box"]:
        outline = max(outline, round(fs * 0.18, 1))
    primary = ass_color(st["primary"])
    hl = ass_color(st["highlight"])
    karaoke_secondary = ass_color(st.get("karaoke_base", "#FFFFFF80"))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{fs},{primary},{karaoke_secondary if st['mode'] == 'karaoke' else primary},{outline_col},{back_col},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},{align},{mh},{mh},{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    up = st["uppercase"]
    chunks = chunk_words(words, st)
    for ci, ch in enumerate(chunks):
        c_start = ch[0]["start"]
        c_end = ch[-1]["end"] + st["linger"]
        if ci + 1 < len(chunks):
            nxt = chunks[ci + 1][0]["start"]
            c_end = nxt if nxt - c_end < 0.35 else min(c_end, nxt)
        toks = [_clean(w["word"], up) for w in ch]

        def ev(a: float, b: float, text: str) -> None:
            if b - a >= 0.02:
                events.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Cap,,0,0,0,,{text}")

        mode = st["mode"]
        if mode == "static":
            ev(c_start, c_end, "{\\fad(80,60)}" + " ".join(toks))
        elif mode == "karaoke":
            parts = []
            for w, tok in zip(ch, toks):
                k = max(1, int(round((w["end"] - w["start"]) * 100)))
                parts.append(f"{{\\kf{k}}}{tok}")
            ev(c_start, c_end, "".join(" " + p if i else p for i, p in enumerate(parts)))
        elif mode == "word":
            s = st["pop_scale"]
            ev(c_start, c_end, f"{{\\fscx{int(s*100)}\\fscy{int(s*100)}\\t(0,90,\\fscx100\\fscy100)}}" + toks[0])
        else:  # highlight / pop
            for wi, w in enumerate(ch):
                a = c_start if wi == 0 else w["start"]
                b = ch[wi + 1]["start"] if wi + 1 < len(ch) else c_end
                parts = []
                for j, tok in enumerate(toks):
                    if j == wi:
                        tag = f"{{\\c{hl}}}"
                        if mode == "pop":
                            s = int(st["pop_scale"] * 100)
                            tag = f"{{\\c{hl}\\fscx{s}\\fscy{s}\\t(0,100,\\fscx100\\fscy100)}}"
                        parts.append(f"{tag}{tok}{{\\r}}")
                    else:
                        parts.append(tok)
                ev(a, b, " ".join(parts))
    return header + "\n".join(events) + "\n"
