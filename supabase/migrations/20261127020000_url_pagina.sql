-- Dirección pública de la página "Subir" (Netlify). Se usa en los mails.
insert into public.configuracion (clave, valor, nota)
values ('url_pagina', '', 'Dirección de la página Subir, sin barra final. Ej: https://multiredes.netlify.app')
on conflict (clave) do nothing;

-- Fotos: toma el próximo pedido de fotos (de a uno), respetando el mismo cupo de piezas
create or replace function public.tomar_siguiente_foto()
returns setof jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_reel reels%rowtype;
begin
  perform pg_advisory_xact_lock(424243);

  if exists (select 1 from reels where status = 'en_proceso' and tipo <> 'video') then
    return;
  end if;

  select r.* into v_reel
  from reels r
  join businesses b on b.id = r.business_id
  left join planes p on p.id = b.plan_id
  where r.status = 'crudo' and r.tipo in ('foto', 'carrusel')
    and b.estado in ('activo', 'en_gracia')
    and (p.videos_por_semana is null or piezas_usadas(b.id) + r.piezas <= p.videos_por_semana)
    and (p.videos_total is null or piezas_usadas(b.id, true) + r.piezas <= p.videos_total)
  order by r.created_at
  limit 1
  for update of r skip locked;

  if not found then
    return;
  end if;

  update reels
     set status = 'en_proceso', started_at = now(), intentos = intentos + 1,
         error_message = null, updated_at = now()
   where id = v_reel.id;

  return query
  select jsonb_build_object(
    'reel_id',              v_reel.id,
    'tipo',                 v_reel.tipo,
    'archivos',             v_reel.archivos,
    'intento',              v_reel.intentos + 1,
    'business_id',          b.id,
    'cliente_id',           b.slug,
    'nombre_cliente',       b.name,
    'email_aviso',          b.email,
    'token_subida',         b.token_subida,
    'datos',                b.datos,
    'ajustes',              b.ajustes,
    'carpeta_historias_id', b.carpeta_historias_id,
    'carpeta_feed_id',      b.carpeta_feed_id,
    'logo_id',              b.logo_file_id,
    'fuente_id',            coalesce(b.fuente_file_id, (select valor from configuracion where clave = 'fuente_por_defecto')),
    'nombre_servicio',      coalesce((select valor from configuracion where clave = 'nombre_servicio'), ''),
    'indicacion_cliente',   coalesce(v_reel.client_note, ''),
    'url_pagina',           coalesce((select valor from configuracion where clave = 'url_pagina'), '')
  )
  from businesses b where b.id = v_reel.business_id;
end $$;

