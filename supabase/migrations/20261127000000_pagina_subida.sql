-- =====================================================================
-- Etapa 2: página "Subir" de cada cliente (videos y fotos)
-- - Cada cliente tiene un link personal con token_subida.
-- - Una subida = un pedido = una fila en reels (tipo video, foto o carrusel).
-- - El cupo semanal se cuenta en "piezas": video 1, foto 1, carrusel 2
--   (en Pro, el primer carrusel de la semana no cuenta; un carrusel de regalo tampoco).
-- - El archivo sube directo del navegador al Drive del cliente (subida reanudable);
--   n8n solo abre la subida y la confirma.
-- =====================================================================

alter table public.businesses
  add column if not exists token_subida uuid not null default gen_random_uuid();
create unique index if not exists businesses_token_subida_key on public.businesses (token_subida);

alter table public.reels
  add column if not exists tipo     text    not null default 'video',
  add column if not exists piezas   integer not null default 1,
  add column if not exists archivos jsonb,          -- [{ "nombre": "...", "mime": "...", "file_id": "..." }]
  add column if not exists origen   text    not null default 'drive';  -- 'drive' (carpeta) o 'pagina'

do $$ begin
  alter table public.reels add constraint reels_tipo_check check (tipo in ('video', 'foto', 'carrusel'));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.reels add constraint reels_piezas_check check (piezas between 0 and 10);
exception when duplicate_object then null; end $$;

alter table public.reels drop constraint if exists reels_status_check;
alter table public.reels add constraint reels_status_check check (status in
  ('subiendo', 'crudo', 'en_proceso', 'listo', 'cambio_pedido', 'publicado', 'descartado', 'error'));

-- ---------- Cupo ----------
-- Inicio de la semana (lunes 00:00, hora de Argentina)
create or replace function public.inicio_semana()
returns timestamptz language sql stable as $$
  select (date_trunc('week', now() at time zone 'America/Argentina/Buenos_Aires')) at time zone 'America/Argentina/Buenos_Aires';
$$;

-- Piezas ya usadas: esta semana (p_total = false) o desde siempre (p_total = true, para la prueba)
create or replace function public.piezas_usadas(p_business_id uuid, p_total boolean default false)
returns integer language sql stable security definer set search_path = public as $$
  select coalesce(sum(piezas), 0)::int from reels
  where business_id = p_business_id
    and status in ('en_proceso', 'listo', 'cambio_pedido', 'publicado')
    and (p_total or started_at >= inicio_semana());
$$;

-- ---------- Datos para la página ----------
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
      'limite', v_limite,                                   -- null = sin límite
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
          'cantidad', coalesce(jsonb_array_length(r.archivos), 1)) as x
        from reels r
        where r.business_id = b.id and r.status <> 'descartado'
          and (r.status <> 'subiendo' or r.created_at > now() - interval '1 hour')
        order by r.created_at desc limit 30) t), '[]'::jsonb)
  );
end $$;

