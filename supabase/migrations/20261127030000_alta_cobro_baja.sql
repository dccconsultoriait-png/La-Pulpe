-- =====================================================================
-- Alta, cobro y baja
-- 1. El cliente llena el formulario: queda "pendiente_pago" (registrar_alta).
-- 2. Paga en Mercado Pago: suscripción mensual, o pago único para la Prueba.
-- 3. Llega el aviso del pago aprobado: queda "activo" y se le crean las carpetas (registrar_pago, guardar_carpetas).
-- 4. Revisión diaria: vencido -> 3 días de gracia -> pausado -> baja a los 30 días (revision_diaria).
-- Nada se borra solo. Los clientes con periodo_hasta vacío (como La Pulpe) no entran en la revisión.
-- =====================================================================

alter table public.businesses add column if not exists mp_estado text;   -- estado de la suscripción en Mercado Pago

-- Datos que esperan el primer pago (el logo, en base64, hasta crear las carpetas)
create table if not exists public.altas_pendientes (
  business_id uuid primary key references public.businesses(id) on delete cascade,
  logo_b64    text,
  logo_mime   text,
  created_at  timestamptz not null default now()
);
alter table public.altas_pendientes enable row level security;

insert into public.configuracion (clave, valor, nota) values
  ('email_admin', 'dcc.consultoria.it@gmail.com', 'Recibe copia de cada alta y baja'),
  ('carpeta_clientes_id', '', 'Carpeta de Drive donde se crean las carpetas de cada cliente (vacío = Mi unidad)'),
  ('dias_gracia', '3', 'Días de gracia cuando falla el cobro'),
  ('dias_pausa_hasta_baja', '30', 'Días en pausa hasta la baja')
on conflict (clave) do nothing;

-- ---------- Planes para el formulario ----------
create or replace function public.planes_publicos()
returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', id, 'nombre', nombre, 'precio', precio_ars, 'por_semana', videos_por_semana,
    'total', videos_total, 'dias', dias_duracion) order by orden), '[]'::jsonb)
  from planes where publico;
$$;

