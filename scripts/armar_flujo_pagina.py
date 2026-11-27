"""Arma el flujo de n8n que atiende la página "Subir" de cada cliente.

Uso: python3 scripts/armar_flujo_pagina.py n8n/pagina-subida-api.json

La página (docs/subir/index.html, publicada en Netlify) llama a un solo webhook
con { accion, t, ... }:
  - info       -> datos del cliente, cupo y sus pedidos
  - preparar   -> anota el pedido y abre una subida reanudable en el Drive del cliente
                  por cada archivo; devuelve las direcciones para subir
  - confirmar  -> marca el pedido como subido (pasa a la fila de edición)
El archivo va directo del navegador a Google Drive: n8n no lo toca.
"""
import json
import sys
import uuid

SUPABASE = 'https://smmmbtmhcceivjipnfxe.supabase.co'
ORIGEN_PAGINA = 'https://dccconsultoriait-png.github.io'


def nid(nombre):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'multiredes-pagina/' + nombre))


LEER_PEDIDO = r"""// Lee lo que manda la página y arma la llamada a Supabase
// La página manda un formulario con un campo "d" que trae el JSON
const leer = x => { if (typeof x !== 'string') return x; try { return JSON.parse(x); } catch (e) { return null; } };
const body = leer($json.body ?? {}) || {};
const query = $json.query || {};
let b = leer(body.d) || leer(query.d) || body;
if (!b || typeof b !== 'object') b = {};
const t = /^[0-9a-f-]{36}$/i.test(String(b.t || '')) ? String(b.t) : '00000000-0000-0000-0000-000000000000';
const accion = ['info', 'preparar', 'confirmar'].includes(b.accion) ? b.accion : 'info';
const origin = String(($json.headers || {}).origin || '__ORIGEN__');

let rpc, cuerpo;
if (accion === 'preparar') {
  rpc = 'preparar_subida';
  cuerpo = { p_token: t, p_tipo: String(b.tipo || ''), p_nota: String(b.nota || '').slice(0, 1000),
             p_archivos: Array.isArray(b.archivos) ? b.archivos.slice(0, 10) : [] };
} else if (accion === 'confirmar') {
  rpc = 'confirmar_subida';
  cuerpo = { p_token: t, p_pedido_id: /^[0-9a-f-]{36}$/i.test(String(b.pedido_id || '')) ? b.pedido_id : '00000000-0000-0000-0000-000000000000',
             p_archivos: Array.isArray(b.archivos) ? b.archivos.slice(0, 10) : [] };
} else {
  rpc = 'pagina_cliente';
  cuerpo = { p_token: t };
}
return [{ json: { accion, rpc, cuerpo, nota: String(b.nota || '').slice(0, 1000), origin } }];
""".replace('__ORIGEN__', ORIGEN_PAGINA)

UN_ITEM_POR_ARCHIVO = r"""// Una subida en Drive por cada archivo del pedido
const r = $input.first().json;
const p = $('Leer pedido').first().json;
return r.archivos.map(a => ({ json: {
  nombre: a.nombre, mime: a.mime, tamano: a.tamano,
  carpeta: r.carpeta_id, nota: p.nota, origin: p.origin,
} }));
"""

ARMAR_RESPUESTA = r"""// Devuelve a la página adónde subir cada archivo
const r = $('Llamar a Supabase').first().json;
const subidas = $input.all();
const archivos = r.archivos.map((a, i) => {
  const h = (subidas[i] && subidas[i].json.headers) || {};
  return { nombre: a.nombre, url: h.location || h.Location || null };
});
if (archivos.some(a => !a.url)) {
  return [{ json: { ok: false, error: 'No pude abrir la subida en Drive' } }];
}
return [{ json: { ok: true, pedido_id: r.pedido_id, archivos } }];
"""


