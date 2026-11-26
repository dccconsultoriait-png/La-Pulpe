# Etapa 1: cómo poner en marcha el flujo para todos los clientes

Lleva unos 15 minutos. Hacelo en este orden.

## 0. Agregar FFmpeg a n8n (una sola vez)

Los nodos de edición (los que muestran un "?") necesitan FFmpeg y el nodo Execute Command, que n8n trae apagado.

1. Entrá a [hPanel → VPS](https://hpanel.hostinger.com/vps), tocá **Administrar** en tu servidor y después el botón **Terminal del navegador** (arriba a la derecha).
2. Pegá esta línea y apretá Enter:
   `curl -fsSL https://raw.githubusercontent.com/dccconsultoriait-png/La-Pulpe/claude/project-thread-9gacdu/servidor/instalar-ffmpeg.sh | bash`
3. Esperá a que diga **LISTO** (2 o 3 minutos). Si dice ERROR, mandá una captura.
4. Volvé a n8n y recargá la página: los "?" tienen que desaparecer.

Para deshacerlo, al final el script muestra el comando exacto.

## 1. Conectar n8n con Supabase (una sola vez)

1. En Supabase, entrá al proyecto y andá a **Project Settings → API Keys**. Copiá la clave **secret** (en proyectos viejos se llama `service_role`). Es secreta: no la pegues en ningún chat.
2. En n8n, andá a **Credentials → Add credential → Supabase API** y completá:
   - **Host:** `https://smmmbtmhcceivjipnfxe.supabase.co`
   - **Service Role Secret:** la clave que copiaste
   - Ponele de nombre **Supabase (clientes)** y guardala.

## 2. Importar el flujo nuevo

1. En n8n: **Workflows → Import from file** y elegí `videos-todos-los-clientes.json`.
2. Abrí cada nodo que muestre un aviso rojo de credencial y elegí la que corresponde. Son las mismas que ya usás:
   - Google Drive, Groq, Anthropic (Claude) y Gmail: las de siempre.
   - Los nodos **Clientes a revisar**, **Registrar videos nuevos**, **Tomar siguiente video** y **Marcar video listo** llevan la credencial **Supabase (clientes)**.
3. Guardá el flujo. **Todavía no lo actives.**

## 3. Apagar el flujo viejo de La Pulpe

Desactivá el flujo **"La Pulpe - Crudo a Listos"**. Si quedan los dos prendidos, cada video se procesaría dos veces.

## 4. Probar

1. Subí un video corto (10 a 20 segundos) a la carpeta **Crudo** de La Pulpe.
2. En el flujo nuevo tocá **Execute workflow**.
3. Revisá que aparezcan el reel, la historia, la portada y el texto en **Listos**, y que llegue el mail.
4. En Supabase, en **Table Editor → reels**, el video tiene que figurar con estado **listo**.

Si todo salió bien, **activá** el flujo nuevo. A partir de ahí revisa las carpetas de todos los clientes cada 2 minutos.

## Qué cambió respecto del flujo viejo

- **No hay ningún cliente escrito en el flujo.** Los datos de cada cliente (nombre, teléfono, colores, carpetas, mail, plan) están en Supabase, en la tabla **businesses**. Para cambiar algo de un cliente se edita su fila ahí, no en n8n.
- **El video crudo ya no se mueve a "Edición".** Queda en Crudo, y Supabase anota cuáles se procesaron, así ninguno sale dos veces.
- **Se procesa de a un video por vez, en orden de llegada.** Si se cortó a la mitad, se reintenta solo (hasta 3 veces). Si falla 3 veces, queda con estado **error** en la tabla reels para revisarlo.
- **El cupo del plan ya se controla.** Si un cliente llegó a su límite de la semana, sus videos esperan hasta el lunes.
- **El mail de aviso** va a la dirección de la columna **email** del cliente. Por ahora el de La Pulpe va a tu Gmail; cambialo ahí si tiene que ir a otra persona.

## Dónde mirar en Supabase

| Tabla | Qué tiene |
|---|---|
| businesses | Un cliente por fila: datos, carpetas, plan, estado |
| planes | Los planes con precio y cupo semanal |
| reels | Cada video: de quién es, en qué estado está, textos generados |
| pagos | Los cobros de Mercado Pago (se empieza a usar en la etapa 3) |
| eventos | Registro de novedades: altas, pagos, pausas, cambios de datos |
| configuracion | Ajustes generales: el nombre del servicio con el que se firman los mails (`nombre_servicio`) y la fuente por defecto |
