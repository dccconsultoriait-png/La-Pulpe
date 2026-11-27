"""Arma el flujo de n8n "Alta, cobro y baja" (un solo flujo, tres disparadores).

Uso: python3 scripts/armar_flujo_alta.py n8n/alta-cobro-baja.json

1. Formulario de alta (docs/subir/alta.html) -> webhook "multiredes-alta"
   - accion "planes": devuelve los planes
   - accion "alta": anota al cliente (pendiente de pago) y crea el cobro en Mercado Pago:
       planes mensuales -> suscripción (débito automático cada mes)
       Prueba           -> pago único
     devuelve la dirección de Mercado Pago para pagar
2. Aviso de Mercado Pago -> webhook "multiredes-mp"
   - vuelve a pedir el pago o la suscripción a Mercado Pago (no confía en lo que llega)
   - pago aprobado por primera vez: crea las carpetas en Drive, sube el logo y manda el mail de bienvenida
   - pagos siguientes: mail de "recibimos tu pago"; suscripción cancelada: mail de aviso
3. Revisión diaria (9 h): gracia, pausa y baja según lo que diga Supabase; en la baja cancela la suscripción
"""
import json
import sys
import uuid

SUPA = 'https://smmmbtmhcceivjipnfxe.supabase.co/rest/v1/rpc/'
MP = 'https://api.mercadopago.com'
WEBHOOK_MP = 'https://n8n-fg3m.srv2056463.hstgr.cloud/webhook/multiredes-mp'
CRED_SUPA = {'supabaseApi': {'id': '', 'name': 'Supabase (clientes)'}}
CRED_DRIVE = {'googleDriveOAuth2Api': {'id': '', 'name': 'Google Drive (La Pulpe)'}}
CRED_GMAIL = {'gmailOAuth2': {'id': '', 'name': 'Gmail DCC'}}
CRED_MP = {'httpHeaderAuth': {'id': '', 'name': 'Mercado Pago (prueba)'}}


def nid(nombre):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'multiredes-alta/' + nombre))


# Devuelve lo que contestó Supabase, venga como objeto o envuelto con el nombre de la función
DESENVOLVER = r"""const desenvolver = j => {
  if (j && typeof j === 'object' && !Array.isArray(j)) {
    const k = Object.keys(j);
    if (k.length === 1 && j[k[0]] && typeof j[k[0]] === 'object') return j[k[0]];
  }
  return j || {};
};
"""

# ---------------------------------------------------------------- 1. Alta
LEER_FORMULARIO = r"""// Lee lo que manda el formulario: un campo "d" con el JSON
const leer = x => { if (typeof x !== 'string') return x; try { return JSON.parse(x); } catch (e) { return null; } };
const body = leer($input.first().json.body ?? {}) || {};
let b = leer(body.d) || leer(($input.first().json.query || {}).d) || body;
if (!b || typeof b !== 'object') b = {};
const accion = b.accion === 'alta' ? 'alta' : 'planes';
if (accion === 'planes') return [{ json: { accion, rpc: 'planes_publicos', cuerpo: {} } }];
const d = (b.datos && typeof b.datos === 'object') ? b.datos : {};
const txt = (v, n) => String(v ?? '').slice(0, n);
return [{ json: {
  accion, rpc: 'registrar_alta',
  email_mp: txt(b.email_mp, 120).trim().toLowerCase(),
  cuerpo: {
    p_email: txt(b.email, 120), p_plan: txt(b.plan, 40),
    p_datos: { nombre: txt(d.nombre, 80), rubro: txt(d.rubro, 200), descripcion: txt(d.descripcion, 400),
               tono: txt(d.tono, 200), telefono: txt(d.telefono, 40), instagram: txt(d.instagram, 60),
               direccion: txt(d.direccion, 120), horario: txt(d.horario, 120) },
    p_logo_b64: txt(b.logo, 4000001), p_logo_mime: txt(b.logo_mime || 'image/png', 40),
  },
} }];
"""

