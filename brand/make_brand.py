"""Prism Loops — genera el logo (2048×2048) y el banner (2560×1440) del canal.

    python brand/make_brand.py                 # todas las variantes, calidad final
    python brand/make_brand.py --draft         # rápido (1/4 de resolución, sin SSAA)
    python brand/make_brand.py --only logo_infinity banner_flow

Renderiza en GPU con brand/prism.frag + el post-proceso de vj (bloom, ACES,
grano) y compone el texto con Pillow. Salida en brand/out/.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from vj.renderer import VERTEX_SHADER, create_context, load_shader, set_uniforms  # noqa: E402

OUT = ROOT / "out"
FONTS = ROOT / "fonts"
MAXP, MAXK = 160, 32
BG_HEX = "#0A0A12"

# Acentos de marca: violeta, cian, magenta, ámbar.
BRAND = ["#7B2CFF", "#2D6BFF", "#00E5FF", "#F2F6FF", "#FFB000", "#FF5A3C", "#FF2BD6"]
COOL = ["#6A1BFF", "#3D4BFF", "#00C8FF", "#7DF9FF", "#E8F4FF", "#C86BFF", "#FF2BD6"]


# --------------------------------------------------------------------------- color

def hex_to_lin(h: str) -> np.ndarray:
    h = h.lstrip("#")
    c = np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def cie_rgb(lam_nm: float) -> np.ndarray:
    """Ajuste analítico de las funciones CIE 1931 (Wyman et al. 2013) → sRGB lineal."""
    def g(x, mu, s1, s2):
        s = s1 if x < mu else s2
        return math.exp(-0.5 * ((x - mu) / s) ** 2)
    x = 1.056 * g(lam_nm, 599.8, 37.9, 31.0) + 0.362 * g(lam_nm, 442.0, 16.0, 26.7) - 0.065 * g(lam_nm, 501.1, 20.4, 26.2)
    y = 0.821 * g(lam_nm, 568.8, 46.9, 40.5) + 0.286 * g(lam_nm, 530.9, 16.3, 31.1)
    z = 1.217 * g(lam_nm, 437.0, 11.8, 36.0) + 0.681 * g(lam_nm, 459.0, 26.0, 13.8)
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    return np.maximum(m @ np.array([x, y, z]), 0.0)


def spectrum(kind: str, k: int = 24) -> list[tuple]:
    """K colores ordenados de violeta a rojo; su suma es blanco neutro (luz recombinada)."""
    if kind == "physical":
        cols = np.array([cie_rgb(400 + 300 * (i + 0.5) / k) for i in range(k)])
    else:
        stops = np.array([hex_to_lin(h) for h in (BRAND if kind == "brand" else COOL)])
        cols = []
        for i in range(k):
            x = (i + 0.5) / k * (len(stops) - 1)
            a = int(x)
            cols.append(stops[a] * (1 - (x - a)) + stops[min(a + 1, len(stops) - 1)] * (x - a))
        cols = np.array(cols)
    cols = cols / cols.sum(axis=0) * (k / 3.0)   # cada canal suma lo mismo → mezcla blanca
    cols = cols / cols.max() * 1.0
    return [tuple(c) for c in cols]


def aces(x):
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


def bg_input(hex_color: str, post: dict) -> tuple:
    """Valor HDR que, tras el post de vj, sale exactamente como `hex_color`.

    Invierte la cadena del post en orden inverso: contraste → gamma → saturación →
    ACES → exposición (la viñeta y el bloom apenas afectan al centro del fondo)."""
    h = hex_color.lstrip("#")
    t = np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    t = (t - 0.5) / post.get("contrast", 1.0) + 0.5
    lin = np.clip(t, 0, 1) ** 2.2
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    lin = lum + (lin - lum) / post.get("saturation", 1.0)
    out = []
    for target in np.clip(lin, 0, 1):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if aces(mid) < target else (lo, mid)
        out.append((lo + hi) / 2 / post["exposure"])
    return tuple(out)


# --------------------------------------------------------------------------- caminos

def resample(pts: np.ndarray, n: int = MAXP) -> np.ndarray:
    """Remuestrea una polilínea (x, y, spread, twist) a n puntos equiespaciados por longitud.

    spread < 0 marca los tramos que pasan por detrás del prisma; twist es el
    ángulo de giro de la cinta (0 = plana de frente, π/2 = de canto)."""
    seg = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, i]) for i in range(4)], axis=1)


def spline(ctrl: list[tuple], samples: int = 600) -> np.ndarray:
    """Catmull-Rom por puntos de control (x, y, spread, twist)."""
    c = np.array(ctrl, dtype=float)
    c = np.vstack([c[0] * 2 - c[1], c, c[-1] * 2 - c[-2]])
    out = []
    per = max(2, samples // (len(c) - 3))
    for i in range(1, len(c) - 2):
        p0, p1, p2, p3 = c[i - 1], c[i], c[i + 1], c[i + 2]
        for t in np.linspace(0, 1, per, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(c[-2])
    return resample(np.array(out))


def split_crossfade(pts: np.ndarray, at: float, overlap: float):
    """Parte un camino que se cruza consigo mismo en dos, con un tramo común de
    longitud `overlap` donde uno se desvanece mientras el otro aparece (suma = 1).
    El shader solo evalúa la rama más cercana de cada camino; separados, el cruce
    se dibuja completo en vez de mostrar un corte. Devuelve (a, fade_a, b, fade_b)."""
    seg = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    cut = at * s[-1]
    a = pts[s <= cut + overlap / 2]
    b = pts[s >= cut - overlap / 2]
    la = s[s <= cut + overlap / 2][-1]
    lb = s[-1] - s[s >= cut - overlap / 2][0]
    return resample(a), overlap / la, resample(b), overlap / lb


def lemniscate(a: float, spread_max: float, twists: float = 0.5) -> np.ndarray:
    """Bucle ∞ que nace en el centro (dentro del prisma). La cinta da `twists`
    medias vueltas: con 0.5 es una banda de Möbius, el espectro sale invertido."""
    t = np.linspace(-math.pi / 2, 3 * math.pi / 2, 900)
    den = 1 + np.sin(t) ** 2
    x = a * np.cos(t) / den
    y = a * np.sin(t) * np.cos(t) / den
    u = (t + math.pi / 2) / (2 * math.pi)
    # Lóbulo derecho: luz dispersada (abierta); izquierdo: se recombina hacia blanco.
    spread = spread_max * np.abs(np.sin(u * math.pi * 2)) * np.where(u < 0.5, 1.0, 0.75)
    spread = np.maximum(spread, 0.006)
    twist = u * math.pi * 2 * twists
    return resample(np.stack([x, y, spread, twist], axis=1))


def ellipse_ring(rx: float, ry: float, tilt: float, spread: float, twists: float = 2.0,
                 center=(0.0, 0.0)) -> np.ndarray:
    t = np.linspace(0, 2 * math.pi, 900)
    x, y = rx * np.cos(t), ry * np.sin(t)
    c, s = math.cos(tilt), math.sin(tilt)
    xr, yr = c * x - s * y + center[0], s * x + c * y + center[1]
    behind = np.sin(t) > 0                     # mitad superior pasa por detrás del prisma
    sp = np.where(behind, -spread, spread)
    return resample(np.stack([xr, yr, sp, t * twists], axis=1))


# --------------------------------------------------------------------------- render

class BrandRenderer:
    def __init__(self):
        self.ctx = create_context()
        frag = (ROOT / "prism.frag").read_text(encoding="utf-8")
        self.prog = self.ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=frag)
        self.post = self.ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=load_shader("post.frag"))
        self.vao = self.ctx.vertex_array(self.prog, [])
        self.post_vao = self.ctx.vertex_array(self.post, [])

    def render(self, w: int, h: int, ss: int, scene: dict, post: dict) -> np.ndarray:
        size = (w * ss, h * ss)
        accum = self.ctx.texture(size, 4, dtype="f2")
        accum.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        fbo = self.ctx.framebuffer(color_attachments=[accum])
        out = self.ctx.simple_framebuffer((w, h), components=4)

        uniforms = dict(scene)
        for i in (0, 1, 2):
            pts = uniforms.pop(f"path{i}", None)
            if pts is None:
                uniforms[f"u_path{i}_n"] = 0
                continue
            uniforms[f"u_path{i}"] = [tuple(p) for p in pts]
            uniforms[f"u_path{i}_n"] = len(pts)
        spec = uniforms.pop("spectrum")
        uniforms["u_spec"] = spec + [(0.0, 0.0, 0.0)] * (MAXK - len(spec))
        uniforms["u_spec_n"] = len(spec)
        uniforms["u_resolution"] = (float(size[0]), float(size[1]))
        # Las distancias del shader están en unidades de alto de imagen.
        set_uniforms(self.prog, uniforms)

        fbo.use()
        fbo.clear(0, 0, 0, 1)
        self.vao.render(moderngl.TRIANGLES, vertices=3)
        accum.build_mipmaps()

        set_uniforms(self.post, {
            "u_out_res": (float(w), float(h)), "u_ss": ss, "u_accum": 0, "u_frame": 0.0,
            "u_exposure": post["exposure"], "u_vignette": post["vignette"], "u_grain": post["grain"],
            "u_ca": post["ca"], "u_bloom": post["bloom"], "u_bloom_radius": post["bloom_radius"],
            "u_saturation": post.get("saturation", 1.0), "u_contrast": post.get("contrast", 1.0),
        })
        out.use()
        accum.use(location=0)
        self.post_vao.render(moderngl.TRIANGLES, vertices=3)
        img = np.frombuffer(out.read(components=3, alignment=1), np.uint8).reshape(h, w, 3)[::-1]
        for obj in (accum, fbo, out):
            obj.release()
        return img.copy()


# --------------------------------------------------------------------------- texto

def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / name), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def text_mask(w: int, h: int, text: str, fnt: ImageFont.FreeTypeFont, cx: float, cy: float,
              tracking: float) -> Image.Image:
    """Máscara L del texto centrado en (cx, cy) px, con espaciado `tracking` (fracción del tamaño)."""
    advances = [fnt.getlength(ch) for ch in text]
    track = tracking * fnt.size
    total = sum(advances) + track * (len(text) - 1)
    asc, desc = fnt.getmetrics()
    bbox = fnt.getbbox("PRISMLOOPS")              # alto de mayúsculas para centrar ópticamente
    cap_mid = (bbox[1] + bbox[3]) / 2
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    x = cx - total / 2
    for ch, adv in zip(text, advances):
        d.text((x, cy - cap_mid), ch, font=fnt, fill=255)
        x += adv + track
    return m


def composite_text(img: np.ndarray, layers: list[dict]) -> np.ndarray:
    """Texto blanco con halo espectral tenue y leve separación cromática."""
    h, w, _ = img.shape
    out = img.astype(np.float32) / 255.0
    lin = out ** 2.2
    grad_x = np.linspace(0, 1, w)[None, :, None]
    stops = np.array([hex_to_lin(c) for c in ("#7B2CFF", "#00E5FF", "#FF2BD6", "#FFB000")])
    idx = grad_x * (len(stops) - 1)
    a = np.clip(idx.astype(int), 0, len(stops) - 2)
    f = idx - a
    spectral = stops[a[..., 0]] * (1 - f) + stops[a[..., 0] + 1] * f        # (1, w, 3)

    for L in layers:
        m = text_mask(w, h, L["text"], L["font"], L["cx"], L["cy"], L["tracking"])
        mask = np.asarray(m, np.float32)[..., None] / 255.0
        # Halo espectral (dos radios) en luz lineal.
        for radius, k in ((L["size_px"] * 0.12, 0.55), (L["size_px"] * 0.45, 0.35)):
            g = np.asarray(m.filter(ImageFilter.GaussianBlur(radius)), np.float32)[..., None] / 255.0
            lin += spectral * g * k * L["glow"]
        # Separación cromática: rojo a la izquierda, azul a la derecha.
        shift = max(1, int(L["size_px"] * 0.02))
        mr = np.roll(mask, -shift, axis=1)
        mb = np.roll(mask, shift, axis=1)
        lin += np.concatenate([mr * 0.25, np.zeros_like(mr), mb * 0.35], axis=2) * L["glow"]
        # Texto blanco encima (alpha over).
        lin = lin * (1 - mask) + np.array(L.get("color", (1.0, 1.0, 1.0))) * mask * L.get("opacity", 1.0) \
            + lin * mask * (1 - L.get("opacity", 1.0))
    out = np.clip(lin, 0, 1) ** (1 / 2.2)
    return (out * 255 + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------- escenas

POST_LOGO = dict(exposure=1.0, vignette=0.12, grain=0.010, ca=0.0012, bloom=0.30, bloom_radius=1.0,
                 saturation=1.12, contrast=1.05)
POST_BANNER = dict(exposure=1.0, vignette=0.10, grain=0.012, ca=0.0010, bloom=0.35, bloom_radius=1.1,
                   saturation=1.12, contrast=1.05)


def base_scene(post: dict) -> dict:
    return {
        "u_bg": bg_input(BG_HEX, post),
        "u_haze": tuple(hex_to_lin("#5B2DFF") * 0.5 + hex_to_lin("#00E5FF") * 0.2),
        "u_haze_i": 0.03,
        "u_text_box": (0.0, 0.0, 0.0, 0.0), "u_text_dim": 0.0,
        "u_caustic": (0.0, 0.0, 1.0, 0.0),
        "u_fade0": (0.02, 0.02), "u_fade1": (0.02, 0.02),
        "u_ribbon1": (0.0, 0.004, 0.0, 0.0), "u_ribbon2": (0.0, 0.004, 0.0, 0.0), "u_fade2": (0.0, 0.0),
        "u_glass": 1.0,
    }


CAM_DIST = 1.1   # en alturas de imagen: perspectiva suave, ~15° de campo sobre el prisma


def prism_geom(c, r, yaw=28.0, pitch=-14.0, roll=0.0, length=None, ior=(1.50, 1.53, 1.57)):
    """Prisma 3D: uniforms + silueta proyectada (casco convexo en 2D) para colocar el haz.

    yaw/pitch/roll en grados; length = largo de la extrusión (por defecto 0.9·r)."""
    length = 0.9 * r if length is None else length
    a, b, g = (math.radians(v) for v in (yaw, pitch, roll))
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    rz = np.array([[math.cos(g), -math.sin(g), 0], [math.sin(g), math.cos(g), 0], [0, 0, 1]])
    world = rz @ rx @ ry                       # local → mundo
    m = world.T                                # mundo → local (ortonormal)
    verts = []
    for z in (-length / 2, length / 2):
        for k in range(3):
            ang = math.pi / 2 + k * 2 * math.pi / 3
            v = world @ np.array([r * math.cos(ang), r * math.sin(ang), z])
            k = CAM_DIST / (CAM_DIST + v[2])          # misma proyección que el shader
            verts.append((c[0] + v[0] * k, c[1] + v[1] * k))
    hull = convex_hull(verts)
    uniforms = {"u_prism_c": c, "u_prism_r": r, "u_prism_len": length,
                "u_prism_m": tuple(m.T.flatten()),   # GLSL mat3: columnas consecutivas
                "u_ior": ior, "u_cam_dist": CAM_DIST}
    return uniforms, hull


def convex_hull(pts):
    pts = sorted(set(pts))
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p_ in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p_) <= 0:
            lower.pop()
        lower.append(p_)
    for p_ in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p_) <= 0:
            upper.pop()
        upper.append(p_)
    return lower[:-1] + upper[:-1]


def hull_point(hull, y, side, inset=0.004):
    """Punto de la silueta a la altura y (side=-1 izquierda, +1 derecha), un poco hacia dentro."""
    xs = []
    for i in range(len(hull)):
        (x0, y0), (x1, y1) = hull[i], hull[(i + 1) % len(hull)]
        if (y0 - y) * (y1 - y) <= 0 and y0 != y1:
            xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    x = min(xs) if side < 0 else max(xs)
    return (x - side * inset, y)


TAU = 2 * math.pi


def logo_scenes() -> dict[str, dict]:
    scenes = {}
    s0 = base_scene(POST_LOGO)

    # 1) Infinity Prism: la luz nace en el prisma, se dispersa y vuelve en un bucle ∞
    #    que es una banda de Möbius (el espectro regresa invertido).
    pg, H = prism_geom((0.0, 0.0), 0.13, yaw=30, pitch=-12, length=0.8 * 0.13)
    scenes["logo_infinity"] = {**s0, **pg,
        "u_edge_w": 0.0045, "u_beam_w": 0.0, "u_beam_i": 0.0,
        "u_beam_a": (0, 0), "u_beam_e": (-0.05, 0.0), "u_beam_x": (0.05, 0.0),
        "path0": lemniscate(0.262, 0.095, twists=0.5), "u_ribbon0": (0.16, 0.0050, 0.12, 0),
        "u_fade0": (0.0, 0.0), "spectrum": spectrum("brand"),
        "u_caustic": (0.0, -0.20, 0.34, 0.10)}

    # 2) Orbit: anillo espectral inclinado que pasa por detrás y por delante del prisma.
    pg, H = prism_geom((0.0, 0.012), 0.135, yaw=26, pitch=-14)
    e = hull_point(H, 0.025, -1)
    x = hull_point(H, -0.005, +1)
    scenes["logo_orbit"] = {**s0, **pg,
        "u_edge_w": 0.0045, "u_beam_w": 0.0045, "u_beam_i": 0.9,
        "u_beam_a": (-0.285, e[1] + 0.045), "u_beam_e": e, "u_beam_x": x,
        "path0": ellipse_ring(0.262, 0.088, math.radians(-14), 0.070, twists=2.0, center=(0.0, -0.005)),
        "u_ribbon0": (0.17, 0.0050, 0.12, 0), "u_fade0": (0.0, 0.0),
        "spectrum": spectrum("physical"),
        "u_caustic": (0.0, -0.21, 0.32, 0.09)}

    # 3) Loop Beam: el haz blanco entra, sale como abanico y rodea el prisma de vuelta.
    pg, H = prism_geom((-0.01, -0.035), 0.115, yaw=24, pitch=-12)
    e = hull_point(H, -0.045, -1)
    x = hull_point(H, -0.030, +1)
    k = 0.76                                   # escala para caber en el círculo del 70 %
    ctrl = [
        (x[0], x[1], 0.006, 0), (0.15, -0.035, 0.05, 0), (0.27, 0.04, 0.10, 0.3),
        (0.28, 0.18, 0.13, 0.9), (0.15, 0.29, 0.14, 1.6), (-0.05, 0.31, 0.13, 2.2),
        (-0.22, 0.24, 0.11, 2.8), (-0.31, 0.10, 0.08, 3.1), (-0.31, -0.05, 0.04, 3.14),
        (-0.25, -0.15, 0.008, 3.14)]
    loop = spline([ctrl[0]] + [(cx * k, cy * k, sp * k, tw) for cx, cy, sp, tw in ctrl[1:]])
    scenes["logo_loopbeam"] = {**s0, **pg,
        "u_edge_w": 0.0045, "u_beam_w": 0.005, "u_beam_i": 1.0,
        "u_beam_a": (-0.20, e[1] - 0.13), "u_beam_e": e, "u_beam_x": x,
        "path0": loop, "u_ribbon0": (0.17, 0.0052, 0.12, 0), "u_fade0": (0.02, 0.12),
        "spectrum": spectrum("cool"),
        "u_caustic": (0.0, -0.23, 0.30, 0.09)}
    return scenes


# Banner: unidades = alto de imagen (1440 px). Franja segura 1546×423 → x ±0.537, y ±0.147.
SAFE_HW, SAFE_HH = 1546 / 2 / 1440, 423 / 2 / 1440
EDGE_X = 2560 / 2 / 1440 + 0.03


def banner_scenes() -> dict[str, dict]:
    scenes = {}
    s0 = base_scene(POST_BANNER)

    # 1) Flow: prisma a la izquierda; el abanico se abre plano alrededor del texto y
    #    se cierra girando (bucles) hacia el borde derecho.
    pg, H = prism_geom((-0.41, 0.0), 0.09, yaw=32, pitch=-10, roll=-4)
    e = hull_point(H, 0.014, -1)
    x = hull_point(H, -0.004, +1)
    flow = spline([
        (x[0], x[1], 0.005, 0), (-0.25, -0.004, 0.08, 0), (-0.12, 0.0, 0.20, 0),
        (0.14, 0.0, 0.215, 0), (0.40, 0.0, 0.20, 0), (0.56, -0.004, 0.12, 0.6),
        (0.68, 0.0, 0.08, 1.6 * TAU / 2), (0.80, 0.006, 0.07, 2.6 * TAU / 2),
        (EDGE_X, 0.012, 0.07, 3.6 * TAU / 2)])
    beam_y = e[1] + 0.035
    # Reflejo parcial en la cara de entrada: una cinta tenue que sale hacia el borde izquierdo.
    reflect_l = spline([(e[0] - 0.004, e[1] - 0.004, 0.004, 0), (-0.58, -0.05, 0.05, 0.3),
                        (-0.76, -0.10, 0.09, 0.7), (-EDGE_X, -0.125, 0.11, 1.0)])
    scenes["banner_flow"] = {**s0, **pg,
        "u_edge_w": 0.0022, "u_beam_w": 0.0022, "u_beam_i": 1.0,
        "u_beam_a": (-EDGE_X, beam_y), "u_beam_e": e, "u_beam_x": x,
        "path0": flow, "u_ribbon0": (0.12, 0.0021, 0.12, 0), "u_fade0": (0.0, 0.03),
        "path1": reflect_l, "u_ribbon1": (0.06, 0.0016, 0.25, 0), "u_fade1": (0.12, 0.0),
        "spectrum": spectrum("brand"),
        "u_text_box": (0.11, 0.003, 0.355, 0.056), "u_text_dim": 0.9,
        "u_caustic": (-0.25, -0.20, 0.45, 0.10),
        "text": {"cx": 0.11, "font": ("Montserrat[wght].ttf", 300), "tracking": 0.38,
                 "title_px": 100, "sub_px": 28, "sub_font": ("Montserrat[wght].ttf", 400),
                 "sub_tracking": 0.32, "title_y": -0.012, "sub_y": 0.060}}

    # 2) Horizon: texto centrado sobre el haz blanco (que se interrumpe tras él); un
    #    prisma a la derecha lo abre en cintas que dan un bucle en la zona decorativa.
    pg, H = prism_geom((0.47, -0.004), 0.072, yaw=-28, pitch=-10, roll=3)
    e = hull_point(H, -0.010, -1)
    x = hull_point(H, -0.014, +1)
    # Bucle bajo y a la izquierda de la esquina superior derecha (donde YouTube
    # superpone los enlaces), que debe quedar tranquila.
    curl = spline([
        (x[0], x[1], 0.005, 0), (0.58, -0.014, 0.045, 0), (0.665, 0.0, 0.065, 0.4),
        (0.70, 0.045, 0.07, 1.2), (0.655, 0.078, 0.065, 2.0), (0.605, 0.045, 0.065, 2.8),
        (0.645, -0.005, 0.065, 3.4), (0.78, -0.035, 0.06, 3.9), (EDGE_X, -0.045, 0.055, 4.4)])
    curl_a, fa, curl_b, fb = split_crossfade(curl, 0.55, 0.03)
    echo = spline([(e[0] - 0.004, e[1] - 0.004, 0.004, 0), (0.25, -0.075, 0.04, 0.2),
                   (-0.20, -0.12, 0.08, 0.6), (-0.60, -0.15, 0.11, 1.0), (-EDGE_X, -0.17, 0.12, 1.2)])
    scenes["banner_horizon"] = {**s0, **pg,
        "u_edge_w": 0.0020, "u_beam_w": 0.0020, "u_beam_i": 0.9,
        "u_beam_a": (-EDGE_X, -0.010), "u_beam_e": e, "u_beam_x": x,
        "path0": curl_a, "u_ribbon0": (0.13, 0.0020, 0.12, 0), "u_fade0": (0.0, fa),
        "path1": curl_b, "u_ribbon1": (0.13, 0.0020, 0.12, 0), "u_fade1": (fb, 0.03),
        "path2": echo, "u_ribbon2": (0.055, 0.0015, 0.25, 0), "u_fade2": (0.10, 0.0),
        "spectrum": spectrum("physical"),
        "u_text_box": (-0.075, 0.0, 0.32, 0.06), "u_text_dim": 0.97,
        "u_caustic": (0.10, -0.22, 0.42, 0.09),
        "text": {"cx": -0.075, "font": ("Outfit[wght].ttf", 250), "tracking": 0.44,
                 "title_px": 104, "sub_px": 28, "sub_font": ("Outfit[wght].ttf", 350),
                 "sub_tracking": 0.34, "title_y": -0.012, "sub_y": 0.062}}

    # 3) Strands: minimalista. Hebras finas y frías que pasan bajo el texto y se
    #    abren hacia el borde derecho; tipografía ancha.
    pg, H = prism_geom((-0.44, 0.006), 0.08, yaw=22, pitch=-12)
    e = hull_point(H, 0.022, -1)
    x = hull_point(H, 0.008, +1)
    strands = spline([
        (x[0], x[1], 0.005, 0), (-0.31, -0.03, 0.05, 0), (-0.16, -0.085, 0.07, 0),
        (0.10, -0.10, 0.08, 0), (0.40, -0.09, 0.09, 0), (0.62, -0.05, 0.12, 0.3),
        (0.78, -0.01, 0.16, 0.6), (EDGE_X, 0.01, 0.20, 0.9)])
    scenes["banner_strands"] = {**s0, **pg,
        "u_edge_w": 0.0019, "u_beam_w": 0.0017, "u_beam_i": 0.9,
        "u_beam_a": (-EDGE_X, 0.045), "u_beam_e": e, "u_beam_x": x,
        "path0": strands, "u_ribbon0": (0.11, 0.0012, 0.05, 1), "u_fade0": (0.0, 0.03),
        "spectrum": spectrum("cool", 32),
        "u_caustic": (0.05, -0.21, 0.55, 0.08),
        "text": {"cx": 0.09, "font": ("Michroma-Regular.ttf", None), "tracking": 0.30,
                 "title_px": 78, "sub_px": 25, "sub_font": ("Montserrat[wght].ttf", 350),
                 "sub_tracking": 0.36, "title_y": 0.0, "sub_y": 0.056}}
    return scenes


# --------------------------------------------------------------------------- export

def add_banner_text(img: np.ndarray, t: dict, scale: float) -> np.ndarray:
    h, w, _ = img.shape
    ux = lambda x: w / 2 + x * h          # noqa: E731  unidades → px
    uy = lambda y: h / 2 + y * h          # noqa: E731  (y hacia abajo en la imagen)
    title_px = int(t["title_px"] * scale)
    sub_px = int(t["sub_px"] * scale)
    layers = [
        {"text": "PRISM LOOPS", "font": font(t["font"][0], title_px, t["font"][1]), "size_px": title_px,
         "cx": ux(t["cx"]), "cy": uy(t["title_y"]), "tracking": t["tracking"], "glow": 1.0},
        {"text": "ABSTRACT 4K VISUALS & LOOPS", "font": font(t["sub_font"][0], sub_px, t["sub_font"][1]),
         "size_px": sub_px, "cx": ux(t["cx"]), "cy": uy(t["sub_y"]), "tracking": t["sub_tracking"],
         "glow": 0.35, "color": (0.80, 0.82, 0.90), "opacity": 0.92},
    ]
    return composite_text(img, layers)


def circle_crop(img: Image.Image, size: int, bg=(15, 15, 15)) -> Image.Image:
    """Avatar como lo muestra YouTube: recortado en círculo y reducido a `size` px."""
    small = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGB", (size, size), bg)
    out.paste(small, (0, 0), mask)
    return out


def logo_preview(img: Image.Image, path: Path) -> None:
    """Ficha: imagen completa con el círculo seguro del 70 % + recortes a 176/98/48 px
    sobre fondo oscuro y claro (temas de YouTube)."""
    w = img.width
    full = img.resize((720, 720), Image.LANCZOS).convert("RGB")
    d = ImageDraw.Draw(full)
    r = 720 * 0.35
    d.ellipse((360 - r, 360 - r, 360 + r, 360 + r), outline=(255, 210, 0), width=2)
    d.ellipse((0, 0, 719, 719), outline=(120, 120, 120), width=1)
    sheet = Image.new("RGB", (720 + 40 + 2 * 220, 760), (24, 24, 24))
    sheet.paste(full, (20, 20))
    for col, bg in enumerate(((15, 15, 15), (255, 255, 255))):
        x0 = 760 + col * 220
        panel = Image.new("RGB", (200, 720), bg)
        y = 20
        for size in (176, 98, 48):
            panel.paste(circle_crop(img, size, bg), ((200 - size) // 2, y))
            y += size + 40
        sheet.paste(panel, (x0, 20))
    sheet.save(path)


def banner_preview(img: Image.Image, path: Path) -> None:
    """Ficha: banner con zonas de YouTube (TV completo, escritorio 2560×423,
    móvil/seguro 1546×423) y los recortes reales de escritorio y móvil."""
    w, h = img.size
    sx = 1280 / w
    full = img.resize((1280, int(h * sx)), Image.LANCZOS).convert("RGB")
    d = ImageDraw.Draw(full)
    def box(bw, bh, color):
        x0, y0 = (w - bw) / 2 * sx, (h - bh) / 2 * sx
        d.rectangle((x0, y0, x0 + bw * sx, y0 + bh * sx), outline=color, width=2)
    box(2560, 423, (0, 200, 255))
    box(1546, 423, (255, 210, 0))
    desk = img.crop((0, (h - 423) // 2, w, (h + 423) // 2)).resize((1280, int(423 * sx)), Image.LANCZOS)
    mob = img.crop(((w - 1546) // 2, (h - 423) // 2, (w + 1546) // 2, (h + 423) // 2))
    mob = mob.resize((int(1546 * 0.5), int(423 * 0.5)), Image.LANCZOS)
    sheet = Image.new("RGB", (1320, full.height + desk.height + mob.height + 100), (24, 24, 24))
    sheet.paste(full, (20, 20))
    sheet.paste(desk, (20, full.height + 50))
    sheet.paste(mob, (20, full.height + desk.height + 80))
    sheet.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true", help="1/4 de resolución, sin SSAA")
    ap.add_argument("--only", nargs="*", help="nombres de variantes")
    ap.add_argument("--ss", type=int, default=2)
    args = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    scale = 0.25 if args.draft else 1.0
    ss = 1 if args.draft else args.ss
    r = BrandRenderer()

    for name, scene in logo_scenes().items():
        if args.only and name not in args.only:
            continue
        size = int(2048 * scale)
        img = r.render(size, size, ss, scene, POST_LOGO)
        path = OUT / f"{name}{'_draft' if args.draft else ''}.png"
        Image.fromarray(img).save(path, optimize=True)
        logo_preview(Image.fromarray(img), OUT / f"preview_{name}{'_draft' if args.draft else ''}.png")
        print(f"{path}  {path.stat().st_size / 1e6:.2f} MB")

    for name, scene in banner_scenes().items():
        if args.only and name not in args.only:
            continue
        scene = dict(scene)
        text = scene.pop("text")
        w, h = int(2560 * scale), int(1440 * scale)
        img = r.render(w, h, ss, scene, POST_BANNER)
        img = add_banner_text(img, text, scale)
        path = OUT / f"{name}{'_draft' if args.draft else ''}.jpg"
        Image.fromarray(img).save(path, quality=97, subsampling=0, optimize=True)
        if not args.draft:
            banner_preview(Image.fromarray(img), OUT / f"preview_{name}.png")
        print(f"{path}  {path.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
