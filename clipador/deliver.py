"""Entrega: thumbnail, texto de postagem por plataforma e pacote final pronto para publicar."""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

from .ff import ClipadorError, font_file, fmt_time, probe
from .spec import load_spec, resolve_path

HASHTAGS_BASE = {
    "shorts": ["#shorts"],
    "tiktok": ["#fyp", "#paravoce"],
    "reels": ["#reels"],
}


# ---------------------------------------------------------------- thumbnail


def make_thumbnail(video: str, out: str, text: str = "", t: float | None = None, size=(1280, 720),
                   face_rect: list[float] | None = None, color: str = "#FFE600") -> str:
    """Thumbnail 16:9 (ou 9:16 se size for vertical): frame + texto grande com contorno.
    Com `face_rect` (facecam da live), o rosto entra ampliado do lado direito — padrão de thumb de reação."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont

    from .faces import frame_at

    info = probe(video)
    if t is None:
        t = info["duration"] * 0.4
    fr = frame_at(video, t, width=1920)
    if fr is None:
        raise ClipadorError("não foi possível ler frame para a thumbnail")
    im = Image.fromarray(fr[:, :, ::-1])
    W, H = size
    # fundo: preenche o tamanho alvo
    scale = max(W / im.width, H / im.height)
    bg = im.resize((int(im.width * scale), int(im.height * scale)))
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = ImageEnhance.Contrast(ImageEnhance.Color(bg).enhance(1.35)).enhance(1.15)
    if face_rect:
        x, y, w, h = face_rect
        face = im.crop((int(x * im.width), int(y * im.height), int((x + w) * im.width), int((y + h) * im.height)))
        fh = int(H * 0.82)
        fw = int(face.width * fh / face.height)
        if fw > W * 0.48:  # limita a largura e corta o excesso em volta do rosto
            fw = int(W * 0.48)
        face = face.resize((int(face.width * fh / face.height), fh))
        if face.width > fw:
            off = (face.width - fw) // 2
            face = face.crop((off, 0, off + fw, fh))
        bg.paste(face, (W - face.width - int(W * 0.02), H - fh))
    draw = ImageDraw.Draw(bg)
    if text:
        font_path = font_file("Inter Black")
        max_w = int(W * (0.55 if face_rect else 0.9))
        fs = int(H * 0.16)
        words = text.upper().split()
        while fs > 20:
            font = ImageFont.truetype(font_path, fs)
            lines, cur = [], ""
            for wd in words:
                test = (cur + " " + wd).strip()
                if draw.textlength(test, font=font) <= max_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = wd
            lines.append(cur)
            total_h = len(lines) * fs * 1.08
            if len(lines) <= 3 and total_h < H * 0.8 and all(draw.textlength(l, font=font) <= max_w for l in lines):
                break
            fs -= 6
        y0 = int(H * 0.08)
        for i, line in enumerate(lines):
            fill = color if i == len(lines) - 1 else "#FFFFFF"
            draw.text((int(W * 0.04), y0 + int(i * fs * 1.08)), line, font=font, fill=fill,
                      stroke_width=max(4, fs // 9), stroke_fill="#000000")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(out, quality=92)
    return out


# ---------------------------------------------------------------- texto de postagem


def post_text(spec: dict, platform: str) -> dict:
    """Título/descrição/hashtags para uma plataforma, a partir do campo `post` da receita."""
    post = dict(spec.get("post") or {})
    plat = (post.get("platforms") or {}).get(platform, {})
    title = plat.get("title") or post.get("title") or spec.get("title") or Path(spec["output"]).stem
    desc = plat.get("description") or post.get("description") or ""
    tags = list(dict.fromkeys((post.get("hashtags") or []) + (plat.get("hashtags") or []) + HASHTAGS_BASE.get(platform, [])))
    if not plat and platform == "shorts":
        plat = (post.get("platforms") or {}).get("youtube", {})
    if platform == "youtube" and post.get("chapters"):
        desc = (desc + "\n\n" + "\n".join(post["chapters"])).strip()
    credit = post.get("credit")
    if credit:
        desc = (desc + "\n\n" + credit).strip()
    caption = (title + ("\n\n" + desc if desc else "") + ("\n\n" + " ".join(tags) if tags else "")).strip()
    return {"title": title[:100], "description": (desc + ("\n\n" + " ".join(tags) if tags else "")).strip(),
            "caption": caption[:2200], "hashtags": tags, "tags": [t.lstrip("#") for t in tags]}


def platforms_for(spec: dict) -> list[str]:
    preset = spec.get("preset", "shorts")
    if preset in ("youtube", "youtube4k"):
        return ["youtube"]
    if preset == "shorts":
        return ["shorts", "tiktok", "reels"]  # o mesmo vertical serve para os três
    return {"reels": ["reels"], "tiktok": ["tiktok"], "feed45": ["reels"], "vertical": ["shorts", "tiktok", "reels"],
            "square": ["reels"]}.get(preset, ["youtube"])


# ---------------------------------------------------------------- pacote


def _thumb_for(spec: dict, video: Path, info: dict, out: Path) -> str:
    from .ff import parse_time
    from .workspace import PROJECTS, project_name
    post = spec.get("post") or {}
    th = post.get("thumbnail") or {}
    text = th.get("text") or post.get("thumb_text") or ""
    if info["height"] > info["width"]:
        # vertical: frame do próprio clipe editado (já com layout/legenda), usado como capa no TikTok/Reels
        t = float(th["time"]) if th.get("time") is not None else info["duration"] * 0.35
        return make_thumbnail(str(video), str(out), text, t=t, size=(1080, 1920))
    src = resolve_path(spec, spec.get("source") or spec["segments"][0]["source"])
    face = th.get("face_rect")
    if face is None:
        rf = spec.get("reframe") or {}
        if rf.get("mode") == "stream" and isinstance(rf.get("facecam"), list):
            face = rf["facecam"]
        else:
            fc = PROJECTS / project_name(src) / "work" / "facecam.json"
            if fc.exists():
                face = json.loads(fc.read_text())["rect"]
    t = th.get("time")
    if t is None:
        seg = spec["segments"][0]
        t = (parse_time(seg.get("start", 0)) + parse_time(seg.get("end", seg.get("start", 0)))) / 2
    if not text:
        text = post.get("title") or ""
        text = " ".join(text.split()[:5])
    return make_thumbnail(src, str(out), text, t=float(t), size=(1280, 720), face_rect=face)



def package(spec_paths: list[str], dest: str | None = None, thumbs: bool = True) -> dict:
    """Monta `entregas/<data>/<clipe>/` com vídeo, thumbnail, post.md e post.json."""
    dest_dir = Path(dest or f"entregas/{date.today().isoformat()}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for sp in spec_paths:
        spec = load_spec(sp)
        video = Path(resolve_path(spec, spec["output"]))
        if not video.exists():
            raise ClipadorError(f"vídeo ainda não renderizado: {video} (rode render antes)")
        d = dest_dir / video.stem
        d.mkdir(exist_ok=True)
        shutil.copy2(video, d / video.name)
        info = probe(str(video))
        item = {"clip": video.stem, "video": str(d / video.name), "duration": round(info["duration"], 1),
                "format": f"{info['width']}x{info['height']}", "platforms": {}}
        post = spec.get("post") or {}
        if thumbs:
            item["thumbnail"] = _thumb_for(spec, video, info, d / "thumbnail.jpg")
        md = [f"# {video.stem}", "", f"Duração: {fmt_time(info['duration'], ms=False)} · {item['format']}", ""]
        for plat in platforms_for(spec):
            pt = post_text(spec, plat)
            item["platforms"][plat] = pt
            md += [f"## {plat}", "", f"**Título:** {pt['title']}", "", "**Legenda/descrição:**", "", "```",
                   pt["caption"] if plat not in ("youtube", "shorts") else pt["description"], "```", ""]
        (d / "post.md").write_text("\n".join(md), encoding="utf-8")
        (d / "post.json").write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append(item)
    (dest_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"dest": str(dest_dir), "clips": index}
