"""Testes de ponta a ponta com mídia sintética (gerada pelo próprio ffmpeg)."""
import json
import subprocess
from pathlib import Path

import pytest

from clipador import analyze as an
from clipador import transcript as tr
from clipador.captions import build_ass, chunk_words, load_style
from clipador.ff import parse_time, probe
from clipador.render import keyframe_expr, render


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    src = d / "bruto.mp4"
    # 20 s, 16:9, "fala" 3 s / silêncio 1 s
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=20",
                    "-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,4),3),0.4*sin(2*PI*220*t),0)':s=48000:d=20",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)], check=True)
    music = d / "musica.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=5", str(music)], check=True)
    from PIL import Image, ImageDraw
    logo = d / "logo.png"
    im = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, 299, 119), 20, fill=(255, 0, 80, 230))
    im.save(logo)
    words = []
    t = 0.0
    while t < 20:
        if t % 4 < 3:
            words.append({"start": round(t, 2), "end": round(t + 0.4, 2), "word": f"palavra{int(t * 2)}"})
        t += 0.5
    trans = d / "bruto.transcript.json"
    tr.save({"source": str(src), "segments": [{"start": 0, "end": 20, "text": "x", "words": words}]}, str(trans))
    return {"dir": d, "src": str(src), "music": str(music), "logo": str(logo), "transcript": str(trans)}


def test_parse_time():
    assert parse_time("01:02.5") == 62.5
    assert parse_time("1:00:00") == 3600
    assert parse_time(3) == 3.0
    assert parse_time("00:00:01,250") == 1.25


def test_keyframe_expr():
    e = keyframe_expr([[0, 0.2], [2, 0.8]])
    assert e.startswith("if(lt(t,0)")


def test_silences(media):
    sil = an.detect_silences(media["src"], -35, 0.5)
    assert len(sil) >= 4
    assert abs(sil[0][0] - 3.0) < 0.15
    # com início deslocado os tempos continuam absolutos
    sil2 = an.detect_silences(media["src"], -35, 0.5, start=5.0, end=12.0)
    assert abs(sil2[0][0] - 7.0) < 0.15
    rng = an.speech_ranges(media["src"], 0, 8, pad=0.1)
    assert len(rng) == 2


def test_captions_chunks():
    st = load_style("bold_pop")
    words = [{"start": i * 0.3, "end": i * 0.3 + 0.25, "word": w} for i, w in enumerate("isso é muito bom mesmo pessoal".split())]
    ch = chunk_words(words, st)
    assert all(len(c) <= 3 for c in ch)
    ass = build_ass(words, 1080, 1920, st)
    assert "Dialogue:" in ass and "PlayResY: 1920" in ass


def test_sheet(media):
    out = an.contact_sheet(media["src"], str(media["dir"] / "sheet.jpg"), every=5)
    assert Path(out).exists()


def _spec(media, name, **kw):
    spec = {"source": media["src"], "output": str(media["dir"] / f"{name}.mp4"), "preset": "shorts"}
    spec.update(kw)
    p = media["dir"] / f"{name}.json"
    p.write_text(json.dumps(spec))
    return str(p)


def test_render_full_short(media):
    spec = _spec(media, "short",
                 reframe={"mode": "crop", "x": [[0, 0.2], [6, 0.8]]},
                 segments=[{"start": 0, "end": 6, "zooms": [{"start": 1, "end": 3, "scale": 1.3}]},
                           {"start": "00:10", "end": "00:14", "speed": 1.25, "reframe": {"mode": "blur"}}],
                 transition={"type": "fade", "duration": 0.3},
                 overlays=[{"file": media["logo"], "position": "top-right", "width": 0.3, "start": 1, "end": 5}],
                 texts=[{"text": "TÍTULO DE TESTE", "start": 0, "end": 3, "position": "top", "box": True}],
                 captions={"transcript": media["transcript"], "style": "bold_pop"},
                 audio={"music": {"file": media["music"], "volume": 0.1}},
                 fade_out=0.5)
    meta = render(spec, draft=True)
    info = probe(meta["output"])
    assert (info["width"], info["height"]) == (540, 960)
    expected = 6 + 4 / 1.25 - 0.3
    assert abs(info["duration"] - expected) < 0.15
    assert info["has_audio"]


def test_render_remove_silence_horizontal(media):
    spec = _spec(media, "jump", preset="youtube", segments=[{"start": 0, "end": 12}],
                 remove_silence={"min_silence": 0.5, "pad": 0.1},
                 captions={"transcript": media["transcript"], "style": "clean_box"})
    meta = render(spec, draft=True)
    info = probe(meta["output"])
    assert (info["width"], info["height"]) == (960, 540)
    # 12 s com 3 silêncios de ~1 s (menos padding) -> ~9.6 s
    assert 9.0 < info["duration"] < 10.5


def test_render_split_and_fit(media):
    spec = _spec(media, "split", preset="shorts",
                 segments=[{"start": 0, "end": 3, "reframe": {"mode": "split", "top": [0.7, 0, 0.3, 0.4],
                                                              "bottom": [0, 0, 1, 1], "ratio": 0.4}},
                           {"start": 3, "end": 5, "reframe": {"mode": "fit"}}])
    meta = render(spec, draft=True, preview=True)
    assert abs(probe(meta["output"])["duration"] - 5) < 0.15
    assert Path(meta["preview"]).exists()


def test_captions_repeated_hook(media):
    """Trecho usado como gancho e repetido depois deve ter legenda nas duas vezes."""
    from clipador.render import caption_words
    from clipador.spec import expand_segments, load_spec
    p = _spec(media, "hook", segments=[{"start": 5, "end": 6}, {"start": 4, "end": 7}],
              captions={"transcript": media["transcript"]})
    spec = load_spec(p)
    words = caption_words(spec, spec["captions"], expand_segments(spec), 0.0)
    w10 = [w for w in words if w["word"] == "palavra10"]  # fala em 5.0 s no bruto
    assert len(w10) == 2
    assert abs(w10[0]["start"] - 0.0) < 0.01 and abs(w10[1]["start"] - 2.0) < 0.01
