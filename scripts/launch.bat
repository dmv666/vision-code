@echo off
rem Prepara el entorno la primera vez (.venv + dependencias) y abre Prism Loops Studio.
setlocal
cd /d "%~dp0\.."

set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 (
  echo [vj] Necesitas Python 3.9 o superior: https://www.python.org/downloads/
  echo      Al instalarlo marca "Add python.exe to PATH".
  pause & exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [vj] Falta ffmpeg. Instalalo con:   winget install Gyan.FFmpeg
  echo      y vuelve a abrir este archivo.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [vj] Primera vez: preparando el entorno en .venv, 1-2 minutos...
  %PY% -m venv .venv
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" -c "import moderngl, numpy" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv\Scripts\python.exe" -m vj.gui %*
pause
