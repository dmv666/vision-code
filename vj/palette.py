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


class ColorCycle:
    """Secuencia de paletas que se suceden durante el loop ("palette.cycle").

    La paleta base es la primera; después vienen cycle.palettes en orden y la
    última enlaza otra vez con la base. Cada paleta ocupa un tramo igual del
    loop; en la parte final de cada tramo (cycle.transition) se funde con la
    siguiente. Como la secuencia da `repeats` vueltas ENTERAS por loop, la fase
    1.0 cae exactamente en el inicio de la base: el loop cierra sin salto.
    """

    def __init__(self, items: list[dict], repeats: int, transition: float):
        self.items = items
        self.repeats = repeats
        self.transition = transition

    @property
    def changes(self) -> int:
        """Cambios de paleta por loop."""
        return self.repeats * len(self.items)

    def uniforms(self, phase: float) -> dict:
        k = len(self.items)
        s = phase * self.changes
        seg = int(s // 1)
        f = s - seg
        tr = self.transition
        m = min(1.0, max(0.0, (f - (1.0 - tr)) / tr)) if tr > 0 else 0.0
        m = m * m * (3.0 - 2.0 * m)                      # entrada y salida suaves
        a, b = self.items[seg % k], self.items[(seg + 1) % k]
        bg = tuple(x + (y - x) * m for x, y in zip(a["u_background"], b["u_background"]))
        return {"u_colors": a["u_colors"], "u_num_colors": a["u_num_colors"],
                "u_colors_b": b["u_colors"], "u_num_colors_b": b["u_num_colors"],
                "u_palette_mix": m, "u_background": bg}


def resolve_color_cycle(pcfg: dict) -> ColorCycle | None:
    cyc = pcfg.get("cycle")
    if not cyc:
        return None
    if not isinstance(cyc, dict):
        raise ValueError("palette.cycle debe ser un objeto")
    extra = cyc.get("palettes") or []
    if not isinstance(extra, list) or not all(isinstance(p, dict) for p in extra):
        raise ValueError("palette.cycle.palettes debe ser una lista de paletas")
    if not extra:
        return None
    repeats = cyc.get("repeats", 1)
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("palette.cycle.repeats debe ser un entero >= 1 (vueltas de la secuencia por loop)")
    transition = float(cyc.get("transition", 0.35))
    if not 0.0 <= transition <= 1.0:
        raise ValueError("palette.cycle.transition debe estar entre 0 (corte seco) y 1 (fundido continuo)")
    base = {k: v for k, v in pcfg.items() if k != "cycle"}
    intensity = pcfg.get("intensity", 1.0)
    items = [resolve_palette(base)] + [resolve_palette({"intensity": intensity, **p}) for p in extra]
    return ColorCycle(items, repeats, transition)


def layer_palette(global_pcfg: dict, layer_pcfg: dict | None) -> dict:
    """Paleta de una capa. Si la capa trae sus propios colores (preset o colors)
    no hereda la secuencia global, salvo que defina su propio "cycle"."""
    if not layer_pcfg:
        return global_pcfg
    merged = {**global_pcfg, **layer_pcfg}
    if ("preset" in layer_pcfg or "colors" in layer_pcfg) and "cycle" not in layer_pcfg:
        merged.pop("cycle", None)
    return merged
