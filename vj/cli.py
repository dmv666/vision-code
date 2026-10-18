"""CLI: python -m vj configs/hex_tunnel.json [opciones]"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from .config import ConfigError, layers_of, load_config, wants_hardware
from .encoder import FFmpegWriter, resolve_output_path, save_png, select_encoder
from .loop import plan_loop
from .renderer import Renderer


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="vj", description="Genera VJ loops perfectos desde un config JSON/YAML.")
    ap.add_argument("config", help="ruta al archivo .json / .yaml")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR",
                    help="sobrescribe un valor, p.ej. --set output.fps=30 --set palette.preset=acid")
    ap.add_argument("-o", "--output", help="ruta de salida (sobrescribe output.path)")
    ap.add_argument("--preview", action="store_true",
                    help="render rápido: 960x540, sin supersampling ni motion blur")
    ap.add_argument("--stills", type=int, metavar="N",
                    help="en lugar de vídeo, guarda N PNGs repartidos por el loop")
    ap.add_argument("--check-loop", action="store_true",
                    help="verifica numéricamente que el loop cierra sin costura y sale")
    ap.add_argument("--plan", action="store_true", help="muestra el plan del loop y sale")
    hw = ap.add_mutually_exclusive_group()
    hw.add_argument("--hw", dest="hardware", action="store_const", const=True,
                    help="fuerza encoder por hardware (VideoToolbox en Mac, NVENC en NVIDIA)")
    hw.add_argument("--no-hw", dest="hardware", action="store_const", const=False,
                    help="fuerza encoder por software (máxima calidad por bit)")
    return ap.parse_args(argv)


def frame_delta(a: bytes, b: bytes) -> float:
    x = np.frombuffer(a, np.uint8).astype(np.int16)
    y = np.frombuffer(b, np.uint8).astype(np.int16)
    return float(np.abs(x - y).mean())


def check_loop(renderer: Renderer) -> int:
    """Prueba definitiva: el frame N (que no se exporta) debe ser idéntico al frame 0.

    Si f(fase=1) == f(fase=0), la transición N-1 → 0 del archivo es exactamente
    la misma que N-1 → N de una animación continua: no puede haber costura.
    """
    plan = renderer.plan
    n = plan.frames
    f0, f1, f_last = (renderer.render(i) for i in (0, 1, n - 1))
    f_n = renderer.render(n, wrap=False)  # fase 1.0 real, no envuelta a 0
    exact = frame_delta(f0, f_n)
    seam = frame_delta(f_last, f0)
    print(f"  |frame N − frame 0|        = {exact:.4f}  (debe ser ~0)")
    print(f"  costura  frame N-1 → 0     = {seam:.4f}")
    print(f"  paso     frame 0 → 1       = {frame_delta(f0, f1):.4f}")
    if plan.beats > 1 and n % plan.beats == 0:
        # El frame 0 cae en un golpe (ataque del pulso). La referencia justa es
        # otro paso que también cae en un golpe, a mitad del loop.
        m = (plan.beats // 2) * (n // plan.beats)
        ref = frame_delta(renderer.render(m - 1), renderer.render(m))
        print(f"  paso en otro golpe {m - 1}→{m} = {ref:.4f}  (la costura debería parecerse)")
    ok = exact < 0.5
    print("  ✓ loop perfecto" if ok else "  ✗ el loop tiene un salto: hay términos no periódicos en el shader")
    return 0 if ok else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    overrides = []
    if args.preview:
        overrides += ["output.width=960", "output.height=540", "output.supersample=1",
                      "output.motion_blur.samples=1"]
    overrides += args.set  # --set gana sobre --preview
    if args.output:
        overrides.append(f"output.path={args.output}")
    if args.hardware is not None:
        overrides.append(f"output.hardware={'true' if args.hardware else 'false'}")
    try:
        cfg = load_config(args.config, overrides)
        plan = plan_loop(cfg)
    except (ConfigError, ValueError) as e:
        print(f"[vj] error de configuración: {e}", file=sys.stderr)
        return 2

    out = cfg["output"]
    layers = layers_of(cfg)
    for i, layer in enumerate(layers):
        if layer.get("animation"):  # cuantiza ya para mostrar los redondeos por capa
            plan.layer_uniforms({**cfg["animation"], **layer["animation"]}, f"layers[{i}]:{layer['pattern']}",
                                explicit=set(layer["animation"]))
    names = " + ".join(f"{l['pattern']}" + (f"×{l['opacity']}" if "opacity" in l else "") for l in layers)
    print(f"[vj] {names} · {out['width']}x{out['height']} @ {plan.fps}fps · "
          f"{plan.frames} frames ({plan.duration:.3f}s) · SSAA {out['supersample']}x · "
          f"motion blur {out['motion_blur']['samples']} muestras")
    print(f"[vj] ciclos/loop: travel={plan.travel} rotation={plan.rotation} wobble={plan.wobble} "
          f"hue={plan.hue_cycles} beats={plan.beats}")
    for note in plan.notes:
        print(f"[vj]   · {note}")
    if args.plan:
        return 0

    renderer = Renderer(cfg, plan)
    print(f"[vj] GPU: {renderer.gpu}")
    try:
        if args.check_loop:
            return check_loop(renderer)

        if args.stills:
            base = Path(out["path"]).with_suffix("")
            for k in range(args.stills):
                i = round(k * plan.frames / args.stills)
                p = base.parent / f"{base.name}_{i:05d}.png"
                save_png(p, renderer.render(i), renderer.width, renderer.height)
                print(f"[vj] {p}")
            return 0

        path = resolve_output_path(out["path"], out["codec"])
        encoder = select_encoder(out["codec"], out["quality"], renderer.width, renderer.height,
                                 plan.fps, wants_hardware(out))
        print(f"[vj] encoder: {encoder.label()}")
        t0 = time.perf_counter()
        with FFmpegWriter(path, renderer.width, renderer.height, plan.fps, encoder) as w:
            # Frames 0..N-1. NUNCA el frame N: es idéntico al 0 y duplicarlo
            # produce un "tartamudeo" de un frame en cada vuelta del loop.
            t_warm = None
            for i in range(plan.frames):
                w.write(renderer.render(i))
                if i == 0:
                    # El primer frame incluye compilar shaders y arrancar el encoder:
                    # no cuenta para la velocidad ni el ETA.
                    t_warm = time.perf_counter()
                    print(f"[vj] primer frame listo en {t_warm - t0:.1f}s (incluye compilar shaders)")
                    continue
                if i % max(1, plan.fps // 2) == 0 or i == plan.frames - 1:
                    rate = i / (time.perf_counter() - t_warm)
                    eta = (plan.frames - i - 1) / rate
                    print(f"\r[vj] frame {i + 1}/{plan.frames}  {rate:.2f} fps  ETA {eta / 60:5.1f} min ",
                          end="", flush=True)
        print(f"\n[vj] listo → {path}  ({time.perf_counter() - t0:.1f}s)")
        return 0
    finally:
        renderer.release()
