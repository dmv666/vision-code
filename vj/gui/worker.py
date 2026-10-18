"""Trabajo pesado de la interfaz: un hilo con el contexto GL para previsualizar y
una cola de renders completos que se ejecutan como procesos aparte."""
from __future__ import annotations

import concurrent.futures as cf
import itertools
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

import numpy as np

from ..check import measure_loop
from ..config import config_from_dict
from ..loop import plan_loop
from ..renderer import Renderer, create_context

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


class PreviewEngine:
    """Un único hilo es dueño del contexto GL: todas las operaciones de GPU pasan por él.

    Las previsualizaciones se piden muy seguido (al mover un slider); si llegan
    varias mientras la GPU está ocupada, solo se atiende la más reciente de cada
    tipo y las anteriores se cancelan.
    """

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
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
            kind, seq, fn, fut = self._q.get()
            if kind and self._latest.get(kind) != seq:
                fut.cancel()                      # llegó una petición más nueva del mismo tipo
                continue
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(self.ctx))
            except Exception as e:
                fut.set_exception(e)

    def submit(self, fn, kind: str | None = None) -> cf.Future:
        fut: cf.Future = cf.Future()
        if self.error:
            fut.set_exception(RuntimeError(self.error))
            return fut
        seq = next(self._seq)
        if kind:
            self._latest[kind] = seq
        self._q.put((kind, seq, fn, fut))
        return fut

    # Tamaño de previsualización respetando la proporción del config.
    @staticmethod
    def _size(cfg: dict, width: int) -> tuple[int, int]:
        out = cfg["output"]
        h = max(2, round(width * out["height"] / out["width"] / 2) * 2)
        return width, h

    def preview(self, user_cfg: dict, phase: float, width: int = 640, hq: bool = False) -> bytes:
        def job(ctx):
            cfg = config_from_dict(user_cfg)
            if not hq:
                cfg["output"]["supersample"] = 1
                cfg["output"]["motion_blur"]["samples"] = 1
            plan = plan_loop(cfg)
            w, h = self._size(cfg, width)
            r = Renderer(cfg, plan, w, h, ctx=ctx)
            try:
                frame = int(round(phase * plan.frames)) % plan.frames
                img = np.frombuffer(r.render(frame), np.uint8).reshape(h, w, 3)[::-1]
                return encode_png(img)
            finally:
                r.release()
        return self.submit(job, kind="preview").result()

    def flipbook(self, user_cfg: dict, frames: int = 32, width: int = 400) -> list[bytes]:
        def job(ctx):
            cfg = config_from_dict(user_cfg)
            cfg["output"]["supersample"] = 1
            cfg["output"]["motion_blur"]["samples"] = 1
            plan = plan_loop(cfg)
            w, h = self._size(cfg, width)
            r = Renderer(cfg, plan, w, h, ctx=ctx)
            try:
                out = []
                for k in range(frames):
                    i = round(k * plan.frames / frames) % plan.frames
                    out.append(encode_png(np.frombuffer(r.render(i), np.uint8).reshape(h, w, 3)[::-1]))
                return out
            finally:
                r.release()
        return self.submit(job, kind="flipbook").result()

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


# --------------------------------------------------------------------------- renders


class Job:
    _ids = itertools.count(1)

    def __init__(self, cfg: dict, output: Path, config_file: Path, name: str):
        self.id = next(self._ids)
        self.name = name
        self.cfg_file = config_file
        self.output = output
        self.state = "en cola"
        self.frame = 0
        self.total = 0
        self.fps = 0.0
        self.eta = None
        self.encoder = ""
        self.log: list[str] = []
        self.started = None
        self.finished = None
        self.proc: subprocess.Popen | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "name", "state", "frame", "total", "fps", "eta",
                                               "encoder", "started", "finished")} | {
            "output": str(self.output), "log": self.log[-12:]}


class RenderQueue:
    """Renders completos de uno en uno, cada uno en su propio proceso `python -m vj`
    (la GPU queda libre para las previsualizaciones y un fallo no tumba la interfaz)."""

    def __init__(self, root: Path):
        self.root = root
        self.jobs: list[Job] = []
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, cfg: dict, output: str, name: str) -> Job:
        tmp = self.root / "renders" / ".jobs"
        tmp.mkdir(parents=True, exist_ok=True)
        out = Path(output)
        if not out.is_absolute():
            out = self.root / out
        job = Job(cfg, out, tmp / f"job_{int(time.time() * 1000)}.json", name)
        job.cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        with self._lock:
            self.jobs.append(job)
        self._q.put(job)
        return job

    def cancel(self, job_id: int) -> bool:
        for job in self.jobs:
            if job.id == job_id:
                if job.state == "en cola":
                    job.state = "cancelado"
                elif job.proc and job.proc.poll() is None:
                    job.state = "cancelando"
                    job.proc.terminate()
                return True
        return False

    def _run(self) -> None:
        while True:
            job = self._q.get()
            if job.state == "cancelado":
                continue
            job.state = "renderizando"
            job.started = time.time()
            cmd = [sys.executable, "-u", "-m", "vj", str(job.cfg_file), "-o", str(job.output)]
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            job.proc = subprocess.Popen(cmd, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, bufsize=1, env=env)   # text=True: '\r' también corta líneas
            for line in job.proc.stdout:
                self._parse(job, line.strip())
            code = job.proc.wait()
            job.finished = time.time()
            if job.state == "cancelando":
                job.state = "cancelado"
            else:
                job.state = "listo" if code == 0 else "error"
            job.cfg_file.unlink(missing_ok=True)

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
        job.log.append(line)
