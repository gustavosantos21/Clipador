"""Motor de renderização: transforma uma receita JSON em um único comando ffmpeg."""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import transcript as tr
from .captions import build_ass, load_style
from .ff import ClipadorError, escape_filter_path, font_file, fmt_time, parse_time, probe, run_ffmpeg, FONTS_DIR
from .presets import QUALITY
from .spec import expand_segments, load_spec, output_format, resolve_path, source_to_output_map, validate


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _num(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def keyframe_expr(points, var: str = "t") -> str:
    """[[t0,v0],[t1,v1],...] -> expressão ffmpeg com interpolação linear."""
    if isinstance(points, (int, float)):
        return _num(float(points))
    pts = sorted((float(a), float(b)) for a, b in points)
    if len(pts) == 1:
        return _num(pts[0][1])
    expr = _num(pts[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(pts, pts[1:]))):
        seg = f"{_num(v0)}+({_num(v1 - v0)})*({var}-{_num(t0)})/{_num(max(t1 - t0, 1e-3))}"
        expr = f"if(lt({var},{_num(t1)}),{seg},{expr})"
    return f"if(lt({var},{_num(pts[0][0])}),{_num(pts[0][1])},{expr})"


def color_ff(c: str) -> str:
    """'#RRGGBB' ou '#RRGGBBAA' -> '0xRRGGBB@a' para filtros ffmpeg."""
    if not c.startswith("#"):
        return c
    h = c[1:]
    if len(h) == 8:
        return f"0x{h[:6]}@{int(h[6:], 16) / 255:.2f}"
    return f"0x{h}"


class Graph:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []
        self.chains: list[str] = []
        self._n = 0

    def add_input(self, args: list[str]) -> int:
        self.inputs.append(args)
        return len(self.inputs) - 1

    def label(self, prefix: str = "x") -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def add(self, chain: str) -> None:
        self.chains.append(chain)


# ---------------------------------------------------------------- reenquadramento


def reframe_chain(g: Graph, inp: str, rf: dict, W: int, H: int, seg: dict) -> str:
    mode = rf.get("mode", "crop")
    out = g.label("rf")

    def to_rel(points):
        # keyframes em tempo de ORIGEM -> tempo relativo do segmento de saída
        if isinstance(points, (int, float)):
            return points
        return [[(parse_time(t) - seg["start"]) / seg["speed"], v] for t, v in points]

    pre = ""
    if rf.get("rect"):  # recorte manual na origem, normalizado [x, y, w, h]
        x, y, w, h = rf["rect"]
        pre = f"crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:iw*{x}:ih*{y},"

    if mode == "crop":
        xe = keyframe_expr(to_rel(rf.get("x", 0.5)))
        ye = keyframe_expr(to_rel(rf.get("y", 0.5)))
        s = float(rf.get("scale", 1.0))
        extra = f",scale=trunc(iw*{s}/2)*2:-2" if s != 1.0 else ""
        g.add(f"[{inp}]{pre}scale={W}:{H}:force_original_aspect_ratio=increase{extra},"
              f"crop={W}:{H}:x='(iw-ow)*({xe})':y='(ih-oh)*({ye})'[{out}]")
    elif mode == "fit":
        col = color_ff(rf.get("color", "#000000"))
        g.add(f"[{inp}]{pre}scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={col}[{out}]")
    elif mode == "blur":
        a, b, bg, fg = g.label("a"), g.label("b"), g.label("bg"), g.label("fg")
        fgw = _even(W * float(rf.get("fg_scale", 1.0)))
        fgh_max = _even(H * float(rf.get("fg_max_h", 0.7)))
        y = rf.get("fg_y", "center")
        ye = "(H-h)/2" if y == "center" else f"H*{float(y)}"
        g.add(f"[{inp}]{pre}split[{a}][{b}]")
        g.add(f"[{a}]scale={_even(W/4)}:{_even(H/4)}:force_original_aspect_ratio=increase,"
              f"crop={_even(W/4)}:{_even(H/4)},boxblur={int(rf.get('blur', 12))}:2,"
              f"eq=brightness={rf.get('darken', -0.12)},scale={W}:{H}[{bg}]")
        g.add(f"[{b}]scale={fgw}:{fgh_max}:force_original_aspect_ratio=decrease,setsar=1[{fg}]")
        g.add(f"[{bg}][{fg}]overlay=(W-w)/2:{ye}[{out}]")
    elif mode == "split":
        # dois recortes da origem empilhados (ex.: rosto em cima, tela/jogo embaixo)
        ratio = float(rf.get("ratio", 0.5))
        h1 = _even(H * ratio)
        h2 = H - h1
        a, b, ta, tb = g.label("a"), g.label("b"), g.label("t"), g.label("u")
        g.add(f"[{inp}]split[{a}][{b}]")
        for lab, rect, hh, o in ((a, rf["top"], h1, ta), (b, rf["bottom"], h2, tb)):
            x, y, w, h = rect
            g.add(f"[{lab}]crop=trunc(iw*{w}/2)*2:trunc(ih*{h}/2)*2:iw*{x}:ih*{y},"
                  f"scale={W}:{hh}:force_original_aspect_ratio=increase,crop={W}:{hh}[{o}]")
        g.add(f"[{ta}][{tb}]vstack[{out}]")
    else:
        raise ClipadorError(f"reframe.mode desconhecido: {mode} (crop|fit|blur|split)")
    return out


def zoom_chain(g: Graph, inp: str, zooms: list[dict], seg: dict, W: int, H: int) -> str:
    if not zooms:
        return inp
    zterms, xterms, yterms = [], [], []
    for z in zooms:
        a = (z["start"] - seg["start"]) / seg["speed"]
        b = (z["end"] - seg["start"]) / seg["speed"]
        r = float(z.get("ramp", 0.25))
        w = (f"between(t,{_num(a)},{_num(b)})" if r <= 0
             else f"clip(min((t-{_num(a)})/{_num(r)},({_num(b)}-t)/{_num(r)}),0,1)")
        s = float(z.get("scale", 1.25))
        zterms.append(f"{_num(s - 1)}*{w}")
        xterms.append(f"{_num(float(z.get('x', 0.5)) - 0.5)}*{w}")
        yterms.append(f"{_num(float(z.get('y', 0.45)) - 0.5)}*{w}")
    ze = "1+" + "+".join(zterms)
    xe = "0.5+" + "+".join(xterms)
    ye = "0.5+" + "+".join(yterms)
    out = g.label("z")
    g.add(f"[{inp}]scale=w='trunc({W}*({ze})/2)*2':h='trunc({H}*({ze})/2)*2':eval=frame,"
          f"crop={W}:{H}:x='(iw-{W})*({xe})':y='(ih-{H})*({ye})'[{out}]")
    return out


def atempo_chain(speed: float) -> str:
    parts = []
    s = speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={_num(s)}")
    return ",".join(parts)


# ---------------------------------------------------------------- posicionamento


def position_xy(pos: str, margin: float, W: int, H: int, ow: str = "w", oh: str = "h",
                mainw: str = "W", mainh: str = "H") -> tuple[str, str]:
    mx, my = int(margin * W), int(margin * W)
    v, _, h = pos.partition("-") if "-" in pos else (pos, "", pos)
    if pos in ("left", "right"):
        v, h = "center", pos
    if pos in ("top", "bottom"):
        v, h = pos, "center"
    if pos == "center":
        v = h = "center"
    x = {"left": f"{mx}", "center": f"({mainw}-{ow})/2", "right": f"{mainw}-{ow}-{mx}"}[h]
    y = {"top": f"{my}", "center": f"({mainh}-{oh})/2", "bottom": f"{mainh}-{oh}-{my}"}[v]
    return x, y


# ---------------------------------------------------------------- render


def build(spec_path: str, draft: bool = False, workdir: str | None = None) -> tuple[list[str], dict]:
    spec = load_spec(spec_path)
    warns = validate(spec)
    fmt = output_format(spec)
    q = dict(QUALITY["draft" if draft else spec.get("quality", "final")])
    k = q["scale"]
    W, H, FPS = _even(fmt["width"] * k), _even(fmt["height"] * k), fmt["fps"]
    segs = expand_segments(spec)
    tr_cfg = spec.get("transition") or {}
    ttype = tr_cfg.get("type", "none")
    td = float(tr_cfg.get("duration", 0.3)) if ttype != "none" else 0.0
    out_path = resolve_out(spec)
    work = Path(workdir) if workdir else Path(out_path).parent / ".work"
    work.mkdir(parents=True, exist_ok=True)
    stem = Path(out_path).stem

    g = Graph()
    vlabels, alabels, durs = [], [], []
    for i, seg in enumerate(segs):
        sd = seg["end"] - seg["start"]
        od = sd / seg["speed"]
        if ttype != "none" and od <= td * 1.5 and len(segs) > 1:
            raise ClipadorError(f"segmento {seg['label']} ({od:.2f}s) curto demais para transição de {td}s")
        if seg["is_image"]:
            n = g.add_input(["-loop", "1", "-framerate", str(FPS), "-t", f"{sd:.3f}", "-i", seg["source"]])
        else:
            n = g.add_input(["-ss", f"{seg['start']:.3f}", "-t", f"{sd:.3f}", "-i", seg["source"]])
        v0 = g.label("v")
        speed = "" if seg["speed"] == 1 else f",setpts=PTS/{_num(seg['speed'])}"
        g.add(f"[{n}:v]setpts=PTS-STARTPTS{speed},fps={FPS}[{v0}]")
        v1 = reframe_chain(g, v0, seg["reframe"], W, H, seg)
        v2 = zoom_chain(g, v1, seg["zooms"], seg, W, H)
        vf = g.label("vs")
        g.add(f"[{v2}]trim=duration={od:.3f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[{vf}]")
        af = g.label("as")
        if seg["has_audio"]:
            tempo = "" if seg["speed"] == 1 else "," + atempo_chain(seg["speed"])
            vol = "" if seg["volume"] == 1 else f",volume={seg['volume']}"
            g.add(f"[{n}:a]asetpts=PTS-STARTPTS{tempo}{vol},aresample=48000,"
                  f"aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={od:.3f}[{af}]")
        else:
            g.add(f"anullsrc=r=48000:cl=stereo,atrim=duration={od:.3f},aformat=sample_fmts=fltp[{af}]")
        vlabels.append(vf)
        alabels.append(af)
        durs.append(od)

    # ---- junção
    if len(segs) == 1:
        vj, aj = vlabels[0], alabels[0]
        total = durs[0]
    elif ttype == "none":
        vj, aj = g.label("vj"), g.label("aj")
        g.add("".join(f"[{v}][{a}]" for v, a in zip(vlabels, alabels)) + f"concat=n={len(segs)}:v=1:a=1[{vj}][{aj}]")
        total = sum(durs)
    else:
        vj, aj = vlabels[0], alabels[0]
        acc = durs[0]
        for v, a, d in zip(vlabels[1:], alabels[1:], durs[1:]):
            nv, na = g.label("xv"), g.label("xa")
            g.add(f"[{vj}][{v}]xfade=transition={ttype}:duration={td}:offset={acc - td:.3f}[{nv}]")
            g.add(f"[{aj}][{a}]acrossfade=d={td}[{na}]")
            vj, aj = nv, na
            acc += d - td
        total = acc

    cur = vj
    # ---- overlays (abaixo das legendas)
    overlays = spec.get("overlays", [])
    for ov in [o for o in overlays if not o.get("above_captions")]:
        cur = overlay_chain(g, cur, ov, spec, W, H, total, k)
    # ---- textos
    for tx in spec.get("texts", []):
        cur = text_chain(g, cur, tx, W, H, total, work, stem)
    # ---- legendas
    cap = spec.get("captions")
    if cap and cap.get("enabled", True):
        ass_path = work / f"{stem}.ass"
        words = caption_words(spec, cap, segs, td)
        style = load_style(cap.get("style", "bold_pop"), cap.get("overrides"))
        ass_path.write_text(build_ass(words, W, H, style), encoding="utf-8")
        nxt = g.label("cap")
        g.add(f"[{cur}]ass=filename='{escape_filter_path(ass_path)}':fontsdir='{escape_filter_path(FONTS_DIR)}'[{nxt}]")
        cur = nxt
    for ov in [o for o in overlays if o.get("above_captions")]:
        cur = overlay_chain(g, cur, ov, spec, W, H, total, k)
    # ---- fades
    fi, fo = float(spec.get("fade_in", 0)), float(spec.get("fade_out", 0))
    fades = []
    if fi:
        fades.append(f"fade=t=in:st=0:d={fi}")
    if fo:
        fades.append(f"fade=t=out:st={max(0, total - fo):.3f}:d={fo}")
    vout = g.label("vout")
    g.add(f"[{cur}]{','.join(fades + ['format=yuv420p'])}[{vout}]")

    aout = audio_post(g, aj, spec, total, fi, fo)

    script = work / f"{stem}.filter.txt"
    script.write_text(";\n".join(g.chains), encoding="utf-8")
    args: list[str] = []
    for ia in g.inputs:
        args += ia
    args += ["-filter_complex_script", str(script), "-map", f"[{vout}]", "-map", f"[{aout}]",
             "-c:v", "libx264", "-preset", q["preset"], "-crf", str(q["crf"]), "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-c:a", "aac", "-b:a", q["audio_bitrate"], "-ar", "48000",
             "-movflags", "+faststart", "-t", f"{total:.3f}", out_path]
    meta = {"output": out_path, "width": W, "height": H, "fps": FPS, "duration": round(total, 3),
            "segments": len(segs), "warnings": warns, "filter_script": str(script),
            "max_duration": fmt.get("max_duration")}
    if fmt.get("max_duration") and total > fmt["max_duration"]:
        meta["warnings"].append(f"duração {total:.1f}s passa do limite do preset ({fmt['max_duration']}s)")
    return args, meta


def resolve_out(spec: dict) -> str:
    out = Path(spec["output"])
    out.parent.mkdir(parents=True, exist_ok=True)
    return str(out)


def overlay_chain(g: Graph, cur: str, ov: dict, spec: dict, W: int, H: int, total: float, k: float) -> str:
    f = resolve_path(spec, ov["file"])
    info = probe(f)
    start = parse_time(ov.get("start", 0))
    end = parse_time(ov["end"]) if ov.get("end") is not None else total
    if info.get("is_image"):
        n = g.add_input(["-loop", "1", "-t", f"{total:.3f}", "-i", f])
    else:
        loop = ["-stream_loop", "-1"] if ov.get("loop") else []
        n = g.add_input(loop + ["-i", f])
    lab = g.label("ov")
    filters = ["format=rgba"]
    if ov.get("chromakey"):
        filters.append(f"colorkey={color_ff(ov['chromakey'])}:{ov.get('similarity', 0.3)}:{ov.get('blend', 0.1)}")
    if ov.get("fullscreen"):
        filters.append(f"scale={W}:{H}")
    else:
        wv = ov.get("width", 0.25)
        px = int(wv * W) if wv <= 1 else int(wv * k)
        filters.append(f"scale={_even(px)}:-2")
    op = float(ov.get("opacity", 1.0))
    if op < 1:
        filters.append(f"colorchannelmixer=aa={op}")
    filters.append(f"setpts=PTS-STARTPTS+{start:.3f}/TB")
    g.add(f"[{n}:v]{','.join(filters)}[{lab}]")
    if ov.get("fullscreen"):
        x, y = "0", "0"
    elif "x" in ov and "y" in ov:
        x, y = f"{float(ov['x']) * W:.0f}", f"{float(ov['y']) * H:.0f}"
    else:
        x, y = position_xy(ov.get("position", "top-right"), float(ov.get("margin", 0.04)), W, H)
    out = g.label("o")
    eof = "repeat" if info.get("is_image") else "pass"
    g.add(f"[{cur}][{lab}]overlay=x={x}:y={y}:eof_action={eof}:enable='between(t,{start:.3f},{end:.3f})'[{out}]")
    return out


def text_chain(g: Graph, cur: str, tx: dict, W: int, H: int, total: float, work: Path, stem: str) -> str:
    start = parse_time(tx.get("start", 0))
    end = parse_time(tx["end"]) if tx.get("end") is not None else total
    idx = len(list(work.glob(f"{stem}.text*.txt")))
    tf = work / f"{stem}.text{idx}.txt"
    text = tx["text"].upper() if tx.get("uppercase") else tx["text"]
    tf.write_text(text, encoding="utf-8")
    fs = int(float(tx.get("size", 0.05)) * H)
    font = font_file(tx.get("font", "Inter Black"))
    pos = tx.get("position", "top")
    ypos = {"top": f"{H * float(tx.get('margin', 0.12)):.0f}", "center": "(h-text_h)/2",
            "bottom": f"h-text_h-{H * float(tx.get('margin', 0.12)):.0f}"}.get(pos, "(h-text_h)/2")
    if "y" in tx:
        ypos = f"{float(tx['y']) * H:.0f}"
    xpos = f"{float(tx['x']) * W:.0f}" if "x" in tx else "(w-text_w)/2"
    fade = float(tx.get("fade", 0.2))
    alpha = (f"if(lt(t,{start + fade:.3f}),(t-{start:.3f})/{fade},if(gt(t,{end - fade:.3f}),({end:.3f}-t)/{fade},1))"
             if fade > 0 else "1")
    opts = [f"fontfile='{escape_filter_path(font)}'", f"textfile='{escape_filter_path(tf)}'",
            f"fontsize={fs}", f"fontcolor={color_ff(tx.get('color', '#FFFFFF'))}",
            f"x={xpos}", f"y={ypos}", f"line_spacing={int(fs * 0.15)}",
            f"enable='between(t,{start:.3f},{end:.3f})'", f"alpha='{alpha}'"]
    bw = float(tx.get("outline", 0.08))
    if bw:
        opts += [f"borderw={max(1, int(bw * fs))}", f"bordercolor={color_ff(tx.get('outline_color', '#000000'))}"]
    if tx.get("box"):
        opts += ["box=1", f"boxcolor={color_ff(tx.get('box_color', '#000000B0'))}", f"boxborderw={int(fs * 0.35)}"]
    out = g.label("t")
    g.add(f"[{cur}]drawtext={':'.join(opts)}[{out}]")
    return out


def caption_words(spec: dict, cap: dict, segs: list[dict], td: float) -> list[dict]:
    if cap.get("words"):  # palavras manuais já na timeline de saída
        return cap["words"]
    data = tr.load(resolve_path(spec, cap["transcript"]))
    src = resolve_path(spec, cap.get("source") or data.get("source") or spec["source"])
    _, offsets = source_to_output_map(segs, td)
    repl = cap.get("replace", {})
    words = tr.all_words(data)
    src_r = Path(src).resolve()
    out = []
    # percorre por segmento: um mesmo trecho do bruto pode aparecer mais de uma vez (ex.: gancho repetido)
    for seg, off in zip(segs, offsets):
        if Path(seg["source"]).resolve() != src_r:
            continue
        sp = seg["speed"]
        for w in words:
            if not (seg["start"] <= w["start"] < seg["end"]):
                continue
            word = repl.get(w["word"], w["word"])
            if not word.strip():
                continue
            t0 = off + (w["start"] - seg["start"]) / sp
            t1 = off + (min(w["end"], seg["end"]) - seg["start"]) / sp
            out.append({"start": t0, "end": max(t1, t0 + 0.05), "word": word})
    out.sort(key=lambda x: x["start"])
    for a, b in zip(out, out[1:]):  # evita sobreposição em jump cuts
        a["end"] = min(a["end"], b["start"]) if b["start"] > a["start"] else a["end"]
    return out


def audio_post(g: Graph, aj: str, spec: dict, total: float, fi: float, fo: float) -> str:
    audio = spec.get("audio") or {}
    mix = [aj]
    music = audio.get("music")
    if music:
        f = resolve_path(spec, music["file"])
        n = g.add_input(["-stream_loop", "-1", "-i", f])
        m = g.label("mus")
        mst = parse_time(music.get("start", 0))
        g.add(f"[{n}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
              f"atrim=duration={total:.3f},volume={music.get('volume', 0.12)},"
              f"afade=t=in:d={music.get('fade_in', 1.0)},"
              f"afade=t=out:st={max(0, total - float(music.get('fade_out', 1.5))):.3f}:d={music.get('fade_out', 1.5)}"
              + (f",adelay={int(mst * 1000)}:all=1" if mst else "") + f"[{m}]")
        if music.get("duck", True):
            v, sc, md = g.label("voice"), g.label("sc"), g.label("md")
            g.add(f"[{aj}]asplit[{v}][{sc}]")
            g.add(f"[{m}][{sc}]sidechaincompress=threshold={music.get('duck_threshold', 0.03)}:"
                  f"ratio={music.get('duck_ratio', 8)}:attack=15:release=400[{md}]")
            mix = [v, md]
        else:
            mix = [aj, m]
    for sfx in audio.get("sfx", []):
        f = resolve_path(spec, sfx["file"])
        n = g.add_input(["-i", f])
        s = g.label("sfx")
        at = int(parse_time(sfx["at"]) * 1000)
        g.add(f"[{n}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
              f"volume={sfx.get('volume', 0.8)},adelay={at}:all=1[{s}]")
        mix.append(s)
    cur = aj
    if len(mix) > 1:
        cur = g.label("mix")
        g.add("".join(f"[{x}]" for x in mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0[{cur}]")
    post = []
    if audio.get("normalize", True):
        post.append(f"loudnorm=I={audio.get('lufs', -14)}:TP=-1.5:LRA=11")
    if fi:
        post.append(f"afade=t=in:st=0:d={fi}")
    if fo:
        post.append(f"afade=t=out:st={max(0, total - fo):.3f}:d={fo}")
    post += ["aresample=48000", f"atrim=duration={total:.3f}"]
    out = g.label("aout")
    g.add(f"[{cur}]{','.join(post)}[{out}]")
    return out


def render(spec_path: str, draft: bool = False, dry_run: bool = False, preview: bool = False) -> dict:
    args, meta = build(spec_path, draft=draft)
    meta["command"] = "ffmpeg " + " ".join(_q(a) for a in args)
    if dry_run:
        return meta
    run_ffmpeg(args)
    info = probe(meta["output"])
    meta["rendered_duration"] = round(info["duration"], 3)
    if preview:
        from .analyze import contact_sheet
        sheet = str(Path(meta["output"]).with_suffix(".preview.jpg"))
        n = 12
        times = [info["duration"] * (i + 0.5) / n for i in range(n)]
        contact_sheet(meta["output"], sheet, times=times, cols=6 if meta["height"] > meta["width"] else 4,
                      thumb_w=220 if meta["height"] > meta["width"] else 360)
        meta["preview"] = sheet
    Path(meta["output"]).with_suffix(".render.json").write_text(
        json.dumps({k: v for k, v in meta.items() if k != "command"}, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def _q(a: str) -> str:
    return f"'{a}'" if any(c in a for c in " ;[]()'\"") else a
