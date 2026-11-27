"""Arma el flujo de n8n que edita las fotos que suben los clientes.

Uso: python3 scripts/armar_flujo_fotos.py n8n/fotos-todos-los-clientes.json

- 1 foto       -> post 4:5 + historia 9:16
- 2 a 10 fotos -> carrusel 4:5 (Claude elige el orden y el texto de cada placa) + placa final
                  con los datos del negocio + historia con la portada
Claude mira las fotos (en tamaño chico) y la indicación del cliente para escribir.
"""
import json
import os
import sys
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
SUPA = 'https://smmmbtmhcceivjipnfxe.supabase.co/rest/v1/rpc/'
CRED_SUPA = {'supabaseApi': {'id': '', 'name': 'Supabase (clientes)'}}
CRED_DRIVE = {'googleDriveOAuth2Api': {'id': '', 'name': 'Google Drive (La Pulpe)'}}
CRED_CLAUDE = {'anthropicApi': {'id': '', 'name': 'Anthropic account'}}
CRED_GMAIL = {'gmailOAuth2': {'id': '', 'name': 'Gmail DCC'}}


def nid(nombre):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'multiredes-fotos/' + nombre))


CONFIG = r"""// === CONFIG DE LAS FOTOS: todo sale de Supabase ===
const fila = $input.all().map(i => i.json)
  .map(j => (j && j.reel_id) ? j : (j && j.tomar_siguiente_foto) || null)
  .find(j => j && j.reel_id);
if (!fila) return [];   // no hay fotos para editar ahora (o ya hay un pedido en proceso)

for (const k of ['carpeta_historias_id', 'carpeta_feed_id', 'logo_id', 'fuente_id', 'email_aviso']) {
  if (!fila[k]) throw new Error(`Al cliente ${fila.cliente_id} le falta "${k}" en Supabase`);
}
const archivos = (fila.archivos || []).filter(a => a && a.file_id);
if (!archivos.length) throw new Error('El pedido no tiene fotos');
if (fila.tipo === 'carrusel' && archivos.length < 2) throw new Error('Un carrusel necesita 2 fotos o más');

const seguro = s => String(s).replace(/[^a-zA-Z0-9_-]/g, '_');
const dir = `/home/node/.n8n-files/fotos/${seguro(fila.cliente_id)}/${seguro(fila.reel_id)}`;
const lista = archivos.slice(0, 10).map((a, i) => {
  const n = String(i + 1).padStart(2, '0');
  const ext = (String(a.nombre || '').match(/\.[a-zA-Z0-9]+$/) || ['.jpg'])[0].toLowerCase();
  return { n, file_id: a.file_id, ruta: `${dir}/foto-${n}${ext}`, chica: `${dir}/chica-${n}.jpg` };
});
// Copias chicas (1280 px) para que Claude las mire rápido y barato
const cmd_achicar = lista.map(f =>
  `ffmpeg -hide_banner -loglevel error -y -i "${f.ruta}" -vf "scale='min(1280,iw)':-2" -frames:v 1 -q:v 4 "${f.chica}"`).join(' && ');
const fecha = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Argentina/Buenos_Aires' }).format(new Date());
const url = String(fila.url_pagina || '').replace(/\/+$/, '');
return [{ json: {
  reel_id: fila.reel_id,
  tipo: fila.tipo,
  cliente_id: fila.cliente_id,
  email_aviso: fila.email_aviso,
  nombre_servicio: fila.nombre_servicio || '',
  indicacion_cliente: String(fila.indicacion_cliente || '').trim().slice(0, 1000),
  link_pagina: url && fila.token_subida ? `${url}/?t=${fila.token_subida}` : '',
  carpeta_historias_id: fila.carpeta_historias_id,
  carpeta_feed_id: fila.carpeta_feed_id,
  logo_id: fila.logo_id,
  fuente_id: fila.fuente_id,
  datos: fila.datos || {},
  archivos: lista,
  cmd_achicar,
  dir,
  fecha,
}}];
"""

