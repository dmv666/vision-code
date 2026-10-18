"""Registro de patrones. Cada patrón = un fragment shader + parámetros por defecto.

Cada clave de `geometry.params` se envía al shader como uniform `u_<clave>`.
Para añadir un patrón: crea `shaders/<nombre>.frag` (incluyendo common.glsl)
y regístralo aquí.
"""
from __future__ import annotations

PATTERNS: dict[str, dict] = {
    "hex_tunnel": {
        "shader": "hex_tunnel.frag",
        "params": {
            "sides": 6,            # 6 = hexágono; 3, 4, 8... también funcionan
            "radius": 1.0,
            "segment": 1.0,        # longitud de cada anillo (unidades de mundo)
            "line_width": 0.03,
            "twist": 0.06,         # radianes por unidad de profundidad (espiral)
            "fov": 1.0,
            "fog": 16.0,           # profundidad a la que la luz cae a 1/e
            "grid": 3,             # subdivisiones por cara
            "pulse_speed": 0.08,   # cómo viaja la onda de pulso hacia el fondo
            "panel_density": 0.12, # fracción de paneles iluminados
            "streams": 0.0,        # flujos de luz por las aristas (0 = off, 1 = intenso)
            "stream_speed": 1.5,   # × velocidad del túnel
        },
    },
    "particle_sphere": {
        "shader": "particle_sphere.frag",
        "params": {
            "count": 280,          # partículas por capa (coste ∝ count × shells)
            "shells": 2,
            "radius": 1.0,
            "size": 0.010,
            "displacement": 0.08,  # deformación orgánica de la superficie
            "camera_distance": 3.2,
            "focal": 1.6,
        },
    },
    "kaleidoscope": {
        "shader": "kaleidoscope.frag",
        "params": {
            "segments": 8,         # espejos
            "zoom": 0.7,           # densidad del zoom logarítmico infinito
            "complexity": 3,       # iteraciones de pliegue (KIFS)
            "line_width": 0.005,   # en unidades de celda: 0.002 fino · 0.01 grueso
        },
    },
    "starfield": {
        "shader": "starfield.frag",
        "params": {
            "layers": 16,          # capas de profundidad (coste ∝ layers)
            "density": 0.12,
            "size": 0.03,
            "far_scale": 40.0,
            "streak": 3.0,         # estelas warp en las estrellas cercanas
            "twinkle": 0.3,
        },
    },
    "organic_waves": {
        "shader": "organic_waves.frag",
        "params": {
            "scale": 1.6,
            "bands": 9,            # curvas de nivel
            "warp": 1.4,           # distorsión de dominio (más = más líquido)
            "line_width": 0.025,   # en fracción de banda
            "flow_radius": 0.6,
            "horizon": 0.0,        # >0 (p.ej. 0.15) = suelo en perspectiva tipo synthwave
        },
    },
}


def resolve_pattern(gcfg: dict) -> tuple[str, dict]:
    """Acepta un bloque `geometry` o una capa de `layers` (ambos con pattern/params)."""
    name = gcfg["pattern"]
    if name not in PATTERNS:
        raise ValueError(f"Patrón desconocido {name!r}. Opciones: {sorted(PATTERNS)}")
    spec = PATTERNS[name]
    params = {**spec["params"], **(gcfg.get("params") or {})}
    return spec["shader"], params
