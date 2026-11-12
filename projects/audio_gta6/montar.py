"""Monta o 'bruto' do vídeo só-áudio: ilustrações com movimento lento, na linha do tempo do áudio original.

O resultado (raw/audio_gta6.mp4) vira a fonte de uma receita normal do Clipador (cortes, legenda, zooms).
Uso: python projects/audio_gta6/montar.py
"""
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
CARDS = HERE / "work" / "cards"
AUDIO = "raw/audio_gta6.mp3"
OUT = "raw/audio_gta6.mp4"
DUR = 117.43
# (card, início no áudio bruto) — cada card vai até o início do próximo
TIMELINE = [("mapa", 0), ("1_vice_city", 34.2), ("2_leonida_keys", 43.6), ("3_grassrivers", 52.42),
            ("4_port_gellhorn", 62.0), ("5_ambrosia", 83.6), ("6_mount_kalaga", 91.41), ("pergunta", 99.37),
            ("cta", 106.6)]
FPS = 30

inputs, chains = [], []
for i, (card, t0) in enumerate(TIMELINE):
    t1 = TIMELINE[i + 1][1] if i + 1 < len(TIMELINE) else DUR
    d = t1 - t0
    n = int(round(d * FPS))
    inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(CARDS / f"{card}.png")]
    # zoom lento 1.00 -> 1.10 (Ken Burns), alternando o ponto de foco
    fy = "ih*0.42" if i % 2 else "ih*0.55"
    chains.append(f"[{i}:v]scale=2160:3840,zoompan=z='1+0.10*on/{n}':x='iw/2-iw/zoom/2':y='{fy}-ih/zoom/2':"
                  f"d=1:s=1080x1920:fps={FPS},trim=duration={d:.3f},setpts=PTS-STARTPTS[v{i}]")
k = len(TIMELINE)
graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0[v]"
cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-i", AUDIO, "-filter_complex", graph, "-map", "[v]", "-map", f"{k}:a",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
       "-shortest", OUT]
subprocess.run(cmd, check=True)
print(OUT)