-- ---------- Alta (formulario) ----------
-- p_datos: { nombre, rubro, descripcion, tono, telefono, instagram, direccion, horario }
create or replace function public.registrar_alta(p_email text, p_plan text, p_datos jsonb, p_logo_b64 text, p_logo_mime text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_email text := lower(trim(coalesce(p_email, '')));
  v_nombre text := left(trim(coalesce(p_datos->>'nombre', '')), 80);
  p planes%rowtype;
  b businesses%rowtype;
  v_slug text; v_base text; v_i int := 1;
  v_datos jsonb; v_tel text; v_ig text;
begin
  if v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then return jsonb_build_object('ok', false, 'error', 'Revisá el email.'); end if;
  if length(v_nombre) < 2 then return jsonb_build_object('ok', false, 'error', 'Falta el nombre del negocio.'); end if;
  if coalesce(trim(p_datos->>'rubro'), '') = '' then return jsonb_build_object('ok', false, 'error', 'Falta a qué se dedica el negocio.'); end if;
  if coalesce(length(p_logo_b64), 0) < 100 then return jsonb_build_object('ok', false, 'error', 'Falta el logo.'); end if;
  if length(p_logo_b64) > 4000000 then return jsonb_build_object('ok', false, 'error', 'El logo es muy pesado.'); end if;
  select * into p from planes where id = p_plan and publico;
  if not found then return jsonb_build_object('ok', false, 'error', 'Elegí un plan.'); end if;

  -- ¿ya existe con ese email?
  select * into b from businesses where lower(email) = v_email order by created_at desc limit 1;
  if found and b.estado in ('activo', 'en_gracia') then
    return jsonb_build_object('ok', false, 'error', 'Ya tenés una cuenta activa con ese email. Revisá el mail de bienvenida o escribinos.');
  end if;

  v_tel := left(trim(coalesce(p_datos->>'telefono', '')), 40);
  v_ig := left(trim(coalesce(p_datos->>'instagram', '')), 60);
  if v_ig <> '' and left(v_ig, 1) <> '@' then v_ig := '@' || v_ig; end if;
  v_datos := jsonb_strip_nulls(jsonb_build_object(
    'nombre', v_nombre,
    'rubro', left(trim(p_datos->>'rubro'), 200),
    'descripcion', nullif(left(trim(coalesce(p_datos->>'descripcion', '')), 400), ''),
    'tono', coalesce(nullif(left(trim(coalesce(p_datos->>'tono', '')), 200), ''), 'cercano y simple, español rioplatense'),
    'telefono_reservas', nullif(v_tel, ''),
    'instagram', nullif(v_ig, ''),
    'direccion', nullif(left(trim(coalesce(p_datos->>'direccion', '')), 120), ''),
    'horario', nullif(left(trim(coalesce(p_datos->>'horario', '')), 120), ''),
    'hashtags_base', jsonb_build_array('#' || regexp_replace(v_nombre, '[^[:alnum:]]', '', 'g')),
    'color_marco', '#F3EBDD', 'color_texto', '#1A1A1A',
    'logo_en_reel', true, 'logo_ancho_px', 200, 'logo_opacidad', 0.9));

  if b.id is not null and b.estado in ('pendiente_pago', 'pausado', 'baja') and b.carpeta_raiz_id is null then
    -- reintento de un alta que no llegó a pagar: se actualiza la misma fila
    update businesses set name = v_nombre, plan_id = p.id, datos = v_datos, estado = 'pendiente_pago',
           mp_preapproval_id = null, mp_estado = null, updated_at = now()
     where id = b.id returning * into b;
  elsif b.id is not null and b.carpeta_raiz_id is not null then
    -- ex cliente que vuelve: conserva sus carpetas; el pago lo reactiva
    update businesses set plan_id = p.id, datos = b.datos || v_datos, mp_preapproval_id = null, mp_estado = null, updated_at = now()
     where id = b.id returning * into b;
  else
    v_base := trim(both '-' from regexp_replace(lower(translate(v_nombre, 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN')), '[^a-z0-9]+', '-', 'g'));
    if v_base = '' then v_base := 'cliente'; end if;
    v_slug := v_base;
    while exists (select 1 from businesses where slug = v_slug) loop
      v_i := v_i + 1; v_slug := v_base || '-' || v_i;
    end loop;
    insert into businesses (name, slug, email, estado, plan_id, datos, ajustes)
    values (v_nombre, v_slug, v_email, 'pendiente_pago', p.id, v_datos, '{}'::jsonb)
    returning * into b;
  end if;

  insert into altas_pendientes (business_id, logo_b64, logo_mime) values (b.id, p_logo_b64, coalesce(p_logo_mime, 'image/png'))
  on conflict (business_id) do update set logo_b64 = excluded.logo_b64, logo_mime = excluded.logo_mime, created_at = now();
  insert into eventos (business_id, tipo, detalle) values (b.id, 'alta_formulario', jsonb_build_object('plan', p.id, 'email', v_email));

  return jsonb_build_object('ok', true, 'business_id', b.id, 'email', v_email, 'nombre', v_nombre,
    'plan', jsonb_build_object('id', p.id, 'nombre', p.nombre, 'precio', p.precio_ars, 'dias', p.dias_duracion,
                               'mensual', p.dias_duracion is null),
    'servicio', coalesce((select valor from configuracion where clave = 'nombre_servicio'), 'Multiredes'),
    'url_pagina', coalesce((select valor from configuracion where clave = 'url_pagina'), ''));
end $$;

-- Guarda el id de la suscripción creada en Mercado Pago
create or replace function public.guardar_suscripcion(p_business_id uuid, p_preapproval_id text)
returns jsonb language sql security definer set search_path = public as $$
  update businesses set mp_preapproval_id = p_preapproval_id, mp_estado = 'pending', updated_at = now()
   where id = p_business_id
  returning jsonb_build_object('ok', true);
$$;

-- ---------- Pagos ----------
-- Idempotente: el mismo pago avisado dos veces se registra una sola vez.
create or replace function public.registrar_pago(
  p_mp_payment_id text, p_business_id text, p_preapproval_id text,
  p_monto numeric, p_estado text, p_detalle jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  b businesses%rowtype; p planes%rowtype;
  v_nuevo boolean; v_primera boolean; v_hasta timestamptz;
begin
  if coalesce(p_mp_payment_id, '') = '' then return jsonb_build_object('ok', false, 'error', 'sin id de pago'); end if;
  if p_business_id ~ '^[0-9a-f-]{36}$' then select * into b from businesses where id = p_business_id::uuid; end if;
  if b.id is null and coalesce(p_preapproval_id, '') <> '' then
    select * into b from businesses where mp_preapproval_id = p_preapproval_id;
  end if;
  if b.id is null then return jsonb_build_object('ok', false, 'error', 'no encontré el cliente de este pago'); end if;

  insert into pagos (business_id, mp_payment_id, mp_preapproval_id, plan_id, monto, estado, detalle)
  values (b.id, p_mp_payment_id, p_preapproval_id, b.plan_id, p_monto, p_estado, coalesce(p_detalle, '{}'::jsonb))
  on conflict (mp_payment_id) do update set estado = excluded.estado, detalle = excluded.detalle
  returning (xmax = 0) into v_nuevo;   -- true si la fila es nueva

  -- solo un pago aprobado que no se había contado extiende el período
  if p_estado <> 'approved' or exists (
       select 1 from eventos where tipo = 'pago_aprobado' and detalle->>'mp_payment_id' = p_mp_payment_id) then
    return jsonb_build_object('ok', true, 'aprobado_nuevo', false, 'estado', p_estado);
  end if;

  select * into p from planes where id = b.plan_id;
  v_primera := b.carpeta_raiz_id is null;
  v_hasta := greatest(coalesce(b.periodo_hasta, now()), now())
             + case when p.dias_duracion is not null then make_interval(days => p.dias_duracion) else interval '1 month' end;

  update businesses
     set estado = 'activo', periodo_desde = coalesce(case when estado in ('activo', 'en_gracia') then periodo_desde end, now()),
         periodo_hasta = v_hasta, gracia_hasta = null, pausado_desde = null, baja_en = null,
         mp_preapproval_id = coalesce(nullif(p_preapproval_id, ''), mp_preapproval_id), updated_at = now()
   where id = b.id;
  insert into eventos (business_id, tipo, detalle)
  values (b.id, 'pago_aprobado', jsonb_build_object('mp_payment_id', p_mp_payment_id, 'monto', p_monto, 'hasta', v_hasta));

  return jsonb_build_object(
    'ok', true, 'aprobado_nuevo', true, 'primera_vez', v_primera, 'reactivado', b.estado in ('en_gracia', 'pausado', 'baja'),
    'business_id', b.id, 'slug', b.slug, 'nombre', b.name, 'email', b.email,
    'plan', coalesce(p.nombre, ''), 'por_semana', p.videos_por_semana, 'total', p.videos_total,
    'hasta', to_char(v_hasta at time zone 'America/Argentina/Buenos_Aires', 'DD/MM/YYYY'),
    'token_subida', b.token_subida,
    'url_pagina', coalesce((select valor from configuracion where clave = 'url_pagina'), ''),
    'servicio', coalesce((select valor from configuracion where clave = 'nombre_servicio'), 'Multiredes'),
    'email_admin', coalesce((select valor from configuracion where clave = 'email_admin'), ''),
    'carpeta_clientes_id', coalesce((select valor from configuracion where clave = 'carpeta_clientes_id'), ''),
    'logo_b64', (select logo_b64 from altas_pendientes where business_id = b.id),
    'logo_mime', (select logo_mime from altas_pendientes where business_id = b.id));
end $$;

-- Guarda las carpetas creadas en Drive y borra los datos temporales del alta
create or replace function public.guardar_carpetas(
  p_business_id uuid, p_raiz text, p_crudo text, p_reels text, p_historias text, p_feed text, p_recursos text, p_logo text)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  update businesses
     set carpeta_raiz_id = p_raiz, carpeta_crudo_id = p_crudo, carpeta_reels_id = p_reels,
         carpeta_historias_id = p_historias, carpeta_feed_id = p_feed, carpeta_recursos_id = p_recursos,
         logo_file_id = coalesce(nullif(p_logo, ''), logo_file_id), updated_at = now()
   where id = p_business_id;
  delete from altas_pendientes where business_id = p_business_id;
  insert into eventos (business_id, tipo, detalle) values (p_business_id, 'carpetas_creadas', jsonb_build_object('raiz', p_raiz));
  return jsonb_build_object('ok', true);
end $$;

-- ---------- Cambios de la suscripción ----------
-- p_estado: pending, authorized, paused, cancelled
create or replace function public.actualizar_suscripcion(p_preapproval_id text, p_business_id text, p_estado text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare b businesses%rowtype;
begin
  select * into b from businesses where mp_preapproval_id = p_preapproval_id;
  if b.id is null and p_business_id ~ '^[0-9a-f-]{36}$' then select * into b from businesses where id = p_business_id::uuid; end if;
  if b.id is null then return jsonb_build_object('ok', false, 'error', 'no encontré el cliente'); end if;
  if b.mp_estado is not distinct from p_estado and b.mp_preapproval_id is not distinct from p_preapproval_id then
    return jsonb_build_object('ok', true, 'cambio', false);
  end if;
  update businesses set mp_preapproval_id = coalesce(p_preapproval_id, mp_preapproval_id), mp_estado = p_estado, updated_at = now()
   where id = b.id;
  insert into eventos (business_id, tipo, detalle) values (b.id, 'suscripcion_' || coalesce(p_estado, '?'), jsonb_build_object('preapproval', p_preapproval_id));
  -- Si la cancela, sigue activo hasta el fin del período pagado; la revisión diaria le da la baja.
  return jsonb_build_object('ok', true, 'cambio', true, 'estado', p_estado, 'estado_cliente', b.estado, 'email', b.email, 'nombre', b.name,
    'hasta', to_char(b.periodo_hasta at time zone 'America/Argentina/Buenos_Aires', 'DD/MM/YYYY'),
    'servicio', coalesce((select valor from configuracion where clave = 'nombre_servicio'), 'Multiredes'),
    'email_admin', coalesce((select valor from configuracion where clave = 'email_admin'), ''));
end $$;

-- ---------- Revisión diaria ----------
-- Aplica los cambios de estado y devuelve a quién avisar.
create or replace function public.revision_diaria()
returns setof jsonb language plpgsql security definer set search_path = public as $$
declare
  v_gracia int := coalesce((select valor::int from configuracion where clave = 'dias_gracia'), 3);
  v_pausa int := coalesce((select valor::int from configuracion where clave = 'dias_pausa_hasta_baja'), 30);
  v_serv text := coalesce((select valor from configuracion where clave = 'nombre_servicio'), 'Multiredes');
  v_admin text := coalesce((select valor from configuracion where clave = 'email_admin'), '');
  r record;
begin
  perform pg_advisory_xact_lock(424244);

  -- 1) Venció el período: la Prueba o una suscripción cancelada terminan; el resto entra en gracia
  for r in
    update businesses b
       set estado = case when b.plan_id = 'prueba' or b.mp_estado = 'cancelled' then 'pausado' else 'en_gracia' end,
           gracia_hasta = case when b.plan_id = 'prueba' or b.mp_estado = 'cancelled' then null else now() + make_interval(days => v_gracia) end,
           pausado_desde = case when b.plan_id = 'prueba' or b.mp_estado = 'cancelled' then now() else null end,
           updated_at = now()
     where b.estado = 'activo' and b.periodo_hasta is not null
       -- a las mensuales se les dan 2 días: Mercado Pago cobra ese mismo día y el aviso puede llegar tarde
       and b.periodo_hasta < now() - case when b.plan_id = 'prueba' then interval '0' else interval '2 days' end
    returning b.*
  loop
    insert into eventos (business_id, tipo, detalle) values (r.id, 'revision_' || r.estado, '{}'::jsonb);
    return next jsonb_build_object('accion', case when r.plan_id = 'prueba' then 'fin_prueba'
                                                  when r.mp_estado = 'cancelled' then 'fin_suscripcion' else 'gracia' end,
      'business_id', r.id, 'email', r.email, 'nombre', r.name, 'preapproval', r.mp_preapproval_id,
      'servicio', v_serv, 'email_admin', v_admin, 'dias', v_gracia);
  end loop;

  -- 2) Terminó la gracia sin pago: pausa
  for r in
    update businesses b set estado = 'pausado', pausado_desde = now(), gracia_hasta = null, updated_at = now()
     where b.estado = 'en_gracia' and b.gracia_hasta < now()
    returning b.*
  loop
    insert into eventos (business_id, tipo, detalle) values (r.id, 'revision_pausado', '{}'::jsonb);
    return next jsonb_build_object('accion', 'pausa', 'business_id', r.id, 'email', r.email, 'nombre', r.name,
      'preapproval', r.mp_preapproval_id, 'servicio', v_serv, 'email_admin', v_admin, 'dias', v_pausa);
  end loop;

  -- 3) Muchos días en pausa: baja (no se borra nada; se cancela la suscripción si sigue viva)
  for r in
    update businesses b set estado = 'baja', baja_en = now(), updated_at = now()
     where b.estado = 'pausado' and b.pausado_desde < now() - make_interval(days => v_pausa)
    returning b.*
  loop
    insert into eventos (business_id, tipo, detalle) values (r.id, 'revision_baja', '{}'::jsonb);
    return next jsonb_build_object('accion', 'baja', 'business_id', r.id, 'email', r.email, 'nombre', r.name,
      'preapproval', case when r.mp_estado in ('authorized', 'paused', 'pending') then r.mp_preapproval_id end,
      'servicio', v_serv, 'email_admin', v_admin);
  end loop;

  -- 4) Altas que nunca pagaron: se limpia el logo guardado a los 7 días
  delete from altas_pendientes a using businesses b
   where a.business_id = b.id and b.estado = 'pendiente_pago' and a.created_at < now() - interval '7 days';
end $$;

-- Solo n8n (service_role)
revoke all on function public.planes_publicos() from public, anon, authenticated;
revoke all on function public.registrar_alta(text, text, jsonb, text, text) from public, anon, authenticated;
revoke all on function public.guardar_suscripcion(uuid, text) from public, anon, authenticated;
revoke all on function public.registrar_pago(text, text, text, numeric, text, jsonb) from public, anon, authenticated;
revoke all on function public.guardar_carpetas(uuid, text, text, text, text, text, text, text) from public, anon, authenticated;
revoke all on function public.actualizar_suscripcion(text, text, text) from public, anon, authenticated;
revoke all on function public.revision_diaria() from public, anon, authenticated;
grant execute on function public.planes_publicos() to service_role;
grant execute on function public.registrar_alta(text, text, jsonb, text, text) to service_role;
grant execute on function public.guardar_suscripcion(uuid, text) to service_role;
grant execute on function public.registrar_pago(text, text, text, numeric, text, jsonb) to service_role;
grant execute on function public.guardar_carpetas(uuid, text, text, text, text, text, text, text) to service_role;
grant execute on function public.actualizar_suscripcion(text, text, text) to service_role;
grant execute on function public.revision_diaria() to service_role;
