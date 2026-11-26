# La Pulpe: app de reels "Crudo → Listos" (Etapa 1)

v1, 26 nov 2026. ⚠️ = falta verificar o confirmar antes de usar.

## Qué hace

1. El cliente filma con el celular y sube el video a la carpeta **Crudo** de Google Drive (desde la app de Drive, es "tipo una app" sin programar una).
2. n8n lo detecta (revisa cada 1 minuto) y:
   - lo pasa a vertical 9:16 (1080×1920), lo corta a 90 s como máximo y empareja el volumen;
   - lo transcribe (Groq, Whisper) y le **quema subtítulos** grandes, de 4 palabras por bloque (ver `ejemplo-subtitulos.png`);
   - Claude escribe título, texto de portada, caption y hashtags, sin inventar precios ni fechas.
3. En **Listos** aparecen el `.mp4` y un `.txt` con el caption listo para copiar.
4. El crudo pasa a **Procesados** (así no se procesa dos veces) y le llega un mail al cliente con el link.
5. El cliente lo revisa y lo sube él mismo a Instagram.

**Todavía no hace (lo dejo para la v2, cuando el cliente lo use):** cortar silencios ni elegir las mejores partes, poner música ni el logo, avisar por WhatsApp.

## Archivos

| Archivo | Para qué |
|---|---|
| `workflow-crudo-a-listos.json` | El flujo de n8n para importar (20 nodos) |
| `Dockerfile` | Agrega FFmpeg a tu n8n de Hostinger |
| `ejemplo-subtitulos.png` | Cómo quedan los subtítulos (prueba con video de barras) |
| `prototipo/index.html` | Prototipo de la app para mostrarle al cliente (se abre en el navegador, con ejemplos de La Pulpe) |

Lo que probé acá: los comandos de FFmpeg (sacar audio y armar el reel 1080×1920 con subtítulos, en ~2 s para un video de 6 s), el código que arma los subtítulos y el que lee la respuesta de Claude. **No lo probé dentro de n8n ni contra Drive, Groq o Claude de verdad:** eso es el paso 6.

---

## Pasos (en orden)

