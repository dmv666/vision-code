#!/bin/bash
# Prepara el entorno la primera vez (.venv-tubedl + yt-dlp) y abre Tube Saver.
cd "$(dirname "$0")/.." || exit 1

fail() { echo; echo "[tubedl] $1"; read -r -p "Pulsa Enter para cerrar…" _; exit 1; }

PY=$(command -v python3 || command -v python) || fail "Necesitas Python 3.9 o superior: https://www.python.org/downloads/"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "Tu Python es demasiado antiguo; instala 3.9 o superior."

if ! command -v ffmpeg >/dev/null; then
  if [ "$(uname)" = "Darwin" ] && command -v brew >/dev/null; then
    echo "[tubedl] instalando ffmpeg con Homebrew…"
    brew install ffmpeg || fail "No se pudo instalar ffmpeg."
  else
    echo "[tubedl] aviso: falta ffmpeg (macOS: brew install ffmpeg · Linux: sudo apt install ffmpeg)."
  fi
fi

if [ ! -x .venv-tubedl/bin/python ]; then
  echo "[tubedl] primera vez: preparando el entorno…"
  "$PY" -m venv .venv-tubedl || fail "No se pudo crear el entorno virtual."
fi
# yt-dlp se actualiza en cada arranque: YouTube cambia a menudo y las versiones viejas dejan de funcionar.
.venv-tubedl/bin/python -m pip install --disable-pip-version-check -q -U -r tubedl/requirements.txt \
  || .venv-tubedl/bin/python -c "import yt_dlp" 2>/dev/null \
  || fail "No se pudo instalar yt-dlp (¿hay conexión a Internet?)."

exec .venv-tubedl/bin/python -m tubedl "$@"
