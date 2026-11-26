-- =====================================================================
-- Alta automática de clientes - base de datos (etapa 1)
-- Planes, datos de cada cliente, videos procesados, cobros y registro.
-- Todo se usa desde n8n con la clave secreta (service_role).
-- Nadie más puede leer ni escribir: RLS activo y sin políticas públicas.
-- =====================================================================

-- ---------- Planes ----------
create table if not exists public.planes (
  id                 text primary key,              -- 'prueba', 'inicial', ...
  nombre             text not null,
  precio_ars         numeric not null default 0 check (precio_ars >= 0),
  videos_por_semana  integer check (videos_por_semana is null or videos_por_semana > 0), -- null = sin límite
  videos_total       integer check (videos_total is null or videos_total > 0),           -- para la prueba
  dias_duracion      integer check (dias_duracion is null or dias_duracion > 0),         -- para la prueba
  publico            boolean not null default true,  -- false = no se ofrece en el formulario
  orden              integer not null default 0,
  created_at         timestamptz not null default now()
);
alter table public.planes enable row level security;

insert into public.planes (id, nombre, precio_ars, videos_por_semana, videos_total, dias_duracion, publico, orden) values
  ('prueba',      'Prueba',       15000,  null, 3,    7,    true,  1),
  ('inicial',     'Inicial',     120000,  2,    null, null, true,  2),
  ('crecimiento', 'Crecimiento', 200000,  4,    null, null, true,  3),
  ('pro',         'Pro',         350000,  7,    null, null, true,  4),
  ('interno',     'Interno (sin cupo)', 0, null, null, null, false, 99)
on conflict (id) do nothing;

-- ---------- Ajustes generales ----------
create table if not exists public.configuracion (
  clave  text primary key,
  valor  text,
  nota   text
);
alter table public.configuracion enable row level security;

-- ---------- Clientes (se extiende la tabla businesses existente) ----------
alter table public.businesses
  add column if not exists email                 text,
  add column if not exists estado                text not null default 'pendiente_pago',
  add column if not exists plan_id               text references public.planes(id),
  add column if not exists datos                 jsonb not null default '{}'::jsonb,  -- lo que antes era datos-negocio.json
  add column if not exists ajustes               jsonb not null default '{}'::jsonb,  -- ajustes técnicos propios (opcional)
  add column if not exists carpeta_raiz_id       text,
  add column if not exists carpeta_crudo_id      text,
  add column if not exists carpeta_reels_id      text,
  add column if not exists carpeta_historias_id  text,
  add column if not exists carpeta_feed_id       text,
  add column if not exists carpeta_recursos_id   text,
  add column if not exists logo_file_id          text,
  add column if not exists fuente_file_id        text,
  add column if not exists token_datos           uuid not null default gen_random_uuid(), -- link personal "Cambiar mis datos"
  add column if not exists periodo_desde         timestamptz,
  add column if not exists periodo_hasta         timestamptz,
  add column if not exists gracia_hasta          timestamptz,
  add column if not exists pausado_desde         timestamptz,
  add column if not exists baja_en               timestamptz,
  add column if not exists mp_preapproval_id     text,
  add column if not exists updated_at            timestamptz not null default now();

do $$ begin
  alter table public.businesses add constraint businesses_estado_check
    check (estado in ('pendiente_pago', 'activo', 'en_gracia', 'pausado', 'baja'));
exception when duplicate_object then null; end $$;
create unique index if not exists businesses_token_datos_key on public.businesses (token_datos);
create unique index if not exists businesses_mp_preapproval_key on public.businesses (mp_preapproval_id) where mp_preapproval_id is not null;
create unique index if not exists businesses_crudo_key on public.businesses (carpeta_crudo_id) where carpeta_crudo_id is not null;

-- ---------- Videos (se extiende la tabla reels existente) ----------
alter table public.reels
  add column if not exists intentos     integer not null default 0,
  add column if not exists started_at   timestamptz,
  add column if not exists historia_file_id text,
  add column if not exists portada_file_id  text;
create unique index if not exists reels_raw_file_key on public.reels (raw_file_id) where raw_file_id is not null;
create index if not exists reels_status_idx on public.reels (status, created_at);
create index if not exists reels_business_started_idx on public.reels (business_id, started_at);

-- ---------- Cobros (se usa en la etapa 3) ----------
create table if not exists public.pagos (
  id                 uuid primary key default gen_random_uuid(),
  business_id        uuid references public.businesses(id),
  mp_payment_id      text unique,                 -- evita procesar dos veces el mismo aviso
  mp_preapproval_id  text,
  plan_id            text references public.planes(id),
  monto              numeric,
  estado             text,                        -- approved, rejected, ...
  detalle            jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);
alter table public.pagos enable row level security;
create index if not exists pagos_business_idx on public.pagos (business_id, created_at);

-- ---------- Registro de novedades (altas, pagos, pausas, cambios de datos) ----------
create table if not exists public.eventos (
  id           bigint generated always as identity primary key,
  business_id  uuid references public.businesses(id),
  tipo         text not null,
  detalle      jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);
alter table public.eventos enable row level security;
create index if not exists eventos_business_idx on public.eventos (business_id, created_at);

