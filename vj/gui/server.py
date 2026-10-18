"""Servidor local de la interfaz: python -m vj.gui  (abre el navegador solo).

Solo escucha en 127.0.0.1. Lee y guarda configs dentro de configs/ y deja los
renders en renders/ del repositorio.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import ConfigError, config_from_dict, layers_of
from ..encoder import CONTAINER
from ..loop import plan_loop
from . import schema
from .worker import PreviewEngine, RenderQueue

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
RENDERS = ROOT / "renders"
STATIC = Path(__file__).resolve().parent / "static"


def inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def list_configs() -> list[dict]:
    out = []
    for p in sorted(CONFIGS.rglob("*.json")):
        rel = p.relative_to(CONFIGS)
        group = rel.parts[0] if len(rel.parts) > 1 else "básicas"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            patterns = [l["pattern"] for l in layers_of({"geometry": {"pattern": "?"}, **data})] \
                if "layers" in data or "geometry" in data else []
        except (json.JSONDecodeError, KeyError):
            patterns = []
        out.append({"path": str(rel), "name": p.stem, "group": group, "patterns": patterns})
    return out


def plan_summary(user_cfg: dict) -> dict:
    cfg = config_from_dict(user_cfg)
    plan = plan_loop(cfg)
    layers = layers_of(cfg)
    for i, layer in enumerate(layers):
        if layer.get("animation"):
            plan.layer_uniforms({**cfg["animation"], **layer["animation"]}, f"capa {i + 1} ({layer['pattern']})",
                                explicit=set(layer["animation"]))
    return {"frames": plan.frames, "duration": plan.duration, "fps": plan.fps,
            "cycles": {"travel": plan.travel, "rotation": plan.rotation, "wobble": plan.wobble,
                       "hue": plan.hue_cycles, "beats": plan.beats},
            "notes": plan.notes, "container": CONTAINER[cfg["output"]["codec"]]}


def reveal(path: Path) -> None:
    """Muestra el archivo en Finder / el explorador de archivos."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.exists() else ["open", str(path.parent)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


class App:
    def __init__(self):
        self.engine = PreviewEngine()
        self.queue = RenderQueue(ROOT)


class Handler(BaseHTTPRequestHandler):
    app: App = None  # se asigna en main()

    def log_message(self, fmt, *args):  # silencio: la interfaz hace muchas peticiones
        pass

    # ---- respuestas ----
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, msg: str, code: int = 400) -> None:
        self._json({"error": msg}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- GET ----
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path == "/api/meta":
                return self._json(schema.meta(self.app.engine.gpu) | {"gpu_error": self.app.engine.error,
                                                                         "root": str(ROOT)})
            if url.path == "/api/configs":
                return self._json(list_configs())
            if url.path == "/api/config":
                p = (CONFIGS / q["path"][0])
                if not inside(p, CONFIGS) or not p.exists():
                    return self._error("config no encontrado", 404)
                return self._json(json.loads(p.read_text(encoding="utf-8")))
            if url.path == "/api/jobs":
                return self._json([j.to_dict() for j in self.app.queue.jobs])
            # Archivos estáticos
            name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            f = STATIC / name
            if inside(f, STATIC) and f.is_file():
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                return self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
            return self._error("no encontrado", 404)
        except Exception as e:
            return self._error(str(e), 500)

    # ---- POST ----
    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._body()
            if url.path == "/api/plan":
                return self._json(plan_summary(body["config"]))
            if url.path == "/api/preview":
                png = self.app.engine.preview(body["config"], float(body.get("phase", 0)),
                                              int(body.get("width", 640)), bool(body.get("hq", False)))
                return self._send(200, png, "image/png")
            if url.path == "/api/flipbook":
                frames = self.app.engine.flipbook(body["config"], int(body.get("frames", 32)),
                                                  int(body.get("width", 400)))
                return self._json({"frames": ["data:image/png;base64," + base64.b64encode(f).decode()
                                              for f in frames]})
            if url.path == "/api/check":
                return self._json(self.app.engine.check(body["config"]))
            if url.path == "/api/save":
                rel = body["path"]
                if not rel.endswith(".json"):
                    rel += ".json"
                p = CONFIGS / rel
                if not inside(p, CONFIGS):
                    return self._error("la ruta debe estar dentro de configs/")
                config_from_dict(body["config"])          # valida antes de escribir
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(body["config"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                return self._json({"path": str(p.relative_to(CONFIGS))})
            if url.path == "/api/render":
                cfg = body["config"]
                config_from_dict(cfg)
                job = self.app.queue.submit(cfg, body["output"], body.get("name", "render"))
                return self._json(job.to_dict())
            if url.path == "/api/cancel":
                return self._json({"ok": self.app.queue.cancel(int(body["id"]))})
            if url.path == "/api/reveal":
                p = Path(body["path"])
                p = p if p.is_absolute() else ROOT / p
                if not (inside(p, RENDERS) or inside(p, CONFIGS)):
                    return self._error("solo se pueden mostrar archivos de renders/ o configs/")
                reveal(p)
                return self._json({"ok": True})
            return self._error("no encontrado", 404)
        except (ConfigError, ValueError, KeyError) as e:
            return self._error(f"{type(e).__name__}: {e}")
        except Exception as e:
            return self._error(f"{type(e).__name__}: {e}", 500)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vj.gui", description="Interfaz web local de vj")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    url = f"http://127.0.0.1:{args.port}/"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        # Ya hay una interfaz abierta en ese puerto (doble clic dos veces): reutilizarla.
        print(f"[vj] la interfaz ya está abierta en {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    Handler.app = App()
    srv.daemon_threads = True
    gpu = Handler.app.engine.gpu if not Handler.app.engine.error else f"sin GPU ({Handler.app.engine.error})"
    print(f"[vj] interfaz en {url}  ·  GPU: {gpu}")
    print("[vj] cierra esta ventana (o Ctrl+C) para salir")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
