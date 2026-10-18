#!/bin/bash
# Doble clic en macOS: abre la interfaz de Prism Loops en el navegador.
# (Se abre una ventana de Terminal: ciérrala para apagar la interfaz.)
cd "$(dirname "$0")" || exit 1
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
exec python3 -m vj.gui
