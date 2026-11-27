# Etapa 2: la página "Subir" de cada cliente

Cada cliente tiene un link personal para subir videos o fotos, dejar una indicación
y ver lo que está en proceso y lo que ya está listo.

```
https://<sitio>.netlify.app/?t=<token del cliente>
```

El token está en Supabase, tabla `businesses`, columna `token_subida`. No lo publiques:
quien tiene el link puede subir contenido a nombre de ese cliente.

## Cómo funciona

1. La página le pide a n8n que anote el pedido (Supabase) y que abra una subida en el Drive del cliente.
2. El archivo va **directo del celular a Google Drive**, a la carpeta Crudo del cliente. n8n no lo toca,
   así que no hay límite de tamaño en el servidor.
3. La página confirma la subida y el pedido pasa a la fila. Los videos los toma el flujo de siempre.
   Si la confirmación se pierde, la revisión de cada 2 minutos encuentra el video igual y respeta la indicación.

## Cupo

Se cuenta en piezas por semana (de lunes a domingo, hora de Argentina):
video 1, foto 1, carrusel 2. En Pro el primer carrusel de la semana no cuenta.
Un carrusel de regalo (`ajustes.regalos_pendientes`) tampoco cuenta.
Lo que pase del cupo queda en la fila y se edita desde el lunes.

## Puesta en marcha (una sola vez)

1. **Publicar la página** (gratis): en https://app.netlify.com/drop arrastrá un zip con
   `docs/subir/index.html` adentro (como `index.html`). Para actualizarla, se vuelve a arrastrar.
2. **Importar el flujo** `n8n/pagina-subida-api.json` en n8n. Asignale la credencial de Supabase
   en "Llamar a Supabase" y la de Google Drive en "Abrir subida en Drive". Guardalo y activalo.
3. Abrí el link del cliente y probá subir algo.
