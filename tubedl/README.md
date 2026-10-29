# Tube Saver — descarga audio o vídeo de YouTube

App personal que corre en tu equipo (solo escucha en `127.0.0.1`). Pegas un
enlace, eliges **Audio** (MP3, M4A, Opus, WAV) o **Vídeo** (MP4, mejor calidad o
hasta 2160p/1440p/1080p/720p/480p/360p) y el archivo queda en `descargas/`;
desde la propia página puedes guardarlo en otra carpeta o borrarlo.

## Abrir

- **macOS / Linux:** doble clic en `Tube Saver.command` (o `./"Tube Saver.command"`).
- **Windows:** doble clic en `Tube Saver.bat`.

La primera vez crea un entorno en `.venv-tubedl` e instala
[yt-dlp](https://github.com/yt-dlp/yt-dlp). En cada arranque lo actualiza,
porque YouTube cambia a menudo y las versiones viejas dejan de funcionar.

Necesita **ffmpeg** para convertir el audio y unir vídeo + sonido:
`brew install ffmpeg` (macOS), `sudo apt install ffmpeg` (Linux) o
`winget install Gyan.FFmpeg` (Windows).

## A mano

```bash
pip install -r tubedl/requirements.txt
python -m tubedl                     # abre http://127.0.0.1:8790/
python -m tubedl --out ~/Music/yt --port 9000 --no-browser
```

Úsala solo con contenido que tengas derecho a descargar (tuyo, con licencia
libre o con permiso del autor) y respetando los términos de YouTube.
