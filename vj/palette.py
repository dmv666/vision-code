"""Paletas de color. Los hex se convierten a RGB lineal (el post-proceso aplica tonemap + gamma)."""
from __future__ import annotations

MAX_COLORS = 8

PRESETS: dict[str, dict] = {
    "neon":        {"colors": ["#ff00e6", "#00f0ff", "#7a00ff", "#00ff9d"], "background": "#030008"},
    "cyberpunk":   {"colors": ["#ff2a6d", "#05d9e8", "#d1f7ff", "#7700a6"], "background": "#01012b"},
    "synthwave":   {"colors": ["#f72585", "#7209b7", "#3a0ca3", "#4cc9f0"], "background": "#0b0014"},
    "acid":        {"colors": ["#ccff00", "#00ff66", "#ff00aa", "#00e5ff"], "background": "#000000"},
    "dark_techno": {"colors": ["#ff1a1a", "#550000", "#ffffff", "#330000"], "background": "#000000"},
    "ice":         {"colors": ["#a8f0ff", "#2f6bff", "#ffffff", "#0a1a4f"], "background": "#00040d"},
    "sunset":      {"colors": ["#ff7b00", "#ff006e", "#8338ec", "#ffbe0b"], "background": "#0d0221"},
}


def hex_to_linear(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Color hex inválido: #{h}")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)


def resolve_palette(pcfg: dict) -> dict:
    preset_name = pcfg.get("preset")
    base = PRESETS.get(preset_name, {}) if preset_name else {}
    if preset_name and not base:
        raise ValueError(f"Paleta desconocida {preset_name!r}. Opciones: {sorted(PRESETS)}")
    colors = pcfg.get("colors") or base.get("colors")
    if not colors:
        raise ValueError("La paleta necesita 'preset' o 'colors'")
    if len(colors) > MAX_COLORS:
        raise ValueError(f"Máximo {MAX_COLORS} colores por paleta")
    background = pcfg.get("background") or base.get("background", "#000000")
    k = float(pcfg.get("intensity", 1.0))
    lin = [tuple(c * k for c in hex_to_linear(c)) for c in colors]
    padded = lin + [(0.0, 0.0, 0.0)] * (MAX_COLORS - len(lin))
    return {
        "u_colors": padded,
        "u_num_colors": len(lin),
        "u_background": hex_to_linear(background),
    }