DATOS_NEGOCIO = r"""// === Datos del negocio: vienen de Supabase (columna "datos" del cliente) ===
const d = { ...($('Config de las fotos').first().json.datos || {}) };
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
return [{ json: d }];
"""

UN_ITEM_POR_FOTO = r"""// Una vuelta por cada foto del pedido
return $('Config de las fotos').first().json.archivos.map(f => ({ json: f }));
"""

PEDIDO_CLAUDE = r"""// === Arma el pedido a Claude con las fotos (chicas) y la indicación del cliente ===
const c = $('Config de las fotos').first().json;
const d = $('Datos del negocio').first().json;
const items = $input.all();
const fotos = [];
for (let i = 0; i < items.length; i++) {
  const nombre = (items[i].binary && items[i].binary.data && items[i].binary.data.fileName) || '';
  const buf = await this.helpers.getBinaryDataBuffer(i, 'data');
  fotos.push({ nombre, data: buf.toString('base64') });
}
fotos.sort((a, b) => a.nombre.localeCompare(b.nombre));   // chica-01, chica-02, ...
if (!fotos.length) throw new Error('No pude leer las fotos');

const esCarrusel = c.tipo === 'carrusel';
const system = [
  `Sos el community manager de ${d.nombre} (${d.descripcion || ''}; rubro: ${d.rubro || ''}; abre: ${d.horario || ''}). Tono: ${d.tono || 'cercano'}.`,
  esCarrusel
    ? `Te paso ${fotos.length} fotos numeradas para armar un carrusel de Instagram. Escribís:`
    : 'Te paso una foto para un post de Instagram y una historia. Escribís:',
  '- titulo: corto (máx. 8 palabras), para nombrar el archivo.',
  '- gancho: texto para poner sobre la imagen, máx. 7 palabras, que dé ganas de verla.',
  esCarrusel
    ? '- placas: una por cada foto, en el orden en que conviene mostrarlas. Usá cada foto exactamente una vez (campo foto = su número). La primera placa es la portada: elegí la foto más atractiva. texto: máx. 8 palabras sobre lo que se ve en esa foto (en la portada va el gancho, así que su texto puede quedar vacío).'
    : '- placas: una sola, { foto: 1, texto: "" }.',
  '- caption: 2 a 4 oraciones para Instagram, con un llamado a la acción al final. Podés usar 1 o 2 emojis.',
  '- hashtags: 3 a 6 hashtags relevantes en español, con #.',
  'No escribas teléfono, dirección ni horario en el caption: se agregan solos al final.',
  'REGLAS: describí solo lo que se ve en las fotos. No inventes precios, fechas, promociones, horarios, nombres de platos ni datos que no estén en las fotos o en la indicación. Si no estás seguro de qué es algo, nombralo de forma general.',
  'Si el cliente dejó una indicación (una promoción, un evento, un sorteo, un aniversario), es lo más importante que tiene que comunicar este contenido: usala en el gancho y en el caption, con los datos tal como los escribió.',
  'Las fotos pueden ser de días anteriores: no afirmes cosas que pueden haber cambiado (lleno, agotado, últimos lugares, "hoy", "mañana"), salvo que el cliente lo confirme en su indicación.',
].join('\n');

const content = [];
fotos.forEach((f, i) => {
  content.push({ type: 'text', text: `Foto ${i + 1}:` });
  content.push({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: f.data } });
});
content.push({ type: 'text', text: c.indicacion_cliente
  ? `Indicación del cliente: «${c.indicacion_cliente}»`
  : 'El cliente no dejó indicación.' });

const body = {
  model: 'claude-opus-5-5',
  max_tokens: 4000,
  output_config: {
    effort: 'low',
    format: { type: 'json_schema', schema: {
      type: 'object',
      properties: {
        titulo: { type: 'string' },
        gancho: { type: 'string' },
        placas: { type: 'array', items: {
          type: 'object',
          properties: { foto: { type: 'integer' }, texto: { type: 'string' } },
          required: ['foto', 'texto'], additionalProperties: false } },
        caption: { type: 'string' },
        hashtags: { type: 'array', items: { type: 'string' } },
      },
      required: ['titulo', 'gancho', 'placas', 'caption', 'hashtags'],
      additionalProperties: false,
    } },
  },
  system,
  messages: [{ role: 'user', content }],
};
return [{ json: { body, cantidad: fotos.length } }];
"""

