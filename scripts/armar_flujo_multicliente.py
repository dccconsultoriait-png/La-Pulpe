"""Convierte el flujo original de La Pulpe en el flujo único para todos los clientes.

Uso: python3 scripts/armar_flujo_multicliente.py <flujo-original.json> <salida.json>
"""
import copy, json, sys, uuid

SUPA = 'https://smmmbtmhcceivjipnfxe.supabase.co/rest/v1/rpc/'
CRED_SUPA = {'supabaseApi': {'id': '', 'name': 'Supabase (clientes)'}}
CRED_DRIVE = {'googleDriveOAuth2Api': {'id': '', 'name': 'Google Drive (La Pulpe)'}}

orig = json.load(open(sys.argv[1]))
by_name = {n['name']: n for n in orig['nodes']}


def rpc(name, fn, body_expr, pos):
    return {
        'parameters': {
            'method': 'POST', 'url': SUPA + fn,
            'authentication': 'predefinedCredentialType', 'nodeCredentialType': 'supabaseApi',
            'sendBody': True, 'specifyBody': 'json', 'jsonBody': body_expr,
            'options': {'timeout': 30000},
        },
        'name': name, 'type': 'n8n-nodes-base.httpRequest', 'typeVersion': 4.2,
        'position': pos, 'credentials': CRED_SUPA,
    }


def code(name, js, pos, mode=None):
    p = {'jsCode': js}
    if mode:
        p['mode'] = mode
    return {'parameters': p, 'name': name, 'type': 'n8n-nodes-base.code', 'typeVersion': 2, 'position': pos}


ARMAR_BUSQUEDA = r"""// === Arma una sola búsqueda en Drive con las carpetas Crudo de todos los clientes activos ===
const clientes = $input.all().map(i => i.json).filter(c => c && c.business_id && c.carpeta_crudo_id);
if (!clientes.length) return [];   // no hay clientes activos: el flujo termina acá
const mapa = {};
for (const c of clientes) mapa[c.carpeta_crudo_id] = c.business_id;
const esc = s => String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
const carpetas = Object.keys(mapa).map(id => `'${esc(id)}' in parents`).join(' or ');
return [{ json: {
  q: `(${carpetas}) and mimeType contains 'video/' and trashed = false`,
  mapa,
}}];"""

VIDEOS_NUEVOS = r"""// === Arma la lista de videos encontrados, con el cliente al que pertenecen ===
const mapa = $('Armar búsqueda').first().json.mapa || {};
const MAX_MB = 500;   // evita archivos gigantes
const videos = [];
for (const item of $input.all()) {
  const f = item.json || {};
  if (!f.id || !String(f.mimeType || '').startsWith('video/')) continue;
  if (Number(f.size || 0) / 1024 / 1024 > MAX_MB) continue;
  const carpeta = (f.parents || []).find(p => mapa[p]);
  if (!carpeta) continue;
  videos.push({ business_id: mapa[carpeta], file_id: f.id, file_name: f.name || 'video.mp4' });
}
return [{ json: { videos } }];   // aunque no haya nuevos, seguimos: puede haber videos en espera"""

CONFIG_VIDEO = r"""// === CONFIG DEL VIDEO: todo sale de Supabase, nada de un cliente está escrito acá ===
// Para cambiar datos de un cliente se edita su fila en Supabase (tabla businesses), no n8n.
// (Supabase puede devolver la fila sola o envuelta con el nombre de la función)
const fila = $input.all().map(i => i.json)
  .map(j => (j && j.reel_id) ? j : (j && j.tomar_siguiente_video) || null)
  .find(j => j && j.reel_id);
if (!fila) return [];   // no hay videos para procesar ahora (o ya hay uno en proceso)

const DEFAULTS = {
  duracion_max_seg: 90,       // reel
  historia_max_seg: 15,       // historia
  subs_palabras_por_bloque: 4,
  subs_mayusculas: true,
};
const ajustes = { ...DEFAULTS, ...(fila.ajustes || {}) };
for (const k of ['carpeta_reels_id', 'carpeta_historias_id', 'carpeta_feed_id', 'logo_id', 'fuente_id', 'email_aviso']) {
  if (!fila[k]) throw new Error(`Al cliente ${fila.cliente_id} le falta "${k}" en Supabase`);
}
const seguro = s => String(s).replace(/[^a-zA-Z0-9_-]/g, '_');
const ext = (String(fila.file_name || '').match(/\.[a-zA-Z0-9]+$/) || ['.mp4'])[0].toLowerCase();
const dir = `/home/node/.n8n-files/videos/${seguro(fila.cliente_id)}/${seguro(fila.file_id)}`;
const fecha = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Argentina/Buenos_Aires' }).format(new Date());
return [{ json: {
  ...ajustes,
  reel_id: fila.reel_id,
  business_id: fila.business_id,
  cliente_id: fila.cliente_id,
  email_aviso: fila.email_aviso,
  nombre_servicio: fila.nombre_servicio || '',
  carpeta_reels_id: fila.carpeta_reels_id,
  carpeta_historias_id: fila.carpeta_historias_id,
  carpeta_feed_id: fila.carpeta_feed_id,
  logo_id: fila.logo_id,
  fuente_id: fila.fuente_id,
  datos: fila.datos || {},
  file_id: fila.file_id,
  file_name: fila.file_name,
  dir,
  crudo: `${dir}/crudo${ext}`,
  fecha,
}}];"""

