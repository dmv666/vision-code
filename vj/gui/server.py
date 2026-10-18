"""Servidor de Prism Loops Studio: python -m vj.gui  (abre el navegador solo).

Por defecto solo escucha en 127.0.0.1 (uso personal, sin login). Con --share
escucha en la red local: cada persona entra con su nombre y el código de
acceso, guarda sus escenas en configs/users/<nombre>/ y sus vídeos en
renders/<nombre>/, con límites de resolución/duración configurables.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..config import ConfigError, config_from_dict, layers_of
from ..encoder import CONTAINER
from ..loop import plan_loop
from . import generator, schema
from .auth import COOKIE, LOCAL, SESSION_DAYS, Auth, AuthError, Limits, User
from .worker import CODE_ROOT, PreviewEngine, RenderQueue, probe_duration, video_thumbnail

STATIC = Path(__file__).resolve().parent / "static"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
MAX_BODY = 4 << 20
SAFE_NAME = re.compile(r"[^A-Za-z0-9_\-]+")


def inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def safe_name(s: str, fallback: str = "loop") -> str:
    return SAFE_NAME.sub("_", s).strip("_")[:60] or fallback


class HTTPError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# --------------------------------------------------------------------------- espacio de trabajo


class Workspace:
    """Carpeta con configs/ y renders/. Por defecto el propio repositorio; con
    --workspace otra carpeta (Docker, un disco externo...), que se siembra con las
    escenas de ejemplo la primera vez."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.configs = self.root / "configs"
        self.renders = self.root / "renders"
        self.studio = self.root / ".studio"
        if not self.configs.exists() and (CODE_ROOT / "configs").exists() and self.root != CODE_ROOT:
            shutil.copytree(CODE_ROOT / "configs", self.configs)
        for d in (self.configs, self.renders, self.studio):
            d.mkdir(parents=True, exist_ok=True)

    # ---- permisos
    def user_configs(self, user: User) -> Path:
        return self.configs / "users" / user.name

    def user_renders(self, user: User) -> Path:
        return self.renders if user.admin else self.renders / user.name

    def can_read_config(self, user: User, p: Path) -> bool:
        if not inside(p, self.configs):
            return False
        if user.admin or not inside(p, self.configs / "users"):
            return True
        return inside(p, self.user_configs(user))

    def can_write_config(self, user: User, p: Path) -> bool:
        return inside(p, self.configs) if user.admin else inside(p, self.user_configs(user))

    def can_touch_render(self, user: User, p: Path) -> bool:
        return inside(p, self.user_renders(user)) and not inside(p, self.studio)

    # ---- listados
    def list_configs(self, user: User) -> list[dict]:
        out = []
        for p in sorted(self.configs.rglob("*.json")):
            if not self.can_read_config(user, p):
                continue
            rel = p.relative_to(self.configs)
            if rel.parts[0] == "users":
                owner = rel.parts[1] if len(rel.parts) > 2 else ""
                group = "mis escenas" if owner == user.name else f"usuarios · {owner}"
            else:
                group = rel.parts[0] if len(rel.parts) > 1 else "básicas"
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                patterns = [l["pattern"] for l in layers_of({"geometry": {"pattern": "?"}, **data})] \
                    if "layers" in data or "geometry" in data else []
            except (json.JSONDecodeError, KeyError, TypeError):
                patterns = []
            out.append({"path": str(rel), "name": p.stem, "group": group, "patterns": patterns,
                        "mtime": int(p.stat().st_mtime), "writable": self.can_write_config(user, p)})
        out.sort(key=lambda c: (c["group"] != "mis escenas", c["group"] == "básicas", c["group"], c["name"]))
        return out

    def list_renders(self, user: User, queue: RenderQueue) -> list[dict]:
        base = self.user_renders(user)
        if not base.exists():
            return []
        out = []
        for p in base.rglob("*"):
            if p.suffix.lower() not in VIDEO_EXT or not p.is_file() or inside(p, self.studio) \
                    or any(part.startswith(".") for part in p.relative_to(self.renders).parts):
                continue
            if queue.busy(p):
                continue
            rel = p.relative_to(self.renders)
            st = p.stat()
            job = queue.job_for_output(p)
            out.append({"path": str(rel), "name": p.name, "size": st.st_size, "mtime": int(st.st_mtime),
                        "owner": job.owner if job else (rel.parts[0] if len(rel.parts) > 1 else "local"),
                        "has_config": bool(job and job.cfg), "kind": job.kind if job else "render",
                        "minutes": job.minutes if job else None})
        out.sort(key=lambda r: -r["mtime"])
        return out