LEER_CLAUDE = r"""// === Lee la respuesta de Claude y la deja lista para editar ===
const r = $input.first().json;
if (r.stop_reason === 'refusal') throw new Error('Claude rechazó el pedido: revisar las fotos a mano');
const bloque = (r.content || []).find(b => b.type === 'text');
if (!bloque) throw new Error('Claude no devolvió texto');
const d = JSON.parse(bloque.text);
const c = $('Config de las fotos').first().json;
const datos = $('Datos del negocio').first().json;
const n = c.archivos.length;

// Cada foto una sola vez; si Claude se equivoca, se usa el orden en que se subieron
let placas = (Array.isArray(d.placas) ? d.placas : [])
  .map(p => ({ foto: Number(p.foto), texto: String(p.texto || '').trim() }))
  .filter(p => Number.isInteger(p.foto) && p.foto >= 1 && p.foto <= n);
const vistas = new Set(placas.map(p => p.foto));
if (placas.length !== n || vistas.size !== n) {
  placas = c.archivos.map((_, i) => ({ foto: i + 1, texto: (placas.find(p => p.foto === i + 1) || {}).texto || '' }));
}
if (c.tipo === 'foto') placas = [{ foto: 1, texto: '' }];

const hashtags = [...new Set([...(datos.hashtags_base || []), ...(d.hashtags || [])])].join(' ');
const limpio = String(d.titulo || 'fotos').replace(/[\\/:*?"<>|]/g, '').slice(0, 60).trim();
return [{ json: {
  titulo: d.titulo,
  gancho: d.gancho,
  placas,
  caption: [String(d.caption || '').trim(), datos.pie_caption].filter(Boolean).join('\n\n'),
  hashtags,
  nombre_archivo: `${c.fecha} - ${limpio}`,
}}];
"""

with open(os.path.join(AQUI, 'fotos_comandos.js'), encoding='utf-8') as f:
    ARMAR_EDICION = f.read()

JUNTAR = r"""// === Junta lo que se subió a Drive: qué es cada archivo y su id ===
const salidas = [];
for (const it of $input.all()) {
  const nombre = String(it.json.name || '');
  const id = it.json.id;
  let m;
  if (/ - post\.jpg$/.test(nombre)) salidas.push({ tipo: 'post', n: 1, file_id: id });
  else if (/ - historia\.jpg$/.test(nombre)) salidas.push({ tipo: 'historia', n: 1, file_id: id });
  else if ((m = nombre.match(/ - placa-(\d+)\.jpg$/))) salidas.push({ tipo: 'placa', n: Number(m[1]), file_id: id });
}
const peso = { post: 0, placa: 1, historia: 2 };
salidas.sort((a, b) => peso[a.tipo] - peso[b.tipo] || a.n - b.n);
if (!salidas.length) throw new Error('No se subió ninguna pieza a Drive');
const ver = id => `https://drive.google.com/file/d/${id}/view`;
const nombres = { post: 'Post', historia: 'Historia', placa: 'Placa' };
const links = salidas.map(s => `${nombres[s.tipo]}${s.tipo === 'placa' ? ' ' + s.n : ''}: ${ver(s.file_id)}`).join('\n');
return [{ json: { salidas, links } }];
"""

