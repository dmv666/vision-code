"""Metadatos para construir los controles de la interfaz (rangos de sliders, menús)."""
from __future__ import annotations

import math

from ..config import DEFAULTS
from ..encoder import PRORES_PROFILES
from ..palette import PRESETS
from ..patterns import PATTERNS

# Rangos explícitos para parámetros de patrón donde la heurística no basta.
PARAM_RANGES: dict[str, tuple[float, float, float]] = {
    "sides": (3, 12, 1), "grid": (1, 8, 1), "shells": (1, 6, 1), "count": (20, 3000, 10),
    "segments": (2, 24, 1), "complexity": (1, 5, 1), "layers": (4, 40, 1), "bands": (2, 30, 1),
    "blobs": (2, 16, 1), "bubbles": (0, 64, 1), "drops": (0, 16, 1), "pads": (0, 5, 1),
    "birds": (0, 6, 1), "fireflies": (0, 64, 1),
    "horizon": (-0.45, 0.45, 0.005), "twist": (-0.4, 0.4, 0.005), "floor": (-0.45, 0.0, 0.005),
    "density": (0.0, 1.0, 0.01), "lights": (0.0, 1.0, 0.01), "trees": (0.0, 1.0, 0.01),
    "panel_density": (0.0, 1.0, 0.01), "streams": (0.0, 1.0, 0.01), "star_density": (0.0, 0.3, 0.005),
    "blur": (0.02, 1.0, 0.01), "intensity": (0.0, 3.0, 0.01), "gloss": (0.0, 2.0, 0.01),
}

# Campos de las secciones globales: (clave, etiqueta, min, max, paso).
SECTIONS = {
    "animation": [
        ("bpm", "BPM (0 = sin pulso)", 0, 200, 1),
        ("speed", "Velocidad (ciclos/seg)", 0, 4, 0.0005),
        ("rotation", "Rotación (vueltas/seg)", -0.5, 0.5, 0.0005),
        ("wobble", "Oscilación (ciclos/seg)", 0, 1, 0.0005),
        ("hue_cycles", "Ciclo de color (vueltas/seg)", -0.5, 0.5, 0.0005),
        ("pulse_strength", "Fuerza del pulso", 0, 1.5, 0.01),
        ("pulse_decay", "Caída del pulso", 0.5, 16, 0.1),
    ],
    "post": [
        ("exposure", "Exposición", 0.2, 3, 0.01),
        ("bloom", "Bloom", 0, 1.5, 0.01),
        ("bloom_radius", "Radio del bloom", 0.5, 2, 0.01),
        ("vignette", "Viñeta", 0, 1, 0.01),
        ("grain", "Grano", 0, 0.08, 0.001),
        ("chromatic_aberration", "Aberración cromática", 0, 0.01, 0.0001),
        ("saturation", "Saturación", 0, 2, 0.01),
        ("contrast", "Contraste", 0.5, 1.6, 0.01),
    ],
}

RESOLUTIONS = [
    ("4K UHD", 3840, 2160), ("1440p", 2560, 1440), ("1080p", 1920, 1080), ("720p", 1280, 720),
    ("Vertical 1080×1920", 1080, 1920), ("Cuadrado 2048", 2048, 2048),
]
QUALITIES = {"h264": ["draft", "high", "master"], "hevc": ["draft", "high", "master"],
             "prores": PRORES_PROFILES}


def param_range(key: str, default) -> dict:
    is_int = isinstance(default, int) and not isinstance(default, bool)
    if key in PARAM_RANGES:
        lo, hi, step = PARAM_RANGES[key]
        return {"min": lo, "max": hi, "step": step, "int": is_int or step == 1}
    if is_int:
        return {"min": 0, "max": max(10, default * 3), "step": 1, "int": True}
    v = float(default)
    if v == 0:
        return {"min": 0, "max": 1, "step": 0.01, "int": False}
    step = 10 ** (math.floor(math.log10(abs(v))) - 2)
    if v < 0:
        return {"min": v * 3, "max": -v * 3, "step": step, "int": False}
    return {"min": 0, "max": v * 3, "step": step, "int": False}


def meta(gpu: str) -> dict:
    return {
        "gpu": gpu,
        "defaults": DEFAULTS,
        "patterns": {
            name: {"params": {k: {"default": v, **param_range(k, v)} for k, v in spec["params"].items()}}
            for name, spec in PATTERNS.items()
        },
        "presets": PRESETS,
        "sections": {k: [dict(zip(("key", "label", "min", "max", "step"), f)) for f in v]
                     for k, v in SECTIONS.items()},
        "resolutions": [dict(zip(("label", "width", "height"), r)) for r in RESOLUTIONS],
        "qualities": QUALITIES,
        "codecs": ["h264", "hevc", "prores"],
        "fps": [24, 25, 30, 50, 60],
    }
