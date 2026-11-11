"""Interface de linha de comando do Clipador.

Uso: python -m clipador <comando> [opções]   (ou `clipador` se instalado com pip install -e .)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import analyze as an
from . import transcript as tr
from .captions import list_styles
from .ff import ClipadorError, fmt_time, parse_time, probe, require_binaries
from .presets import PRESETS


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def cmd_probe(a):
    _print(probe(a.file))


def cmd_analyze(a):
    rep = an.analyze(a.file, silence_db=a.silence_db, scene_threshold=a.scene_threshold)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"análise salva em {a.out}")
    summary = {k: rep[k] for k in ("file", "duration_tc", "video", "silence_ratio")}
    summary["n_silences"] = len(rep["silences"])
    summary["n_scenes"] = len(rep["scenes"])
    summary["energy_peaks"] = [f"{p['tc']} (+{p['above_median_db']} dB)" for p in rep["energy_peaks"]]
    _print(summary if a.out else rep)


def cmd_sheet(a):
    times = [parse_time(t) for t in a.at.split(",")] if a.at else None
    start = parse_time(a.start) if a.start else 0.0
    end = parse_time(a.end) if a.end else None
    every = parse_time(a.every) if a.every else None
    out = an.contact_sheet(a.file, a.out, times=times, every=every, start=start, end=end,
                           cols=a.cols, max_frames=a.max)
    print(out)


def cmd_transcribe(a):
    data = tr.transcribe(a.file, a.out, model=a.model, language=a.language or None, device=a.device)
    n = sum(len(s["words"]) for s in data["segments"])
    print(f"transcrição salva em {a.out} ({len(data['segments'])} frases, {n} palavras)")


def cmd_import_srt(a):
    data = tr.import_srt(a.srt, a.out, source=a.source)
    print(f"{len(data['segments'])} legendas importadas -> {a.out}")


def cmd_transcript(a):
    data = tr.load(a.file)
    print(tr.render_text(data, parse_time(a.start) if a.start else None, parse_time(a.end) if a.end else None))


def cmd_silences(a):
    start = parse_time(a.start) if a.start else None
    end = parse_time(a.end) if a.end else None
    for s, e in an.detect_silences(a.file, a.threshold_db, a.min, start, end):
        print(f"{fmt_time(s)}  →  {fmt_time(e)}   ({e - s:.2f}s)")


def cmd_render(a):
    from .render import render
    for spec in a.specs:
        meta = render(spec, draft=a.draft, dry_run=a.dry_run, preview=a.preview)
        if a.dry_run:
            print(meta.pop("command"))
            print(Path(meta["filter_script"]).read_text())
        _print(meta)


def cmd_validate(a):
    from .spec import expand_segments, load_spec, output_format, validate
    for p in a.specs:
        spec = load_spec(p)
        warns = validate(spec)
        segs = expand_segments(spec)
        dur = sum((s["end"] - s["start"]) / s["speed"] for s in segs)
        fmt = output_format(spec)
        print(f"OK {p}: {len(segs)} trechos, ~{dur:.1f}s, {fmt['width']}x{fmt['height']}")
        for w in warns:
            print(f"  aviso: {w}")


def cmd_cut(a):
    """Corte rápido sem re-encode (cópia de stream) — para separar trechos do bruto."""
    from .ff import run_ffmpeg
    s, e = parse_time(a.start), parse_time(a.end)
    run_ffmpeg(["-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", a.file, "-c", "copy", "-avoid_negative_ts", "1", a.out])
    print(a.out)


def cmd_facecam(a):
    from .faces import detect_facecam
    res = detect_facecam(a.file, samples=a.samples, debug_image=a.debug)
    _print(res or {"facecam": None})


def cmd_faces(a):
    from .faces import auto_crop_keyframes
    _print(auto_crop_keyframes(a.file, parse_time(a.start), parse_time(a.end), a.aspect))


def cmd_scan(a):
    from .highlights import scan
    res = scan(a.file, a.chat, top=a.top)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in res["candidates"]:
        print(f"{c['id']}  {c['tc']}  ({c['duration']}s)  score {c['score']:5.2f}  {', '.join(c['reasons'])}")


def cmd_transcribe_ranges(a):
    ranges = []
    if a.candidates:
        cands = json.loads(Path(a.candidates).read_text())["candidates"]
        ranges = [(c["start"] - 5, c["end"] + 5) for c in cands[: a.top]]
    for r in a.range or []:
        x, y = r.split("~", 1)
        ranges.append((parse_time(x), parse_time(y)))
    data = tr.transcribe_ranges(a.file, ranges, a.out, model=a.model, language=a.language or None)
    print(f"{len(data['segments'])} frases em {a.out}")


def cmd_worker(a):
    from . import jobs
    stop = jobs.start_workers(a.n)
    print(f"{a.n} worker(s) consumindo {jobs.DB_PATH}. Ctrl+C para sair.")
    try:
        stop.wait()
    except KeyboardInterrupt:
        stop.set()


def cmd_jobs(a):
    from . import jobs
    if a.add:
        print(jobs.enqueue(a.add, json.loads(a.args or "{}")))
        return
    for j in jobs.list_jobs(a.limit):
        print(f"#{j['id']:<4} {j['kind']:10s} {j['status']:8s} {j['progress']:.0%}  {j['message'][:80]}")


def cmd_serve(a):
    from .server import serve
    serve(a.host, a.port, a.workers)


def cmd_compile(a):
    from .workspace import RAW, make_compilation_spec, project_name, work
    name = project_name(a.file)
    cands = json.loads((work(name) / "candidates.json").read_text())["candidates"]
    p = make_compilation_spec(name, Path(a.file).name, cands, n=a.n, preset=a.preset)
    print(p)


def cmd_thumb(a):
    from .deliver import make_thumbnail
    size = (1080, 1920) if a.vertical else (1280, 720)
    face = [float(x) for x in a.face.split(",")] if a.face else None
    print(make_thumbnail(a.file, a.out, a.text or "", t=parse_time(a.at) if a.at else None, size=size, face_rect=face))


def cmd_package(a):
    from .deliver import package
    res = package(a.specs, a.dest, thumbs=not a.no_thumbs)
    print(f"pacote em {res['dest']} ({len(res['clips'])} vídeos)")


def cmd_publish(a):
    from .publish import youtube_upload
    for s in a.specs:
        _print(youtube_upload(s, privacy=a.privacy, publish_at=a.publish_at, thumbnail=a.thumbnail,
                              dry_run=a.dry_run))


def cmd_publish_auth(a):
    from .publish import youtube_auth
    youtube_auth(headless=a.headless)
    print("YouTube autorizado (token em secrets/youtube_token.json)")


def cmd_presets(a):
    for k, v in PRESETS.items():
        lim = f"máx {v['max_duration']}s" if v["max_duration"] else "sem limite"
        print(f"{k:10s} {v['width']}x{v['height']}@{v['fps']}  {lim:12s} {v['desc']}")
    print("\nestilos de legenda:", ", ".join(list_styles()))


def main(argv=None):
    p = argparse.ArgumentParser(prog="clipador", description="Clipagem e edição de vídeo por receitas JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("probe", help="informações técnicas do arquivo")
    s.add_argument("file"); s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("analyze", help="silêncios, cenas e picos de energia")
    s.add_argument("file"); s.add_argument("-o", "--out")
    s.add_argument("--silence-db", type=float, default=-35)
    s.add_argument("--scene-threshold", type=float, default=0.3)
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("sheet", help="folha de contato (grade de frames com timecode)")
    s.add_argument("file"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--at", help="tempos separados por vírgula")
    s.add_argument("--every", help="intervalo entre frames (s)")
    s.add_argument("--start"); s.add_argument("--end")
    s.add_argument("--cols", type=int, default=4); s.add_argument("--max", type=int, default=24)
    s.set_defaults(fn=cmd_sheet)

    s = sub.add_parser("transcribe", help="transcrever com faster-whisper (palavra a palavra)")
    s.add_argument("file"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--model", default="small"); s.add_argument("--language", default="pt")
    s.add_argument("--device", default="auto")
    s.set_defaults(fn=cmd_transcribe)

    s = sub.add_parser("import-srt", help="converter .srt em transcrição JSON")
    s.add_argument("srt"); s.add_argument("-o", "--out", required=True); s.add_argument("--source")
    s.set_defaults(fn=cmd_import_srt)

    s = sub.add_parser("transcript", help="ler transcrição com timecodes")
    s.add_argument("file"); s.add_argument("--start"); s.add_argument("--end")
    s.set_defaults(fn=cmd_transcript)

    s = sub.add_parser("silences", help="listar silêncios")
    s.add_argument("file"); s.add_argument("--threshold-db", type=float, default=-35)
    s.add_argument("--min", type=float, default=0.4); s.add_argument("--start"); s.add_argument("--end")
    s.set_defaults(fn=cmd_silences)

    s = sub.add_parser("cut", help="corte rápido sem re-encode")
    s.add_argument("file"); s.add_argument("start"); s.add_argument("end"); s.add_argument("-o", "--out", required=True)
    s.set_defaults(fn=cmd_cut)

    s = sub.add_parser("validate", help="validar receitas")
    s.add_argument("specs", nargs="+"); s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("render", help="renderizar receitas")
    s.add_argument("specs", nargs="+")
    s.add_argument("--draft", action="store_true", help="meia resolução, encode rápido")
    s.add_argument("--dry-run", action="store_true", help="só mostra o comando/filtergraph")
    s.add_argument("--preview", action="store_true", help="gera folha de contato do resultado")
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("facecam", help="detectar a webcam sobreposta numa stream")
    s.add_argument("file"); s.add_argument("--samples", type=int, default=40); s.add_argument("--debug")
    s.set_defaults(fn=cmd_facecam)

    s = sub.add_parser("faces", help="keyframes de recorte automático no rosto para um trecho")
    s.add_argument("file"); s.add_argument("start"); s.add_argument("end")
    s.add_argument("--aspect", type=float, default=9 / 16)
    s.set_defaults(fn=cmd_faces)

    s = sub.add_parser("scan", help="candidatos a clipe numa stream longa (áudio + chat)")
    s.add_argument("file"); s.add_argument("--chat"); s.add_argument("--top", type=int, default=30)
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("transcribe-ranges", help="transcrever só trechos (candidatos) de um vídeo longo")
    s.add_argument("file"); s.add_argument("-o", "--out", required=True)
    s.add_argument("--candidates", help="candidates.json do scan"); s.add_argument("--top", type=int, default=30)
    s.add_argument("--range", action="append", help="INICIO~FIM (pode repetir)")
    s.add_argument("--model", default="small"); s.add_argument("--language", default="pt")
    s.set_defaults(fn=cmd_transcribe_ranges)

    s = sub.add_parser("compile", help="receita de vídeo longo (melhores momentos) a partir dos candidatos")
    s.add_argument("file", help="vídeo bruto (raw/...)"); s.add_argument("-n", type=int, default=10)
    s.add_argument("--preset", default="youtube")
    s.set_defaults(fn=cmd_compile)

    s = sub.add_parser("thumb", help="gerar thumbnail")
    s.add_argument("file"); s.add_argument("-o", "--out", required=True); s.add_argument("--text")
    s.add_argument("--at"); s.add_argument("--face", help="x,y,w,h normalizado (facecam)")
    s.add_argument("--vertical", action="store_true")
    s.set_defaults(fn=cmd_thumb)

    s = sub.add_parser("package", help="pacote de entrega: vídeo + thumbnail + textos de postagem")
    s.add_argument("specs", nargs="+"); s.add_argument("--dest"); s.add_argument("--no-thumbs", action="store_true")
    s.set_defaults(fn=cmd_package)

    s = sub.add_parser("publish", help="publicar no YouTube (Shorts ou longo)")
    s.add_argument("specs", nargs="+")
    s.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    s.add_argument("--publish-at", help="agendar, ISO 8601 com fuso: 2026-11-20T18:00:00-03:00")
    s.add_argument("--thumbnail"); s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("publish-auth", help="autorizar a conta do YouTube (uma vez)")
    s.add_argument("platform", choices=["youtube"]); s.add_argument("--headless", action="store_true")
    s.set_defaults(fn=cmd_publish_auth)

    s = sub.add_parser("worker", help="processar a fila de jobs")
    s.add_argument("-n", type=int, default=2); s.set_defaults(fn=cmd_worker)

    s = sub.add_parser("jobs", help="listar/adicionar jobs")
    s.add_argument("--add", help="tipo: scan|transcribe|autospec|render|pipeline")
    s.add_argument("--args", help="JSON"); s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_jobs)

    s = sub.add_parser("serve", help="interface web local")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8765)
    s.add_argument("--workers", type=int, default=2)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("presets", help="listar presets e estilos")
    s.set_defaults(fn=cmd_presets)

    a = p.parse_args(argv)
    try:
        require_binaries()
        a.fn(a)
    except ClipadorError as e:
        print(f"erro: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
