"""Trabajo pesado de la interfaz: un hilo con el contexto GL para previsualizar y
colas de trabajos largos (renders completos y versiones largas) en procesos aparte."""
from __future__ import annotations

import concurrent.futures as cf
import itertools
import json
import math
import os
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

import numpy as np

from ..check import measure_loop
from ..config import config_from_dict
from ..loop import plan_loop
from ..renderer import Renderer, create_context

CODE_ROOT = Path(__file__).resolve().parents[2]   # donde vive el paquete vj (para `python -m vj`)

# --------------------------------------------------------------------------- PNG


def encode_png(rgb: np.ndarray) -> bytes:
    """PNG RGB8 mínimo (sin dependencias): filas con filtro 0 + zlib."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --------------------------------------------------------------------------- GPU

INTERACTIVE, BACKGROUND = 0, 1   # prioridades: lo que el usuario está mirando va primero


class PreviewEngine:
    """Un único hilo es dueño del contexto GL: todas las operaciones de GPU pasan por él.

    Las previsualizaciones se piden muy seguido (al mover un slider); si llegan
    varias del mismo tipo (y de la misma persona) mientras la GPU está ocupada,
    solo se atiende la más reciente y las anteriores se cancelan.
    """

    def __init__(self):
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._latest: dict[str, int] = {}
        self._seq = itertools.count()
        ready = threading.Event()
        self.gpu = "?"
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(30)

    def _run(self, ready: threading.Event) -> None:
        try:
            self.ctx = create_context()
            self.gpu = self.ctx.info.get("GL_RENDERER", "?")
        except Exception as e:  # sin GPU utilizable: la interfaz lo muestra
            self.error = str(e)
            ready.set()
            return
        ready.set()
        while True:
            _prio, seq, kind, fn, fut = self._q.get()
            if kind and self._latest.get(kind) != seq:
                fut.cancel()                      # llegó una petición más nueva del mismo tipo
                continue
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(self.ctx))
            except Exception as e:
                fut.set_exception(e)

    def submit(self, fn, kind: str | None = None, prio: int = INTERACTIVE) -> cf.Future:
        fut: cf.Future = cf.Future()
        if self.error:
            fut.set_exception(RuntimeError(self.error))
            return fut
        seq = next(self._seq)
        if kind:
            self._latest[kind] = seq
        self._q.put((prio, seq, kind, fn, fut))
        return fut

    # Tamaño de previsualización respetando la proporción del config.
    @staticmethod
    def _size(cfg: dict, width: int) -> tuple[int, int]:
        out = cfg["output"]
        width = max(64, min(int(width), 1600))
        h = max(2, round(width * out["height"] / out["width"] / 2) * 2)
        return width, h

    @staticmethod
    def _fast(cfg: dict) -> dict:
        cfg["output"]["supersample"] = 1
        cfg["output"]["motion_blur"]["samples"] = 1
        return cfg

    def _frames(self, ctx, user_cfg: dict, phases: list[float], width: int, hq: bool = False) -> list[bytes]:
        cfg = config_from_dict(user_cfg)
        if not hq:
            self._fast(cfg)
        plan = plan_loop(cfg)
        w, h = self._size(cfg, width)
        r = Renderer(cfg, plan, w, h, ctx=ctx)
        try:
            return [encode_png(np.frombuffer(r.render(int(round(p * plan.frames)) % plan.frames), np.uint8)
                               .reshape(h, w, 3)[::-1]) for p in phases]
        finally:
            r.release()

    def preview(self, user_cfg: dict, phase: float, width: int = 640, hq: bool = False, who: str = "") -> bytes:
        return self.submit(lambda ctx: self._frames(ctx, user_cfg, [phase], width, hq)[0],
                           kind=f"preview:{who}").result()

    def flipbook(self, user_cfg: dict, frames: int = 32, width: int = 400, who: str = "") -> list[bytes]:
        frames = max(2, min(int(frames), 120))
        return self.submit(lambda ctx: self._frames(ctx, user_cfg, [k / frames for k in range(frames)], width),
                           kind=f"flipbook:{who}").result()

    def clip(self, user_cfg: dict, width: int = 480, fps: int = 24, who: str = "") -> bytes:
        """El loop completo a velocidad real como MP4 ligero (se repite en el navegador sin salto)."""
        def job(ctx):
            cfg = self._fast(config_from_dict(user_cfg))
            plan = plan_loop(cfg)
            w, h = self._size(cfg, width)
            n = max(2, min(round(plan.duration * fps), 720))
            r = Renderer(cfg, plan, w, h, ctx=ctx)
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "clip.mp4"
                rate = n / plan.duration
                proc = subprocess.Popen(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                     "-s", f"{w}x{h}", "-r", f"{rate:.6f}", "-i", "-", "-vf", "vflip", "-c:v", "libx264",
                     "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                     "-an", str(out)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    for k in range(n):
                        # Fase exacta k/n: n no tiene por qué dividir a plan.frames.
                        proc.stdin.write(r.render(k * plan.frames / n))
                    proc.stdin.close()
                    err = proc.stderr.read().decode(errors="replace")
                    if proc.wait() != 0:
                        raise RuntimeError(f"ffmpeg: {err.strip()[-300:]}")
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    r.release()
                return out.read_bytes()
        return self.submit(job, kind=f"clip:{who}").result()

    def thumbnails(self, cfgs: list[dict], width: int = 320, phase: float = 0.3, who: str = "") -> list[bytes]:
        """Una imagen por config (variaciones). Un fallo en una no tumba las demás."""
        def job(ctx):
            out = []
            for c in cfgs:
                try:
                    out.append(self._frames(ctx, c, [phase], width)[0])
                except Exception:
                    out.append(b"")
            return out
        return self.submit(job, kind=f"variations:{who}").result()

    def thumbnail(self, user_cfg: dict, width: int = 256) -> bytes:
        return self.submit(lambda ctx: self._frames(ctx, user_cfg, [0.3], width)[0], prio=BACKGROUND).result()

    def check(self, user_cfg: dict) -> dict:
        def job(ctx):
            cfg = config_from_dict(user_cfg)
            cfg["output"]["supersample"] = 1
            plan = plan_loop(cfg)
            w, h = self._size(cfg, 480)
            r = Renderer(cfg, plan, w, h, ctx=ctx)
            try:
                return measure_loop(r)
            finally:
                r.release()
        return self.submit(job).result()


# --------------------------------------------------------------------------- utilidades de vídeo


def probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(path)], capture_output=True, text=True, timeout=20).stdout.strip()
        return float(out)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None


def video_thumbnail(src: Path, dst: Path, width: int = 480) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale={width}:-2", "-q:v", "4", str(dst)], capture_output=True, timeout=60)
    return r.returncode == 0 and dst.exists()


# --------------------------------------------------------------------------- trabajos


ACTIVE = ("en cola", "renderizando", "cancelando")


class Job:
    _ids = itertools.count(1)

    def __init__(self, kind: str, name: str, owner: str, output: Path, cfg: dict | None = None,
                 source: Path | None = None, minutes: float | None = None):
        self.id = next(self._ids)
        self.kind = kind                  # "render" | "extend"
        self.name = name
        self.owner = owner
        self.cfg = cfg
        self.output = output
        self.source = source
        self.minutes = minutes
        self.state = "en cola"
        self.frame = 0
        self.total = 0
        self.fps = 0.0
        self.eta = None
        self.encoder = ""
        self.log: list[str] = []
        self.created = time.time()
        self.started = None
        self.finished = None
        self.proc: subprocess.Popen | None = None

    FIELDS = ("id", "kind", "name", "owner", "state", "frame", "total", "fps", "eta", "encoder",
              "created", "started", "finished", "minutes")

    def to_dict(self, with_cfg: bool = False) -> dict:
        d = {k: getattr(self, k) for k in self.FIELDS} | {
            "output": str(self.output), "source": str(self.source) if self.source else None, "log": self.log[-12:]}
        if with_cfg:
            d["cfg"] = self.cfg
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        job = cls.__new__(cls)
        for k in cls.FIELDS:
            setattr(job, k, d.get(k))
        job.output = Path(d["output"])
        job.source = Path(d["source"]) if d.get("source") else None
        job.cfg = d.get("cfg")
        job.log = d.get("log", [])
        job.proc = None
        if job.state in ACTIVE:                 # el servidor se cerró a mitad de trabajo
            job.state = "interrumpido"
        return job


class RenderQueue:
    """Renders completos de uno en uno, cada uno en su propio proceso `python -m vj`
    (la GPU queda libre para las previsualizaciones y un fallo no tumba la interfaz).
    Las versiones largas (copiar el loop N veces con ffmpeg, sin recodificar) van
    por otra cola: no esperan a que termine un render de una hora."""

    HISTORY = 300

    def __init__(self, workdir: Path, studio: Path):
        self.workdir = workdir
        self.studio = studio
        self.history_file = studio / "jobs.json"
        self.jobs: list[Job] = self._load()
        if self.jobs:
            Job._ids = itertools.count(max(j.id for j in self.jobs) + 1)
        self._lock = threading.Lock()
        self._queues = {"render": queue.Queue(), "extend": queue.Queue()}
        for kind, q in self._queues.items():
            threading.Thread(target=self._run, args=(q,), daemon=True).start()

    # ---- historial persistente
    def _load(self) -> list[Job]:
        try:
            return [Job.from_dict(d) for d in json.loads(self.history_file.read_text(encoding="utf-8"))]
        except (OSError, ValueError, KeyError):
            return []

    def _save(self) -> None:
        with self._lock:
            done = [j for j in self.jobs if j.state not in ACTIVE][-self.HISTORY:]
            data = [j.to_dict(with_cfg=True) for j in done]
        tmp = self.history_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.history_file)

    # ---- consultas
    def visible(self, user) -> list[Job]:
        return [j for j in self.jobs if user.admin or j.owner == user.name]

    def get(self, job_id: int) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def active_count(self, owner: str, kind: str = "render") -> int:
        return sum(1 for j in self.jobs if j.owner == owner and j.kind == kind and j.state in ACTIVE)

    def busy(self, path: Path) -> bool:
        p = path.resolve()
        return any(j.state in ACTIVE and (j.output.resolve() == p or (j.source and j.source.resolve() == p))
                   for j in self.jobs)

    def job_for_output(self, path: Path) -> Job | None:
        p = path.resolve()
        for j in reversed(self.jobs):
            if j.state == "listo" and j.output.resolve() == p:
                return j
        return None

    # ---- alta / baja
    def _add(self, job: Job) -> Job:
        with self._lock:
            self.jobs.append(job)
        self._queues[job.kind].put(job)
        return job

    def submit(self, cfg: dict, output: Path, name: str, owner: str) -> Job:
        return self._add(Job("render", name, owner, output, cfg=cfg))

    def extend(self, source: Path, output: Path, minutes: float, owner: str, cfg: dict | None) -> Job:
        return self._add(Job("extend", f"{source.stem} · {minutes:g} min", owner, output, cfg=cfg,
                             source=source, minutes=minutes))

    def cancel(self, job: Job) -> None:
        if job.state == "en cola":
            job.state = "cancelado"
            job.finished = time.time()
            self._save()
        elif job.proc and job.proc.poll() is None:
            job.state = "cancelando"
            job.proc.terminate()

    def forget(self, job: Job) -> None:
        if job.state not in ACTIVE:
            with self._lock:
                self.jobs.remove(job)
            self._save()

    # ---- ejecución
    def _run(self, q: queue.Queue) -> None:
        while True:
            job = q.get()
            if job.state == "cancelado":
                continue
            job.state = "renderizando"
            job.started = time.time()
            try:
                code = self._render(job) if job.kind == "render" else self._extend(job)
            except Exception as e:      # no debería pasar, pero el hilo no puede morir
                job.log.append(f"{type(e).__name__}: {e}")
                code = 1
            job.finished = time.time()
            if job.state == "cancelando":
                job.state = "cancelado"
                job.output.unlink(missing_ok=True)        # archivo a medias: no sirve
            else:
                job.state = "listo" if code == 0 else "error"
            self._save()

    def _render(self, job: Job) -> int:
        tmp = self.studio / "jobs"
        tmp.mkdir(parents=True, exist_ok=True)
        cfg_file = tmp / f"job_{job.id}.json"
        cfg_file.write_text(json.dumps(job.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        job.output.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-u", "-m", "vj", str(cfg_file), "-o", str(job.output)]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        try:
            job.proc = subprocess.Popen(cmd, cwd=self.workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, env=env)   # text=True: '\r' también corta líneas
            for line in job.proc.stdout:
                self._parse(job, line.strip())
            return job.proc.wait()
        finally:
            cfg_file.unlink(missing_ok=True)

    def _extend(self, job: Job) -> int:
        """Repite el loop sin recodificar: minutos de vídeo en segundos y sin pérdida."""
        loop = probe_duration(job.source)
        if not loop:
            job.log.append("no se pudo leer la duración del vídeo")
            return 1
        plays = max(2, math.ceil(job.minutes * 60 / loop - 1e-6))
        job.total = round(plays * loop)
        job.encoder = f"copia ×{plays} (sin recodificar)"
        job.output.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
               "-stream_loop", str(plays - 1), "-i", str(job.source), "-map", "0", "-c", "copy",
               "-movflags", "+faststart", str(job.output)]
        job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        t0 = time.time()
        for line in job.proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") and line[12:].isdigit():
                job.frame = min(job.total, int(line[12:]) // 1_000_000)
                el = time.time() - t0
                if job.frame and el > 0.5:
                    job.fps = job.frame / el            # segundos de vídeo por segundo
                    job.eta = (job.total - job.frame) / job.fps
            elif line and "=" not in line:
                job.log.append(line)
        code = job.proc.wait()
        if code == 0:
            job.frame = job.total
        return code

    @staticmethod
    def _parse(job: Job, line: str) -> None:
        if not line:
            return
        if line.startswith("[vj] frame "):
            # "[vj] frame 120/900  27.41 fps  ETA   1.2 min"
            try:
                parts = line.split()
                job.frame, job.total = (int(x) for x in parts[2].split("/"))
                job.fps = float(parts[3])
                job.eta = float(parts[6]) * 60
            except (ValueError, IndexError):
                pass
            return
        if line.startswith("[vj] encoder:"):
            job.encoder = line.split(":", 1)[1].strip()
        elif line.startswith("[vj] primer frame"):
            job.frame = max(job.frame, 1)
        elif line.startswith("[vj] ") and "frames (" in line and not job.total:
            try:   # "[vj] hex_tunnel · 3840x2160 @ 60fps · 960 frames (16.000s) · ..."
                job.total = int(line.split(" frames (")[0].rsplit(" ", 1)[1])
            except (ValueError, IndexError):
                pass
        job.log.append(line)