DATOS_NEGOCIO = r"""// === Datos del negocio: vienen de Supabase (columna "datos" del cliente) ===
const d = { ...($('Config del video').first().json.datos || {}) };
if (!d.nombre) throw new Error('Falta "nombre" en los datos del cliente (Supabase, columna datos)');
d.hashtags_base = Array.isArray(d.hashtags_base) ? d.hashtags_base : [];
// Pie fijo del caption: lo agregamos nosotros, no Claude, para que el teléfono nunca salga mal
d.pie_caption = [
  d.telefono_reservas ? `📞 Reservas: ${d.telefono_reservas}` : '',
  d.direccion ? `📍 ${d.direccion}` : '',
  d.horario ? `🕛 ${d.horario}` : '',
].filter(Boolean).join('\n');
const hex = (c, def) => (/^#?[0-9a-fA-F]{6}$/.test(String(c || '')) ? String(c).replace('#', '') : def);
d.ff_marco = '0x' + hex(d.color_marco, 'F3EBDD');   // formato de color para FFmpeg
d.ff_texto = '0x' + hex(d.color_texto, '1A1A1A');
return [{ json: d }];"""

TERMINAR_BODY = """={{ JSON.stringify({
  p_reel_id: $('Config del video').first().json.reel_id,
  p_titulo: $('Leer respuesta de Claude').first().json.titulo,
  p_caption: $('Leer respuesta de Claude').first().json.caption,
  p_hashtags: $('Leer respuesta de Claude').first().json.hashtags,
  p_transcripcion: $('Armar subtítulos').first().json.transcripcion,
  p_reel_file_id: $('Subir reel a Listos/Reels').first().json.id,
  p_historia_file_id: $('Subir historia a Listos/Historias').first().json.id,
  p_portada_file_id: $('Subir portada a Listos/Feed').first().json.id
}) }}"""

y = 300
head = [
    {'parameters': {'rule': {'interval': [{'field': 'minutes', 'minutesInterval': 2}]}},
     'name': 'Cada 2 minutos', 'type': 'n8n-nodes-base.scheduleTrigger', 'typeVersion': 1.2, 'position': [-1760, y]},
    rpc('Clientes a revisar', 'clientes_para_revisar', '{}', [-1540, y]),
    code('Armar búsqueda', ARMAR_BUSQUEDA, [-1320, y]),
    {'parameters': {'resource': 'fileFolder', 'searchMethod': 'query', 'queryString': '={{ $json.q }}',
                    'returnAll': True, 'filter': {}, 'options': {'fields': ['*']}},
     'name': 'Buscar videos en Crudo', 'type': 'n8n-nodes-base.googleDrive', 'typeVersion': 3,
     'position': [-1100, y], 'alwaysOutputData': True, 'credentials': CRED_DRIVE},
    code('Videos encontrados', VIDEOS_NUEVOS, [-880, y]),
    rpc('Registrar videos nuevos', 'registrar_videos_nuevos', '={{ JSON.stringify({ p_videos: $json.videos }) }}', [-660, y]),
    rpc('Tomar siguiente video', 'tomar_siguiente_video', '{}', [-440, y]),
    code('Config del video', CONFIG_VIDEO, [-220, y]),
]

drop = {'Nuevo video en Crudo', 'Config La Pulpe', 'Bajar datos del negocio', 'Mover crudo a Edicion'}
body = []
for n in orig['nodes']:
    if n['name'] in drop:
        continue
    n = json.loads(json.dumps(n).replace("$('Config La Pulpe')", "$('Config del video')"))
    if n['name'] == 'Datos del negocio':
        n['parameters']['jsCode'] = DATOS_NEGOCIO
        n['parameters'].pop('mode', None)
    if n['name'] == 'Avisar por mail':
        n['parameters']['message'] = n['parameters']['message'].replace(
            'Ya está listo tu contenido en la carpeta Listos.', 'Ya está listo tu contenido en tu carpeta Listos.'
        ).replace('— DCC Consultoría IT', "— {{ $('Config del video').item.json.nombre_servicio }}")
        assert 'nombre_servicio' in n['parameters']['message']
    body.append(n)

marcar = rpc('Marcar video listo', 'terminar_video', TERMINAR_BODY, [6380, y])

nodes = head + body + [marcar]
for n in nodes:
    n['id'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'videos-multicliente/' + n['name']))

orden = [n['name'] for n in head] + [
    'Preparar carpeta de trabajo', 'Datos del negocio', 'Bajar logo', 'Guardar logo en disco', 'Bajar fuente',
    'Guardar fuente en disco', 'Bajar video crudo', 'Guardar crudo en disco', 'Sacar audio (FFmpeg)', 'Leer audio',
    'Transcribir (Groq Whisper)', 'Armar subtítulos', 'Guardar subtítulos', 'Claude: título y caption',
    'Leer respuesta de Claude', 'Editar reel (FFmpeg)', 'Editar historia (FFmpeg)', 'Hacer portada feed (FFmpeg)',
    'Leer reel listo', 'Subir reel a Listos/Reels', 'Leer historia', 'Subir historia a Listos/Historias',
    'Leer portada', 'Subir portada a Listos/Feed', 'Armar texto para publicar', 'Subir texto a Listos/Reels',
    'Marcar video listo', 'Avisar por mail', 'Limpiar archivos temporales']
names = {n['name'] for n in nodes}
assert names == set(orden), (names ^ set(orden))
connections = {a: {'main': [[{'node': b, 'type': 'main', 'index': 0}]]} for a, b in zip(orden, orden[1:])}

out = {
    'name': 'Videos: Crudo a Listos (todos los clientes) v2.0',
    'nodes': nodes,
    'connections': connections,
    'settings': {'executionOrder': 'v1', 'saveDataErrorExecution': 'all', 'timezone': 'America/Argentina/Buenos_Aires'},
    'pinData': {},
}
txt = json.dumps(out, ensure_ascii=False, indent=2)
assert 'Config La Pulpe' not in txt
json.dump(out, open(sys.argv[2], 'w'), ensure_ascii=False, indent=2)
print('ok', len(nodes), 'nodos')
