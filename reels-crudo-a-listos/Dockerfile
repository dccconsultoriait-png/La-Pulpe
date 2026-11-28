# n8n + FFmpeg para el VPS de Hostinger (La Pulpe - Crudo a Listos)
# Fuente del método: community.n8n.io/t/add-ffmpeg-to-n8n-docker-image/261143
# ⚠️ Cambiá 2.XX.X por la versión exacta de n8n que tenés hoy (Settings > About n8n).
#    Usá la MISMA versión para no actualizar sin querer.

FROM mwader/static-ffmpeg:6.0 AS ffmpeg-source

FROM n8nio/n8n:2.XX.X
USER root
COPY --from=ffmpeg-source /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-source /ffprobe /usr/local/bin/ffprobe
USER node
