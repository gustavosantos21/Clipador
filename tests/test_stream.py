"""Testes de detecção de rosto/facecam, varredura de stream e fila de jobs."""
import json
import subprocess

import pytest

cv2 = pytest.importorskip("cv2")
skdata = pytest.importorskip("skimage.data")


@pytest.fixture(scope="module")
def faces_media(tmp_path_factory):
    from PIL import Image
    d = tmp_path_factory.mktemp("faces")
    astro = Image.fromarray(skdata.astronaut())
    head = d / "head.png"
    astro.crop((90, 0, 420, 330)).resize((330, 330)).save(head)
    cam = d / "cam.png"
    astro.crop((90, 0, 420, 250)).resize((264, 200)).save(cam)
    # rosto atravessando um quadro 16:9 da esquerda para a direita
    moving = d / "moving.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x404850:s=1280x720:r=30:d=8",
                    "-loop", "1", "-i", str(head), "-filter_complex",
                    "[0:v][1:v]overlay=x='if(lt(t,3),60,if(lt(t,4),60+(t-3)*800,860))':y=180:shortest=1,format=yuv420p",
                    "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", str(moving)], check=True)
    # "stream": jogo (testsrc2) + webcam fixa no canto inferior esquerdo + picos de áudio
    stream = d / "stream.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=60",
                    "-loop", "1", "-i", str(cam),
                    "-f", "lavfi", "-i", "aevalsrc='0.02*sin(2*PI*150*t)+0.7*sin(2*PI*330*t)*between(t,30,34)':s=48000:d=60",
                    "-filter_complex", "[1:v]pad=272:208:4:4:color=white[c];[0:v][c]overlay=24:480:shortest=1,format=yuv420p[v]",
                    "-map", "[v]", "-map", "2:a", "-t", "60", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(stream)], check=True)
    chat = d / "stream.chat.json"
    msgs = [{"content_offset_seconds": t, "message": {"body": "oi"}} for t in range(0, 60, 3)]
    msgs += [{"content_offset_seconds": 40 + i * 0.2, "message": {"body": "KEKW"}} for i in range(40)]
    chat.write_text(json.dumps({"comments": msgs}))
    return {"dir": d, "moving": str(moving), "stream": str(stream), "chat": str(chat)}


def test_auto_crop_follows_face(faces_media):
    from clipador.faces import auto_crop_keyframes
    r = auto_crop_keyframes(faces_media["moving"], 0, 8, 9 / 16, step=0.5)
    assert r["hits"] > 10
    kf = r["x"]
    assert isinstance(kf, list) and len(kf) >= 2
    assert kf[0][1] < 0.25 and kf[-1][1] > 0.75   # foi da esquerda para a direita
    # parado no começo (zona morta), sem tremer
    assert all(abs(x - kf[0][1]) < 1e-6 for t, x in kf if t < 2.5)


def test_facecam_detect(faces_media, tmp_path):
    from clipador.faces import detect_facecam
    dbg = tmp_path / "fc.jpg"
    r = detect_facecam(faces_media["stream"], samples=12, debug_image=str(dbg))
    assert r is not None and r["confidence"] > 0.5
    x, y, w, h = r["rect"]
    # webcam real: x=24..296, y=480..688 em 1280x720
    assert abs(x - 24 / 1280) < 0.04 and abs(y - 480 / 720) < 0.05
    assert abs(w - 272 / 1280) < 0.06 and abs(h - 208 / 720) < 0.08
    assert dbg.exists()


def test_scan_finds_hype(faces_media):
    from clipador.highlights import scan
    res = scan(faces_media["stream"], faces_media["chat"], top=3, pre=10, post=5, min_len=8)
    best = res["candidates"][0]
    assert best["start"] <= 32 <= best["end"]
    assert any("chat" in r for r in best["reasons"])


def test_render_stream_layout(faces_media, tmp_path):
    from clipador.ff import probe
    from clipador.render import render
    from clipador.spec import expand_segments, load_spec
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"source": faces_media["stream"], "output": str(tmp_path / "s.mp4"), "preset": "shorts",
                             "reframe": {"mode": "stream", "facecam": "auto"},
                             "segments": [{"start": 28, "end": 34}]}))
    seg = expand_segments(load_spec(str(p)))[0]
    assert seg["reframe"]["mode"] == "split"
    meta = render(str(p), draft=True)
    assert abs(probe(meta["output"])["duration"] - 6) < 0.15


def test_jobs_queue(tmp_path, monkeypatch):
    from clipador import jobs
    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / "j.sqlite")
    a = jobs.enqueue("render", {"spec": "x"})
    b = jobs.enqueue("scan", {"file": "y"}, priority=5)
    assert jobs.claim("w1")["id"] == b       # prioridade primeiro
    assert jobs.claim("w2")["id"] == a
    assert jobs.claim("w3") is None
    jobs.update(a, status="done", result={"ok": 1})
    assert jobs.get(a)["result"] == {"ok": 1}


def test_compile_package_publish_dryrun(faces_media, tmp_path, monkeypatch):
    """Vídeo longo (compilação) -> pacote de entrega -> payload do YouTube."""
    from clipador import workspace
    from clipador.deliver import package
    from clipador.ff import probe
    from clipador.publish import youtube_payload
    from clipador.render import render
    from clipador.spec import load_spec
    monkeypatch.setattr(workspace, "RAW", faces_media["dir"])
    monkeypatch.setattr(workspace, "OUT", tmp_path / "out")
    monkeypatch.setattr(workspace, "PROJECTS", tmp_path / "projects")
    cands = [{"id": "c01", "start": 5.0, "end": 15.0, "score": 9},
             {"id": "c02", "start": 28.0, "end": 38.0, "score": 12},
             {"id": "c03", "start": 45.0, "end": 55.0, "score": 3}]
    sp = workspace.make_compilation_spec("stream", "stream.mp4", cands, n=3)
    spec = json.loads(sp.read_text())
    assert [s["label"] for s in spec["segments"]] == ["c01", "c02", "c03"]   # ordem cronológica
    assert spec["post"]["chapters"][0].startswith("00:00")
    spec["output"] = str(tmp_path / "out" / "comp.mp4")
    spec["source"] = faces_media["stream"]
    spec["post"]["title"] = "Os melhores momentos da live"
    sp.write_text(json.dumps(spec))
    meta = render(str(sp), draft=True)
    assert abs(probe(meta["output"])["duration"] - (30 - 2 * 0.5)) < 0.2
    res = package([str(sp)], str(tmp_path / "entrega"))
    item = res["clips"][0]
    assert (tmp_path / "entrega" / "comp" / "thumbnail.jpg").exists()
    desc = item["platforms"]["youtube"]["description"]
    assert "00:00 Momento 1" in desc and "#shorts" not in desc
    body = youtube_payload(load_spec(str(sp)), publish_at="2026-11-20T18:00:00-03:00")
    assert body["status"]["privacyStatus"] == "private" and body["status"]["publishAt"]
    assert body["_short"] is False
