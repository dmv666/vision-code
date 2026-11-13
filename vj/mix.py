"""Mix: un vídeo largo que pasa por varias escenas con fundidos, sin costuras.

    python -m vj.mix mix.json -o renders/mix.mp4

Solo se renderiza lo que es único: el loop de cada escena (una vez) y cada
fundido entre dos escenas. El vídeo final se monta repitiendo esas piezas sin
recodificar, así que una hora de mix cuesta lo mismo que unos pocos loops.

Por qué no hay saltos:
  · Un bloque es `n` repeticiones del loop de la escena X; termina en fase 1 = fase 0.
  · El fundido X→Y dura `f` segundos: X sigue desde su fase 0 mientras Y entra
    con sus ÚLTIMOS `f` segundos. Al acabar, Y está exactamente en fase 0, donde
    empieza su propio loop.
  · Con `loop_back` el último fundido vuelve a la primera escena, y el mix
    entero es a su vez un loop perfecto.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from .config import ConfigError, config_from_dict, wants_hardware
from .encoder import CONTAINER, FFmpegWriter, select_encoder
from .loop import plan_loop
from .renderer import Renderer, create_context

CACHE_VERSION = 1
DEFAULTS = {"minutes": 60.0, "scene_minutes": 5.0, "transition": 6.0, "loop_back": True}


class MixError(ValueError):
    pass


def scene_config(scene: dict, output: dict) -> dict:
    """Config completo de una escena con la salida común del mix (todas las piezas
    deben compartir resolución, fps y codec para poder unirse sin recodificar)."""
    user = copy.deepcopy(scene)
    out = {k: v for k, v in (user.get("output") or {}).items() if k == "duration"}   # el loop es de la escena
    user["output"] = {**out, **{k: v for k, v in output.items() if k not in ("path", "duration")}}
    return config_from_dict(user)


def plan_mix(spec: dict) -> dict:
    """Calcula el montaje: qué escena suena en cada bloque y cuántas veces se repite."""
    scenes = spec.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 2:
        raise MixError("un mix necesita al menos 2 escenas")
    if len(scenes) > 40:
        raise MixError("como máximo 40 escenas por mix")
    try:
        minutes = float(spec.get("minutes", DEFAULTS["minutes"]))
        block = float(spec.get("scene_minutes", DEFAULTS["scene_minutes"])) * 60
        fade = float(spec.get("transition", DEFAULTS["transition"]))
    except (TypeError, ValueError):
        raise MixError("minutes, scene_minutes y transition deben ser números") from None
    if minutes <= 0 or block <= 0 or fade < 0:
        raise MixError("minutes y scene_minutes deben ser > 0, y transition >= 0")
    loop_back = bool(spec.get("loop_back", DEFAULTS["loop_back"]))
    output = spec.get("output") or {}

    cfgs = [scene_config(s, output) for s in scenes]
    plans = [plan_loop(c) for c in cfgs]
    fps = plans[0].fps
    nf = round(fade * fps)
    fade = nf / fps

    total = minutes * 60
    # Tantos bloques como quepan, pero al menos uno por escena (todas deben salir).
    n_blocks = max(len(scenes), round(total / block))
    block = total / n_blocks
    blocks, t = [], 0.0
    for k in range(n_blocks):
        s = k % len(scenes)
        last = k == n_blocks - 1
        nxt = 0 if last else (k + 1) % len(scenes)
        # Sin fundido si es corte seco, si el mix no vuelve al inicio, o si la escena
        # siguiente es la misma (su loop ya enlaza solo).
        has_fade = nf > 0 and (not last or loop_back) and nxt != s
        loop = plans[s].frames / fps
        plays = max(1, round((block - (fade if has_fade else 0)) / loop))
        nxt = nxt if has_fade else None
        blocks.append({"scene": s, "plays": plays, "start": t, "next": nxt})
        t += plays * loop + (fade if has_fade else 0)
    return {"cfgs": cfgs, "plans": plans, "fps": fps, "fade_frames": nf, "fade": fade,
            "blocks": blocks, "duration": t, "loop_back": loop_back,
            "transitions": sorted({(b["scene"], b["next"]) for b in blocks if b["next"] is not None})}


def summary(spec: dict) -> dict:
    """Resumen para la interfaz (sin objetos internos)."""
    p = plan_mix(spec)
    fps = p["fps"]
    return {
        "duration": p["duration"], "fps": fps, "fade": p["fade"], "blocks": len(p["blocks"]),
        "loops": [pl.frames / fps for pl in p["plans"]],
        "render_frames": sum(pl.frames for pl in p["plans"]) + len(p["transitions"]) * p["fade_frames"],
        "timeline": [{"scene": b["scene"], "start": b["start"], "plays": b["plays"]} for b in p["blocks"]],
    }


def _key(*parts) -> str:
    blob = json.dumps([CACHE_VERSION, *parts], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:20]


def _cfg_id(cfg: dict) -> dict:
    c = copy.deepcopy(cfg)
    c["output"].pop("path", None)
    return c


class _Progress:
    def __init__(self, total: int):
        self.total, self.done, self.t0, self.last = total, 0, None, 0.0

    def tick(self) -> None:
        self.done += 1
        now = time.perf_counter()
        if self.t0 is None:
            self.t0 = now          # el primer frame incluye compilar shaders: no cuenta
            return
        if now - self.last > 0.5 or self.done == self.total:
            self.last = now
            rate = (self.done - 1) / max(now - self.t0, 1e-6)
            eta = (self.total - self.done) / max(rate, 1e-6)
            print(f"[vj] frame {self.done}/{self.total}  {rate:.2f} fps  ETA {eta / 60:5.1f} min", flush=True)


def render_mix(spec: dict, out_path: Path, cache: Path) -> Path:
    p = plan_mix(spec)
    cfgs, plans, fps, nf = p["cfgs"], p["plans"], p["fps"], p["fade_frames"]
    out = cfgs[0]["output"]
    ext = CONTAINER[out["codec"]]
    out_path = out_path.with_suffix(ext)
    cache.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = out["width"], out["height"]
    encoder = select_encoder(out["codec"], out["quality"], width, height, fps, wants_hardware(out))
    print(f"[vj] mix de {len(cfgs)} escenas · {width}x{height} @ {fps}fps · "
          f"{len(p['blocks'])} bloques · {p['duration'] / 60:.1f} min · fundidos de {p['fade']:.1f} s")
    print(f"[vj] encoder: {encoder.label()}")

    ids = [_cfg_id(c) for c in cfgs]
    loop_files = [cache / f"loop_{_key(ids[i], encoder.label())}{ext}" for i in range(len(cfgs))]
    fade_files = {(a, b): cache / f"fade_{_key(ids[a], ids[b], nf, encoder.label())}{ext}"
                  for a, b in p["transitions"]}
    todo_loops = [i for i, f in enumerate(loop_files) if not f.exists()]
    todo_fades = [ab for ab, f in fade_files.items() if not f.exists()]
    reused = len(loop_files) + len(fade_files) - len(todo_loops) - len(todo_fades)
    if reused:
        print(f"[vj] {reused} piezas ya estaban renderizadas (caché): se reutilizan")
    prog = _Progress(sum(plans[i].frames for i in todo_loops) + nf * len(todo_fades))

    ctx = create_context() if todo_loops or todo_fades else None
    try:
        for i in todo_loops:
            r = Renderer(cfgs[i], plans[i], ctx=ctx)
            tmp = loop_files[i].with_name("tmp_" + loop_files[i].name)
            try:
                with FFmpegWriter(tmp, width, height, fps, encoder) as w:
                    for f in range(plans[i].frames):
                        w.write(r.render(f))
                        prog.tick()
                tmp.replace(loop_files[i])
            finally:
                r.release()
                tmp.unlink(missing_ok=True)
        for a, b in todo_fades:
            ra, rb = Renderer(cfgs[a], plans[a], ctx=ctx), Renderer(cfgs[b], plans[b], ctx=ctx)
            na, nb = plans[a].frames, plans[b].frames
            dst = fade_files[(a, b)]
            tmp = dst.with_name("tmp_" + dst.name)
            try:
                with FFmpegWriter(tmp, width, height, fps, encoder) as w:
                    for i in range(nf):
                        # A sigue desde su fase 0; B entra con sus últimos nf frames y
                        # acaba justo antes de su frame 0.
                        fa = np.frombuffer(ra.render(i % na), np.uint8).astype(np.float32)
                        fb = np.frombuffer(rb.render((nb - nf + i) % nb), np.uint8)
                        x = (i + 1) / (nf + 1)
                        wgt = x * x * (3.0 - 2.0 * x)
                        fa += (fb - fa) * wgt
                        w.write(np.rint(fa).astype(np.uint8).tobytes())
                        prog.tick()
                tmp.replace(dst)
            finally:
                ra.release()
                rb.release()
                tmp.unlink(missing_ok=True)
    finally:
        if ctx is not None:
            ctx.release()

    # Montaje: lista de piezas repetidas, copiadas sin recodificar.
    lines = []
    for blk in p["blocks"]:
        lines += [f"file '{_esc(loop_files[blk['scene']])}'"] * blk["plays"]
        if blk["next"] is not None:
            lines.append(f"file '{_esc(fade_files[(blk['scene'], blk['next'])])}'")
    listing = cache / f"mix_{_key(lines, time.time_ns())}.txt"
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = p["duration"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing)]
    audio = spec.get("audio")
    if audio:
        fade = min(5.0, total / 4)
        cmd += ["-stream_loop", "-1", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
                "-af", f"afade=t=in:st=0:d=2,afade=t=out:st={total - fade:.3f}:d={fade:.3f}", "-t", f"{total:.3f}"]
    else:
        cmd += ["-map", "0:v:0", "-c", "copy"]
    cmd += ["-movflags", "+faststart", str(out_path)]
    print("[vj] montando el mix (sin recodificar)…", flush=True)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        listing.unlink(missing_ok=True)
    if res.returncode != 0:
        raise MixError("ffmpeg no pudo montar el mix: " + res.stderr.strip()[-500:])
    print(f"[vj] listo → {out_path}")
    return out_path


def _esc(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def prune_cache(cache: Path, days: float = 14) -> None:
    """Las piezas del mix pesan: se borran las que nadie ha usado en `days` días."""
    if not cache.exists():
        return
    limit = time.time() - days * 86400
    for f in cache.iterdir():
        try:
            if f.is_file() and f.stat().st_atime < limit and f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vj.mix", description="Monta un vídeo largo con varias escenas y fundidos.")
    ap.add_argument("spec", help="mix.json: {scenes: [config | ruta], output, minutes, scene_minutes, transition}")
    ap.add_argument("-o", "--output", default="renders/mix.mp4")
    ap.add_argument("--cache", default=".studio/mix_cache", help="carpeta de piezas renderizadas (se reutilizan)")
    ap.add_argument("--plan", action="store_true", help="muestra el montaje y sale")
    args = ap.parse_args(argv)
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        base = Path(args.spec).parent
        spec["scenes"] = [json.loads((base / s).read_text(encoding="utf-8")) if isinstance(s, str) else s
                          for s in spec.get("scenes") or []]
        if args.plan:
            s = summary(spec)
            print(f"[vj] {s['duration'] / 60:.2f} min · {s['blocks']} bloques · se renderizan {s['render_frames']} frames")
            for b in s["timeline"]:
                print(f"[vj]   {b['start'] / 60:6.2f} min  escena {b['scene'] + 1}  ×{b['plays']}")
            return 0
        prune_cache(Path(args.cache))
        render_mix(spec, Path(args.output), Path(args.cache))
        return 0
    except (ConfigError, MixError, ValueError, OSError) as e:
        print(f"[vj] error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
