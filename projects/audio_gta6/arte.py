"""Ilustrações próprias (vetor simples, estilo synthwave) para o vídeo do mapa de Leonida.

Tudo desenhado com Pillow, sem imagens de terceiros. Gera cards 1080x1920 em work/cards/.
Uso: python projects/audio_gta6/arte.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from clipador.ff import font_file

W, H = 1080, 1920
SS = 2  # supersampling para bordas suaves
OUT = Path(__file__).parent / "work" / "cards"
FONT = font_file("Inter Black")


def canvas():
    return Image.new("RGB", (W * SS, H * SS))


def grad(img, stops, y0=0.0, y1=1.0):
    """Gradiente vertical por paradas [(pos, (r,g,b)), ...] entre y0 e y1 (frações da altura)."""
    w, h = img.size
    a, b = int(y0 * h), int(y1 * h)
    ys = np.linspace(0, 1, b - a)
    pos = [p for p, _ in stops]
    cols = np.array([c for _, c in stops], float)
    arr = np.stack([np.interp(ys, pos, cols[:, k]) for k in range(3)], 1)
    band = np.repeat(arr[:, None, :], w, 1).astype(np.uint8)
    img.paste(Image.fromarray(band), (0, a))


def S(*v):
    return [int(x * SS) for x in v]


def poly(d, pts, fill):
    d.polygon([(int(x * SS), int(y * SS)) for x, y in pts], fill=fill)


def palm(d, x, y, h, col=(25, 10, 40)):
    """Coqueiro em silhueta: tronco curvo + folhas."""
    pts = []
    for i in range(21):
        t = i / 20
        pts.append((x + math.sin(t * 1.4) * h * 0.18, y - t * h))
    for i in range(20):
        d.line(S(*pts[i], *pts[i + 1]), fill=col, width=int(h * 0.05 * SS * (1.2 - pts.index(pts[i]) / 30)))
    tx, ty = pts[-1]
    for ang in (-160, -120, -75, -30, 10, 200, 250):
        a = math.radians(ang)
        leaf = []
        for i in range(12):
            t = i / 11
            r = h * 0.42 * t
            leaf.append((tx + math.cos(a) * r, ty + math.sin(a) * r + (t ** 2) * h * 0.22))
        for i in range(11):
            wdt = (1 - abs(i / 11 - 0.4)) * h * 0.05
            d.line(S(*leaf[i], *leaf[i + 1]), fill=col, width=max(2, int(wdt * SS)))


def title(img, small, big, color=(255, 230, 0), y=210):
    d = ImageDraw.Draw(img)
    f1 = ImageFont.truetype(FONT, 58 * SS)
    fs = 150
    while True:
        f2 = ImageFont.truetype(FONT, fs * SS)
        if d.textlength(big, font=f2) <= (W - 110) * SS:
            break
        fs -= 6
    for txt, f, yy, fill in ((small, f1, y, (255, 255, 255)), (big, f2, y + 75, color)):
        tw = d.textlength(txt, font=f)
        d.text(((W * SS - tw) / 2, yy * SS), txt, font=f, fill=fill, stroke_width=int(f.size * 0.09),
               stroke_fill=(0, 0, 0))


def finish(img, name, vignette=True):
    img = img.resize((W, H), Image.LANCZOS)
    if vignette:
        yy, xx = np.mgrid[0:H, 0:W]
        v = 1 - 0.35 * (((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.75)) ** 2)
        img = Image.fromarray((np.asarray(img) * np.clip(v, 0.55, 1)[..., None]).astype(np.uint8))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.png")
    return OUT / f"{name}.png"


def stars(d, n, y_max, seed=1):
    r = random.Random(seed)
    for _ in range(n):
        x, y, s = r.uniform(0, W), r.uniform(0, y_max), r.uniform(1, 3.2)
        d.ellipse(S(x - s, y - s, x + s, y + s), fill=(255, 255, 255))


# ---------------------------------------------------------------- mapa de Leonida (inventado, estilizado)

COAST = [(360, 560), (560, 540), (700, 600), (760, 720), (780, 880), (830, 1020), (880, 1160), (900, 1300),
         (870, 1420), (800, 1500), (720, 1470), (650, 1360), (560, 1240), (500, 1120), (450, 980), (360, 900),
         (250, 860), (170, 800), (150, 700), (220, 620)]
REGIONS = [  # (n, nome, x, y)
    (1, "VICE CITY", 820, 1330), (2, "LEONIDA KEYS", 620, 1610), (3, "GRASSRIVERS", 700, 1150),
    (4, "PORT GELLHORN", 240, 770), (5, "AMBROSIA", 580, 820), (6, "MOUNT KALAGA", 500, 600)]


def _T(x, y):
    return 540 + (x - 520) * 0.82, 505 + (y - 540) * 0.72


def leonida_map(highlight_all=True, sub="O MAPA DO GTA 6", big="LEONIDA", name="mapa"):
    """Mapa ilustrativo (inventado, não é o mapa oficial). Fica acima da faixa da legenda."""
    img = canvas()
    grad(img, [(0, (10, 30, 70)), (1, (5, 110, 140))])
    d = ImageDraw.Draw(img)
    # ondas
    for k in range(40):
        y = 480 + k * 38
        d.line(S(0, y, W, y + 6), fill=(30, 140, 170), width=SS)
    # terra com sombra
    poly(d, [_T(x + 14, y + 18) for x, y in COAST], (0, 40, 60))
    poly(d, [_T(*p) for p in COAST], (60, 170, 110))
    poly(d, [_T(*p) for p in [(560, 1240), (650, 1360), (720, 1470), (800, 1500), (870, 1420), (790, 1300),
                              (700, 1180)]], (40, 130, 90))  # pântano
    poly(d, [_T(*p) for p in [(360, 560), (560, 540), (620, 640), (480, 700), (360, 660)]], (110, 150, 90))  # montanha
    # ilhas das Keys
    for i, (x, y) in enumerate([_T(*p) for p in [(760, 1560), (700, 1600), (630, 1630), (560, 1650), (490, 1660),
                                                 (420, 1665)]]):
        d.ellipse(S(x - 34 + i * 2, y - 16, x + 34, y + 16), fill=(230, 210, 150))
        if i:
            d.line(S(x + 34, y, x + 60, y - 10), fill=(240, 240, 240), width=4 * SS)
    # pinos
    f = ImageFont.truetype(FONT, 34 * SS)
    fn = ImageFont.truetype(FONT, 40 * SS)
    for n, nome, x, y in REGIONS:
        x, y = _T(x, y)
        d.ellipse(S(x - 34, y - 34, x + 34, y + 34), fill=(255, 40, 120), outline=(255, 255, 255), width=5 * SS)
        tw = d.textlength(str(n), font=fn)
        d.text((x * SS - tw / 2, (y - 24) * SS), str(n), font=fn, fill=(255, 255, 255))
        lw = d.textlength(nome, font=f)
        lx = min(max(x * SS - lw / 2, 30 * SS), (W - 30) * SS - lw)
        d.text((lx, (y + 42) * SS), nome, font=f, fill=(255, 255, 255), stroke_width=4 * SS, stroke_fill=(0, 0, 0))
    title(img, sub, big)
    return finish(img, name)


# ---------------------------------------------------------------- regiões


def vice_city():
    img = canvas()
    grad(img, [(0, (40, 10, 80)), (0.45, (200, 40, 120)), (0.62, (255, 140, 60)), (0.66, (255, 190, 90))], 0, 0.66)
    grad(img, [(0, (60, 20, 90)), (1, (10, 20, 60))], 0.66, 1)
    d = ImageDraw.Draw(img)
    stars(d, 60, 500)
    # sol listrado
    cx, cy, r = W / 2, 1060, 300
    for y in range(int(cy - r), int(cy + 1)):
        dx = math.sqrt(max(r * r - (y - cy) ** 2, 0))
        t = (y - (cy - r)) / r
        col = (255, int(230 - 120 * t), int(80 + 60 * t))
        if t > 0.5 and int((y - cy) / 14) % 2 == 0:
            continue
        d.line(S(cx - dx, y, cx + dx, y), fill=col, width=SS)
    # prédios
    r_ = random.Random(3)
    x = 0
    while x < W:
        bw, bh = r_.randint(60, 130), r_.randint(220, 620)
        poly(d, [(x, 1270), (x, 1270 - bh), (x + bw, 1270 - bh), (x + bw, 1270)], (35, 15, 60))
        for wy in range(1270 - bh + 25, 1250, 34):
            for wx in range(x + 12, x + bw - 14, 24):
                if r_.random() < 0.45:
                    c = r_.choice([(255, 80, 200), (60, 240, 255), (255, 230, 120)])
                    d.rectangle(S(wx, wy, wx + 10, wy + 14), fill=c)
        x += bw + r_.randint(4, 14)
    d.rectangle(S(0, 1268, W, 1274), fill=(255, 60, 200))
    # mar com reflexo
    for i in range(30):
        y = 1290 + i * 22
        wdt = 280 - i * 6
        if wdt > 0:
            d.line(S(cx - wdt, y, cx + wdt, y), fill=(255, 150, 120), width=3 * SS)
    # praia
    poly(d, [(0, 1700), (W, 1580), (W, H), (0, H)], (240, 190, 140))
    palm(d, 140, 1760, 620)
    palm(d, 930, 1700, 520)
    title(img, "1ª REGIÃO", "VICE CITY", (60, 240, 255))
    return finish(img, "1_vice_city")


def keys():
    img = canvas()
    grad(img, [(0, (90, 190, 255)), (1, (200, 240, 255))], 0, 0.5)
    grad(img, [(0, (20, 200, 210)), (1, (0, 90, 140))], 0.5, 1)
    d = ImageDraw.Draw(img)
    for i, (x, y, rx) in enumerate([(200, 1080, 220), (620, 1180, 170), (930, 1050, 140), (380, 1500, 260)]):
        d.ellipse(S(x - rx, y - rx * 0.25, x + rx, y + rx * 0.25), fill=(240, 220, 160))
        d.ellipse(S(x - rx * 0.75, y - rx * 0.22, x + rx * 0.75, y + rx * 0.12), fill=(70, 170, 90))
        palm(d, x - rx * 0.2, y - 10, rx * 1.2, (20, 70, 50))
    # ponte longa
    pts = [(0, 960), (W, 1000)]
    d.line(S(*pts[0], *pts[1]), fill=(245, 245, 245), width=14 * SS)
    for x in range(30, W, 90):
        y = 960 + 40 * x / W
        d.line(S(x, y, x, y + 70), fill=(220, 220, 220), width=8 * SS)
    # barcos
    for x, y, s in [(760, 1400, 1.4), (240, 1300, 1.0), (840, 1680, 1.8)]:
        poly(d, [(x - 80 * s, y), (x + 90 * s, y), (x + 60 * s, y + 30 * s), (x - 60 * s, y + 30 * s)], (255, 255, 255))
        poly(d, [(x - 30 * s, y), (x + 30 * s, y), (x + 15 * s, y - 28 * s), (x - 20 * s, y - 28 * s)], (255, 60, 120))
        d.line(S(x - 160 * s, y + 34 * s, x - 80 * s, y + 30 * s), fill=(220, 255, 255), width=5 * SS)
    title(img, "2ª REGIÃO", "LEONIDA KEYS", (255, 230, 0))
    return finish(img, "2_leonida_keys")


def grassrivers():
    img = canvas()
    grad(img, [(0, (120, 160, 120)), (1, (220, 220, 170))], 0, 0.55)
    grad(img, [(0, (60, 90, 50)), (1, (20, 40, 25))], 0.55, 1)
    d = ImageDraw.Draw(img)
    r_ = random.Random(7)
    for layer, col in enumerate([(70, 110, 70), (45, 85, 45)]):  # mata ao fundo
        for x in range(-40, W + 40, 50):
            hh = r_.randint(140, 320) - layer * 60
            d.ellipse(S(x - 70, 1056 - hh, x + 70, 1056 - hh + 220), fill=col)
    d.rectangle(S(0, 1056, W, H), fill=(40, 70, 45))
    d.rectangle(S(0, 1430, W, H), fill=(30, 75, 70))  # água escura
    for i in range(18):
        yy = 1450 + i * 26
        x0 = r_.uniform(0, W)
        d.line(S(x0, yy, x0 + r_.uniform(80, 260), yy), fill=(60, 110, 100), width=3 * SS)
    for _ in range(220):  # capim alto
        x, y = r_.uniform(0, W), r_.uniform(1060, 1440)
        hh = r_.uniform(40, 160) * (y / H)
        d.line(S(x, y, x + r_.uniform(-20, 20), y - hh), fill=(90, 140, 60), width=3 * SS)
    # aerobarco
    x, y = 300, 1350
    poly(d, [(x - 170, y), (x + 170, y), (x + 140, y + 50), (x - 150, y + 50)], (240, 240, 240))
    d.rectangle(S(x - 160, y - 190, x - 120, y - 10), fill=(80, 80, 80))
    d.ellipse(S(x - 260, y - 290, x - 20, y - 50), outline=(30, 30, 30), width=10 * SS)
    d.line(S(x - 140, y - 290, x - 140, y - 50), fill=(30, 30, 30), width=6 * SS)
    # jacaré
    # jacaré desenhado em escala 1 numa camada e ampliado 1.6x
    layer = Image.new("RGBA", (900 * SS, 260 * SS), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    gx, gy = 330, 150

    def P(*v):
        return [int(x * SS) for x in v]
    g.ellipse(P(gx - 300, gy - 30, gx + 200, gy + 40), fill=(50, 80, 40))
    for k in range(9):
        g.polygon([tuple(P(gx - 260 + k * 50, gy - 25)), tuple(P(gx - 235 + k * 50, gy - 60)),
                   tuple(P(gx - 210 + k * 50, gy - 25))], fill=(45, 70, 35))
    g.polygon([tuple(P(gx + 150, gy - 25)), tuple(P(gx + 380, gy - 5)), tuple(P(gx + 380, gy + 20)),
               tuple(P(gx + 150, gy + 35))], fill=(55, 90, 45))
    for ex in (gx + 170, gx + 215):
        g.ellipse(P(ex - 22, gy - 52, ex + 22, gy - 10), fill=(55, 90, 45))
        g.ellipse(P(ex - 10, gy - 42, ex + 10, gy - 22), fill=(255, 220, 0))
        g.ellipse(P(ex - 3, gy - 42, ex + 3, gy - 22), fill=(0, 0, 0))
    for k in range(6):
        g.polygon([tuple(P(gx + 200 + k * 30, gy + 20)), tuple(P(gx + 212 + k * 30, gy + 5)),
                   tuple(P(gx + 224 + k * 30, gy + 20))], fill=(255, 255, 255))
    layer = layer.resize((int(layer.width * 1.25), int(layer.height * 1.25)))
    img.paste(layer, (int(-40 * SS), int(1560 * SS)), layer)
    d = ImageDraw.Draw(img)
    for i in range(6):  # ondinhas em volta
        d.arc(S(200 + i * 110, 1790, 300 + i * 110, 1830), 0, 180, fill=(90, 140, 130), width=3 * SS)
    title(img, "3ª REGIÃO", "GRASSRIVERS", (160, 255, 90))
    return finish(img, "3_grassrivers")


def port_gellhorn():
    img = canvas()
    grad(img, [(0, (40, 50, 70)), (1, (150, 120, 110))], 0, 0.6)
    grad(img, [(0, (40, 60, 70)), (1, (15, 25, 35))], 0.6, 1)
    d = ImageDraw.Draw(img)
    r_ = random.Random(5)
    # guindastes
    for x, s in [(200, 1.0), (560, 1.25), (900, 0.9)]:
        base = 1150
        d.rectangle(S(x - 18 * s, base - 520 * s, x + 18 * s, base), fill=(200, 80, 30))
        d.rectangle(S(x - 260 * s, base - 540 * s, x + 200 * s, base - 505 * s), fill=(200, 80, 30))
        d.line(S(x - 200 * s, base - 505 * s, x - 200 * s, base - 300 * s), fill=(60, 60, 60), width=3 * SS)
        for k in range(-6, 5):
            d.line(S(x + k * 40 * s, base - 540 * s, x + (k + 1) * 40 * s, base - 505 * s), fill=(150, 60, 20),
                   width=3 * SS)
    # contêineres
    cols = [(180, 50, 40), (40, 90, 160), (220, 160, 40), (60, 130, 80), (120, 120, 130)]
    for row in range(4):
        x = -20 + row * 30
        while x < W:
            cw = r_.choice([150, 210])
            y = 1150 - (row + 1) * 70
            if r_.random() < 0.85 - row * 0.15:
                c = r_.choice(cols)
                d.rectangle(S(x, y, x + cw - 6, y + 66), fill=c)
                for lx in range(x + 12, x + cw - 12, 16):
                    d.line(S(lx, y + 6, lx, y + 60), fill=tuple(int(v * 0.75) for v in c), width=2 * SS)
            x += cw
    d.rectangle(S(0, 1150, W, 1175), fill=(70, 70, 70))
    for i in range(40):  # água turva com reflexos
        y = 1190 + i * 18
        x0 = r_.uniform(0, W)
        d.line(S(x0, y, x0 + r_.uniform(60, 220), y), fill=(90, 100, 100), width=3 * SS)
    # placa enferrujada
    d.rectangle(S(90, 1500, 640, 1640), fill=(120, 70, 40), outline=(60, 30, 20), width=6 * SS)
    f = ImageFont.truetype(FONT, 46 * SS)
    d.text(S(120, 1535), "PERIGO · PORTO", font=f, fill=(250, 220, 170))
    title(img, "4ª REGIÃO", "PORT GELLHORN", (255, 140, 60))
    return finish(img, "4_port_gellhorn")


def ambrosia():
    img = canvas()
    grad(img, [(0, (120, 180, 230)), (1, (250, 210, 150))], 0, 0.55)
    grad(img, [(0, (220, 180, 60)), (1, (150, 110, 30))], 0.55, 1)
    d = ImageDraw.Draw(img)
    # refinaria
    for x, h in [(620, 520), (720, 600), (820, 480)]:
        d.rectangle(S(x, 1056 - h, x + 50, 1056), fill=(110, 110, 120))
        for k in range(6):  # fumaça
            r = 40 + k * 18
            d.ellipse(S(x + 25 - r + k * 30, 1056 - h - 60 - k * 70 - r, x + 25 + r + k * 30, 1056 - h - 60 - k * 70 + r),
                      fill=(235, 235, 235))
    d.rectangle(S(560, 820, 1000, 1056), fill=(150, 150, 160))
    for wx in range(590, 980, 60):
        d.rectangle(S(wx, 870, wx + 30, 920), fill=(255, 220, 120))
    f = ImageFont.truetype(FONT, 40 * SS)
    d.text(S(600, 960), "AÇÚCAR", font=f, fill=(255, 255, 255))
    # celeiro
    poly(d, [(100, 1056), (100, 840), (240, 740), (380, 840), (380, 1056)], (190, 40, 40))
    d.rectangle(S(190, 920, 290, 1056), fill=(120, 20, 20))
    d.line(S(190, 920, 290, 1056), fill=(255, 255, 255), width=6 * SS)
    d.line(S(290, 920, 190, 1056), fill=(255, 255, 255), width=6 * SS)
    d.rectangle(S(400, 760, 480, 1056), fill=(200, 200, 200))  # silo
    d.ellipse(S(400, 730, 480, 790), fill=(200, 200, 200))
    # plantação em perspectiva
    for k in range(-14, 15):
        d.line(S(W / 2 + k * 18, 1060, W / 2 + k * 160, H), fill=(120, 150, 40), width=10 * SS)
    title(img, "5ª REGIÃO", "AMBROSIA", (255, 230, 0))
    return finish(img, "5_ambrosia")


def kalaga():
    img = canvas()
    grad(img, [(0, (30, 60, 120)), (0.7, (255, 170, 120)), (1, (255, 210, 160))], 0, 0.6)
    d = ImageDraw.Draw(img)
    layers = [((90, 90, 140), 700, 520), ((60, 80, 110), 860, 400), ((40, 70, 70), 1000, 300)]
    r_ = random.Random(11)
    for col, base, amp in layers:
        pts = [(0, H)]
        x = 0
        while x <= W + 120:
            pts.append((x, base + r_.uniform(-amp, 0) * (0.6 + 0.4 * math.sin(x / 180))))
            x += 120
        pts.append((W, H))
        poly(d, pts, col)
    # neve no pico mais alto
    d.rectangle(S(0, 1150, W, H), fill=(30, 60, 45))
    for _ in range(70):  # pinheiros
        x, y = r_.uniform(-20, W + 20), r_.uniform(1100, H)
        s = 0.5 + (y - 1100) / 700
        for k in range(3):
            poly(d, [(x - 50 * s + k * 8 * s, y - k * 45 * s), (x + 50 * s - k * 8 * s, y - k * 45 * s),
                     (x, y - (k * 45 + 110) * s)], (20 + k * 6, 70 + k * 10, 40))
    # trilha
    pts = [(560, H), (520, 1750), (620, 1620), (540, 1480), (600, 1350), (560, 1200)]
    for a, b in zip(pts, pts[1:]):
        d.line(S(*a, *b), fill=(200, 160, 110), width=int(26 * SS * (a[1] / H)))
    title(img, "6ª REGIÃO", "MOUNT KALAGA", (255, 255, 255))
    return finish(img, "6_mount_kalaga")


def pergunta():
    return leonida_map(sub="QUAL VOCÊ VISITA", big="PRIMEIRO?", name="pergunta")


def cta():
    img = canvas()
    grad(img, [(0, (15, 5, 30)), (0.5, (60, 10, 70)), (1, (10, 10, 25))])
    d = ImageDraw.Draw(img)
    stars(d, 120, H, seed=4)
    # brilho
    for r in range(420, 0, -12):
        a = int(70 * (1 - r / 420))
        d.ellipse(S(W / 2 - r, 900 - r, W / 2 + r, 900 + r), fill=(60 + a, 10, 80 + a))
    f_big = ImageFont.truetype(FONT, 230 * SS)
    f_mid = ImageFont.truetype(FONT, 76 * SS)
    f_sm = ImageFont.truetype(FONT, 52 * SS)

    def center(txt, f, y, fill, glow=None):
        tw = d.textlength(txt, font=f)
        if glow:
            d.text(((W * SS - tw) / 2 + 8 * SS, y * SS + 8 * SS), txt, font=f, fill=glow)
        d.text(((W * SS - tw) / 2, y * SS), txt, font=f, fill=fill, stroke_width=int(f.size * 0.06),
               stroke_fill=(0, 0, 0))
    center("LIVE DE", f_mid, 360, (255, 255, 255))
    center("GTA 6", f_big, 440, (255, 255, 255), glow=(255, 0, 90))
    center("NO DIA 19", f_mid, 700, (0, 240, 255))
    # barra de progresso até 50
    x0, x1, y = 140, W - 140, 880
    d.rounded_rectangle(S(x0, y, x1, y + 70), radius=35 * SS, fill=(40, 30, 60), outline=(255, 255, 255), width=4 * SS)
    d.rounded_rectangle(S(x0 + 8, y + 8, x0 + (x1 - x0) * 0.62, y + 62), radius=28 * SS, fill=(255, 0, 90))
    center("FALTAM POUCOS SEGUIDORES", f_sm, 975, (255, 255, 255))
    center("50 SEGUIDORES = LIVE", f_mid, 1045, (255, 230, 0))
    # botão seguir
    d.rounded_rectangle(S(260, 1160, W - 260, 1290), radius=30 * SS, fill=(255, 0, 90))
    center("+ SEGUIR", f_mid, 1180, (255, 255, 255))
    return finish(img, "cta", vignette=False)


def all_cards():
    return {"mapa": leonida_map(), "vice": vice_city(), "keys": keys(), "grass": grassrivers(),
            "port": port_gellhorn(), "ambrosia": ambrosia(), "kalaga": kalaga(), "pergunta": pergunta(), "cta": cta()}


if __name__ == "__main__":
    for k, v in all_cards().items():
        print(k, v)
