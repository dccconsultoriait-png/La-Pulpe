#!/bin/bash
# Agrega FFmpeg a n8n y habilita el nodo "Execute Command" (n8n de Hostinger, plantilla Docker).
# Para deshacerlo: cd /docker/n8n && rm docker-compose.override.yml && docker compose up -d
set -e
cd /docker/n8n 2>/dev/null || { echo "ERROR: no encontré la carpeta /docker/n8n. Avisale a Claude."; exit 1; }
docker compose config --services | grep -qx n8n || { echo "ERROR: no encontré el servicio n8n. Avisale a Claude."; exit 1; }
if [ -f docker-compose.override.yml ] && ! grep -q "n8n-ffmpeg" docker-compose.override.yml; then
  echo "ERROR: ya existe un docker-compose.override.yml que no es nuestro. Avisale a Claude antes de seguir."; exit 1
fi
VER=$(docker compose exec -T n8n n8n --version | tr -d '\r' | tail -1)
echo "Versión de n8n: $VER"
cat > Dockerfile.ffmpeg <<DOCKER
FROM mwader/static-ffmpeg:6.0 AS ffmpeg-source
FROM n8nio/n8n:$VER
USER root
COPY --from=ffmpeg-source /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-source /ffprobe /usr/local/bin/ffprobe
USER node
DOCKER
echo "Armando n8n con FFmpeg (tarda 1 o 2 minutos)..."
docker build -q -t "n8n-ffmpeg:$VER" -f Dockerfile.ffmpeg .
cat > docker-compose.override.yml <<YAML
# Agregado para Multiredes: n8n con FFmpeg y el nodo Execute Command habilitado.
services:
  n8n:
    image: n8n-ffmpeg:$VER
    environment:
      - NODES_EXCLUDE=[]
      - N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n-files
YAML
echo "Reiniciando n8n..."
docker compose up -d
sleep 20
if docker compose exec -T n8n ffmpeg -version >/dev/null 2>&1; then
  echo ""
  echo "LISTO: FFmpeg instalado y n8n reiniciado. Ya podés volver a n8n."
else
  echo "ERROR: n8n arrancó pero no encuentra FFmpeg. Mandale a Claude una captura de esta pantalla."; exit 1
fi