# --------------------------------------------------------------------------- app


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
    def __init__(self, ws: Workspace, auth: Auth, limits: Limits, bind: str, port: int, scheme: str = "http"):
        self.ws = ws
        self.scheme = scheme
        self.auth = auth
        self.limits = limits
        self.bind = bind
        self.port = port
        self.engine = PreviewEngine()
        self.queue = RenderQueue(CODE_ROOT, ws.studio)
        self.thumb_lock = threading.Lock()

    def checked(self, user: User, user_cfg: dict) -> dict:
        """Valida el config y aplica los límites del servidor a los invitados."""
        if not isinstance(user_cfg, dict):
            raise ConfigError("el config debe ser un objeto JSON")
        cfg = config_from_dict(user_cfg)
        if not user.admin:
            self.limits.enforce(cfg)
        return cfg


# --------------------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    app: App = None  # se asigna en main()
    protocol_version = "HTTP/1.1"
    server_version = "PrismLoopsStudio"

    def log_message(self, fmt, *args):  # silencio: la interfaz hace muchas peticiones
        pass

    # ---- respuestas
    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200, headers: dict | None = None) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                   headers)

    def _error(self, msg: str, code: int = 400) -> None:
        self._json({"error": msg}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise HTTPError(413, "petición demasiado grande")
        data = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(data, dict):
            raise HTTPError(400, "se esperaba un objeto JSON")
        return data

    # ---- seguridad
    def _host_ok(self) -> bool:
        """Contra DNS rebinding: en modo local solo se aceptan nombres locales."""
        if self.app.auth.shared:
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    PROXY_HEADERS = ("X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP")

    def _client_ip(self) -> str:
        # Detrás de un túnel o proxy (cloudflared, ngrok, nginx...) todas las
        # conexiones llegan desde 127.0.0.1: no deben contar como el dueño del equipo.
        if any(self.headers.get(h) for h in self.PROXY_HEADERS):
            return "proxy"
        return self.client_address[0]

    def _user(self) -> User | None:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            token = cookie[COOKIE].value if COOKIE in cookie else None
        except Exception:   # cookie malformada de otra web en el mismo host
            token = None
        return self.app.auth.user_for(self._client_ip(), token)

    def _need_user(self) -> User:
        user = self._user()
        if not user:
            raise HTTPError(401, "inicia sesión")
        return user

    def _cookie(self, value: str, max_age: int) -> dict:
        secure = "; Secure" if isinstance(self.connection, ssl.SSLSocket) else ""
        return {"Set-Cookie": f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"}

    def _resolve_render(self, user: User, rel: str) -> Path:
        p = (self.app.ws.renders / rel)
        if not self.app.ws.can_touch_render(user, p) or not p.is_file():
            raise HTTPError(404, "vídeo no encontrado")
        return p

    def _resolve_config(self, user: User, rel: str) -> Path:
        p = self.app.ws.configs / rel
        if not self.app.ws.can_read_config(user, p) or not p.is_file():
            raise HTTPError(404, "config no encontrado")
        return p

    # ---- despacho
    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            return self._error("host no permitido", 403)
        url = urlparse(self.path)
        try:
            if method == "POST":
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    raise HTTPError(415, "se esperaba application/json")   # bloquea CSRF con formularios
                return self._post(url)
            return self._get(url)
        except HTTPError as e:
            return self._error(str(e), e.code)
        except AuthError as e:
            return self._error(str(e), 403)
        except (ConfigError, ValueError, KeyError, TypeError) as e:
            return self._error(f"{e}" if isinstance(e, ConfigError) else f"{type(e).__name__}: {e}")
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as e:
            return self._error(f"{type(e).__name__}: {e}", 500)

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    # ---- GET
    def _get(self, url) -> None:
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        app, ws = self.app, self.app.ws
        path = url.path

        if path == "/api/me":
            user = self._user()
            return self._json({
                "user": user.to_dict() if user else None, "shared": app.auth.shared,
                "limits": app.limits.to_dict() if user and not user.admin else None,
                "can_reveal": bool(user and user.admin and user == LOCAL),
                # Al anfitrión se le muestra cómo invitar a otros (direcciones + código).
                "share": {"urls": [f"{app.scheme}://{a}:{app.port}/" for a in lan_addresses()], "code": app.auth.code}
                if app.auth.shared and user == LOCAL else None,
            })
        if not path.startswith("/api/") and not path.startswith("/media/"):
            return self._static(path)

        user = self._need_user()
        if path == "/api/meta":
            return self._json(schema.meta(app.engine.gpu) | {"gpu_error": app.engine.error})
        if path == "/api/configs":
            return self._json(ws.list_configs(user))
        if path == "/api/config":
            return self._json(json.loads(self._resolve_config(user, q["path"]).read_text(encoding="utf-8")))
        if path == "/api/jobs":
            return self._json([self._job_dict(j, user) for j in app.queue.visible(user)])
        if path == "/api/renders":
            return self._json(ws.list_renders(user, app.queue))
        if path == "/api/render-config":
            job = app.queue.job_for_output(self._resolve_render(user, q["path"]))
            if not job or not job.cfg:
                raise HTTPError(404, "no se guardó la configuración de este vídeo")
            return self._json(job.cfg)
        if path == "/api/clip-status":
            return self._json(self._own_clip(user, q.get("id")).to_dict())
        if path == "/api/clip-file":
            job = self._own_clip(user, q.get("id"))
            if job.state != "done" or not job.path.exists():
                raise HTTPError(404, "el pre-render aún no está listo")
            return self._media(job.path, False)
        if path == "/api/thumb":
            return self._thumb(user, q)
        if path.startswith("/media/"):
            return self._media(self._resolve_render(user, unquote(path[len("/media/"):])), q.get("dl") == "1")
        raise HTTPError(404, "no encontrado")

    def _static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        f = STATIC / name
        if not (inside(f, STATIC) and f.is_file()):
            raise HTTPError(404, "no encontrado")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype == "text/javascript":
            ctype = "application/javascript"
        return self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if "text" in ctype or "javascript" in ctype else ""))

    def _thumb(self, user: User, q: dict) -> None:
        """Miniaturas cacheadas en .studio/thumbs (clave = contenido, así se invalidan solas)."""
        ws, cache = self.app.ws, self.app.ws.studio / "thumbs"
        cache.mkdir(parents=True, exist_ok=True)
        if "config" in q:
            src = self._resolve_config(user, q["config"])
            key = hashlib.sha1(src.read_bytes() + b"v1").hexdigest()[:20]
            dst = cache / f"c_{key}.png"
            if not dst.exists():
                png = self.app.engine.thumbnail(json.loads(src.read_text(encoding="utf-8")))
                dst.write_bytes(png)
            ctype = "image/png"
        else:
            src = self._resolve_render(user, q["render"])
            st = src.stat()
            key = hashlib.sha1(f"{src.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:20]
            dst = cache / f"r_{key}.jpg"
            if not dst.exists():
                with self.app.thumb_lock:
                    if not dst.exists() and not video_thumbnail(src, dst):
                        raise HTTPError(404, "sin miniatura")
            ctype = "image/jpeg"
        return self._send(200, dst.read_bytes(), ctype, {"Cache-Control": "private, max-age=86400"})

    def _media(self, p: Path, download: bool) -> None:
        """Sirve vídeos con soporte de Range (necesario para poder saltar en <video>)."""
        size = p.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1
        ctype = {".mov": "video/quicktime", ".webm": "video/webm"}.get(p.suffix.lower(), "video/mp4")
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "private, no-cache")
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(p.name)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with p.open("rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---- POST
    def _post(self, url) -> None:
        app, ws = self.app, self.app.ws
        body = self._body()
        path = url.path

        if path == "/api/login":
            if not app.auth.shared:
                return self._json({"user": LOCAL.to_dict()})
            user = app.auth.login(str(body.get("name", "")), str(body.get("code", "")), self._client_ip())
            return self._json({"user": user.to_dict()},
                              headers=self._cookie(app.auth.issue(user), SESSION_DAYS * 86400))
        if path == "/api/logout":
            return self._json({"ok": True}, headers=self._cookie("", 0))

        user = self._need_user()
        who = user.name
        if path == "/api/plan":
            return self._json(plan_summary(body["config"]))
        if path == "/api/preview":
            png = app.engine.preview(body["config"], float(body.get("phase", 0)), int(body.get("width", 640)),
                                     bool(body.get("hq", False)), who=who)
            return self._send(200, png, "image/png")
        if path == "/api/flipbook":
            frames = app.engine.flipbook(body["config"], int(body.get("frames", 32)), int(body.get("width", 400)),
                                         who=who)
            return self._json({"frames": [_data_url(f) for f in frames]})
        if path == "/api/clip":
            job = app.engine.start_clip(body["config"], str(body.get("quality", "rapida")), ws.studio / "clips", who=who)
            return self._json(job.to_dict())
        if path == "/api/clip-cancel":
            job = self._own_clip(user, body.get("id"))
            job.cancelled = True
            return self._json({"ok": True})
        if path == "/api/check":
            return self._json(app.engine.check(body["config"]))
        if path == "/api/variations":
            return self._variations(user, body)
        if path == "/api/save":
            rel = str(body["path"])
            rel = rel if rel.endswith(".json") else rel + ".json"
            p = (ws.configs / rel) if user.admin else ws.user_configs(user) / Path(rel).name
            if not ws.can_write_config(user, p):
                raise HTTPError(403, "solo puedes guardar en tus escenas")
            if p.exists() and body.get("overwrite") is False:
                raise HTTPError(409, "ya existe una escena con ese nombre")
            config_from_dict(body["config"])          # valida antes de escribir
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(body["config"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return self._json({"path": str(p.relative_to(ws.configs))})
        if path == "/api/delete-config":
            p = self._resolve_config(user, body["path"])
            if not ws.can_write_config(user, p):
                raise HTTPError(403, "no puedes borrar esta escena")
            p.unlink()
            return self._json({"ok": True})
        if path == "/api/render":
            return self._render(user, body)
        if path == "/api/extend":
            return self._extend(user, body)
        if path == "/api/cancel":
            job = self._own_job(user, body)
            app.queue.cancel(job)
            return self._json({"ok": True})
        if path == "/api/forget":
            app.queue.forget(self._own_job(user, body))
            return self._json({"ok": True})
        if path == "/api/delete-render":
            p = self._resolve_render(user, body["path"])
            if app.queue.busy(p):
                raise HTTPError(409, "ese vídeo se está usando en un trabajo")
            p.unlink()
            return self._json({"ok": True})
        if path == "/api/reveal":
            if user != LOCAL:
                raise HTTPError(403, "solo disponible en el equipo donde corre el servidor")
            p = Path(body["path"])
            p = p if p.is_absolute() else ws.root / p
            if not (inside(p, ws.renders) or inside(p, ws.configs)):
                raise HTTPError(400, "solo se pueden mostrar archivos de renders/ o configs/")
            reveal(p)
            return self._json({"ok": True})
        raise HTTPError(404, "no encontrado")

    def _job_dict(self, job, user: User) -> dict:
        """Añade la ruta para la galería (relativa a renders/) si el vídeo ya existe.
        A los invitados no se les muestran rutas del disco del servidor."""
        d = job.to_dict()
        renders = self.app.ws.renders
        rel = str(job.output.resolve().relative_to(renders.resolve())) if inside(job.output, renders) else None
        d["media"] = rel if job.state == "listo" and rel and job.output.exists() else None
        if not user.admin:
            root = str(self.app.ws.root)
            d["output"] = rel or job.output.name
            d["source"] = None
            d["log"] = [line.replace(root + os.sep, "").replace(root, "") for line in d["log"]]
        return d

    def _own_clip(self, user: User, job_id):
        job = self.app.engine.clip_job(int(job_id))
        if not job or not (user.admin or job.who == user.name):
            raise HTTPError(404, "pre-render no encontrado")
        return job

    def _own_job(self, user: User, body: dict):
        job = self.app.queue.get(int(body["id"]))
        if not job or not (user.admin or job.owner == user.name):
            raise HTTPError(404, "trabajo no encontrado")
        return job

    def _output_path(self, user: User, requested: str, codec: str) -> Path:
        ext = CONTAINER[codec]
        ws = self.app.ws
        if user.admin:
            p = Path(requested or "renders/loop")
            p = p if p.is_absolute() else ws.root / p
            return p.with_suffix(ext)   # el contenedor lo decide el codec (ProRes → .mov)
        # Invitados: solo un nombre, dentro de renders/<nombre>/ y sin pisar archivos.
        base = safe_name(Path(requested or "loop").stem)
        out = ws.user_renders(user) / f"{base}{ext}"
        k = 2
        while out.exists() or self.app.queue.busy(out):
            out = ws.user_renders(user) / f"{base}_{k}{ext}"
            k += 1
        return out

    def _render(self, user: User, body: dict) -> None:
        app = self.app
        cfg = app.checked(user, body["config"])
        if not user.admin and app.queue.active_count(user.name) >= app.limits.max_jobs:
            raise HTTPError(429, f"ya tienes {app.limits.max_jobs} renders en cola; espera a que termine alguno")
        out = self._output_path(user, str(body.get("output", "")), cfg["output"]["codec"])
        if app.queue.busy(out):
            raise HTTPError(409, "ya hay un trabajo escribiendo ese archivo")
        job = app.queue.submit(body["config"], out, safe_name(str(body.get("name", "render")), "render"), user.name)
        return self._json(self._job_dict(job, user))

    def _extend(self, user: User, body: dict) -> None:
        app = self.app
        src = self._resolve_render(user, body["path"])
        minutes = float(body["minutes"])
        top = 600 if user.admin else app.limits.max_extend_minutes
        if not 1 <= minutes <= top:
            raise HTTPError(400, f"la duración debe estar entre 1 y {top} minutos")
        if not user.admin and app.queue.active_count(user.name, "extend") >= 1:
            raise HTTPError(429, "ya tienes una versión larga en curso")
        tag = f"{minutes:g}min".replace(".", "_")
        out = src.with_name(f"{src.stem}_{tag}{src.suffix}")
        if app.queue.busy(out):
            raise HTTPError(409, "ya se está generando esa versión")
        origin = app.queue.job_for_output(src)
        job = app.queue.extend(src, out, minutes, user.name, origin.cfg if origin else None)
        return self._json(self._job_dict(job, user))

    def _variations(self, user: User, body: dict) -> None:
        app = self.app
        n = max(1, min(int(body.get("count", 6)), 9))
        seed = int(body.get("seed", time.time_ns() % (1 << 30)))
        if body.get("mode") == "surprise":
            bases = []
            for c in app.ws.list_configs(user):
                try:
                    bases.append(json.loads((app.ws.configs / c["path"]).read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    pass
            keep = body.get("config", {}).get("output")
            cfgs = [generator.surprise(bases, keep, seed + i) for i in range(n)]
        else:
            config_from_dict(body["config"])
            cfgs = [generator.vary(body["config"], float(body.get("amount", 0.35)), seed + i) for i in range(n)]
        imgs = app.engine.thumbnails(cfgs, int(body.get("width", 320)), who=user.name)
        return self._json({"items": [{"config": c, "image": _data_url(i) if i else None}
                                     for c, i in zip(cfgs, imgs)]})


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


# --------------------------------------------------------------------------- arranque


def lan_addresses() -> list[str]:
    ips = []
    try:   # truco UDP: no envía nada, solo pregunta qué interfaz usaría
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    host = socket.gethostname()
    if sys.platform == "darwin" and not host.endswith(".local"):
        host += ".local"
    return [ip for ip in ips if not ip.startswith("127.")] + [host]


def parse_res(s: str) -> int:
    named = {"720p": 1280 * 720, "1080p": 1920 * 1080, "1440p": 2560 * 1440, "4k": 3840 * 2160, "8k": 7680 * 4320}
    if s.lower() in named:
        return named[s.lower()]
    w, h = s.lower().split("x")
    return int(w) * int(h)


def main(argv=None) -> int:
    env = os.environ.get
    ap = argparse.ArgumentParser(prog="vj.gui", description="Prism Loops Studio: interfaz web de vj")
    ap.add_argument("--port", type=int, default=int(env("PRISM_PORT", 8765)))
    ap.add_argument("--share", action="store_true", default=env("PRISM_SHARE") == "1",
                    help="escucha en la red local para que otras personas entren con un código de acceso")
    ap.add_argument("--host", help="dirección donde escuchar (por defecto 127.0.0.1, o 0.0.0.0 con --share)")
    ap.add_argument("--code", default=env("PRISM_CODE"), help="código de acceso para invitados (si no, se genera uno)")
    ap.add_argument("--admin-code", default=env("PRISM_ADMIN_CODE"),
                    help="código que da permisos de administrador desde otros equipos")
    ap.add_argument("--require-login", action="store_true", default=env("PRISM_REQUIRE_LOGIN") == "1",
                    help="pide login también desde este equipo (útil detrás de un proxy)")
    ap.add_argument("--workspace", default=env("PRISM_WORKSPACE"),
                    help="carpeta con configs/ y renders/ (por defecto, la del proyecto)")
    ap.add_argument("--max-res", default=env("PRISM_MAX_RES", "4k"), help="resolución máxima para invitados: 1080p, 1440p, 4k o 2560x1440")
    ap.add_argument("--max-duration", type=float, default=float(env("PRISM_MAX_DURATION", 120)),
                    help="duración máxima del loop para invitados (s)")
    ap.add_argument("--max-jobs", type=int, default=int(env("PRISM_MAX_JOBS", 2)),
                    help="renders simultáneos en cola por invitado")
    ap.add_argument("--cert", help="certificado TLS (PEM) para servir por HTTPS")
    ap.add_argument("--key", help="clave privada TLS (PEM)")
    ap.add_argument("--no-browser", action="store_true", default=env("PRISM_NO_BROWSER") == "1")
    args = ap.parse_args(argv)

    shared = args.share or (args.host not in (None, "127.0.0.1", "localhost", "::1"))
    bind = args.host or ("0.0.0.0" if shared else "127.0.0.1")
    scheme = "https" if args.cert else "http"
    local_url = f"{scheme}://127.0.0.1:{args.port}/"

    try:
        srv = ThreadingHTTPServer((bind, args.port), Handler)
    except OSError:
        # Ya hay una interfaz abierta en ese puerto (doble clic dos veces): reutilizarla.
        print(f"[vj] la interfaz ya está abierta en {local_url}")
        if not args.no_browser:
            webbrowser.open(local_url)
        return 0
    if args.cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.cert, args.key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)

    ws = Workspace(Path(args.workspace).expanduser() if args.workspace else CODE_ROOT)
    auth = Auth(ws.studio, shared, args.code, args.admin_code, local_admin=not args.require_login)
    limits = Limits(max_pixels=parse_res(args.max_res), max_duration=args.max_duration, max_jobs=args.max_jobs)
    Handler.app = App(ws, auth, limits, bind, args.port, scheme)
    srv.daemon_threads = True

    engine = Handler.app.engine
    gpu = engine.gpu if not engine.error else f"sin GPU ({engine.error})"
    print(f"[vj] Prism Loops Studio  ·  GPU: {gpu}")
    print(f"[vj] en este equipo:   {local_url}")
    if shared:
        for addr in lan_addresses():
            print(f"[vj] en la red:        {scheme}://{addr}:{args.port}/")
        print(f"[vj] código de acceso: {auth.code}")
        if args.admin_code:
            print("[vj] código de administrador configurado")
    print(f"[vj] carpeta de trabajo: {ws.root}")
    print("[vj] cierra esta ventana (o Ctrl+C) para salir")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(local_url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
