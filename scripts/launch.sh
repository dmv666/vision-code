#!/bin/bash
# Prepara el entorno la primera vez (.venv + dependencias) y abre Prism Loops Studio.
# Uso: scripts/launch.sh [opciones de vj.gui]     p. ej.  scripts/launch.sh --share
cd "$(dirname "$0")/.." || exit 1

fail() { echo; echo "[vj] $1"; read -r -p "Pulsa Enter para cerrar…" _; exit 1; }

PY=$(command -v python3 || command -v python) || fail "Necesitas Python 3.9 o superior: https://www.python.org/downloads/"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "Tu Python es demasiado antiguo; instala 3.9 o superior."

if ! command -v ffmpeg >/dev/null; then
  echo "[vj] falta ffmpeg (necesario para exportar vídeo)."
  if [ "$(uname)" = "Darwin" ] && command -v brew >/dev/null; then
    echo "[vj] instalándolo con Homebrew…"
    brew install ffmpeg || fail "No se pudo instalar ffmpeg."
  elif [ "$(uname)" = "Darwin" ]; then
    fail "Instala Homebrew (https://brew.sh) y después ejecuta: brew install ffmpeg"
  else
    fail "Instálalo con el gestor de tu sistema, p. ej.: sudo apt install ffmpeg"
  fi
fi

if [ ! -x .venv/bin/python ]; then
  echo "[vj] primera vez: preparando el entorno en .venv (1–2 minutos)…"
  "$PY" -m venv .venv || fail "No se pudo crear el entorno virtual."
fi
if ! .venv/bin/python -c "import moderngl, numpy" 2>/dev/null; then
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt \
    || fail "No se pudieron instalar las dependencias (¿hay conexión a Internet?)."
fi

exec .venv/bin/python -m vj.gui "$@"
