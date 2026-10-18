"""Carga, valida y completa el archivo de configuración (JSON o YAML)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "output": {
        "path": "renders/loop.mp4",
        "width": 3840,
        "height": 2160,
        "fps": 60,
        "duration": 16.0,          # segundos (se ignora si animation.bars está definido)
        "codec": "h264",           # h264 | h264_nvenc | prores
        "quality": "high",         # draft | high | master  (prores: proxy | lt | standard | hq | 4444)
        "supersample": 2,          # SSAA: renderiza a N×N y reduce (anti-aliasing)
        "motion_blur": {"samples": 1, "shutter": 0.5},  # samples=1 desactiva
    },
    "geometry": {
        "pattern": "hex_tunnel",
        "params": {},
    },
    "palette": {
        "preset": "cyberpunk",
        # "colors": ["#ff2a6d", "#05d9e8"],  # sobrescribe el preset
        # "background": "#01012b",
        "intensity": 1.0,          # multiplicador HDR de los colores
    },
    "animation": {
        "speed": 2.0,              # ciclos espaciales/seg (segmentos del túnel, capas de zoom...)
        "rotation": 0.0625,        # vueltas completas por segundo
        "wobble": 0.125,           # oscilaciones secundarias (cámara/deformación) por segundo
        "hue_cycles": 0.0,         # vueltas completas de la paleta por segundo
        "bpm": 128,                # 0 desactiva el pulso
        "bars": None,              # si se define, duration = bars * beats_per_bar * 60 / bpm
        "beats_per_bar": 4,
        "pulse_strength": 0.6,
        "pulse_decay": 5.0,        # cuánto tarda en apagarse cada golpe (mayor = más seco)
    },
    "post": {
        "exposure": 1.0,
        "vignette": 0.35,
        "grain": 0.015,            # además de textura, hace dithering contra el banding de 8 bits
        "chromatic_aberration": 0.0015,
    },
}

VALID_CODECS = {"h264", "h264_nvenc", "prores"}


class ConfigError(ValueError):
    pass


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as e:  # pragma: no cover
            raise ConfigError("Para configs YAML instala pyyaml: pip install pyyaml") from e
        return yaml.safe_load(text) or {}
    return json.loads(text)


def apply_override(cfg: dict, expr: str) -> None:
    """Aplica `ruta.con.puntos=valor` (valor en JSON o texto plano)."""
    if "=" not in expr:
        raise ConfigError(f"--set espera clave=valor, recibido: {expr!r}")
    key, raw = expr.split("=", 1)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    node = cfg
    parts = key.strip().split(".")
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def load_config(path: str | Path, overrides: list[str] | None = None) -> dict:
    user = _read_file(Path(path))
    cfg = deep_merge(DEFAULTS, user)
    for expr in overrides or []:
        apply_override(cfg, expr)
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    out = cfg["output"]
    for k in ("width", "height", "fps"):
        if not isinstance(out[k], int) or out[k] <= 0:
            raise ConfigError(f"output.{k} debe ser un entero > 0")
    if out["codec"] not in VALID_CODECS:
        raise ConfigError(f"output.codec debe ser uno de {sorted(VALID_CODECS)}")
    if out["codec"] != "prores" and (out["width"] % 2 or out["height"] % 2):
        raise ConfigError("H.264 4:2:0 requiere ancho y alto pares")
    if int(out["supersample"]) < 1:
        raise ConfigError("output.supersample debe ser >= 1")
    if int(out["motion_blur"]["samples"]) < 1:
        raise ConfigError("output.motion_blur.samples debe ser >= 1")
    anim = cfg["animation"]
    if anim["bars"] is None and float(out["duration"]) <= 0:
        raise ConfigError("output.duration debe ser > 0")
    if anim["bars"] is not None and float(anim["bpm"]) <= 0:
        raise ConfigError("animation.bars requiere animation.bpm > 0")