QUE_SIGUE = DESENVOLVER + r"""// Decide: contestar ya (planes o error) o crear el cobro en Mercado Pago
const f = $('Leer formulario').first().json;
const r = desenvolver($input.first().json);
if (f.accion === 'planes') {
  // Supabase devuelve una lista: n8n la parte en un ítem por plan
  let planes = $input.all().map(i => i.json);
  if (planes.length === 1 && !planes[0].id) {
    const v = planes[0].planes_publicos || planes[0].data;
    planes = Array.isArray(v) ? v : [];
  }
  return [{ json: { cobrar: false, resp: { ok: true, planes } } }];
}
if (!r.ok) return [{ json: { cobrar: false, resp: { ok: false, error: r.error || 'No se pudo hacer el alta' } } }];
if (!r.url_pagina) return [{ json: { cobrar: false, resp: { ok: false, error: 'Falta url_pagina en la configuración' } } }];

const p = r.plan;
const volver = r.url_pagina + '/gracias.html';
let mp_url, mp_body;
if (p.mensual) {
  // Suscripción: Mercado Pago le cobra solo cada mes
  mp_url = '__MP__/preapproval';
  mp_body = {
    reason: `${r.servicio} - Plan ${p.nombre}`,
    external_reference: r.business_id,
    payer_email: f.email_mp || r.email,
    auto_recurring: { frequency: 1, frequency_type: 'months', transaction_amount: Number(p.precio), currency_id: 'ARS' },
    back_url: volver,
    status: 'pending',
  };
} else {
  // Prueba: pago único
  mp_url = '__MP__/checkout/preferences';
  mp_body = {
    items: [{ id: p.id, title: `${r.servicio} - ${p.nombre}`, quantity: 1, unit_price: Number(p.precio), currency_id: 'ARS' }],
    external_reference: r.business_id,
    back_urls: { success: volver, failure: volver, pending: volver },
    auto_return: 'approved',
    notification_url: '__WEBHOOK_MP__',
    statement_descriptor: String(r.servicio).toUpperCase().slice(0, 13),
  };
}
return [{ json: { cobrar: true, mensual: p.mensual, business_id: r.business_id, mp_url, mp_body } }];
""".replace('__MP__', MP).replace('__WEBHOOK_MP__', WEBHOOK_MP)

LEER_COBRO = r"""// Lo que contestó Mercado Pago: la dirección para pagar
const a = $('¿Qué sigue con el alta?').first().json;
const m = $input.first().json || {};
const url = m.init_point || m.sandbox_init_point;
if (!url) {
  const motivo = m.message || m.error || 'sin detalle';
  return [{ json: { guardar: false, resp: { ok: false, error: 'Mercado Pago no aceptó el cobro (' + motivo + '). Probá de nuevo en un rato.' } } }];
}
return [{ json: { guardar: a.mensual === true, cuerpo: { p_business_id: a.business_id, p_preapproval_id: String(m.id || '') },
                  resp: { ok: true, url } } }];
"""

RESPUESTA_FINAL = r"""return [{ json: { resp: $('Leer respuesta de Mercado Pago').first().json.resp } }];
"""

# ---------------------------------------------------------------- 2. Avisos de Mercado Pago
QUE_AVISO = r"""// Mercado Pago avisa "qué cambió" (tipo + id). Acá solo se arma a dónde preguntar.
const body = (typeof $input.first().json.body === 'object' && $input.first().json.body) || {};
const q = $input.first().json.query || {};
const tipo = String(body.type || body.topic || q.type || q.topic || '');
const id = String((body.data && body.data.id) || q['data.id'] || q.id || body.id || '');
if (!/^[A-Za-z0-9-]{1,64}$/.test(id)) return [];
const rutas = {
  payment: '/v1/payments/',
  subscription_authorized_payment: '/authorized_payments/',
  subscription_preapproval: '/preapproval/',
  preapproval: '/preapproval/',
};
if (!rutas[tipo]) return [];   // otros avisos (merchant_order, planes, etc.) no hacen falta
return [{ json: { tipo, id, url: '__MP__' + rutas[tipo] + id } }];
""".replace('__MP__', MP)

