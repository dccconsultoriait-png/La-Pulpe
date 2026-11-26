#!/bin/bash
# Agrega FFmpeg a n8n y habilita el nodo "Execute Command" (n8n de Hostinger, plantilla Docker).
# Para deshacerlo: en la carpeta de n8n que muestra el script, borrar el archivo *override* que creó y correr docker compose up -d
set -e
# Busca solo dónde está instalado n8n (el contenedor que está corriendo)
CID=$(docker ps --format '{{.ID}} {{.Image}}' | grep -E ' (docker\.n8n\.io/)?n8nio/n8n(:|$)| n8n-ffmpeg:' | head -1 | cut -d' ' -f1)
if [ -z "$CID" ]; then
  echo "ERROR: no encontré n8n corriendo. Mandale a Claude esto:"; docker ps --format '{{.Names}} | {{.Image}}'; exit 1
fi
DIR=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$CID")
SVC=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$CID")
if [ -z "$DIR" ] || [ -z "$SVC" ] || [ ! -d "$DIR" ]; then
  echo "ERROR: n8n no está instalado con docker compose. Mandale a Claude esto:"
  docker ps --format '{{.Names}} | {{.Image}}'; docker inspect -f '{{json .Config.Labels}}' "$CID"; exit 1
fi
CFG=$(basename "$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$CID" | cut -d, -f1)")
case "$CFG" in
  docker-compose.yml)  OVR=docker-compose.override.yml ;;
  docker-compose.yaml) OVR=docker-compose.override.yaml ;;
  compose.yml)         OVR=compose.override.yml ;;
  compose.yaml)        OVR=compose.override.yaml ;;
  *) echo "ERROR: archivo de configuración inesperado ($CFG). Mandale a Claude una captura."; exit 1 ;;
esac
echo "n8n encontrado en $DIR (servicio $SVC, archivo $CFG)"
cd "$DIR"
if [ -f "$OVR" ] && ! grep -q "n8n-ffmpeg" "$OVR"; then
  echo "ERROR: ya existe un $OVR que no es nuestro. Avisale a Claude antes de seguir."; exit 1
fi
VER=$(docker compose exec -T "$SVC" n8n --version </dev/null | tr -d '\r' | tail -1)
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
docker build -q </dev/null -t "n8n-ffmpeg:$VER" -f Dockerfile.ffmpeg .
cat > "$OVR" <<YAML
# Agregado para Multiredes: n8n con FFmpeg y el nodo Execute Command habilitado.
services:
  $SVC:
    image: n8n-ffmpeg:$VER
    environment:
      - NODES_EXCLUDE=[]
      - N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n-files
YAML
echo "Reiniciando n8n..."
docker compose up -d </dev/null
sleep 20
if docker compose exec -T "$SVC" ffmpeg -version </dev/null >/dev/null 2>&1; then
  echo ""
  echo "LISTO: FFmpeg instalado y n8n reiniciado. Ya podés volver a n8n."
  echo "(Para deshacerlo: cd $DIR && rm $OVR && docker compose up -d)"
else
  echo "ERROR: n8n arrancó pero no encuentra FFmpeg. Mandale a Claude una captura de esta pantalla."; exit 1
fi
