#!/bin/bash
# Como "Prism Loops Studio", pero otras personas de tu red pueden entrar desde su
# navegador con el código de acceso que aparece en esta ventana.
exec "$(dirname "$0")/scripts/launch.sh" --share "$@"