ENTENDER_AVISO = r"""// Pasa lo que dice Mercado Pago a una llamada a Supabase
const a = $('¿Qué avisó Mercado Pago?').first().json;
const m = $input.first().json || {};
if (!m.id) return [];   // Mercado Pago no lo encontró (por ejemplo, un aviso de prueba del panel)
if (a.tipo === 'payment') {
  const pre = (m.metadata && (m.metadata.preapproval_id || m.metadata.subscription_id)) || '';
  return [{ json: { rpc: 'registrar_pago', cuerpo: {
    p_mp_payment_id: String(m.id), p_business_id: String(m.external_reference || ''), p_preapproval_id: String(pre),
    p_monto: Number(m.transaction_amount || 0), p_estado: String(m.status || ''),
    p_detalle: { origen: 'payment', detalle: m.status_detail || null, medio: m.payment_type_id || null } } } }];
}
if (a.tipo === 'subscription_authorized_payment') {
  if (!m.payment || !m.payment.id) return [];   // cuota programada que todavía no se cobró
  return [{ json: { rpc: 'registrar_pago', cuerpo: {
    p_mp_payment_id: String(m.payment.id), p_business_id: String(m.external_reference || ''),
    p_preapproval_id: String(m.preapproval_id || ''), p_monto: Number(m.transaction_amount || 0),
    p_estado: String(m.payment.status || ''),
    p_detalle: { origen: 'authorized_payment', cuota: String(m.id), estado_cuota: m.status || null } } } }];
}
return [{ json: { rpc: 'actualizar_suscripcion', cuerpo: {
  p_preapproval_id: String(m.id), p_business_id: String(m.external_reference || ''), p_estado: String(m.status || '') } } }];
"""

QUE_HACER = DESENVOLVER + r"""// Según lo que anotó Supabase: bienvenida, aviso de pago, aviso de cancelación o nada
const r = desenvolver($input.first().json);
if (!r.ok) {
  if (r.error) console.log('Aviso de Mercado Pago sin cliente:', r.error);
  return [];
}
const serv = r.servicio || 'Multiredes';
const firma = `\n\nCualquier duda, respondé este mail.\n${serv}`;
if (r.aprobado_nuevo && r.primera_vez) {
  const link = `${r.url_pagina}/?t=${r.token_subida}`;
  const cupo = r.total ? `${r.total} piezas hasta el ${r.hasta}` : `${r.por_semana} piezas por semana (de lunes a domingo)`;
  const baja = r.total
    ? 'La Prueba termina sola: no se te va a cobrar nada más.'
    : 'Se cobra solo cada mes por Mercado Pago. Si querés darte de baja, la cancelás cuando quieras desde Mercado Pago > Suscripciones.';
  return [{ json: {
    que: 'bienvenida', business_id: r.business_id, email: r.email, bcc: r.email_admin || '',
    carpeta: `${serv} - ${r.nombre}`, padre: r.carpeta_clientes_id || 'root',
    logo_b64: r.logo_b64 || '', logo_mime: r.logo_mime || 'image/png',
    asunto: `¡Bienvenidos a ${serv}! Tu link para subir videos y fotos`,
    texto: `¡Hola, ${r.nombre}!\n\nYa está todo listo. Tu plan: ${r.plan}, ${cupo}.\n\n` +
           `Este es tu link personal para subir videos y fotos:\n${link}\n\n` +
           'Guardá este mail y no compartas el link: es solo tuyo.\n\n' +
           'Cómo funciona:\n' +
           '1. Abrís el link y subís tus videos o fotos, tal como salen del celular.\n' +
           '2. Si querés, nos dejás una nota (una promo, un evento, un sorteo).\n' +
           '3. Te los devolvemos listos para Instagram, TikTok y Facebook: te llega un mail y los ves en la pestaña "Listos".\n\n' +
           'Un video o una foto es 1 pieza; un carrusel (de 2 a 10 fotos) son 2.\n\n' + baja + firma,
  } }];
}
if (r.aprobado_nuevo) {
  const texto = r.reactivado
    ? `¡Hola, ${r.nombre}! Recibimos tu pago y tu cuenta volvió a estar activa hasta el ${r.hasta}. Ya podés seguir subiendo con tu link de siempre.`
    : `¡Hola, ${r.nombre}! Recibimos tu pago. Tu plan ${r.plan} sigue activo hasta el ${r.hasta}.`;
  return [{ json: { que: 'aviso', email: r.email, bcc: r.email_admin || '',
                    asunto: r.reactivado ? `Tu cuenta de ${serv} está activa otra vez` : `Recibimos tu pago - ${serv}`,
                    texto: texto + firma } }];
}
// (si ya estaba de baja o nunca pagó, no hace falta avisar)
if (r.cambio && r.estado === 'cancelled' && ['activo', 'en_gracia', 'pausado'].includes(r.estado_cliente)) {
  return [{ json: { que: 'aviso', email: r.email, bcc: r.email_admin || '',
                    asunto: `Se canceló tu suscripción a ${serv}`,
                    texto: `¡Hola, ${r.nombre}! Se canceló tu suscripción en Mercado Pago: no se te va a cobrar más.\n\n` +
                           (r.hasta ? `Podés seguir subiendo contenido hasta el ${r.hasta}. ` : '') +
                           'Si te arrepentís, te podés volver a sumar cuando quieras.' + firma } }];
}
return [];
"""

