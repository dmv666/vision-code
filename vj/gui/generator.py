"""Escenas aleatorias y variaciones de una escena.

Ninguna variación puede romper el loop: solo se tocan parámetros espaciales,
colores, post-proceso y velocidades, y las velocidades se siguen cuantizando a
ciclos enteros por loop en loop.py.
"""
from __future__ import annotations

import colorsys
import copy
import random

from ..config import DEFAULTS
from ..palette import PRESETS
from ..patterns import PATTERNS
from .schema import SECTIONS, param_range

# Patrones que funcionan bien como capa encima de otro (aportan luz, no tapan).
OVERLAYS = ["starfield", "particle_sphere", "kaleidoscope", "organic_waves"]
BPMS = [0, 90, 100, 110, 120, 124, 128, 135, 140, 150, 174]


def _hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (r, g, b)))


def _rgb(hexcol: str) -> tuple[float, float, float]:
    h = hexcol.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def random_palette(rng: random.Random) -> dict:
    """Paleta armónica (análoga, tríada, complementaria...) sobre un fondo oscuro teñido."""
    if rng.random() < 0.3:
        return {"preset": rng.choice(sorted(PRESETS))}
    base = rng.random()
    scheme = rng.choice(["análoga", "tríada", "complementaria", "dividida", "monocroma"])
    offsets = {
        "análoga": [0, 0.07, 0.14, -0.07],
        "tríada": [0, 1 / 3, 2 / 3],
        "complementaria": [0, 0.5, 0.05, 0.55],
        "dividida": [0, 0.42, 0.58, 0.02],
        "monocroma": [0, 0.01, 0.02],
    }[scheme]
    colors = []
    for i, o in enumerate(offsets):
        light = [0.35, 0.6, 0.85][i] if scheme == "monocroma" else rng.uniform(0.42, 0.72)
        colors.append(_hex(base + o, rng.uniform(0.7, 1.0), light))
    return {"colors": colors, "background": _hex(base, rng.uniform(0.4, 0.9), rng.uniform(0.008, 0.035)),
            "intensity": round(rng.uniform(0.85, 1.3), 2)}


def _snap(v: float, lo: float, hi: float, step: float, is_int: bool):
    v = min(hi, max(lo, v))
    if is_int:
        return int(round(v))
    v = round(v / step) * step
    return float(f"{v:.6g}")


def _jitter(v, lo, hi, step, is_int, amount, rng):
    span = hi - lo
    return _snap(v + rng.gauss(0, 0.35) * amount * span, lo, hi, step, is_int)


def _vary_params(holder: dict, amount: float, rng: random.Random) -> None:
    spec = PATTERNS[holder["pattern"]]["params"]
    params = holder.setdefault("params", {})
    for k, default in spec.items():
        if rng.random() > 0.7:
            continue
        r = param_range(k, default)
        params[k] = _jitter(params.get(k, default), r["min"], r["max"], r["step"], r["int"], amount, rng)


def _vary_section(cfg: dict, section: str, amount: float, rng: random.Random, keys=None) -> None:
    sec = cfg.setdefault(section, {})
    for key, _label, lo, hi, step in SECTIONS[section]:
        if keys is not None and key not in keys:
            continue
        cur = sec.get(key, DEFAULTS[section][key])
        if cur is None:
            continue
        sec[key] = _jitter(cur, lo, hi, step, step == 1, amount, rng)


def _shift_hue(colors: list[str], shift: float) -> list[str]:
    out = []
    for c in colors:
        h, l, s = colorsys.rgb_to_hls(*_rgb(c))
        out.append(_hex(h + shift, s, l))
    return out


def vary(user_cfg: dict, amount: float = 0.35, seed: int | None = None) -> dict:
    """Variación de la escena actual. amount 0..1: de retoque sutil a otra escena."""
    rng = random.Random(seed)
    amount = min(1.0, max(0.0, amount))
    cfg = copy.deepcopy(user_cfg)

    holders = cfg["layers"] if cfg.get("layers") else [cfg.setdefault("geometry", copy.deepcopy(DEFAULTS["geometry"]))]
    for h in holders:
        _vary_params(h, amount, rng)
        if "opacity" in h:
            h["opacity"] = _snap(h["opacity"] + rng.gauss(0, 0.15) * amount, 0.1, 1.0, 0.01, False)

    # Velocidades: factor multiplicativo (conserva el signo y el carácter chill/rápido).
    anim = cfg.setdefault("animation", {})
    for key in ("speed", "rotation", "wobble", "hue_cycles"):
        cur = anim.get(key, DEFAULTS["animation"][key])
        if cur:
            anim[key] = float(f"{cur * 2 ** (rng.gauss(0, 0.6) * amount):.4g}")
    if rng.random() < amount * 0.25 and not anim.get("hue_cycles"):
        anim["hue_cycles"] = rng.choice([-1, 1]) * rng.choice([0.01, 0.02, 0.03])
    _vary_section(cfg, "animation", amount * 0.5, rng, keys={"pulse_strength", "pulse_decay"})
    if rng.random() < amount * 0.3 and anim.get("bars") is None:
        anim["bpm"] = rng.choice(BPMS)

    _vary_section(cfg, "post", amount * 0.35, rng)

    pal = cfg.setdefault("palette", {})
    roll = rng.random()
    if roll < amount * 0.55:
        intensity = pal.get("intensity")
        cfg["palette"] = random_palette(rng)
        if intensity and "intensity" not in cfg["palette"]:
            cfg["palette"]["intensity"] = intensity
        if pal.get("cycle"):
            cfg["palette"]["cycle"] = pal["cycle"]      # la secuencia de colores es parte de la escena
    elif roll < amount * 0.9:
        colors = pal.get("colors") or PRESETS.get(pal.get("preset"), PRESETS["cyberpunk"])["colors"]
        bg = pal.get("background") or PRESETS.get(pal.get("preset"), {}).get("background")
        shift = rng.gauss(0, 0.12) * amount
        pal.pop("preset", None)
        pal["colors"] = _shift_hue(colors, shift)
        if bg:
            pal["background"] = _shift_hue([bg], shift)[0]
    return cfg


def surprise(bases: list[dict], keep_output: dict | None = None, seed: int | None = None) -> dict:
    """Escena nueva: parte de una escena existente (para que el ritmo tenga sentido)
    y la transforma mucho: paleta nueva, parámetros, a veces otra capa encima."""
    rng = random.Random(seed)
    cfg = vary(rng.choice(bases), amount=0.75, seed=rng.randrange(1 << 30))
    cfg["palette"] = {**random_palette(rng), **({"intensity": cfg["palette"]["intensity"]}
                                                if "intensity" in cfg.get("palette", {}) else {})}
    layers = cfg.get("layers")
    if not layers and rng.random() < 0.35:
        base = cfg.pop("geometry")
        over = rng.choice([p for p in OVERLAYS if p != base["pattern"]])
        overlay = {"pattern": over, "opacity": round(rng.uniform(0.3, 0.7), 2), "params": {}}
        _vary_params(overlay, 0.4, rng)
        cfg["layers"] = [base, overlay]
    elif layers and len(layers) > 2 and rng.random() < 0.3:
        layers.pop(rng.randrange(1, len(layers)))
    if keep_output:
        cfg["output"] = copy.deepcopy(keep_output)
    return cfg
