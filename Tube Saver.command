#!/bin/bash
# Doble clic (macOS) o ./"Tube Saver.command" (Linux): abre Tube Saver en el navegador.
exec "$(dirname "$0")/scripts/tubedl.sh" "$@"
