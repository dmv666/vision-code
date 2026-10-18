# Prism Loops Studio como servidor (VPS, NAS, PC de casa siempre encendido).
#   docker compose up -d     → http://<servidor>:8765  (ver docker-compose.yml)
# Sin GPU renderiza con Mesa llvmpipe (CPU): funciona, pero es lento en 4K.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libegl1 libgl1 libgles2 libegl-mesa0 libgl1-mesa-dri \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vj ./vj
COPY configs ./configs

# /data guarda escenas, vídeos y sesiones (se siembra con configs/ la primera vez).
ENV PRISM_WORKSPACE=/data PRISM_NO_BROWSER=1 PRISM_REQUIRE_LOGIN=1 PYTHONUNBUFFERED=1 \
    NVIDIA_DRIVER_CAPABILITIES=all
VOLUME /data
EXPOSE 8765
CMD ["python", "-m", "vj.gui", "--host", "0.0.0.0", "--port", "8765"]
