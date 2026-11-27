# Etapa 3: alta, cobro y baja (Mercado Pago, modo prueba)

Un solo flujo de n8n, **"Multiredes: alta, cobro y baja"** (`n8n/alta-cobro-baja.json`). Se genera con
`python3 scripts/armar_flujo_alta.py n8n/alta-cobro-baja.json`. Tiene tres disparadores:

| Disparador | Qué hace |
|---|---|
| **Formulario de alta** (webhook `multiredes-alta`) | La página `alta.html` pide los planes y manda el alta. El cliente queda "pendiente de pago" y se crea el cobro en Mercado Pago: una suscripción mensual con débito automático, o un pago único si eligió la Prueba. La página lo manda a Mercado Pago a pagar. |
| **Aviso de Mercado Pago** (webhook `multiredes-mp`) | Mercado Pago avisa que algo cambió. El flujo le vuelve a preguntar a Mercado Pago (no confía en lo que llega) y lo anota en Supabase. Con el primer pago aprobado crea las carpetas en Drive, sube el logo y manda el mail de bienvenida con el link personal. Con los pagos siguientes manda "recibimos tu pago". Si se cancela la suscripción, manda un aviso. |
| **Todos los días a las 9** | Revisión diaria: el que no pagó entra en 3 días de gracia, después queda en pausa, y a los 30 días en pausa se le da de baja (se cancela la suscripción). La Prueba termina sola a los 7 días. Cada cambio manda un mail. Nada se borra. |

Dora recibe una copia oculta (CCO) de cada mail (`email_admin` en `configuracion`).

## Reglas

- Planes mensuales: Mercado Pago cobra solo cada mes. Se esperan 2 días después del vencimiento antes de la gracia, por si el aviso del cobro llega tarde.
- Prueba: pago único. Al terminar queda en pausa; si quiere seguir, se suma a un plan mensual con el mismo email y conserva sus carpetas y su link.
- El cliente se da de baja cuando quiera desde Mercado Pago > Suscripciones. Sigue activo hasta el fin del período pago.
- Los clientes con `periodo_hasta` vacío (La Pulpe) no entran en la revisión diaria.
- Las carpetas nuevas se crean en "Mi unidad", o dentro de la carpeta cuyo id esté en `configuracion.carpeta_clientes_id`.
- La carpeta **Listos** de cada cliente queda abierta "con el link" (solo lectura), para que los links de los mails y de la pestaña "Listos" abran siempre. Crudo y Recursos quedan privadas.
- Si el email de la cuenta de Mercado Pago del cliente es otro, lo pone en el formulario: Mercado Pago exige que la suscripción se pague desde esa cuenta.

## Base de datos

`supabase/migrations/20261127030000_alta_cobro_baja.sql` agrega:

- Las funciones `planes_publicos`, `registrar_alta`, `guardar_suscripcion`, `registrar_pago`, `guardar_carpetas`, `actualizar_suscripcion` y `revision_diaria`. Solo n8n las puede usar (service_role).
- La tabla `altas_pendientes`, que guarda el logo hasta el primer pago. Se limpia sola a los 7 días si no paga.
- La columna `businesses.mp_estado`.

Los pagos son idempotentes: el mismo pago avisado dos veces (por "pago" y por "cuota de suscripción") se cuenta una sola vez.

## Credenciales en n8n

| Nodo | Credencial |
|---|---|
| Supabase: ... | Supabase (clientes), la misma de los otros flujos |
| Crear ..., Subir logo, Abrir Listos | Google Drive (La Pulpe) |
| Mail ... | Gmail DCC |
| Mercado Pago: ... | **Mercado Pago (prueba)**: nueva, tipo *Header Auth*, Name `Authorization`, Value `Bearer ` + Access Token |

El Access Token se pega solo en n8n, nunca en el chat ni en el repositorio.

## Webhook en Mercado Pago

Va en Tus integraciones > la aplicación > Webhooks > Configurar notificaciones:

- URL: `https://n8n-fg3m.srv2056463.hstgr.cloud/webhook/multiredes-mp`
- Eventos: **Pagos** y **Planes y suscripciones**

La Prueba manda además su propio aviso a esa misma dirección.

## Pendiente para pasar a cobro real

1. Cambiar la credencial a las del Access Token de producción.
2. Cargar la misma URL de webhook en modo productivo.
3. Opcional: validar la firma `x-signature` de los avisos. Hoy no hace falta, porque cada aviso se vuelve a consultar en Mercado Pago con el token propio, así que un aviso falso no puede activar a nadie.