PREPARAR_LOGO = r"""// El logo que llegó en el formulario pasa a ser un archivo
const n = $('¿Qué hay que hacer?').first().json;
if (!n.logo_b64) return [];   // no hay logo guardado: se sigue sin él
const ext = n.logo_mime === 'image/jpeg' ? 'jpg' : 'png';
const data = await this.helpers.prepareBinaryData(Buffer.from(n.logo_b64, 'base64'), 'logo.' + ext, n.logo_mime);
return [{ json: {}, binary: { data } }];
"""

JUNTAR_CARPETAS = r"""// Junta los ids de las carpetas para guardarlos en Supabase
const id = nombre => { try { return $(nombre).first().json.id || ''; } catch (e) { return ''; } };
let logo = '';
try { logo = $('Subir logo a Recursos').first().json.id || ''; } catch (e) { logo = ''; }
return [{ json: { cuerpo: {
  p_business_id: $('¿Qué hay que hacer?').first().json.business_id,
  p_raiz: id('Crear carpeta del cliente'), p_crudo: id('Crear Crudo'), p_reels: id('Crear Reels'),
  p_historias: id('Crear Historias'), p_feed: id('Crear Feed'), p_recursos: id('Crear Recursos'), p_logo: logo,
} } }];
"""

# ---------------------------------------------------------------- 3. Revisión diaria
AVISOS_DEL_DIA = DESENVOLVER + r"""// Un mail por cada cliente que cambió de estado hoy
const out = [];
for (const it of $input.all()) {
  const lista = Array.isArray(it.json) ? it.json : (Array.isArray(it.json.revision_diaria) ? it.json.revision_diaria : [it.json]);
  for (const x of lista) {
    const r = desenvolver(x);
    if (!r || !r.accion || !r.email) continue;
    const serv = r.servicio || 'Multiredes';
    const firma = `\n\nCualquier duda, respondé este mail.\n${serv}`;
    const t = {
      gracia: [`No pudimos cobrar tu plan de ${serv}`,
        `¡Hola, ${r.nombre}! Mercado Pago no pudo cobrar este mes. Revisá tu medio de pago en Mercado Pago > Suscripciones.\n\n` +
        `Te damos ${r.dias} días para resolverlo: mientras tanto podés seguir subiendo como siempre.`],
      fin_prueba: [`Terminó tu Prueba de ${serv}`,
        `¡Hola, ${r.nombre}! Terminó tu semana de Prueba. Esperamos que te haya gustado.\n\n` +
        'Si querés seguir, elegí un plan mensual en el mismo formulario del alta, con el mismo email: tus carpetas y tu link siguen siendo los mismos.'],
      fin_suscripcion: [`Terminó tu plan de ${serv}`,
        `¡Hola, ${r.nombre}! Terminó el período que tenías pago. Tu cuenta queda en pausa: no se borra nada.\n\n` +
        'Si querés volver, sumate de nuevo con el mismo email.'],
      pausa: [`Tu cuenta de ${serv} quedó en pausa`,
        `¡Hola, ${r.nombre}! No pudimos cobrar tu plan, así que tu cuenta quedó en pausa: por ahora no se editan videos ni fotos nuevos. No se borra nada.\n\n` +
        `Cuando Mercado Pago logre cobrar, se activa sola otra vez. Si en ${r.dias} días sigue sin pago, se da de baja.`],
      baja: [`Te dimos de baja de ${serv}`,
        `¡Hola, ${r.nombre}! Como tu cuenta estuvo un mes en pausa sin pago, la dimos de baja y cancelamos la suscripción: no se te va a cobrar nada más.\n\n` +
        'Tus archivos siguen en tus carpetas. Si querés volver, sumate de nuevo con el mismo email.'],
    }[r.accion];
    if (!t) continue;
    out.push({ json: { accion: r.accion, email: r.email, bcc: r.email_admin || '', asunto: t[0], texto: t[1] + firma,
                       cancelar: r.accion === 'baja' && r.preapproval ? String(r.preapproval) : '' } });
  }
}
return out;
"""


