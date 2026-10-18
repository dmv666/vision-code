"""Carga, valida y completa el archivo de configuración (JSON o YAML)."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "output": {
        "path": "renders/loop.mp4",
        "width": 3840,
        "height": 2160,
        "fps": 60,
        "duration": 16.0,          # segundos (se ignora si animation.bars está definido)
        "codec": "h264",           # h264 | hevc | prores
        "quality": "high",         # draft | high | master  (prores: proxy | lt | standard | hq | 4444 | xq)
        "hardware": "auto",        # auto (= sí en macOS) | true | false  → VideoToolbox / NVENC
        "supersample": 2,          # SSAA: renderiza a N×N y reduce (anti-aliasing)
        "motion_blur": {"samples": 1, "shutter": 0.5},  # samples=1 desactiva
    },
    # Un solo patrón con "geometry", o varios mezclados con "layers" (ver README).
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
        "bloom": 0.35,             # intensidad del resplandor (0 = off)
        "bloom_radius": 1.0,       # >1 = halo más amplio
        "saturation": 1.0,
        "contrast": 1.0,
    },
}

VALID_CODECS = {"h264", "hevc", "prores"}
LEGACY_CODECS = {"h264_nvenc": "h264"}  # codec antiguo → (codec, hardware=True)


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


def _list_index(items: list, part: str, path: str) -> int:
    """Índice en una lista por número (`2`, `-1`) o, en `layers`, por nombre de patrón."""
    try:
        idx = int(part)
    except ValueError:
        matches = [i for i, it in enumerate(items) if isinstance(it, dict) and it.get("pattern") == part]
        if len(matches) == 1:
            return matches[0]
        names = [it.get("pattern") for it in items if isinstance(it, dict)]
        if not matches:
            raise ConfigError(f"{path}: no hay ningún elemento {part!r} (hay: {names})")
        raise ConfigError(f"{path}: {part!r} aparece {len(matches)} veces, usa el índice "
                          f"({', '.join(f'{path}.{i}' for i in matches)})")
    if not -len(items) <= idx < len(items):
        raise ConfigError(f"{path}: índice {idx} fuera de rango (hay {len(items)} elementos: 0..{len(items) - 1})")
    return idx % len(items)


def apply_override(cfg: dict, expr: str) -> None:
    """Aplica `ruta.con.puntos=valor` (valor en JSON o texto plano).

    En listas se entra por índice o, para capas, por nombre de patrón:
    `layers.2.params.count=1200` o `layers.particle_sphere.params.count=1200`.
    """
    if "=" not in expr:
        raise ConfigError(f"--set espera clave=valor, recibido: {expr!r}")
    key, raw = expr.split("=", 1)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    parts = key.strip().split(".")
    node = cfg
    path = ""
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(node, list):
            idx = _list_index(node, part, path)
            if last:
                node[idx] = value
            else:
                node = node[idx]
        elif isinstance(node, dict):
            if last:
                node[part] = value
            elif part == "layers" and part not in node:
                raise ConfigError(f"--set {key}: este config no usa 'layers'; "
                                  f"su patrón se ajusta con geometry.params.<clave>")
            else:
                node = node.setdefault(part, {})
        else:
            raise ConfigError(f"--set {key}: {path!r} es un valor ({node!r}), no se puede entrar en él")
        path = f"{path}.{part}" if path else part


def config_from_dict(user: dict, overrides: list[str] | None = None) -> dict:
    """Como load_config, pero desde un dict ya cargado (lo usa la interfaz)."""
    cfg = deep_merge(DEFAULTS, user)
    for expr in overrides or []:
        apply_override(cfg, expr)
    validate(cfg)
    return cfg


def load_config(path: str | Path, overrides: list[str] | None = None) -> dict:
    user = _read_file(Path(path))
    cfg = deep_merge(DEFAULTS, user)
    for expr in overrides or []:
        apply_override(cfg, expr)
    validate(cfg)
    return cfg


def layers_of(cfg: dict) -> list[dict]:
    """Normaliza a lista de capas. Cada capa: pattern, params, opacity, palette, animation."""
    if cfg.get("layers"):
        return cfg["layers"]
    return [{"pattern": cfg["geometry"]["pattern"], "params": cfg["geometry"].get("params") or {}}]


def wants_hardware(out: dict) -> bool:
    hw = out.get("hardware", "auto")
    if hw == "auto":
        return sys.platform == "darwin"
    return bool(hw)


def validate(cfg: dict) -> None:
    out = cfg["output"]
    if out["codec"] in LEGACY_CODECS:
        out["codec"] = LEGACY_CODECS[out["codec"]]
        out["hardware"] = True
    for k in ("width", "height", "fps"):
        if not isinstance(out[k], int) or out[k] <= 0:
            raise ConfigError(f"output.{k} debe ser un entero > 0")
    if out["codec"] not in VALID_CODECS:
        raise ConfigError(f"output.codec debe ser uno de {sorted(VALID_CODECS)}")
    if out["codec"] != "prores" and (out["width"] % 2 or out["height"] % 2):
        raise ConfigError("H.264/HEVC 4:2:0 requiere ancho y alto pares")
    if out.get("hardware", "auto") not in ("auto", True, False):
        raise ConfigError('output.hardware debe ser "auto", true o false')
    layers = layers_of(cfg)
    for i, layer in enumerate(layers):
        if "pattern" not in layer:
            raise ConfigError(f"layers[{i}] necesita 'pattern'")
        if float(layer.get("opacity", 1.0)) < 0:
            raise ConfigError(f"layers[{i}].opacity debe ser >= 0")
    if int(out["supersample"]) < 1:
        raise ConfigError("output.supersample debe ser >= 1")
    if int(out["motion_blur"]["samples"]) < 1:
        raise ConfigError("output.motion_blur.samples debe ser >= 1")
    anim = cfg["animation"]
    if anim["bars"] is None and float(out["duration"]) <= 0:
        raise ConfigError("output.duration debe ser > 0")
    if anim["bars"] is not None and float(anim["bpm"]) <= 0:
        raise ConfigError("animation.bars requiere animation.bpm > 0")