def main(salida):
    nodos = [
        {
            'parameters': {
                'httpMethod': 'POST',
                'path': 'multiredes-api',
                'responseMode': 'responseNode',
                'options': {'allowedOrigins': '*'},  # la API se protege con el token de cada cliente
            },
            'name': 'Pedido de la página',
            'type': 'n8n-nodes-base.webhook',
            'typeVersion': 2,
            'webhookId': nid('webhook'),
        },
        {
            'parameters': {'jsCode': LEER_PEDIDO},
            'name': 'Leer pedido',
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
        },
        {
            'parameters': {
                'method': 'POST',
                'url': '=' + SUPABASE + '/rest/v1/rpc/{{ $json.rpc }}',
                'authentication': 'predefinedCredentialType',
                'nodeCredentialType': 'supabaseApi',
                'sendBody': True,
                'specifyBody': 'json',
                'jsonBody': '={{ JSON.stringify($json.cuerpo) }}',
                'options': {'timeout': 30000},
            },
            'name': 'Llamar a Supabase',
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'credentials': {'supabaseApi': {'id': '', 'name': 'Supabase account'}},
        },
        {
            'parameters': {
                'conditions': {
                    'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose'},
                    'conditions': [{
                        'id': nid('cond'),
                        'leftValue': "={{ $('Leer pedido').item.json.accion === 'preparar' && $json.ok === true }}",
                        'rightValue': True,
                        'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True},
                    }],
                    'combinator': 'and',
                },
                'options': {},
            },
            'name': '¿Hay que abrir subidas?',
            'type': 'n8n-nodes-base.if',
            'typeVersion': 2,
        },
        {
            'parameters': {'jsCode': UN_ITEM_POR_ARCHIVO},
            'name': 'Un ítem por archivo',
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
        },
        {
            'parameters': {
                'method': 'POST',
                'url': 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true',
                'authentication': 'predefinedCredentialType',
                'nodeCredentialType': 'googleDriveOAuth2Api',
                'sendHeaders': True,
                'headerParameters': {'parameters': [
                    {'name': 'X-Upload-Content-Type', 'value': '={{ $json.mime }}'},
                    {'name': 'X-Upload-Content-Length', 'value': '={{ String($json.tamano) }}'},
                    {'name': 'Origin', 'value': '={{ $json.origin }}'},
                ]},
                'sendBody': True,
                'specifyBody': 'json',
                'jsonBody': '={{ JSON.stringify({ name: $json.nombre, parents: [$json.carpeta], description: $json.nota }) }}',
                'options': {
                    'response': {'response': {'fullResponse': True}},
                    'timeout': 30000,
                },
            },
            'name': 'Abrir subida en Drive',
            'type': 'n8n-nodes-base.httpRequest',
            'typeVersion': 4.2,
            'credentials': {'googleDriveOAuth2Api': {'id': '', 'name': 'Google Drive account'}},
        },
        {
            'parameters': {'jsCode': ARMAR_RESPUESTA},
            'name': 'Armar respuesta',
            'type': 'n8n-nodes-base.code',
            'typeVersion': 2,
        },
        {
            'parameters': {
                'respondWith': 'json',
                'responseBody': '={{ JSON.stringify($json) }}',
                'options': {},
            },
            'name': 'Responder a la página',
            'type': 'n8n-nodes-base.respondToWebhook',
            'typeVersion': 1.1,
        },
    ]
    for i, n in enumerate(nodos):
        n['id'] = nid(n['name'])
        n['position'] = [i * 240, 300]
    # la respuesta va abajo, para que las dos flechas se vean
    nodos[-1]['position'] = [7 * 240, 520]

    def a(destino, idx=0):
        return {'node': destino, 'type': 'main', 'index': idx}

    conexiones = {
        'Pedido de la página': {'main': [[a('Leer pedido')]]},
        'Leer pedido': {'main': [[a('Llamar a Supabase')]]},
        'Llamar a Supabase': {'main': [[a('¿Hay que abrir subidas?')]]},
        '¿Hay que abrir subidas?': {'main': [[a('Un ítem por archivo')], [a('Responder a la página')]]},
        'Un ítem por archivo': {'main': [[a('Abrir subida en Drive')]]},
        'Abrir subida en Drive': {'main': [[a('Armar respuesta')]]},
        'Armar respuesta': {'main': [[a('Responder a la página')]]},
    }
    flujo = {
        'name': 'Multiredes: página de subida (API) v1.0',
        'nodes': nodos,
        'connections': conexiones,
        'settings': {'executionOrder': 'v1', 'timezone': 'America/Argentina/Buenos_Aires',
                     'saveDataErrorExecution': 'all', 'saveDataSuccessExecution': 'all'},
        'pinData': {},
    }
    with open(salida, 'w', encoding='utf-8') as f:
        json.dump(flujo, f, ensure_ascii=False, indent=2)
    print('ok', len(nodos), 'nodos')


if __name__ == '__main__':
    main(sys.argv[1])