# ---------------------------------------------------------------- nodos
def code(nombre, js, **extra):
    return {'parameters': {'jsCode': js}, 'name': nombre, 'type': 'n8n-nodes-base.code', 'typeVersion': 2, **extra}


def rpc(nombre, funcion, body='={{ JSON.stringify($json.cuerpo) }}'):
    return {
        'parameters': {
            'method': 'POST', 'url': ('=' + SUPA + '{{ $json.rpc }}') if funcion is None else SUPA + funcion,
            'authentication': 'predefinedCredentialType', 'nodeCredentialType': 'supabaseApi',
            'sendBody': True, 'specifyBody': 'json', 'jsonBody': body, 'options': {'timeout': 30000},
        },
        'name': nombre, 'type': 'n8n-nodes-base.httpRequest', 'typeVersion': 4.2, 'credentials': CRED_SUPA,
    }


def mp(nombre, metodo, url, body=None, **extra):
    p = {
        'method': metodo, 'url': url,
        'authentication': 'genericCredentialType', 'genericAuthType': 'httpHeaderAuth',
        # se lee la respuesta aunque Mercado Pago conteste con error, para decidir qué hacer
        'options': {'timeout': 30000, 'response': {'response': {'neverError': True}}},
    }
    if body:
        p.update({'sendBody': True, 'specifyBody': 'json', 'jsonBody': body})
    return {'parameters': p, 'name': nombre, 'type': 'n8n-nodes-base.httpRequest', 'typeVersion': 4.2,
            'credentials': CRED_MP, **extra}


