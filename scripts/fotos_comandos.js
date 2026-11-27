// === Code node "Armar edición de fotos" (n8n) ===
// Arma un solo comando de shell que genera, con FFmpeg, todas las piezas del pedido:
//   foto     -> post.jpg (4:5) y historia.jpg (9:16)
//   carrusel -> placa-01.jpg … placa-NN.jpg (4:5), una placa final con los datos del negocio, e historia.jpg
// Los textos van en archivos (base64) para que ninguna comilla rompa el comando.
const c = $('Config de las fotos').first().json;
const d = $('Datos del negocio').first().json;
const r = $('Leer respuesta de Claude').first().json;

const dir = c.dir;
const out = `${dir}/salida`;
const font = `fontfile=${dir}/fuente.ttf:expansion=none`;
const b64 = t => Buffer.from(String(t || ''), 'utf8').toString('base64');
const txt = (nombre, texto) => `printf '%s' '${b64(texto)}' | base64 -d > "${dir}/${nombre}.txt"`;

// Corta un texto en renglones de hasta `ancho` letras (máx. `max` renglones)
function renglones(texto, ancho, max) {
  const palabras = String(texto || '').trim().split(/\s+/).filter(Boolean);
  const rs = [];
  for (const p of palabras) {
    const ult = rs[rs.length - 1];
    if (ult !== undefined && (ult + ' ' + p).length <= ancho) rs[rs.length - 1] = ult + ' ' + p;
    else rs.push(p);
  }
  if (rs.length > max) { rs.length = max; rs[max - 1] = rs[max - 1].replace(/[.,;:]?$/, '…'); }
  return rs.join('\n');
}

// Mejora suave: un poco más de contraste, color y nitidez
const mejora = 'eq=contrast=1.05:saturation=1.1:brightness=0.01,unsharp=5:5:0.6';
const logo = `[1:v]scale=200:-1,colorkey=0xFFFFFF:0.12:0.08[lg]`;
const pie = [d.instagram, d.telefono_reservas ? 'Reservas ' + d.telefono_reservas : ''].filter(Boolean).join('  ·  ');

// Pieza 4:5 con el mismo marco que la portada de los videos: foto arriba, texto y logo abajo
function placa4x5(foto, nombreTexto, tam, salida) {
  const fc = `[0:v]scale=1000:1000:force_original_aspect_ratio=increase,crop=1000:1000,setsar=1,${mejora}[f];${logo};` +
    `[2:v][f]overlay=40:40[a];[a][lg]overlay=W-w-40:1072[b];` +
    `[b]drawtext=${font}:textfile=${dir}/${nombreTexto}.txt:fontsize=${tam}:line_spacing=8:fontcolor=${d.ff_texto}:x=40:y=1072,` +
    `drawtext=${font}:textfile=${dir}/pie.txt:fontsize=24:fontcolor=${d.ff_texto}:x=40:y=1304[out]`;
  return `ffmpeg -hide_banner -loglevel error -y -i "${foto}" -i "${dir}/logo.png" -f lavfi -i color=c=${d.ff_marco}:s=1080x1350:d=1 ` +
    `-filter_complex "${fc}" -map "[out]" -frames:v 1 -q:v 2 "${salida}"`;
}

// Historia 9:16: logo arriba, foto al medio con el gancho, datos de contacto abajo
function historia(foto) {
  const fc = `[0:v]scale=1000:1380:force_original_aspect_ratio=increase,crop=1000:1380,setsar=1,${mejora}[f];` +
    `[1:v]scale=230:-1,colorkey=0xFFFFFF:0.12:0.08[lg];[2:v][f]overlay=40:290[a];[a][lg]overlay=(W-w)/2:30[b];` +
    `[b]drawtext=${font}:textfile=${dir}/hgancho.txt:fontsize=60:line_spacing=10:fontcolor=${d.ff_texto}:` +
    `box=1:boxcolor=${d.ff_marco}@0.92:boxborderw=24:x=(w-text_w)/2:y=1600-text_h,` +
    `drawtext=${font}:textfile=${dir}/hist1.txt:fontsize=64:fontcolor=${d.ff_texto}:x=(w-text_w)/2:y=1712,` +
    `drawtext=${font}:textfile=${dir}/hist2.txt:fontsize=32:fontcolor=${d.ff_texto}:x=(w-text_w)/2:y=1812[out]`;
  return `ffmpeg -hide_banner -loglevel error -y -i "${foto}" -i "${dir}/logo.png" -f lavfi -i color=c=${d.ff_marco}:s=1080x1920:d=1 ` +
    `-filter_complex "${fc}" -map "[out]" -frames:v 1 -q:v 2 "${out}/historia.jpg"`;
}

// Placa de cierre del carrusel: logo grande y datos del negocio, cada renglón centrado
function cierre(lineas, salida) {
  const textos = lineas.map((l, i) =>
    `drawtext=${font}:textfile=${dir}/cierre${i}.txt:fontsize=40:fontcolor=${d.ff_texto}:x=(w-text_w)/2:y=${720 + i * 64}`);
  const fc = `[1:v]scale=420:-1,colorkey=0xFFFFFF:0.12:0.08[lg];[0:v][lg]overlay=(W-w)/2:170[a];` +
    `[a]${textos.join(',')}[out]`;
  return lineas.map((l, i) => txt(`cierre${i}`, l)).join(' && ') + ' && ' +
    `ffmpeg -hide_banner -loglevel error -y -f lavfi -i color=c=${d.ff_marco}:s=1080x1350:d=1 -i "${dir}/logo.png" ` +
    `-filter_complex "${fc}" -map "[out]" -frames:v 1 -q:v 2 "${salida}"`;
}

const cmds = [`rm -rf "${out}"`, `mkdir -p "${out}"`, txt('pie', pie),
  txt('hist1', d.historia_linea_1 || (d.telefono_reservas ? 'RESERVAS ' + d.telefono_reservas : d.nombre)),
  txt('hist2', d.historia_linea_2 || d.horario || ''),
  txt('hgancho', renglones(r.gancho || r.titulo, 22, 2))];

const fotos = c.archivos;                    // [{ ruta, ... }] en el orden en que se subieron
const orden = r.placas.map(p => p.foto - 1);  // índices (0..n-1) en el orden que eligió Claude

if (c.tipo === 'foto') {
  cmds.push(txt('gancho', renglones(r.gancho || r.titulo, 18, 3)));
  cmds.push(placa4x5(fotos[0].ruta, 'gancho', 56, `${out}/post.jpg`));
  cmds.push(historia(fotos[0].ruta));
} else {
  orden.forEach((idx, i) => {
    const n = String(i + 1).padStart(2, '0');
    const texto = i === 0 ? renglones(r.gancho || r.titulo, 18, 3) : renglones(r.placas[i].texto, 24, 3);
    cmds.push(txt(`placa${n}`, texto));
    cmds.push(placa4x5(fotos[idx].ruta, `placa${n}`, i === 0 ? 56 : 44, `${out}/placa-${n}.jpg`));
  });
  const fin = String(orden.length + 1).padStart(2, '0');
  const lineas = [
    d.telefono_reservas ? 'Reservas ' + d.telefono_reservas : '',
    ...renglones(d.direccion, 40, 2).split('\n'),
    ...renglones(d.horario, 40, 2).split('\n'),
    d.instagram || '',
  ].filter(Boolean).slice(0, 7);
  cmds.push(cierre(lineas, `${out}/placa-${fin}.jpg`));
  cmds.push(historia(fotos[orden[0]].ruta));
}

return [{ json: { cmd: cmds.join(' && ') } }];
