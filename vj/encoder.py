"""Codificación con ffmpeg vía pipe (los frames nunca tocan el disco).

Cada codec tiene una lista de encoders candidatos (hardware primero si se pide).
Antes de renderizar se prueba cada candidato con 2 frames sintéticos a la
resolución real; se usa el primero que funcione. Así un Mac sin motor ProRes,
o un ffmpeg compilado sin VideoToolbox, cae al encoder por software en lugar de
fallar a mitad de un render de una hora.
"""
from __future__ import annotations

import queue
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

H264_CRF = {"draft": 23, "high": 16, "master": 10}
X265_CRF = {"draft": 26, "high": 18, "master": 12}
NVENC_CQ = {"draft": 28, "high": 19, "master": 14}
# Bits por píxel y frame para encoders por bitrate (VideoToolbox).
# 4K60 "high" ≈ 3840·2160·60·0.12 ≈ 60 Mbps.
BPP = {"draft": 0.05, "high": 0.12, "master": 0.22}
PRORES_PROFILES = ["proxy", "lt", "standard", "hq", "4444", "xq"]

CODECS = {"h264", "hevc", "prores"}
CONTAINER = {"h264": ".mp4", "hevc": ".mp4", "prores": ".mov"}


@dataclass
class Encoder:
    name: str           # nombre del encoder de ffmpeg
    args: list[str]     # argumentos de vídeo
    hardware: bool

    def label(self) -> str:
        return f"{self.name} ({'hardware' if self.hardware else 'software'})"


@lru_cache(maxsize=None)
def available_encoders() -> frozenset[str]:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return frozenset(m.group(1) for m in re.finditer(r"^\s*V\S*\s+(\S+)", out, re.M))


@lru_cache(maxsize=None)
def supported_pix_fmts(encoder: str) -> tuple[str, ...]:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-h", f"encoder={encoder}"],
                         capture_output=True, text=True).stdout
    m = re.search(r"Supported pixel formats:\s*(.+)", out)
    return tuple(m.group(1).split()) if m else ()


def pick_pix_fmt(encoder: str, preferred: list[str]) -> str | None:
    supported = supported_pix_fmts(encoder)
    for fmt in preferred:
        if fmt in supported:
            return fmt
    return None


def prores_profile(quality: str) -> str:
    return quality if quality in PRORES_PROFILES else "hq"


def candidates(codec: str, quality: str, width: int, height: int, fps: int, hardware: bool) -> list[Encoder]:
    gop = ["-g", str(fps)]  # un keyframe por segundo: seek ágil en software de VJ
    mp4 = ["-movflags", "+faststart"]
    bitrate = f"{max(2, round(width * height * fps * BPP.get(quality, 0.12) / 1e6))}M"
    vt_rate = ["-b:v", bitrate]
    hw: list[Encoder] = []
    sw: list[Encoder] = []

    if codec == "h264":
        if sys.platform == "darwin":
            hw.append(Encoder("h264_videotoolbox", [
                "-c:v", "h264_videotoolbox", *vt_rate, "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-realtime", "0", "-allow_sw", "0", *gop, *mp4], True))
        hw.append(Encoder("h264_nvenc", [
            "-c:v", "h264_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", str(NVENC_CQ.get(quality, 19)),
            "-b:v", "0", "-pix_fmt", "yuv420p", "-profile:v", "high", *gop, *mp4], True))
        sw.append(Encoder("libx264", [
            "-c:v", "libx264", "-preset", "slow", "-crf", str(H264_CRF.get(quality, 16)),
            "-pix_fmt", "yuv420p", "-profile:v", "high", *gop, *mp4], False))

    elif codec == "hevc":
        # 10 bits: casi elimina el banding en degradados oscuros. hvc1 = compatible con QuickTime.
        if sys.platform == "darwin":
            hw.append(Encoder("hevc_videotoolbox", [
                "-c:v", "hevc_videotoolbox", *vt_rate, "-profile:v", "main10", "-pix_fmt", "p010le",
                "-realtime", "0", "-allow_sw", "0", "-tag:v", "hvc1", *gop, *mp4], True))
            hw.append(Encoder("hevc_videotoolbox", [
                "-c:v", "hevc_videotoolbox", *vt_rate, "-profile:v", "main", "-pix_fmt", "yuv420p",
                "-realtime", "0", "-allow_sw", "0", "-tag:v", "hvc1", *gop, *mp4], True))
        hw.append(Encoder("hevc_nvenc", [
            "-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", str(NVENC_CQ.get(quality, 19)),
            "-b:v", "0", "-profile:v", "main10", "-pix_fmt", "p010le", "-tag:v", "hvc1", *gop, *mp4], True))
        sw.append(Encoder("libx265", [
            "-c:v", "libx265", "-preset", "medium", "-crf", str(X265_CRF.get(quality, 18)),
            "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1", "-x265-params", f"keyint={fps}:log-level=error",
            *mp4], False))

    elif codec == "prores":
        profile = prores_profile(quality)
        alpha = profile in {"4444", "xq"}
        if sys.platform == "darwin":
            # Motor ProRes por hardware: M1 Pro/Max/Ultra, M2 y posteriores.
            pref = ["ayuv64le", "yuva444p16le", "p416le", "yuv444p10le"] if alpha else \
                   ["p210le", "yuv422p10le", "p216le", "p010le"]
            fmt = pick_pix_fmt("prores_videotoolbox", pref) if "prores_videotoolbox" in available_encoders() else None
            if fmt:
                hw.append(Encoder("prores_videotoolbox", [
                    "-c:v", "prores_videotoolbox", "-profile:v", profile, "-pix_fmt", fmt], True))
        ks_profile = {"proxy": 0, "lt": 1, "standard": 2, "hq": 3, "4444": 4, "xq": 5}[profile]
        sw.append(Encoder("prores_ks", [
            "-c:v", "prores_ks", "-profile:v", str(ks_profile),
            "-pix_fmt", "yuva444p10le" if alpha else "yuv422p10le", "-vendor", "apl0"], False))
    else:
        raise ValueError(codec)

    return (hw + sw) if hardware else sw


