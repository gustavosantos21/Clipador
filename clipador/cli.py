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
