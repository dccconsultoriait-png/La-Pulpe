-- =====================================================================
-- Etapa 2: flujo de fotos (post + historia con 1 foto, carrusel con 2 a 10)
-- - Videos y fotos se procesan en paralelo: uno de cada tipo a la vez.
-- - Lo que se generó de cada pedido de fotos queda en reels.salidas.
-- =====================================================================

alter table public.reels add column if not exists salidas jsonb;  -- [{ "tipo": "post|historia|placa", "n": 1, "file_id": "..." }]

-- Videos: solo miran a otros videos para esperar su turno
create or replace function public.tomar_siguiente_video()
returns setof jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_reel reels%rowtype;
begin
  perform pg_advisory_xact_lock(424242);

  update reels
     set status = case when intentos >= 3 then 'error' else 'crudo' end,
         error_message = case when intentos >= 3 then 'Falló 3 veces. Revisar a mano.' else 'Reintento automático' end,
         updated_at = now()
   where status = 'en_proceso' and started_at < now() - interval '45 minutes';

  update reels set status = 'error', error_message = 'La subida no terminó.', updated_at = now()
   where status = 'subiendo' and created_at < now() - interval '1 day';

  if exists (select 1 from reels where status = 'en_proceso' and tipo = 'video') then
    return;
  end if;

  select r.* into v_reel
  from reels r
  join businesses b on b.id = r.business_id
  left join planes p on p.id = b.plan_id
  where r.status = 'crudo' and r.tipo = 'video'
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
    'file_id',              v_reel.raw_file_id,
    'file_name',            v_reel.raw_file_name,
    'intento',              v_reel.intentos + 1,
    'business_id',          b.id,
    'cliente_id',           b.slug,
    'nombre_cliente',       b.name,
    'email_aviso',          b.email,
    'plan_id',              b.plan_id,
    'datos',                b.datos,
    'ajustes',              b.ajustes,
    'carpeta_reels_id',     b.carpeta_reels_id,
    'carpeta_historias_id', b.carpeta_historias_id,
    'carpeta_feed_id',      b.carpeta_feed_id,
    'logo_id',              b.logo_file_id,
    'fuente_id',            coalesce(b.fuente_file_id, (select valor from configuracion where clave = 'fuente_por_defecto')),
    'nombre_servicio',      coalesce((select valor from configuracion where clave = 'nombre_servicio'), ''),
    'indicacion_cliente',   coalesce(v_reel.client_note, '')
  )
  from businesses b where b.id = v_reel.business_id;
end $$;

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
    'indicacion_cliente',   coalesce(v_reel.client_note, '')
  )
  from businesses b where b.id = v_reel.business_id;
end $$;

-- Marca un pedido de fotos como terminado
create or replace function public.terminar_foto(
  p_reel_id uuid, p_titulo text, p_caption text, p_hashtags text, p_salidas jsonb)
returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  update reels
     set status = 'listo', ready_at = now(), updated_at = now(),
         title = p_titulo, caption = p_caption,
         hashtags = coalesce(regexp_split_to_array(nullif(trim(p_hashtags), ''), '\s+'), '{}'),
         salidas = p_salidas,
         portada_file_id = (select s->>'file_id' from jsonb_array_elements(p_salidas) s
                             where s->>'tipo' in ('post', 'placa') order by (s->>'n')::int limit 1),
         historia_file_id = (select s->>'file_id' from jsonb_array_elements(p_salidas) s where s->>'tipo' = 'historia' limit 1),
         error_message = null
   where id = p_reel_id;
  return jsonb_build_object('ok', found);
end $$;

-- La página también muestra lo que salió de las fotos
create or replace function public.pagina_cliente(p_token uuid)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  b businesses%rowtype;
  p planes%rowtype;
  v_limite int; v_usadas int; v_pendientes int;
begin
  select * into b from businesses where token_subida = p_token;
  if not found then
    return jsonb_build_object('ok', false, 'error', 'Este link no es válido. Pedile uno nuevo a Multiredes.');
  end if;
  select * into p from planes where id = b.plan_id;

  v_limite := coalesce(p.videos_por_semana, p.videos_total);
  v_usadas := piezas_usadas(b.id, p.videos_por_semana is null and p.videos_total is not null);
  select coalesce(sum(piezas), 0)::int into v_pendientes from reels
   where business_id = b.id and status = 'crudo';

  return jsonb_build_object(
    'ok', true,
    'nombre', b.name,
    'servicio', coalesce((select valor from configuracion where clave = 'nombre_servicio'), 'Multiredes'),
    'activo', b.estado in ('activo', 'en_gracia'),
    'estado', b.estado,
    'plan', coalesce(p.nombre, 'Sin plan'),
    'cupo', jsonb_build_object(
      'limite', v_limite,
      'semanal', p.videos_por_semana is not null,
      'usadas', v_usadas,
      'en_fila', v_pendientes,
      'quedan', case when v_limite is null then null else greatest(v_limite - v_usadas - v_pendientes, 0) end),
    'regalos', coalesce(b.ajustes->'regalos_pendientes', '[]'::jsonb),
    'max_video_mb', coalesce((b.ajustes->>'tamano_max_mb')::int, 500),
    'pedidos', coalesce((
      select jsonb_agg(x order by x->>'creado' desc) from (
        select jsonb_build_object(
          'id', r.id, 'tipo', r.tipo, 'estado', r.status, 'creado', r.created_at, 'listo_en', r.ready_at,
          'nota', r.client_note, 'titulo', r.title, 'caption', r.caption,
          'hashtags', array_to_string(r.hashtags, ' '),
          'reel', r.ready_file_id, 'historia', r.historia_file_id, 'portada', r.portada_file_id,
          'salidas', coalesce(r.salidas, '[]'::jsonb),
          'cantidad', coalesce(jsonb_array_length(r.archivos), 1)) as x
        from reels r
        where r.business_id = b.id and r.status <> 'descartado'
          and (r.status <> 'subiendo' or r.created_at > now() - interval '1 hour')
        order by r.created_at desc limit 30) t), '[]'::jsonb)
  );
end $$;

revoke all on function public.tomar_siguiente_foto() from public, anon, authenticated;
revoke all on function public.terminar_foto(uuid, text, text, text, jsonb) from public, anon, authenticated;
grant execute on function public.tomar_siguiente_foto() to service_role;
grant execute on function public.terminar_foto(uuid, text, text, text, jsonb) to service_role;
