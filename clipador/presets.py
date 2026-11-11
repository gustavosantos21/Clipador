"""Presets de saída por plataforma."""

PRESETS = {
    # vertical 9:16
    "shorts":    {"width": 1080, "height": 1920, "fps": 30, "max_duration": 60,  "desc": "YouTube Shorts 9:16"},
    "reels":     {"width": 1080, "height": 1920, "fps": 30, "max_duration": 90,  "desc": "Instagram Reels 9:16"},
    "tiktok":    {"width": 1080, "height": 1920, "fps": 30, "max_duration": 180, "desc": "TikTok 9:16"},
    "vertical":  {"width": 1080, "height": 1920, "fps": 30, "max_duration": None, "desc": "Vertical genérico 9:16"},
    # horizontal 16:9
    "youtube":   {"width": 1920, "height": 1080, "fps": 30, "max_duration": None, "desc": "YouTube 16:9 1080p"},
    "youtube4k": {"width": 3840, "height": 2160, "fps": 30, "max_duration": None, "desc": "YouTube 16:9 4K"},
    # feed
    "feed45":    {"width": 1080, "height": 1350, "fps": 30, "max_duration": 60,  "desc": "Instagram feed 4:5"},
    "square":    {"width": 1080, "height": 1080, "fps": 30, "max_duration": 60,  "desc": "Quadrado 1:1"},
}

QUALITY = {
    # draft: rápido para revisão; final: para publicar
    "draft": {"preset": "ultrafast", "crf": 30, "audio_bitrate": "128k", "scale": 0.5},
    "final": {"preset": "medium", "crf": 18, "audio_bitrate": "192k", "scale": 1.0},
}


def get_preset(name: str) -> dict:
    if name not in PRESETS:
        raise KeyError(f"preset desconhecido: {name}. Opções: {', '.join(PRESETS)}")
    return dict(PRESETS[name])