-- ---------- Abrir una subida ----------
-- p_archivos: [{ "nombre": "IMG_1234.jpg", "mime": "image/jpeg", "tamano": 123456 }, ...]
-- Devuelve el pedido, la carpeta Crudo y el nombre con que cada archivo se guarda en Drive.
create or replace function public.preparar_subida(p_token uuid, p_tipo text, p_nota text, p_archivos jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  b businesses%rowtype;
  v_n int := coalesce(jsonb_array_length(p_archivos), 0);
  v_max_mb int; v_a jsonb; v_lista jsonb := '[]'::jsonb; v_i int := 0;
  v_pref text; v_ext text; v_id uuid;
begin
  select * into b from businesses where token_subida = p_token;
  if not found then return jsonb_build_object('ok', false, 'error', 'Este link no es válido.'); end if;
  if b.estado not in ('activo', 'en_gracia') then
    return jsonb_build_object('ok', false, 'error', 'Tu cuenta está pausada. Escribinos para reactivarla.');
  end if;
  if b.carpeta_crudo_id is null then
    return jsonb_build_object('ok', false, 'error', 'Tu cuenta todavía se está preparando. Probá en unos minutos.');
  end if;
  if p_tipo not in ('video', 'foto', 'carrusel') then
    return jsonb_build_object('ok', false, 'error', 'Tipo de subida desconocido.');
  end if;
  if p_tipo = 'video' and v_n <> 1 then return jsonb_build_object('ok', false, 'error', 'Subí un video por vez.'); end if;
  if p_tipo = 'foto' and v_n <> 1 then return jsonb_build_object('ok', false, 'error', 'Elegí una foto.'); end if;
  if p_tipo = 'carrusel' and (v_n < 2 or v_n > 10) then
    return jsonb_build_object('ok', false, 'error', 'Para un carrusel elegí entre 2 y 10 fotos.');
  end if;

  v_max_mb := coalesce((b.ajustes->>'tamano_max_mb')::int, 500);
  v_pref := to_char(now() at time zone 'America/Argentina/Buenos_Aires', 'YYYY-MM-DD HH24MI') || ' ' || substr(md5(random()::text), 1, 5);

  for v_a in select * from jsonb_array_elements(p_archivos) loop
    v_i := v_i + 1;
    if p_tipo = 'video' and coalesce(v_a->>'mime', '') not like 'video/%' then
      return jsonb_build_object('ok', false, 'error', 'El archivo no es un video.');
    end if;
    if p_tipo <> 'video' and coalesce(v_a->>'mime', '') not like 'image/%' then
      return jsonb_build_object('ok', false, 'error', 'Alguno de los archivos no es una foto.');
    end if;
    if coalesce((v_a->>'tamano')::bigint, 0) > (case when p_tipo = 'video' then v_max_mb else 25 end)::bigint * 1024 * 1024 then
      return jsonb_build_object('ok', false, 'error',
        case when p_tipo = 'video' then format('El video pesa más de %s MB. Probá con uno más corto.', v_max_mb)
             else 'Alguna foto pesa más de 25 MB.' end);
    end if;
    v_ext := lower(coalesce(substring(v_a->>'nombre' from '\.([A-Za-z0-9]{1,5})$'), case when p_tipo = 'video' then 'mp4' else 'jpg' end));
    v_lista := v_lista || jsonb_build_object(
      'nombre', format('%s %s%s.%s', v_pref, p_tipo, case when v_n > 1 then '-' || lpad(v_i::text, 2, '0') else '' end, v_ext),
      'mime', v_a->>'mime', 'tamano', (v_a->>'tamano')::bigint, 'file_id', null);
  end loop;

  insert into reels (business_id, status, tipo, piezas, archivos, origen, client_note, raw_file_name)
  values (b.id, 'subiendo', p_tipo, case when p_tipo = 'carrusel' then 2 else 1 end, v_lista, 'pagina',
          nullif(left(trim(coalesce(p_nota, '')), 1000), ''), v_lista->0->>'nombre')
  returning id into v_id;

  return jsonb_build_object('ok', true, 'pedido_id', v_id, 'carpeta_id', b.carpeta_crudo_id, 'archivos', v_lista);
end $$;

-- ---------- Confirmar una subida ----------
-- p_archivos: [{ "nombre": "<nombre en Drive>", "file_id": "..." }, ...]
create or replace function public.confirmar_subida(p_token uuid, p_pedido_id uuid, p_archivos jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  b businesses%rowtype; r reels%rowtype;
  v_lista jsonb; v_faltan int; v_piezas int; v_regalos jsonb; v_idx int;
begin
  select * into b from businesses where token_subida = p_token;
  if not found then return jsonb_build_object('ok', false, 'error', 'Este link no es válido.'); end if;
  select * into r from reels where id = p_pedido_id and business_id = b.id for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'No encontré esa subida.'); end if;
  if r.status <> 'subiendo' then return jsonb_build_object('ok', true, 'estado', r.status); end if;

  -- completar los file_id de cada archivo
  select jsonb_agg(a || jsonb_build_object('file_id', coalesce(
            (select e->>'file_id' from jsonb_array_elements(p_archivos) e where e->>'nombre' = a->>'nombre' limit 1),
            a->>'file_id')) order by ord)
    into v_lista
    from jsonb_array_elements(r.archivos) with ordinality as t(a, ord);
  select count(*) into v_faltan from jsonb_array_elements(v_lista) a where coalesce(a->>'file_id', '') = '';
  if v_faltan > 0 then
    update reels set archivos = v_lista, updated_at = now() where id = r.id;
    return jsonb_build_object('ok', false, 'error', 'Faltan archivos por subir.');
  end if;

  -- piezas: carrusel 2, salvo regalo o el primero de la semana en Pro
  v_piezas := r.piezas;
  if r.tipo = 'carrusel' then
    v_regalos := coalesce(b.ajustes->'regalos_pendientes', '[]'::jsonb);
    select ord - 1 into v_idx from jsonb_array_elements(v_regalos) with ordinality as t(g, ord)
     where g->>'tipo' = 'carrusel' limit 1;
    if v_idx is not null then
      v_piezas := 0;
      update businesses set ajustes = jsonb_set(ajustes, '{regalos_pendientes}', (v_regalos - v_idx)), updated_at = now()
       where id = b.id;
      insert into eventos (business_id, tipo, detalle)
      values (b.id, 'regalo_usado', jsonb_build_object('tipo', 'carrusel', 'pedido_id', r.id));
    elsif b.plan_id = 'pro' and not exists (
      select 1 from reels x where x.business_id = b.id and x.id <> r.id and x.tipo = 'carrusel'
        and x.piezas = 0 and x.created_at >= inicio_semana() and x.status <> 'error') then
      v_piezas := 0;
    end if;
  end if;

  update reels
     set archivos = v_lista, raw_file_id = v_lista->0->>'file_id', piezas = v_piezas,
         status = 'crudo', updated_at = now()
   where id = r.id;
  return jsonb_build_object('ok', true, 'estado', 'crudo');
end $$;

-- ---------- La revisión de carpetas respeta las subidas de la página ----------
-- Si un video ya está anotado por la página (mismo nombre, "subiendo"), se completa esa fila en vez de crear otra.
create or replace function public.registrar_videos_nuevos(p_videos jsonb)
returns integer
language plpgsql security definer set search_path = public as $$
declare v_nuevos integer;
begin
  with entrada as (
    select (v->>'business_id')::uuid as business_id, v->>'file_id' as file_id, v->>'file_name' as file_name
    from jsonb_array_elements(coalesce(p_videos, '[]'::jsonb)) v
    where coalesce(v->>'file_id', '') <> ''
  ), de_pagina as (
    update reels r
       set raw_file_id = e.file_id, status = 'crudo', updated_at = now(),
           archivos = jsonb_set(r.archivos, '{0,file_id}', to_jsonb(e.file_id))
      from entrada e
     where r.business_id = e.business_id and r.status = 'subiendo' and r.tipo = 'video'
       and r.raw_file_name = e.file_name
       and not exists (select 1 from reels y where y.raw_file_id = e.file_id)
    returning e.file_id
  ), ins as (
    insert into reels (business_id, raw_file_id, raw_file_name, status)
    select e.business_id, e.file_id, e.file_name, 'crudo'
    from entrada e join businesses b on b.id = e.business_id
    where not exists (select 1 from reels r where r.business_id = e.business_id and r.raw_file_name = e.file_name
                        and r.origen = 'pagina' and r.status in ('subiendo', 'crudo', 'en_proceso', 'listo'))
    on conflict (raw_file_id) where raw_file_id is not null do nothing
    returning 1
  )
  select count(*) into v_nuevos from ins;
  return v_nuevos;
end $$;

-- ---------- Tomar el próximo video (ahora cuenta piezas y solo toma videos) ----------
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

  -- subidas que quedaron a medias (se cerró el navegador)
  update reels set status = 'error', error_message = 'La subida no terminó.', updated_at = now()
   where status = 'subiendo' and created_at < now() - interval '1 day';

  if exists (select 1 from reels where status = 'en_proceso') then
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

-- Solo n8n (service_role)
revoke all on function public.inicio_semana() from public, anon, authenticated;
revoke all on function public.piezas_usadas(uuid, boolean) from public, anon, authenticated;
revoke all on function public.pagina_cliente(uuid) from public, anon, authenticated;
revoke all on function public.preparar_subida(uuid, text, text, jsonb) from public, anon, authenticated;
revoke all on function public.confirmar_subida(uuid, uuid, jsonb) from public, anon, authenticated;
grant execute on function public.inicio_semana() to service_role;
grant execute on function public.piezas_usadas(uuid, boolean) to service_role;
grant execute on function public.pagina_cliente(uuid) to service_role;
grant execute on function public.preparar_subida(uuid, text, text, jsonb) to service_role;
grant execute on function public.confirmar_subida(uuid, uuid, jsonb) to service_role;