-- =====================================================================
-- Funciones que usa n8n
-- =====================================================================

-- Clientes cuyas carpetas Crudo hay que revisar
create or replace function public.clientes_para_revisar()
returns table (business_id uuid, slug text, carpeta_crudo_id text)
language sql stable security definer set search_path = public as $$
  select b.id, b.slug, b.carpeta_crudo_id
  from businesses b
  where b.estado in ('activo', 'en_gracia')
    and b.carpeta_crudo_id is not null
  order by b.created_at;
$$;

-- Anota los videos que aparecieron en las carpetas Crudo. Los repetidos se ignoran.
-- p_videos: [{ "business_id": "...", "file_id": "...", "file_name": "..." }, ...]
create or replace function public.registrar_videos_nuevos(p_videos jsonb)
returns integer
language plpgsql security definer set search_path = public as $$
declare v_nuevos integer;
begin
  with entrada as (
    select (v->>'business_id')::uuid as business_id, v->>'file_id' as file_id, v->>'file_name' as file_name
    from jsonb_array_elements(coalesce(p_videos, '[]'::jsonb)) v
    where coalesce(v->>'file_id', '') <> ''
  ), ins as (
    insert into reels (business_id, raw_file_id, raw_file_name, status)
    select e.business_id, e.file_id, e.file_name, 'crudo'
    from entrada e join businesses b on b.id = e.business_id
    on conflict (raw_file_id) where raw_file_id is not null do nothing
    returning 1
  )
  select count(*) into v_nuevos from ins;
  return v_nuevos;
end $$;

-- Toma el próximo video a procesar, de a uno por vez, respetando el cupo del plan.
-- Devuelve 0 o 1 filas con todo lo que el flujo necesita.
create or replace function public.tomar_siguiente_video()
returns setof jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_tz      constant text := 'America/Argentina/Buenos_Aires';
  v_semana  timestamptz := (date_trunc('week', now() at time zone v_tz)) at time zone v_tz;
  v_reel    reels%rowtype;
begin
  -- un solo flujo a la vez decide qué video sigue
  perform pg_advisory_xact_lock(424242);

  -- videos trabados (el flujo se cortó): se reintentan hasta 3 veces
  update reels
     set status = case when intentos >= 3 then 'error' else 'crudo' end,
         error_message = case when intentos >= 3 then 'Falló 3 veces. Revisar a mano.' else 'Reintento automático' end,
         updated_at = now()
   where status = 'en_proceso' and started_at < now() - interval '45 minutes';

  -- si ya hay uno procesándose, esperamos (de a un video por vez)
  if exists (select 1 from reels where status = 'en_proceso') then
    return;
  end if;

  select r.* into v_reel
  from reels r
  join businesses b on b.id = r.business_id
  left join planes p on p.id = b.plan_id
  where r.status = 'crudo'
    and b.estado in ('activo', 'en_gracia')
    and (p.videos_por_semana is null or (
          select count(*) from reels x
          where x.business_id = b.id and x.id <> r.id
            and x.status in ('en_proceso', 'listo', 'cambio_pedido', 'publicado')
            and x.started_at >= v_semana) < p.videos_por_semana)
    and (p.videos_total is null or (
          select count(*) from reels x
          where x.business_id = b.id and x.id <> r.id
            and x.status in ('en_proceso', 'listo', 'cambio_pedido', 'publicado')) < p.videos_total)
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
    'fuente_id',            coalesce(b.fuente_file_id, (select valor from configuracion where clave = 'fuente_por_defecto'))
  )
  from businesses b where b.id = v_reel.business_id;
end $$;

-- Marca un video como terminado y guarda lo que se generó
create or replace function public.terminar_video(
  p_reel_id uuid, p_titulo text, p_caption text, p_hashtags text,
  p_transcripcion text, p_reel_file_id text, p_historia_file_id text, p_portada_file_id text)
returns jsonb
language plpgsql security definer set search_path = public as $$
begin
  update reels
     set status = 'listo', ready_at = now(), updated_at = now(),
         title = p_titulo, caption = p_caption,
         hashtags = coalesce(regexp_split_to_array(nullif(trim(p_hashtags), ''), '\s+'), '{}'),
         transcript = p_transcripcion,
         ready_file_id = p_reel_file_id, historia_file_id = p_historia_file_id, portada_file_id = p_portada_file_id,
         error_message = null
   where id = p_reel_id;
  return jsonb_build_object('ok', found);
end $$;

-- Solo n8n (service_role) puede usar estas funciones
revoke all on function public.clientes_para_revisar() from public, anon, authenticated;
revoke all on function public.registrar_videos_nuevos(jsonb) from public, anon, authenticated;
revoke all on function public.tomar_siguiente_video() from public, anon, authenticated;
revoke all on function public.terminar_video(uuid, text, text, text, text, text, text, text) from public, anon, authenticated;
grant execute on function public.clientes_para_revisar() to service_role;
grant execute on function public.registrar_videos_nuevos(jsonb) to service_role;
grant execute on function public.tomar_siguiente_video() to service_role;
grant execute on function public.terminar_video(uuid, text, text, text, text, text, text, text) to service_role;
