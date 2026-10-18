#!/bin/bash
# Doble clic (macOS) o ./"Prism Loops Studio.command" (Linux): abre Prism Loops Studio
# en el navegador. La primera vez instala lo necesario. Cierra esta ventana para apagarlo.
exec "$(dirname "$0")/scripts/launch.sh" "$@"