### 1. Ver qué n8n tenés (5 min)
- En n8n: menú de abajo a la izquierda › **Help › About n8n**: anotá la versión (ej. 2.28.6).
- Si en hPanel tu VPS dice que usa la plantilla de n8n, la config está en `/docker/n8n/docker-compose.yml` ([guía de Hostinger](https://www.hostinger.com/support/10473267-how-to-use-the-n8n-vps-template)).
- ⚠️ Si tu n8n **no** es un VPS (por ejemplo, n8n Cloud), FFmpeg no se puede instalar: avisame y vemos un servicio externo de edición (tiene costo).

### 2. Agregar FFmpeg (15 min, por SSH)
```bash
cd /docker/n8n
# copiá ahí el Dockerfile y cambiá 2.XX.X por tu versión
docker build -t n8n-ffmpeg:TU_VERSION .
```
En `docker-compose.yml`, en el servicio `n8n`:
- cambiá `image: ...` por `image: n8n-ffmpeg:TU_VERSION`
- en `environment` agregá:
```yaml
      - NODES_EXCLUDE=[]
      - N8N_RESTRICT_FILE_ACCESS_TO=/home/node/.n8n-files
```
Después `docker compose up -d` y comprobá: `docker compose exec n8n ffmpeg -version`.

Por qué: desde n8n 2.0 el nodo **Execute Command** viene apagado y se prende con `NODES_EXCLUDE=[]` ([foro de n8n](https://community.n8n.io/t/unable-to-re-enable-execute-command-node-in-n8n-2-0-using-documented-environment-variables/238232)); y los nodos que leen y escriben archivos solo pueden usar la carpeta permitida. ⚠️ El valor por defecto de esa carpeta no está claro en la documentación, por eso la fijamos.

⚠️ Seguridad: Execute Command deja correr comandos en el servidor. Que nadie más tenga usuario en ese n8n.

⚠️ Al actualizar n8n, hay que volver a hacer el `docker build` con la versión nueva (si no, `docker compose pull` no trae FFmpeg).

### 3. Carpetas en Drive (5 min)
En el Drive **del cliente** (o en el tuyo, compartido con él): `La Pulpe Reels/` con `Crudo`, `Listos` y `Procesados`. El ID de cada carpeta es lo que sigue a `/folders/` en la URL.

### 4. Credenciales en n8n (nunca en los nodos ni en chats; guardalas en Bitwarden)
| Credencial | Tipo en n8n | Dato |
|---|---|---|
| Google Drive (La Pulpe) | Google Drive OAuth2 | la cuenta dueña de las carpetas |
| Gmail DCC | Gmail OAuth2 | tu mail de envío |
| Groq API | Header Auth | Name `Authorization`, Value `Bearer TU_KEY` (key en console.groq.com) |
| Anthropic API | Header Auth | Name `x-api-key`, Value `TU_KEY` |

### 5. Importar y completar
- n8n › **Import from file** › `workflow-crudo-a-listos.json`.
- Nodo **Nuevo video en Crudo**: ID de la carpeta Crudo.
- Nodo **Config La Pulpe**: IDs de Listos y Procesados, mail de aviso, hashtags. Ya cargué que es una pulpería, Monumento Histórico y Cultural de Los Hornos (La Plata), en pie desde 1878, que abre los domingos al mediodía (comida casera, argentinidad, tradición, fuego, asados, carne y vinos, música en vivo, reservas para el domingo) con ese tono para los captions. Instagram confirmado: @paisanosyalmacenes. ⚠️ Confirmá los hashtags base.
- Asigná las 4 credenciales en los nodos que las piden (aparecen en rojo).

### 6. Probar (30 min)
1. Subí a Crudo un video corto (15-20 s) hablando.
2. En n8n: **Executions** y mirá nodo por nodo. Si falla, el nodo en rojo dice por qué.
3. Probá también: un video horizontal, uno sin voz, y una foto (debe ignorarla).
4. Recién ahí: **Active** (publicar el flujo).

Recomendado: en Settings del flujo, poné un **Error Workflow** que te mande un mail a vos si algo falla, así no se entera primero el cliente.

---

## Costos por reel (estimados, ⚠️ no medidos)

| Pieza | Precio oficial | Por reel de 1 min |
|---|---|---|
| Transcripción Groq `whisper-large-v3-turbo` | USD 0,04 por hora de audio ([Groq](https://console.groq.com/docs/model/whisper-large-v3-turbo)) | menos de USD 0,001 |
| Claude Opus 5.5 (effort bajo) | USD 4 / 20 por millón de tokens entrada/salida | ~USD 0,01-0,03 (supuesto mío: ~1.500 de entrada y hasta ~1.000 de salida) |
| FFmpeg, n8n, Drive | ya los pagás (VPS, Drive) | 0 |

Total: **unos centavos de dólar por reel**. 12 reels por mes salen menos de USD 0,50 de API. Es tu decisión si querés bajar a Claude Haiku 5.5 (`claude-haiku-5-5`, USD 0,10 / 0,50), que alcanza para un caption. Cambiás el modelo en el nodo "Claude: título y caption".

**Por qué Groq y no OpenAI para transcribir:** para los subtítulos hacen falta los tiempos de cada palabra. OpenAI hoy los da solo con `whisper-1`, que se apaga el 26 feb 2027 ([OpenAI](https://developers.openai.com/api/docs/guides/speech-to-text)). Groq los da con `verbose_json` ([Groq](https://console.groq.com/docs/speech-to-text)). Límite: 25 MB de audio en el plan gratis. Como solo le mandamos el audio comprimido (48 kbps), entran unos 70 min.

⚠️ Revisá los términos de uso de datos de Groq antes de producción (el video es del cliente, no tiene datos sensibles, pero conviene saberlo).

## Mi opinión de socia
- **El aviso por mail alcanza para el piloto.** WhatsApp oficial pide plantilla aprobada por Meta y se paga por mensaje si el cliente no escribió en las últimas 24 h. Lo sumamos cuando el piloto esté pago y funcionando.
- **Lo que más valor le va a dar al cliente es el corte automático** (sacar silencios y "eeeh"). Es la v2: con los tiempos de Groq ya tenemos el dato para hacerlo.
- El repo `La-Pulpe` está **público**. No subas ahí este flujo con IDs ni mails del cliente hasta pasarlo a privado.
