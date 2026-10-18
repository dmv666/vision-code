"""Verificación numérica del loop, compartida por la CLI y la interfaz."""
from __future__ import annotations

import numpy as np

from .renderer import Renderer


def _delta(a: bytes, b: bytes) -> np.ndarray:
    return np.abs(np.frombuffer(a, np.uint8).astype(np.int16) - np.frombuffer(b, np.uint8).astype(np.int16))


def measure_loop(renderer: Renderer) -> dict:
    """El frame N (que no se exporta) debe ser idéntico al frame 0.

    Si f(fase=1) == f(fase=0), la transición N-1 → 0 del archivo es exactamente
    la misma que N-1 → N de una animación continua: no puede haber costura.
    El criterio es por píxel, no por media: un salto local (una costura en el
    ruido, una zona de la imagen) puede ser muy visible con una media casi nula.
    """
    plan = renderer.plan
    n = plan.frames
    f0, f1, f_last = (renderer.render(i) for i in (0, 1, n - 1))
    f_n = renderer.render(n, wrap=False)  # fase 1.0 real, no envuelta a 0
    diff = _delta(f0, f_n)
    result = {
        "mean": float(diff.mean()),
        "max": int(diff.max()),
        "bad": int((diff > 2).sum()),
        "seam": float(_delta(f_last, f0).mean()),
        "step": float(_delta(f0, f1).mean()),
        "beat_step": None,
    }
    if plan.beats > 1 and n % plan.beats == 0:
        # El frame 0 cae en un golpe (ataque del pulso). La referencia justa es
        # otro paso que también cae en un golpe, a mitad del loop.
        m = (plan.beats // 2) * (n // plan.beats)
        result["beat_step"] = float(_delta(renderer.render(m - 1), renderer.render(m)).mean())
        result["beat_frames"] = (m - 1, m)
    result["ok"] = result["bad"] == 0
    return result
