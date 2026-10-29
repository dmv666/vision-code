"""Servidor local de Tube Saver: python -m tubedl  (abre el navegador solo).

Solo escucha en 127.0.0.1: es para uso personal en tu equipo.
Los archivos se guardan en ./descargas (cámbialo con --out).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .downloader import AUDIO_FORMATS, VIDEO_QUALITIES, Downloader, DownloadError, fetch_info, has_ffmpeg

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 64 << 10
MEDIA_EXT = {".mp3", ".m4a", ".opus", ".wav", ".mp4", ".webm", ".mkv"}


def make_handler(dl: Downloader):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TubeSaver"

        def log_message(self, fmt, *args):
            pass

        def _json(self, data, status=HTTPStatus.OK):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise DownloadError("Petición demasiado grande.")
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                raise DownloadError("JSON no válido.") from None

        def _file(self, path: Path, attachment: bool):
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            size = path.stat().st_size
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if attachment:
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{quote(path.name)}")
            self.end_headers()
            with path.open("rb") as f:
                while chunk := f.read(1 << 20):
                    self.wfile.write(chunk)

        def _media(self, name: str) -> Path | None:
            p = (dl.out_dir / name).resolve()
            if p.parent != dl.out_dir.resolve() or p.suffix.lower() not in MEDIA_EXT or not p.is_file():
                return None
            return p

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._file(STATIC / "index.html", attachment=False)
            if path == "/api/status":
                return self._json({"ffmpeg": has_ffmpeg(), "out_dir": str(dl.out_dir),
                                   "audio_formats": AUDIO_FORMATS, "video_qualities": VIDEO_QUALITIES})
            if path == "/api/jobs":
                return self._json(dl.list())
            if path == "/api/files":
                files = sorted((p for p in dl.out_dir.iterdir()
                                if p.is_file() and p.suffix.lower() in MEDIA_EXT),
                               key=lambda p: p.stat().st_mtime, reverse=True)
                return self._json([{"name": p.name, "size": p.stat().st_size} for p in files])
            if path.startswith("/files/"):
                p = self._media(unquote(path[len("/files/"):]))
                if p:
                    return self._file(p, attachment=True)
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._body()
                url = str(body.get("url", "")).strip()
                if path in ("/api/info", "/api/download") and not url.startswith(("http://", "https://")):
                    raise DownloadError("Pega un enlace válido (https://…).")
                if path == "/api/info":
                    return self._json(fetch_info(url))
                if path == "/api/download":
                    job = dl.submit(url, str(body.get("kind")), str(body.get("option")))
                    return self._json(job.public())
            except DownloadError as e:
                return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_DELETE(self):
            path = urlparse(self.path).path
            if path.startswith("/files/"):
                p = self._media(unquote(path[len("/files/"):]))
                if p:
                    p.unlink()
                    return self._json({"ok": True})
            self.send_error(HTTPStatus.NOT_FOUND)

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tubedl", description="Descarga audio o vídeo de YouTube.")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--out", type=Path, default=Path("descargas"), help="carpeta de descargas")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    dl = Downloader(args.out.resolve())
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(dl))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[tubedl] Tube Saver en {url}  (descargas en {dl.out_dir})  Ctrl+C para salir")
    if not has_ffmpeg():
        print("[tubedl] aviso: falta ffmpeg; no se podrá convertir audio ni unir vídeo+audio.")
    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
