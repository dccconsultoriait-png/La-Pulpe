# Servicio de reels automáticos

Sistema que convierte los videos crudos de cada cliente en reel, historia y portada para el feed, con textos generados por Claude.

- `n8n/videos-todos-los-clientes.json`: flujo único que procesa los videos de todos los clientes.
- `supabase/migrations/`: tablas y funciones de la base de clientes (planes, videos, cobros).
- `scripts/armar_flujo_multicliente.py`: arma el flujo multi-cliente a partir del flujo original.
- `docs/etapa-1-como-importar.md`: pasos para importar y probar el flujo.

La propuesta completa (planes, cobro con Mercado Pago, alta y baja automáticas) está en el documento "Propuesta: alta automática de clientes".
