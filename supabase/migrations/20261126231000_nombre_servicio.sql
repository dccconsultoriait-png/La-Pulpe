-- Nombre del servicio configurable en un solo lugar (firma de mails, formulario, Mercado Pago)
insert into public.configuracion (clave, valor, nota) values
  ('nombre_servicio', 'DCC Consultoría IT', 'Nombre con el que se firman los mails a los clientes. Cambiarlo acá alcanza.')
on conflict (clave) do nothing;

create or replace function public.tomar_siguiente_video()
returns setof jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_tz      constant text := 'America/Argentina/Buenos_Aires';
  v_semana  timestamptz := (date_trunc('week', now() at time zone v_tz)) at time zone v_tz;
  v_reel    reels%rowtype;
begin
  perform pg_advisory_xact_lock(424242);

  update reels
     set status = case when intentos >= 3 then 'error' else 'crudo' end,
         error_message = case when intentos >= 3 then 'Falló 3 veces. Revisar a mano.' else 'Reintento automático' end,
         updated_at = now()
   where status = 'en_proceso' and started_at < now() - interval '45 minutes';

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
    'fuente_id',            coalesce(b.fuente_file_id, (select valor from configuracion where clave = 'fuente_por_defecto')),
    'nombre_servicio',      coalesce((select valor from configuracion where clave = 'nombre_servicio'), '')
  )
  from businesses b where b.id = v_reel.business_id;
end $$;

revoke all on function public.tomar_siguiente_video() from public, anon, authenticated;
grant execute on function public.tomar_siguiente_video() to service_role;
