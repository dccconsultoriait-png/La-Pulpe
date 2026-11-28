# La Pulpe: "Crudo → Listos" (reel, historia y portada de feed) — Etapa 1

v1.2, 26 nov 2026: de cada video crudo salen 3 piezas con el mismo marco de marca (reel, historia y portada de feed). ⚠️ = falta verificar o confirmar antes de usar.

## Qué hace

1. El cliente filma con el celular y sube el video a la carpeta **Crudo** de Google Drive (desde la app de Drive, es "tipo una app" sin programar una).
2. n8n lo detecta (revisa cada 1 minuto) y:
   - lo pasa a vertical 9:16 (1080×1920), lo corta a 90 s como máximo y empareja el volumen;
   - lo transcribe (Groq, Whisper) y le **quema subtítulos** grandes, de 4 palabras por bloque (ver `ejemplo-subtitulos.png`);
   - arma **3 piezas con la misma identidad** (color crema, tipografía serif y logo; ver `ejemplo-reel-historia-feed.png`):
     - **Reel** 9:16, hasta 90 s: video entero con subtítulos, marco fino crema y el logo arriba a la derecha.
     - **Historia** 9:16, hasta 15 s: banda crema arriba con el logo, el video en el medio con subtítulos, y abajo "RESERVAS 11 6683-2645" y "Domingos al mediodía · @paisanosyalmacenes".
     - **Portada de feed** 4:5 (1080×1350, foto JPG): el mejor cuadro del video con marco crema, el título del reel y el logo. Sirve como posteo de foto, como primera imagen de un carrusel o como portada del reel en el perfil.
   - Claude escribe título, texto de portada, caption y hashtags, sin inventar precios ni fechas;
   - al final del caption agrega solo el teléfono de reservas, la dirección y el horario (los saca de `datos-negocio.json`, no los escribe Claude).
3. En **Listos/Reels** quedan el reel y un `.txt` con el caption; en **Listos/Historias**, la historia; en **Listos/Feed**, la portada.
4. El crudo pasa a **Edicion** (así no se procesa dos veces) y le llega un mail al cliente con los 3 links.
5. El cliente lo revisa y lo sube él mismo a Instagram.

**Todavía no hace (lo dejo para la v2, cuando el cliente lo use):** cortar silencios ni elegir las mejores partes, poner música, avisar por WhatsApp.

## Archivos

| Archivo | Para qué |
|---|---|
| `workflow-crudo-a-listos.json` | El flujo de n8n para importar (32 nodos) |
| `marca/datos-negocio.json` | Nombre, descripción, teléfono, dirección, horario, Instagram, hashtags, colores de marca, textos de la historia y ajustes del logo. **Va a Drive** (paso 3) |
| `marca/fuente.ttf` | Tipografía de los textos y subtítulos (DejaVu Serif Bold, licencia libre en `marca/fuente-LICENCIA.txt`). **Va a Drive** (paso 3) |
| `marca/lapulpe.png` | Logo de La Pulpe. **Va a Drive** (paso 3) |
| `workflow-carrusel.json` | Flujo aparte para **carruseles de fotos** (31 nodos, ver abajo) |
| `ejemplo-carrusel.jpg` | Cómo quedan las placas del carrusel |
| `Dockerfile` | Agrega FFmpeg a tu n8n de Hostinger |
| `ejemplo-subtitulos.png` | Cómo quedan los subtítulos (prueba con video de barras) |
| `ejemplo-reel-historia-feed.png` | Cómo quedan reel, historia y portada (prueba con un video de colores) |
| `prototipo/index.html` | Prototipo de la app para mostrarle al cliente (se abre en el navegador, con ejemplos de La Pulpe) |

Lo que probé acá: los comandos de FFmpeg (sacar audio y armar el reel 1080×1920 con subtítulos, en ~2 s para un video de 6 s), el reel, la historia de 15 s y la portada 4:5 con marco, logo y textos (con y sin audio), el código que lee `datos-negocio.json`, el que arma los subtítulos y el que lee la respuesta de Claude y le suma el teléfono. **No lo probé dentro de n8n ni contra Drive, Groq o Claude de verdad:** eso es el paso 6.

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
En el Drive **del cliente** (o en el tuyo, compartido con él), una carpeta `La_Pulpe` con:

```
La_Pulpe/
├── Crudo        ← acá suben los videos
├── Listos
│   ├── Reels      ← reel + .txt con el caption
│   ├── Historias  ← historia de 15 s
│   └── Feed       ← portada 4:5
├── Edicion      ← el crudo, ya procesado (para no repetirlo)
└── Recursos     ← datos-negocio.json, lapulpe.png y fuente.ttf
```

El ID de cada carpeta es lo que sigue a `/folders/` en la URL. Subí a `Recursos` los 3 archivos de `marca/`. El ID de cada archivo es lo que va entre `/d/` y `/view` en su link.

