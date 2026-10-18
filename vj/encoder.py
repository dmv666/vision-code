"""Codificación con ffmpeg vía pipe (los frames nunca tocan el disco)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

H264_CRF = {"draft": 23, "high": 16, "master": 10}
NVENC_CQ = {"draft": 28, "high": 19, "master": 14}
PRORES_PROFILES = {"proxy": 0, "lt": 1, "standard": 2, "hq": 3, "4444": 4}


def codec_args(codec: str, quality: str, fps: int) -> list[str]:
    gop = str(fps)  # un keyframe por segundo: seek ágil en software de VJ
    if codec == "h264":
        crf = H264_CRF.get(quality, 16)
        return ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-g", gop, "-movflags", "+faststart"]
    if codec == "h264_nvenc":
        cq = NVENC_CQ.get(quality, 19)
        return ["-c:v", "h264_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", str(cq), "-b:v", "0",
                "-pix_fmt", "yuv420p", "-profile:v", "high", "-g", gop, "-movflags", "+faststart"]
    if codec == "prores":
        profile = PRORES_PROFILES.get(quality, 3)
        pix = "yuva444p10le" if profile == 4 else "yuv422p10le"
        return ["-c:v", "prores_ks", "-profile:v", str(profile), "-pix_fmt", pix,
                "-vendor", "apl0", "-bits_per_mb", "8000"]
    raise ValueError(codec)


def resolve_output_path(path: str, codec: str) -> Path:
    p = Path(path)
    if codec == "prores" and p.suffix.lower() != ".mov":
        new = p.with_suffix(".mov")
        print(f"[vj] ProRes no es estándar en MP4 → se usa contenedor MOV: {new}", file=sys.stderr)
        p = new
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class FFmpegWriter:
    def __init__(self, path: Path, width: int, height: int, fps: int, codec: str, quality: str):
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg no encontrado en PATH")
        self.cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
            "-i", "-",
            "-vf", "vflip",  # OpenGL lee de abajo hacia arriba
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            *codec_args(codec, quality, fps),
            "-an", str(path),
        ]
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE)

    def write(self, frame: bytes) -> None:
        self.proc.stdin.write(frame)

    def close(self) -> None:
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg terminó con código {self.proc.returncode}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.close()
        else:
            self.proc.kill()


def save_png(path: Path, frame: bytes, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{width}x{height}", "-i", "-", "-vf", "vflip", "-frames:v", "1", str(path)],
        input=frame, check=True,
    )