TERMINAR_BODY = """={{ JSON.stringify({
  p_reel_id: $('Config de las fotos').first().json.reel_id,
  p_titulo: $('Leer respuesta de Claude').first().json.titulo,
  p_caption: $('Leer respuesta de Claude').first().json.caption,
  p_hashtags: $('Leer respuesta de Claude').first().json.hashtags,
  p_salidas: $('Juntar piezas').first().json.salidas
}) }}"""

MAIL = ("=¡Hola! Ya está listo tu {{ $('Config de las fotos').first().json.tipo === 'carrusel' ? 'carrusel' : 'post con historia' }}.\n\n"
        "{{ $('Juntar piezas').first().json.links }}\n\n"
        "Caption para pegar:\n{{ $('Leer respuesta de Claude').first().json.caption }}\n\n"
        "{{ $('Leer respuesta de Claude').first().json.hashtags }}\n\n"
        "{{ $('Config de las fotos').first().json.link_pagina ? 'También lo tenés en tu página: ' + $('Config de las fotos').first().json.link_pagina : '' }}\n\n"
        "Revisalo antes de publicarlo. Si algo no te gusta, avisanos.\n"
        "— {{ $('Config de las fotos').first().json.nombre_servicio }}")


def rpc(nombre, funcion, body):
    return {
        'parameters': {
            'method': 'POST', 'url': SUPA + funcion,
            'authentication': 'predefinedCredentialType', 'nodeCredentialType': 'supabaseApi',
            'sendBody': True, 'specifyBody': 'json', 'jsonBody': body, 'options': {'timeout': 30000},
        },
        'name': nombre, 'type': 'n8n-nodes-base.httpRequest', 'typeVersion': 4.2, 'credentials': CRED_SUPA,
    }


def code(nombre, js, **extra):
    return {'parameters': {'jsCode': js}, 'name': nombre, 'type': 'n8n-nodes-base.code', 'typeVersion': 2, **extra}


def comando(nombre, cmd, **extra):
    return {'parameters': {'command': cmd}, 'name': nombre, 'type': 'n8n-nodes-base.executeCommand',
            'typeVersion': 1, **extra}


def bajar(nombre, file_id):
    return {'parameters': {'operation': 'download', 'fileId': {'__rl': True, 'value': file_id, 'mode': 'id'},
                           'options': {}},
            'name': nombre, 'type': 'n8n-nodes-base.googleDrive', 'typeVersion': 3, 'credentials': CRED_DRIVE}


def guardar(nombre, ruta):
    return {'parameters': {'operation': 'write', 'fileName': ruta, 'dataPropertyName': 'data', 'options': {}},
            'name': nombre, 'type': 'n8n-nodes-base.readWriteFile', 'typeVersion': 1}


def leer(nombre, selector, **extra):
    return {'parameters': {'operation': 'read', 'fileSelector': selector, 'options': {}},
            'name': nombre, 'type': 'n8n-nodes-base.readWriteFile', 'typeVersion': 1, **extra}


CFG = "$('Config de las fotos').first().json"

