"""Detecção de rosto: recorte vertical automático e detecção da facecam em streams.

Detector:
  - YuNet (OpenCV DNN) se existir assets/models/face_detection_yunet.onnx  → mais preciso, pega perfil
  - senão Haar cascade (vem no opencv-python-headless 4.x)                   → funciona sem download
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from .ff import REPO_ROOT, ClipadorError, probe

YUNET_PATH = REPO_ROOT / "assets" / "models" / "face_detection_yunet.onnx"
CACHE_DIR = REPO_ROOT / ".cache" / "faces"


def _cv2():
    try:
        import cv2  # type: ignore
    except ImportError as e:
        raise ClipadorError('detecção de rosto precisa do OpenCV: pip install "opencv-python-headless<5"') from e
    return cv2


class FaceDetector:
    def __init__(self, min_size_frac: float = 0.04):
        cv2 = _cv2()
        self.cv2 = cv2
        self.min_size_frac = min_size_frac
        self.kind = "haar"
        self.yunet = None
        if YUNET_PATH.exists() and hasattr(cv2, "FaceDetectorYN"):
            self.yunet = cv2.FaceDetectorYN.create(str(YUNET_PATH), "", (320, 320), 0.6, 0.3, 50)
            self.kind = "yunet"
        else:
            base = getattr(cv2, "data", None)
            if base is None or not Path(base.haarcascades, "haarcascade_frontalface_default.xml").exists():
                raise ClipadorError('cascades Haar não encontradas — use "opencv-python-headless<5" '
                                    "ou coloque o modelo YuNet em assets/models/")
            self.front = cv2.CascadeClassifier(str(Path(base.haarcascades, "haarcascade_frontalface_default.xml")))
            self.profile = cv2.CascadeClassifier(str(Path(base.haarcascades, "haarcascade_profileface.xml")))
            self.clahe = cv2.createCLAHE(2.0, (8, 8))

    def detect(self, frame: np.ndarray) -> list[dict]:
        """Retorna rostos com coordenadas normalizadas: {x,y,w,h,cx,cy,score}."""
        h, w = frame.shape[:2]
        boxes: list[tuple[float, float, float, float, float]] = []
        if self.yunet is not None:
            self.yunet.setInputSize((w, h))
            _, faces = self.yunet.detect(frame)
            for f in faces if faces is not None else []:
                boxes.append((f[0], f[1], f[2], f[3], float(f[14])))
        else:
            cv2 = self.cv2
            raw = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ms = max(16, int(self.min_size_frac * w))
            gray = raw
            # 1º cinza puro; se nada, contraste local (CLAHE) — equalizeHist global atrapalha com fundos grandes
            for gray in (raw, self.clahe.apply(raw)):
                for (x, y, bw, bh) in self.front.detectMultiScale(gray, 1.1, 5, minSize=(ms, ms)):
                    boxes.append((x, y, bw, bh, 1.0))
                if boxes:
                    break
            if not boxes:
                for flip in (False, True):
                    g = cv2.flip(gray, 1) if flip else gray
                    for (x, y, bw, bh) in self.profile.detectMultiScale(g, 1.1, 5, minSize=(ms, ms)):
                        x = w - x - bw if flip else x
                        boxes.append((x, y, bw, bh, 0.7))
        out = []
        for x, y, bw, bh, s in boxes:
            out.append({"x": x / w, "y": y / h, "w": bw / w, "h": bh / h,
                        "cx": (x + bw / 2) / w, "cy": (y + bh / 2) / h, "score": round(float(s), 3)})
        return out


# ---------------------------------------------------------------- leitura de frames


def _scaled_size(path: str, width: int) -> tuple[int, int]:
    info = probe(path)
    sw, sh = info["width"], info["height"]
    return width, int(round(width * sh / sw / 2)) * 2


def iter_frames(path: str, start: float, end: float, step: float, width: int = 480):
    """Gera (tempo_absoluto, frame_bgr) a cada `step` s, num único processo ffmpeg (rápido p/ trechos longos)."""
    w, h = _scaled_size(path, width)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", path, "-an",
           "-vf", f"fps=1/{step},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i * step, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def frame_at(path: str, t: float, width: int = 960) -> np.ndarray | None:
    w, h = _scaled_size(path, width)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-an",
           "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    buf = subprocess.run(cmd, capture_output=True).stdout
    if len(buf) < w * h * 3:
        return None
    return np.frombuffer(buf[: w * h * 3], np.uint8).reshape(h, w, 3)


# ---------------------------------------------------------------- cache


def _cache_key(path: str, *parts) -> Path:
    p = Path(path).resolve()
    raw = json.dumps([str(p), p.stat().st_mtime, p.stat().st_size, *parts])
    return CACHE_DIR / (hashlib.sha1(raw.encode()).hexdigest()[:20] + ".json")


def _cached(path: str, parts: list, fn):
    key = _cache_key(path, *parts)
    if key.exists():
        return json.loads(key.read_text())
    val = fn()
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(val))
    return val


# ---------------------------------------------------------------- recorte vertical automático


def track_faces(path: str, start: float, end: float, step: float = 0.5, width: int = 640,
                region: list[float] | None = None) -> list[dict]:
    """Rostos por amostra. `region` [x,y,w,h] restringe a busca (coordenadas continuam relativas ao frame inteiro)."""
    det = FaceDetector()

    def run():
        out = []
        for t, fr in iter_frames(path, start, end, step, width):
            if region:
                H, W = fr.shape[:2]
                x0, y0 = int(region[0] * W), int(region[1] * H)
                sub = fr[y0:y0 + int(region[3] * H), x0:x0 + int(region[2] * W)]
                faces = det.detect(sub)
                for f in faces:
                    for k, base, scale in (("x", region[0], region[2]), ("cx", region[0], region[2]),
                                           ("y", region[1], region[3]), ("cy", region[1], region[3])):
                        f[k] = base + f[k] * scale
                    f["w"] *= region[2]
                    f["h"] *= region[3]
            else:
                faces = det.detect(fr)
            out.append({"t": round(t, 3), "faces": faces})
        return out

    return _cached(path, ["track", round(start, 3), round(end, 3), step, width, region, det.kind], run)


def _pick_subject(samples: list[dict]) -> list[float | None]:
    """Escolhe o rosto principal em cada amostra (maior, com preferência por continuidade)."""
    chosen: list[float | None] = []
    prev = None
    for s in samples:
        faces = s["faces"]
        if not faces:
            chosen.append(None)
            continue

        def score(f):
            sc = f["w"] * f["h"] * f["score"]
            if prev is not None:
                sc *= 1.0 / (1.0 + 4 * abs(f["cx"] - prev))
            return sc

        best = max(faces, key=score)
        prev = best["cx"]
        chosen.append(best["cx"])
    return chosen


def auto_crop_keyframes(path: str, start: float, end: float, out_aspect: float, step: float = 0.5,
                        deadzone: float = 0.07, move_time: float = 0.45, region: list[float] | None = None,
                        default: float = 0.5) -> dict:
    """Keyframes [[t_origem, x]] para reframe crop, seguindo o rosto como um operador de câmera:
    fica parado enquanto o rosto está dentro da zona morta e faz um movimento suave quando sai."""
    info = probe(path)
    src_aspect = info["width"] / info["height"]
    cw = min(1.0, out_aspect / src_aspect)  # largura da janela de corte em fração da origem
    samples = track_faces(path, start, end, step, region=region)
    centers = _pick_subject(samples)
    hits = sum(c is not None for c in centers)
    if cw >= 0.999 or hits == 0:
        return {"x": default, "hits": hits, "samples": len(samples)}

    # preenche buracos (mantém a última posição conhecida; no início usa a primeira)
    first = next(c for c in centers if c is not None)
    filled, last = [], first
    for c in centers:
        last = c if c is not None else last
        filled.append(last)
    # mediana móvel remove detecções espúrias
    arr = np.array(filled)
    k = 5
    med = np.array([np.median(arr[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(arr))])
    target = np.clip((med - cw / 2) / (1 - cw), 0, 1)

    times = [s["t"] for s in samples]
    cur = float(target[0])
    kf = [[round(start, 3), round(cur, 4)]]
    pending = 0
    for t, x in zip(times, target):
        if abs(x - cur) > deadzone:
            pending += 1
            if pending >= 2:  # precisa de 2 amostras seguidas fora da zona morta
                t0 = max(t - step, kf[-1][0] + 0.05)
                kf.append([round(t0, 3), round(cur, 4)])
                cur = float(x)
                kf.append([round(t0 + move_time, 3), round(cur, 4)])
                pending = 0
        else:
            pending = 0
    return {"x": kf if len(kf) > 1 else kf[0][1], "hits": hits, "samples": len(samples)}


# ---------------------------------------------------------------- facecam de stream


def _refine_edges(edge: np.ndarray, box: tuple[int, int, int, int], face: tuple[int, int, int, int]):
    """Ajusta cada lado da caixa para a linha reta estática mais forte (borda da webcam)."""
    H, W = edge.shape
    x0, y0, x1, y1 = box
    fx0, fy0, fx1, fy1 = face
    fw, fh = fx1 - fx0, fy1 - fy0
    base = float(np.median(edge)) + 1e-3

    def best(lo, hi, profile_fn, toward_face_is_high: bool):
        """Entre as linhas fortes, pega a MAIS PRÓXIMA do rosto (a moldura da cam vem antes de HUD/texto)."""
        lo, hi = max(0, lo), max(0, hi)
        if hi <= lo:
            return None
        vals = np.array([profile_fn(i) for i in range(lo, hi)])
        vmax = float(vals.max())
        thr = max(4 * base, 12.0, 0.45 * vmax)
        if vmax < max(4 * base, 12.0):
            return None
        strong = np.nonzero(vals >= thr)[0]
        return lo + int(strong[-1] if toward_face_is_high else strong[0])

    ys, ye = max(0, fy0 - fh), min(H, fy1 + fh)
    xs, xe = max(0, fx0 - fw), min(W, fx1 + fw)
    left = best(fx0 - 3 * fw, fx0 - fw // 4, lambda i: edge[ys:ye, i].mean(), True)
    right = best(fx1 + fw // 4, min(W, fx1 + 3 * fw), lambda i: edge[ys:ye, i].mean(), False)
    top = best(fy0 - 2 * fh, fy0 - fh // 6, lambda i: edge[i, xs:xe].mean(), True)
    bottom = best(fy1 + fh // 4, min(H, fy1 + 3 * fh), lambda i: edge[i, xs:xe].mean(), False)
    return (left if left is not None else x0, top if top is not None else y0,
            right if right is not None else x1, bottom if bottom is not None else y1,
            sum(v is not None for v in (left, right, top, bottom)))


def detect_facecam(path: str, start: float | None = None, end: float | None = None, samples: int = 40,
                   width: int = 960, debug_image: str | None = None) -> dict | None:
    """Encontra a webcam sobreposta numa stream: rosto pequeno que aparece sempre no mesmo lugar.

    Retorna {"rect": [x,y,w,h] normalizado, "face": [...], "confidence": 0..1, "method": ...} ou None.
    """
    cv2 = _cv2()
    info = probe(path)
    dur = info["duration"]
    a = start or 0.0
    b = end if end is not None else dur
    times = [a + (b - a) * (i + 0.5) / samples for i in range(samples)]

    def run():
        det = FaceDetector(min_size_frac=0.02)
        faces_all, frames = [], []
        for t in times:
            fr = frame_at(path, t, width)
            if fr is None:
                continue
            frames.append(fr)
            for f in det.detect(fr):
                if f["w"] < 0.35:  # facecam = rosto pequeno em relação ao frame
                    faces_all.append(f)
        n = len(frames)
        if not faces_all or n == 0:
            return None
        # agrupa por posição (grade de 8% do frame)
        cells: dict[tuple[int, int], list[dict]] = {}
        for f in faces_all:
            cells.setdefault((int(f["cx"] / 0.08), int(f["cy"] / 0.08)), []).append(f)
        # soma vizinhos para não partir um grupo na borda da célula
        best_key, best_n = None, 0
        for (i, j) in cells:
            cnt = sum(len(cells.get((i + di, j + dj), [])) for di in (-1, 0, 1) for dj in (-1, 0, 1))
            if cnt > best_n:
                best_key, best_n = (i, j), cnt
        group = [f for (i, j), fs in cells.items() for f in fs
                 if abs(i - best_key[0]) <= 1 and abs(j - best_key[1]) <= 1]
        conf = min(1.0, len(group) / n)
        if conf < 0.25:
            return None
        med = {k: float(np.median([f[k] for f in group])) for k in ("x", "y", "w", "h", "cx", "cy")}
        H, W = frames[0].shape[:2]
        fx0, fy0 = int(med["x"] * W), int(med["y"] * H)
        fx1, fy1 = int((med["x"] + med["w"]) * W), int((med["y"] + med["h"]) * H)
        fw, fh = fx1 - fx0, fy1 - fy0
        # caixa inicial: webcam típica ~3x a largura do rosto, 16:9
        cw = 3.2 * fw
        ch = cw * 9 / 16
        cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2 + 0.15 * fh
        box = (int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2))
        # bordas estáticas: média do gradiente em muitos frames (o jogo se mexe, a moldura da cam não)
        acc = np.zeros((H, W), np.float32)
        for fr in frames:
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
            acc += np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)) + np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
        acc /= len(frames)
        x0, y0, x1, y1, nref = _refine_edges(acc, box, (fx0, fy0, fx1, fy1))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        rect = [round(x0 / W, 4), round(y0 / H, 4), round((x1 - x0) / W, 4), round((y1 - y0) / H, 4)]
        return {"rect": rect, "face": [round(med[k], 4) for k in ("x", "y", "w", "h")],
                "confidence": round(conf, 2), "edges_found": nref, "samples": n,
                "method": "edges" if nref >= 2 else "estimate", "debug_time": times[len(times) // 2]}

    res = _cached(path, ["facecam", a, b, samples, width], run)
    if res and debug_image:
        fr = frame_at(path, res["debug_time"], width)
        if fr is not None:
            fr = fr.copy()
            H, W = fr.shape[:2]
            x, y, w, h = res["rect"]
            cv2.rectangle(fr, (int(x * W), int(y * H)), (int((x + w) * W), int((y + h) * H)), (0, 230, 255), 3)
            fx, fy, fw, fh = res["face"]
            cv2.rectangle(fr, (int(fx * W), int(fy * H)), (int((fx + fw) * W), int((fy + fh) * H)), (0, 255, 0), 2)
            cv2.putText(fr, f"facecam conf={res['confidence']} ({res['method']})", (12, 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 230, 255), 2)
            Path(debug_image).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(debug_image, fr)
    return res
