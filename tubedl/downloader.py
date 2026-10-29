"""Lógica de descarga sobre yt-dlp: info de un enlace y cola de trabajos con progreso."""
from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

AUDIO_FORMATS = ("mp3", "m4a", "opus", "wav")
VIDEO_QUALITIES = ("best", "2160", "1440", "1080", "720", "480", "360")


class DownloadError(Exception):
    pass


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _base_opts() -> dict:
    return {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True}


def fetch_info(url: str) -> dict:
    """Título, miniatura, duración y alturas de vídeo disponibles."""
    try:
        with yt_dlp.YoutubeDL(_base_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_clean(str(e))) from None
    if info.get("_type") == "playlist":
        raise DownloadError("Es una lista de reproducción; pega el enlace de un solo vídeo.")
    heights = sorted({f["height"] for f in info.get("formats", [])
                      if f.get("height") and f.get("vcodec") not in (None, "none")}, reverse=True)
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "heights": heights,
    }


def _clean(msg: str) -> str:
    msg = msg.replace("ERROR: ", "").split("\n")[0]
    msg = msg.split("; please report this issue")[0].split(" (caused by ")[0]
    return re.sub(r"^\[[\w:]+\] [\w-]+: ", "", msg).strip()


@dataclass
class Job:
    url: str
    kind: str          # "audio" | "video"
    option: str        # formato de audio o altura máxima de vídeo
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"   # queued | downloading | processing | done | error
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    title: str = ""
    filename: str = ""
    error: str = ""
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {k: getattr(self, k) for k in (
            "id", "kind", "option", "status", "progress", "speed", "eta",
            "title", "filename", "error", "url")}


class Downloader:
    def __init__(self, out_dir: Path, workers: int = 2):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(workers)

    def submit(self, url: str, kind: str, option: str) -> Job:
        if kind not in ("audio", "video"):
            raise DownloadError("Tipo no válido.")
        if kind == "audio" and option not in AUDIO_FORMATS:
            raise DownloadError("Formato de audio no válido.")
        if kind == "video" and option not in VIDEO_QUALITIES:
            raise DownloadError("Calidad de vídeo no válida.")
        if not has_ffmpeg():
            raise DownloadError("Falta ffmpeg; instálalo para poder unir/convertir archivos.")
        job = Job(url=url, kind=kind, option=option)
        with self.lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def list(self) -> list[dict]:
        with self.lock:
            return [j.public() for j in sorted(self.jobs.values(), key=lambda j: -j.created)]

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def _opts(self, job: Job) -> dict:
        opts = _base_opts() | {
            # cada trabajo trabaja en su propia carpeta y al final se mueve el resultado:
            # así dos descargas del mismo vídeo (p. ej. MP4 y MP3) no se pisan ni se borran
            "paths": {"home": str(self._tmp(job))},
            "outtmpl": "%(title).150B [%(id)s].%(ext)s",
            "restrictfilenames": False,
            "windowsfilenames": True,
            "progress_hooks": [lambda d: self._hook(job, d)],
            "postprocessor_hooks": [lambda d: self._pp_hook(job, d)],
        }
        if job.kind == "audio":
            opts["format"] = "bestaudio/best"
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": job.option}
            if job.option == "mp3":
                pp["preferredquality"] = "0"
            opts["postprocessors"] = [pp, {"key": "FFmpegMetadata"}]
            if job.option in ("mp3", "m4a"):
                opts["writethumbnail"] = True
                opts["postprocessors"].append({"key": "EmbedThumbnail"})
        else:
            h = "" if job.option == "best" else f"[height<={job.option}]"
            opts["format"] = (f"bestvideo{h}[ext=mp4]+bestaudio[ext=m4a]/"
                              f"bestvideo{h}+bestaudio/best{h}/best")
            opts["merge_output_format"] = "mp4"
            opts["postprocessors"] = [{"key": "FFmpegMetadata"}]
        return opts

    def _tmp(self, job: Job) -> Path:
        return self.out_dir / ".tmp" / job.id

    def _hook(self, job: Job, d: dict) -> None:
        if d["status"] == "downloading":
            job.status = "downloading"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                job.progress = min(99.0, 100.0 * d.get("downloaded_bytes", 0) / total)
            job.speed = (d.get("_speed_str") or "").strip()
            job.eta = (d.get("_eta_str") or "").strip()
        elif d["status"] == "finished":
            job.status = "processing"

    def _pp_hook(self, job: Job, d: dict) -> None:
        if d["status"] == "started":
            job.status = "processing"

    def _run(self, job: Job) -> None:
        with self.sem:
            try:
                with yt_dlp.YoutubeDL(self._opts(job)) as ydl:
                    info = ydl.extract_info(job.url, download=True)
                job.title = info.get("title", "")
                path = Path((info.get("requested_downloads") or [{}])[0].get("filepath") or "")
                if not path.is_file():
                    raise DownloadError("No se encontró el archivo descargado.")
                shutil.move(str(path), self.out_dir / path.name)
                job.filename = path.name
                job.progress = 100.0
                job.status = "done"
            except Exception as e:  # yt-dlp lanza varios tipos
                job.error = _clean(str(e)) or "Error desconocido."
                job.status = "error"
            finally:
                shutil.rmtree(self._tmp(job), ignore_errors=True)