nodos = [
    {'parameters': {'rule': {'interval': [{'field': 'minutes', 'minutesInterval': 2}]}},
     'name': 'Cada 2 minutos', 'type': 'n8n-nodes-base.scheduleTrigger', 'typeVersion': 1.2},
    rpc('Tomar siguiente foto', 'tomar_siguiente_foto', '{}'),
    code('Config de las fotos', CONFIG),
    comando('Preparar carpeta de trabajo', '=mkdir -p "{{ ' + CFG + '.dir }}"'),
    code('Datos del negocio', DATOS_NEGOCIO),
    bajar('Bajar logo', '={{ ' + CFG + '.logo_id }}'),
    guardar('Guardar logo en disco', '={{ ' + CFG + '.dir }}/logo.png'),
    bajar('Bajar fuente', '={{ ' + CFG + '.fuente_id }}'),
    guardar('Guardar fuente en disco', '={{ ' + CFG + '.dir }}/fuente.ttf'),
    code('Un ítem por foto', UN_ITEM_POR_FOTO),
    bajar('Bajar foto', '={{ $json.file_id }}'),
    guardar('Guardar foto en disco', "={{ $('Un ítem por foto').item.json.ruta }}"),
    comando('Achicar fotos para Claude', '={{ ' + CFG + '.cmd_achicar }}', executeOnce=True),
    leer('Leer fotos chicas', '={{ ' + CFG + '.dir }}/chica-*.jpg'),
    code('Armar pedido a Claude', PEDIDO_CLAUDE),
    {
        'parameters': {
            'method': 'POST', 'url': 'https://api.anthropic.com/v1/messages',
            'authentication': 'predefinedCredentialType', 'nodeCredentialType': 'anthropicApi',
            'sendHeaders': True,
            'headerParameters': {'parameters': [
                {'name': 'anthropic-version', 'value': '2026-10-21'},
                {'name': 'content-type', 'value': 'application/json'},
            ]},
            'sendBody': True, 'specifyBody': 'json', 'jsonBody': '={{ JSON.stringify($json.body) }}',
            'options': {'timeout': 180000},
        },
        'name': 'Claude: textos de las fotos', 'type': 'n8n-nodes-base.httpRequest', 'typeVersion': 4.2,
        'credentials': CRED_CLAUDE,
    },
    code('Leer respuesta de Claude', LEER_CLAUDE),
    code('Armar edición de fotos', ARMAR_EDICION),
    comando('Editar fotos (FFmpeg)', '={{ $json.cmd }}'),
    leer('Leer piezas listas', '={{ ' + CFG + '.dir }}/salida/*.jpg', executeOnce=True),
    {
        'parameters': {
            'name': "={{ $('Leer respuesta de Claude').first().json.nombre_archivo }} - {{ $binary.data.fileName }}",
            'driveId': {'__rl': True, 'mode': 'list', 'value': 'My Drive'},
            'folderId': {'__rl': True, 'mode': 'id',
                         'value': "={{ String($binary.data.fileName).startsWith('historia') ? " + CFG +
                                  ".carpeta_historias_id : " + CFG + ".carpeta_feed_id }}"},
            'inputDataFieldName': 'data', 'options': {},
        },
        'name': 'Subir piezas a Listos', 'type': 'n8n-nodes-base.googleDrive', 'typeVersion': 3,
        'credentials': CRED_DRIVE,
    },
    code('Juntar piezas', JUNTAR),
    rpc('Marcar fotos listas', 'terminar_foto', TERMINAR_BODY),
    {
        'parameters': {
            'sendTo': '={{ ' + CFG + '.email_aviso }}',
            'subject': "=📸 Listo: {{ $('Leer respuesta de Claude').first().json.titulo }}",
            'emailType': 'text',
            'message': MAIL,
            'options': {'appendAttribution': False},
        },
        'name': 'Avisar por mail', 'type': 'n8n-nodes-base.gmail', 'typeVersion': 2.1, 'credentials': CRED_GMAIL,
        'executeOnce': True,
    },
    comando('Limpiar archivos temporales', '=rm -rf "{{ ' + CFG + '.dir }}"', executeOnce=True),
]


def main(salida):
    conexiones = {}
    for i, n in enumerate(nodos):
        n['id'] = nid(n['name'])
        n['position'] = [i * 220, 300]
        if i + 1 < len(nodos):
            conexiones[n['name']] = {'main': [[{'node': nodos[i + 1]['name'], 'type': 'main', 'index': 0}]]}
    flujo = {
        'name': 'Fotos: Crudo a Listos (todos los clientes) v1.0',
        'nodes': nodos,
        'connections': conexiones,
        'settings': {'executionOrder': 'v1', 'saveDataErrorExecution': 'all',
                     'timezone': 'America/Argentina/Buenos_Aires'},
        'pinData': {},
    }
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump(flujo, f, ensure_ascii=False, indent=2)
    print('ok', len(nodos), 'nodos')


if __name__ == '__main__':
    main(sys.argv[1])