**Cómo cambiar los datos sin tocar n8n:**
- **Teléfono, dirección, horario, hashtags, descripción:** editá `datos-negocio.json` (con un editor de texto, respetando comillas y comas) y volvé a subirlo **con "Administrar versiones" › "Subir nueva versión"** en Drive. Así conserva el mismo ID. Si lo subís como archivo nuevo, cambia el ID y hay que actualizarlo en el nodo Config.
- **Logo:** lo mismo con `lapulpe.png` (mejor si es cuadrado o con fondo transparente).
- **Textos de la historia:** `historia_linea_1` (grande) y `historia_linea_2` (chica).
- **Colores del marco:** `color_marco` (fondo, crema `#F3EBDD`) y `color_texto` (`#1A1A1A`), en formato `#RRGGBB`.
- **Sacar el logo de los reels:** `"logo_en_reel": false`. Tamaño: `logo_ancho_px` (200 = chico). Transparencia: `logo_opacidad` (1 = sólido).
- Los cambios se aplican desde el próximo video que suban.

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
- Nodo **Config La Pulpe**: IDs de las carpetas Listos/Reels, Listos/Historias, Listos/Feed y Edicion, mail de aviso, y los IDs de `datos-negocio.json`, `lapulpe.png` y `fuente.ttf` (carpeta Recursos). La duración máxima del reel (90 s) y de la historia (15 s) también se cambian acá. Los datos del negocio ya no se cargan acá.
- En `datos-negocio.json` ya cargué: pulpería, Monumento Histórico y Cultural de Los Hornos (La Plata), en pie desde 1878; Av. 161 esq. Av. 78 (sale del logo); domingos al mediodía; reservas 11 6683-2645; Instagram @paisanosyalmacenes. ⚠️ Confirmá los hashtags base.
- Asigná las 4 credenciales en los nodos que las piden (aparecen en rojo).

### 6. Probar (30 min)
1. Subí a Crudo un video corto (15-20 s) hablando.
2. En n8n: **Executions** y mirá nodo por nodo. Si falla, el nodo en rojo dice por qué.
3. Probá también: un video horizontal, uno sin voz, y una foto (debe ignorarla). Fijate que el logo no tape nada importante, que el `.txt` termine con el teléfono, que la historia dure 15 s y que la portada elija un cuadro lindo (si no, la cambiamos por un segundo fijo).
4. Recién ahí: **Active** (publicar el flujo).

Recomendado: en Settings del flujo, poné un **Error Workflow** que te mande un mail a vos si algo falla, así no se entera primero el cliente.

---

## Carrusel de fotos (flujo aparte: `workflow-carrusel.json`)

**Qué hace:** cada 10 minutos mira las **fotos** de `Crudo` (los videos los sigue tomando el flujo de reels). Junta las que se llaman igual hasta `carrusel-01`, `carrusel-02`… (o, si no tienen ese nombre, todas las fotos sueltas) y, cuando pasaron 3 minutos sin fotos nuevas, arma el carrusel:

1. Cada foto pasa a una **placa 4:5 (1080×1350)** con el marco crema: la foto entera (los costados se rellenan con la misma foto desenfocada, así no se cortan los textos escritos encima), y abajo el logo, @paisanosyalmacenes y el número (2/9). La última placa dice "RESERVAS 11 6683-2645".
2. Claude mira todas las fotos (y la descripción del archivo en Drive, si tiene) y escribe título, texto de tapa, caption y hashtags. El teléfono, la dirección y el horario se agregan solos.
3. La **placa 01 es la tapa**: primera foto con el título grande y el logo, igual que la portada de los reels.
4. En `Listos/Feed` crea una carpeta `AAAA-MM-DD - Carrusel - <título>` con `01.jpg`… y `00 - caption.txt`.
5. Mueve las fotos originales a `Edicion` y manda el mail de aviso.

**Para usarlo:** Import from file › `workflow-carrusel.json`; en **Config Carrusel** completá los IDs (los mismos de Crudo, Listos/Feed, Edicion y Recursos) y el mail; asigná las credenciales de Google Drive, Anthropic y Gmail (las mismas del flujo de reels); probalo con **Execute workflow** y después activalo. En **Probar a mano** no hace falta esperar a la hora.

**Claude:** usa `claude-opus-5-5` con `fallbacks: "default"` (encabezado `anthropic-beta: server-side-fallback-2026-07-01`): si el filtro de seguridad rechaza un pedido, la API lo reintenta sola con otro modelo. Si tu cuenta devolviera error 400 por eso, borrá ese encabezado y la línea `fallbacks` del nodo "Pedido a Claude".

Probado en un n8n 2.49.7 de prueba con fotos reales de La Pulpe: corre de punta a punta (Drive, Claude y Gmail simulados). ⚠️ Fotos de celular giradas solo por EXIF podrían salir de costado: si pasa, avisame.

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
