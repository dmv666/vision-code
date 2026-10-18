"""Usuarios, acceso y límites del modo compartido.

En modo local (por defecto) todo el que llega es el dueño del equipo: no hay
login. Con --share el servidor escucha en la red y cada persona entra con su
nombre y el código de acceso; la sesión es una cookie firmada con HMAC.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import ConfigError
from ..loop import plan_loop

COOKIE = "prism_session"
SESSION_DAYS = 30
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class User:
    name: str
    admin: bool

    def to_dict(self) -> dict:
        return asdict(self)


LOCAL = User("local", admin=True)


@dataclass
class Limits:
    """Lo máximo que puede pedir un invitado (el administrador no tiene límites)."""
    max_pixels: int = 3840 * 2160
    max_duration: float = 120.0
    max_fps: int = 60
    max_supersample: int = 2
    max_blur: int = 4
    max_jobs: int = 2              # renders en cola o en curso por persona
    max_extend_minutes: int = 180

    def to_dict(self) -> dict:
        return asdict(self)

    def enforce(self, cfg: dict) -> None:
        """`cfg` ya combinado con los valores por defecto (config_from_dict)."""
        out = cfg["output"]
        if out["width"] * out["height"] > self.max_pixels:
            raise ConfigError(f"este servidor permite como máximo {self.max_pixels / 1e6:.1f} megapíxeles por frame "
                              f"({out['width']}×{out['height']} = {out['width'] * out['height'] / 1e6:.1f})")
        if out["fps"] > self.max_fps:
            raise ConfigError(f"este servidor permite como máximo {self.max_fps} fps")
        if int(out["supersample"]) > self.max_supersample:
            raise ConfigError(f"este servidor permite supersampling hasta {self.max_supersample}")
        if int(out["motion_blur"]["samples"]) > self.max_blur:
            raise ConfigError(f"este servidor permite hasta {self.max_blur} muestras de motion blur")
        duration = plan_loop(cfg).duration
        if duration > self.max_duration + 1e-6:
            raise ConfigError(f"este servidor permite loops de hasta {self.max_duration:g} s "
                              f"(este dura {duration:.1f} s); para vídeos largos usa «Versión larga»")


def normalize_name(raw: str) -> str:
    """'José Pérez' → 'jose-perez' (sirve como carpeta)."""
    s = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().lower().strip()
    s = re.sub(r"[^a-z0-9_-]+", "-", s).strip("-_")[:24]
    if not NAME_RE.match(s) or s in {"local", "users", "admin"}:
        raise AuthError("Nombre no válido: usa letras y números (p. ej. «maria» o «dj-kilo»)")
    return s


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr.split("%")[0]).is_loopback
    except ValueError:
        return False


class Auth:
    def __init__(self, studio: Path, shared: bool, code: str | None, admin_code: str | None,
                 local_admin: bool = True):
        self.shared = shared
        self.local_admin = local_admin
        self.admin_code = admin_code
        studio.mkdir(parents=True, exist_ok=True)
        self.secret = self._persisted(studio / "secret", lambda: secrets.token_hex(32))
        # Sin --code se reutiliza el último código generado: así no hay que
        # volver a repartirlo cada vez que se reinicia el servidor.
        self.code = code or (self._persisted(studio / "access_code", self._new_code) if shared else None)
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _new_code() -> str:
        alphabet = "abcdefghjkmnpqrstuvwxyz23456789"   # sin 0/o, 1/l/i
        return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))

    @staticmethod
    def _persisted(path: Path, make) -> str:
        if path.exists():
            return path.read_text().strip()
        value = make()
        path.write_text(value + "\n")
        path.chmod(0o600)
        return value

    # ---- cookie firmada: nombre.admin.caducidad.firma
    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, user: User) -> str:
        payload = f"{user.name}.{int(user.admin)}.{int(time.time()) + SESSION_DAYS * 86400}"
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str | None) -> User | None:
        if not token or token.count(".") != 3:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None
        name, admin, exp = payload.split(".")
        if not exp.isdigit() or int(exp) < time.time() or not NAME_RE.match(name):
            return None
        return User(name, admin == "1")

    def user_for(self, client_ip: str, token: str | None) -> User | None:
        if not self.shared or (self.local_admin and is_loopback(client_ip)):
            return LOCAL
        return self.verify(token)

    def login(self, raw_name: str, code: str, client_ip: str) -> User:
        with self._lock:
            now = time.time()
            fails = [t for t in self._fails.get(client_ip, []) if now - t < 600]
            self._fails[client_ip] = fails
            if len(fails) >= 8:
                raise AuthError("Demasiados intentos. Espera unos minutos.")
        code = (code or "").strip().lower()
        admin = bool(self.admin_code) and hmac.compare_digest(code, self.admin_code.lower())
        if not admin and not hmac.compare_digest(code, (self.code or "").lower()):
            with self._lock:
                self._fails[client_ip].append(time.time())
            raise AuthError("Código de acceso incorrecto")
        return User(normalize_name(raw_name), admin)
