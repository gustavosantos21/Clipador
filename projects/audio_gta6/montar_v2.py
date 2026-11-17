"""v2: monta o 'bruto' com as imagens do jogo enviadas pelo usuário (raw/imagens_gta6/1..9.png).

Layout vertical: fundo desfocado da própria imagem + imagem grande no meio com movimento lento
(pan/zoom). Faixa de cima livre para o título da região; legenda logo abaixo da imagem.
Áudio: raw/audio_gta6_limpo.wav (RNNoise + EQ + compressão), na linha do tempo do áudio original.
Uso: python projects/audio_gta6/montar_v2.py
"""
import subprocess
import tempfile
from pathlib import Path

IMG = Path("raw/imagens_gta6")
AUDIO = "raw/audio_gta6_limpo.wav"
OUT = "raw/audio_gta6_v2.mov"  # .mov com áudio PCM: evita comprimir o áudio duas vezes
DUR = 117.43
FPS = 30
FG_H = 820          # altura da imagem principal
FG_Y = 470          # topo da imagem principal
CROP_BOTTOM = {"1": 0.07}  # tira a marca d'água do rodapé da imagem 1

# (imagem, início no áudio bruto, pan_de, pan_ate) — pan = centro horizontal do recorte (0..1)
MONTAGE = ["9", "5", "3", "7", "8", "6"]
SHOTS = [("1", 0.0, 0.35, 0.55), ("2", 6.99, 0.6, 0.4)]
t = 11.19
for i, im in enumerate(MONTAGE):  # "seis regiões" — uma imagem de cada, rápida
    SHOTS.append((im, round(t + i * 0.7, 2), 0.5, 0.5))
SHOTS += [("1", 34.2, 0.3, 0.6), ("9", 43.6, 0.25, 0.55), ("5", 52.42, 0.55, 0.4), ("4", 57.49, 0.35, 0.3),
          ("6", 62.0, 0.3, 0.5), ("3", 80.69, 0.25, 0.4), ("7", 83.6, 0.35, 0.6), ("2", 88.16, 0.4, 0.6),
          ("8", 91.41, 0.55, 0.45)]
t = 99.37
for i, im in enumerate(["1", "9", "5", "6", "7", "8"]):  # pergunta final: recapitula as regiões
    SHOTS.append((im, round(t + i * 0.75, 2), 0.5, 0.5))
SHOTS.sort(key=lambda s: s[1])


def shot_filter(i, im, d, p0, p1):
    cb = CROP_BOTTOM.get(im, 0)
    pre = f"crop=iw:ih*{1 - cb}:0:0," if cb else ""
    fg_w = 1080
    # escala para altura FG_H*1.06 (folga do zoom) e recorta 1080 de largura andando de p0 a p1
    return (f"[{i}:v]{pre}split[a{i}][b{i}];"
            f"[a{i}]scale=-2:1920,crop=1080:1920,boxblur=40:2,eq=brightness=-0.18:saturation=1.2[bg{i}];"
            f"[b{i}]scale=-2:{int(FG_H * 1.06)},"
            f"crop={fg_w}:{FG_H}:x='(iw-{fg_w})*({p0}+({p1}-{p0})*t/{d:.3f})':y='(ih-{FG_H})/2'[fg{i}];"
            f"[bg{i}][fg{i}]overlay=0:{FG_Y},trim=duration={d:.3f},setpts=PTS-STARTPTS,fps={FPS}[v{i}]")


def main():
    inputs, chains = [], []
    for i, (im, t0, p0, p1) in enumerate(SHOTS):
        t1 = SHOTS[i + 1][1] if i + 1 < len(SHOTS) else DUR
        d = t1 - t0
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(IMG / f"{im}.png")]
        chains.append(shot_filter(i, im, d, p0, p1))
    k = len(SHOTS)
    graph = ";\n".join(chains) + ";\n" + "".join(f"[v{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0[v]"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(graph)
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-i", AUDIO, "-filter_complex_script", f.name,
                    "-map", "[v]", "-map", f"{k}:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                    "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", OUT], check=True)
    print(OUT)


if __name__ == "__main__":
    main()
