@echo off
rem Prepara el entorno la primera vez (.venv-tubedl + yt-dlp) y abre Tube Saver.
setlocal
cd /d "%~dp0\.."

set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul
if errorlevel 1 (
  echo [tubedl] Necesitas Python 3.9 o superior: https://www.python.org/downloads/
  echo          Al instalarlo marca "Add python.exe to PATH".
  pause & exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [tubedl] Aviso: falta ffmpeg. Instalalo con:   winget install Gyan.FFmpeg
)
if not exist ".venv-tubedl\Scripts\python.exe" (
  echo [tubedl] Primera vez: preparando el entorno...
  %PY% -m venv .venv-tubedl
  if errorlevel 1 ( pause & exit /b 1 )
)
".venv-tubedl\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U -r tubedl\requirements.txt
".venv-tubedl\Scripts\python.exe" -m tubedl %*
pause