def si(nombre, expresion):
    return {
        'parameters': {
            'conditions': {
                'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose'},
                'conditions': [{'id': nid(nombre + '/cond'), 'leftValue': '={{ ' + expresion + ' }}', 'rightValue': True,
                                'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True}}],
                'combinator': 'and',
            },
            'options': {},
        },
        'name': nombre, 'type': 'n8n-nodes-base.if', 'typeVersion': 2,
    }


def carpeta(nombre, titulo, padre):
    return {
        'parameters': {
            'resource': 'folder', 'name': titulo,
            'driveId': {'__rl': True, 'mode': 'list', 'value': 'My Drive'},
            'folderId': {'__rl': True, 'mode': 'id', 'value': padre},
            'options': {},
        },
        'name': nombre, 'type': 'n8n-nodes-base.googleDrive', 'typeVersion': 3, 'credentials': CRED_DRIVE,
    }


def mail(nombre, base):
    return {
        'parameters': {
            'sendTo': '={{ ' + base + '.email }}',
            'subject': '={{ ' + base + '.asunto }}',
            'emailType': 'text',
            'message': '={{ ' + base + '.texto }}',
            'options': {'appendAttribution': False, 'bccList': '={{ ' + base + '.bcc }}'},
        },
        'name': nombre, 'type': 'n8n-nodes-base.gmail', 'typeVersion': 2.1, 'credentials': CRED_GMAIL,
    }


def responder():
    return {
        'parameters': {'respondWith': 'json', 'responseBody': '={{ JSON.stringify($json.resp) }}', 'options': {}},
        'name': 'Responder al formulario', 'type': 'n8n-nodes-base.respondToWebhook', 'typeVersion': 1.1,
    }


NUEVO = "$('¿Qué hay que hacer?').first().json"
RAIZ = "={{ $('Crear carpeta del cliente').first().json.id }}"
LISTOS = "={{ $('Crear Listos').first().json.id }}"

# (nodo, columna, fila)
fila_alta = [
    ({'parameters': {'httpMethod': 'POST', 'path': 'multiredes-alta', 'responseMode': 'responseNode',
                     'options': {'allowedOrigins': '*'}},
      'name': 'Formulario de alta', 'type': 'n8n-nodes-base.webhook', 'typeVersion': 2,
      'webhookId': nid('webhook-alta')}, 0, 0),
    (code('Leer formulario', LEER_FORMULARIO), 1, 0),
    (rpc('Supabase: planes o alta', None), 2, 0),
    (code('¿Qué sigue con el alta?', QUE_SIGUE), 3, 0),
    (si('¿Hay que crear el cobro?', '$json.cobrar === true'), 4, 0),
    (mp('Mercado Pago: crear el cobro', 'POST', '={{ $json.mp_url }}', '={{ JSON.stringify($json.mp_body) }}'), 5, 0),
    (code('Leer respuesta de Mercado Pago', LEER_COBRO), 6, 0),
    (si('¿Es suscripción?', '$json.guardar === true'), 7, 0),
    (rpc('Supabase: guardar suscripción', 'guardar_suscripcion'), 8, 0),
    (code('Respuesta final', RESPUESTA_FINAL), 9, 0),
    (responder(), 10, 0.6),
]

fila_mp = [
    ({'parameters': {'httpMethod': 'POST', 'path': 'multiredes-mp', 'responseMode': 'onReceived', 'options': {}},
      'name': 'Aviso de Mercado Pago', 'type': 'n8n-nodes-base.webhook', 'typeVersion': 2,
      'webhookId': nid('webhook-mp')}, 0, 2),
    (code('¿Qué avisó Mercado Pago?', QUE_AVISO), 1, 2),
    (mp('Mercado Pago: leer el aviso', 'GET', '={{ $json.url }}'), 2, 2),
    (code('Entender el aviso', ENTENDER_AVISO), 3, 2),
    (rpc('Supabase: anotar el aviso', None), 4, 2),
    (code('¿Qué hay que hacer?', QUE_HACER), 5, 2),
    (si('¿Es cliente nuevo?', "$json.que === 'bienvenida'"), 6, 2),
    (carpeta('Crear carpeta del cliente', '={{ $json.carpeta }}', '={{ $json.padre }}'), 7, 1.5),
    (carpeta('Crear Crudo', 'Crudo', RAIZ), 8, 1.5),
    (carpeta('Crear Listos', 'Listos', RAIZ), 9, 1.5),
    (carpeta('Crear Reels', 'Reels', LISTOS), 10, 1.5),
    (carpeta('Crear Historias', 'Historias', LISTOS), 11, 1.5),
    (carpeta('Crear Feed', 'Feed', LISTOS), 12, 1.5),
    (carpeta('Crear Recursos', 'Recursos', RAIZ), 13, 1.5),
    ({'parameters': {
        'method': 'POST',
        'url': "=https://www.googleapis.com/drive/v3/files/{{ $('Crear Listos').first().json.id }}/permissions?supportsAllDrives=true",
        'authentication': 'predefinedCredentialType', 'nodeCredentialType': 'googleDriveOAuth2Api',
        'sendBody': True, 'specifyBody': 'json', 'jsonBody': '{"role": "reader", "type": "anyone"}',
        'options': {'timeout': 30000}},
      'name': 'Abrir Listos con el link', 'type': 'n8n-nodes-base.httpRequest', 'typeVersion': 4.2,
      'credentials': CRED_DRIVE, 'onError': 'continueRegularOutput'}, 14, 1.5),
    (code('Preparar logo', PREPARAR_LOGO, alwaysOutputData=True), 15, 1.5),
    ({'parameters': {
        'name': '={{ $binary.data ? $binary.data.fileName : "logo.png" }}',
        'driveId': {'__rl': True, 'mode': 'list', 'value': 'My Drive'},
        'folderId': {'__rl': True, 'mode': 'id', 'value': "={{ $('Crear Recursos').first().json.id }}"},
        'inputDataFieldName': 'data', 'options': {}},
      'name': 'Subir logo a Recursos', 'type': 'n8n-nodes-base.googleDrive', 'typeVersion': 3,
      'credentials': CRED_DRIVE, 'onError': 'continueRegularOutput'}, 16, 1.5),
    (code('Juntar carpetas', JUNTAR_CARPETAS), 17, 1.5),
    (rpc('Supabase: guardar carpetas', 'guardar_carpetas'), 18, 1.5),
    (mail('Mail de bienvenida', NUEVO), 19, 1.5),
    (mail('Mail de pago o cancelación', '$json'), 7, 2.5),
]

fila_diaria = [
    ({'parameters': {'rule': {'interval': [{'field': 'days', 'triggerAtHour': 9}]}},
      'name': 'Todos los días a las 9', 'type': 'n8n-nodes-base.scheduleTrigger', 'typeVersion': 1.2}, 0, 3.5),
    (rpc('Supabase: revisión diaria', 'revision_diaria', '{}'), 1, 3.5),
    (code('Avisos del día', AVISOS_DEL_DIA), 2, 3.5),
    (si('¿Hay que cancelar la suscripción?', "$json.cancelar !== ''"), 3, 3.5),
    (mp('Mercado Pago: cancelar suscripción', 'PUT',
        "=" + MP + "/preapproval/{{ $json.cancelar }}", '{"status": "cancelled"}'), 4, 3.2),
    (mail('Mail del día', "$('Avisos del día').item.json"), 5, 3.5),
]


def a(destino, idx=0):
    return {'node': destino, 'type': 'main', 'index': idx}


conexiones = {
    # 1. alta
    'Formulario de alta': {'main': [[a('Leer formulario')]]},
    'Leer formulario': {'main': [[a('Supabase: planes o alta')]]},
    'Supabase: planes o alta': {'main': [[a('¿Qué sigue con el alta?')]]},
    '¿Qué sigue con el alta?': {'main': [[a('¿Hay que crear el cobro?')]]},
    '¿Hay que crear el cobro?': {'main': [[a('Mercado Pago: crear el cobro')], [a('Responder al formulario')]]},
    'Mercado Pago: crear el cobro': {'main': [[a('Leer respuesta de Mercado Pago')]]},
    'Leer respuesta de Mercado Pago': {'main': [[a('¿Es suscripción?')]]},
    '¿Es suscripción?': {'main': [[a('Supabase: guardar suscripción')], [a('Responder al formulario')]]},
    'Supabase: guardar suscripción': {'main': [[a('Respuesta final')]]},
    'Respuesta final': {'main': [[a('Responder al formulario')]]},
    # 2. avisos de Mercado Pago
    'Aviso de Mercado Pago': {'main': [[a('¿Qué avisó Mercado Pago?')]]},
    '¿Qué avisó Mercado Pago?': {'main': [[a('Mercado Pago: leer el aviso')]]},
    'Mercado Pago: leer el aviso': {'main': [[a('Entender el aviso')]]},
    'Entender el aviso': {'main': [[a('Supabase: anotar el aviso')]]},
    'Supabase: anotar el aviso': {'main': [[a('¿Qué hay que hacer?')]]},
    '¿Qué hay que hacer?': {'main': [[a('¿Es cliente nuevo?')]]},
    '¿Es cliente nuevo?': {'main': [[a('Crear carpeta del cliente')], [a('Mail de pago o cancelación')]]},
    'Crear carpeta del cliente': {'main': [[a('Crear Crudo')]]},
    'Crear Crudo': {'main': [[a('Crear Listos')]]},
    'Crear Listos': {'main': [[a('Crear Reels')]]},
    'Crear Reels': {'main': [[a('Crear Historias')]]},
    'Crear Historias': {'main': [[a('Crear Feed')]]},
    'Crear Feed': {'main': [[a('Crear Recursos')]]},
    'Crear Recursos': {'main': [[a('Abrir Listos con el link')]]},
    'Abrir Listos con el link': {'main': [[a('Preparar logo')]]},
    'Preparar logo': {'main': [[a('Subir logo a Recursos')]]},
    'Subir logo a Recursos': {'main': [[a('Juntar carpetas')]]},
    'Juntar carpetas': {'main': [[a('Supabase: guardar carpetas')]]},
    'Supabase: guardar carpetas': {'main': [[a('Mail de bienvenida')]]},
    # 3. revisión diaria
    'Todos los días a las 9': {'main': [[a('Supabase: revisión diaria')]]},
    'Supabase: revisión diaria': {'main': [[a('Avisos del día')]]},
    'Avisos del día': {'main': [[a('¿Hay que cancelar la suscripción?')]]},
    '¿Hay que cancelar la suscripción?': {'main': [[a('Mercado Pago: cancelar suscripción')], [a('Mail del día')]]},
    'Mercado Pago: cancelar suscripción': {'main': [[a('Mail del día')]]},
}


def main(salida):
    nodos = []
    for n, col, fila in fila_alta + fila_mp + fila_diaria:
        n['id'] = nid(n['name'])
        n['position'] = [int(col * 220), int(fila * 220)]
        nodos.append(n)
    nombres = {n['name'] for n in nodos}
    assert len(nombres) == len(nodos), 'nombres repetidos'
    for k, v in conexiones.items():
        assert k in nombres, k
        for salida_ in v['main']:
            for c in salida_:
                assert c['node'] in nombres, c['node']
    flujo = {
        'name': 'Multiredes: alta, cobro y baja v1.0',
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