def probe(enc: Encoder, width: int, height: int, fps: int) -> bool:
    if enc.name not in available_encoders():
        return False
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
           "-i", f"testsrc2=s={width}x{height}:r={fps}", "-frames:v", "2", *enc.args, "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def select_encoder(codec: str, quality: str, width: int, height: int, fps: int, hardware: bool) -> Encoder:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg no encontrado en PATH (macOS: brew install ffmpeg)")
    tried = []
    for enc in candidates(codec, quality, width, height, fps, hardware):
        if probe(enc, width, height, fps):
            if tried:
                print(f"[vj] no disponibles: {', '.join(tried)} → usando {enc.label()}", file=sys.stderr)
            return enc
        tried.append(enc.name)
    raise RuntimeError(f"Ningún encoder funcionó para {codec}: {tried}")


def resolve_output_path(path: str, codec: str) -> Path:
    p = Path(path)
    ext = CONTAINER[codec]
    if codec == "prores" and p.suffix.lower() != ".mov":
        print(f"[vj] ProRes no es estándar en MP4 → se usa contenedor MOV", file=sys.stderr)
        p = p.with_suffix(ext)
    elif not p.suffix:
        p = p.with_suffix(ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class FFmpegWriter:
    """Pipe a ffmpeg alimentado desde un hilo: la GPU renderiza el frame i+1
    mientras ffmpeg codifica el frame i."""

    def __init__(self, path: Path, width: int, height: int, fps: int, encoder: Encoder, queue_size: int = 4):
        self.cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
            "-i", "-",
            "-vf", "vflip",  # OpenGL lee de abajo hacia arriba
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            *encoder.args,
            "-an", str(path),
        ]
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE)
        self.queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self) -> None:
        while (frame := self.queue.get()) is not None:
            if self.error:
                continue
            try:
                self.proc.stdin.write(frame)
            except BaseException as e:  # ffmpeg murió: se reporta en el hilo principal
                self.error = e

    def write(self, frame: bytes) -> None:
        if self.error:
            raise RuntimeError(f"ffmpeg dejó de aceptar frames: {self.error}")
        self.queue.put(frame)

    def close(self) -> None:
        self.queue.put(None)
        self.thread.join()
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        if self.proc.wait() != 0 or self.error:
            raise RuntimeError(f"ffmpeg terminó con código {self.proc.returncode}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            self.proc.kill()      # primero matar: desbloquea al hilo si está escribiendo
            self.queue.put(None)
            self.thread.join()


def save_png(path: Path, frame: bytes, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-i", "-", "-vf", "vflip", "-frames:v", "1", str(path)],
        input=frame, check=True,
    )
