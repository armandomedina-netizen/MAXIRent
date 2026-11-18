/* =====================================================================
   CÓDIGO 2 DE 5 · EJECUTIVOS Y ENLACES
   Nombre del archivo en Apps Script: 2-Enlaces   (tipo: Script, .gs)
   Alta de ejecutivos, carpeta propia en Drive, creación, consulta y cancelación de enlaces de firma.
   ===================================================================== */
/**
 * Ejecutivos y enlaces de firma.
 *
 * Estados de un enlace: PENDIENTE -> FIRMADA | CANCELADA | VENCIDA.
 * Un enlace sirve una sola vez y vence a los DIAS_VIGENCIA días (propiedad de script, 7 por omisión).
 */

/* ------------------------------ ejecutivos ------------------------------ */

/** Ejecutivo de la hoja por correo (con su carpeta propia, si la conectó), o null. */
function ejecutivoPorCorreo_(correo, soloActivos) {
  correo = String(correo || '').trim().toLowerCase();
  if (!correo) return null;
  var lista = leerTabla_(HOJA_EJECUTIVOS, ENCABEZADOS_EJECUTIVOS).filas;
  for (var i = 0; i < lista.length; i++) {
    var f = lista[i];
    if (String(f['Correo']).trim().toLowerCase() === correo && (!soloActivos || String(f['Activo']).trim().toUpperCase() !== 'NO')) {
      return { correo: correo, nombre: limpiarTexto_(f['Nombre'], 80) || correo, carpetaId: limpiarTexto_(f['Carpeta (ID)'], 80) };
    }
  }
  return null;
}

/** Ejecutivo autorizado que está usando el panel, o null. */
function ejecutivoActual_() {
  return ejecutivoPorCorreo_(correoActual_(), true);
}

function exigirEjecutivo_() {
  var ej = ejecutivoActual_();
  if (!ej) throw new Error('Su correo no está autorizado para generar fichas. Pida que lo agreguen a la hoja Ejecutivos.');
  return ej;
}

/* ------------------------- funciones del panel ------------------------- */

/** Datos iniciales del panel: quién es el ejecutivo, el estado de su carpeta y sus fichas. */
function panelInicial() {
  var ej = exigirEjecutivo_();
  return { nombre: ej.nombre, correo: ej.correo, carpeta: estadoCarpeta_(ej), fichas: fichasDe_(ej.correo) };
}

/**
 * Conecta una carpeta del propio Drive del ejecutivo. Debe ser suya (el propietario es su
 * cuenta) y estar compartida como Editor con la cuenta que opera el servicio. Desde entonces
 * los documentos de sus fichas se crean, se renombran y se archivan dentro de ella.
 */
function conectarCarpeta(entrada) {
  var ej = exigirEjecutivo_();
  var id = (String(entrada || '').match(/[-\w]{25,}/) || [])[0];
  if (!id) throw new Error('Pegue el enlace de su carpeta de Drive.');
  var carpeta;
  try { carpeta = DriveApp.getFolderById(id); }
  catch (_) { throw new Error('No puedo abrir esa carpeta. Compártala como Editor con ' + correoDueno_() + ' y vuelva a intentarlo.'); }
  var dueno = '';
  try { dueno = String(carpeta.getOwner().getEmail()).toLowerCase(); } catch (_) {}
  if (dueno !== ej.correo) throw new Error('La carpeta debe ser suya: créela desde su cuenta ' + ej.correo + '.');
  try { carpeta_(carpeta, 'Pendientes'); carpeta_(carpeta, 'Firmadas'); }
  catch (_) { throw new Error('Necesito permiso de Editor en esa carpeta. Compártala como Editor con ' + correoDueno_() + '.'); }
  var tabla = leerTabla_(HOJA_EJECUTIVOS, ENCABEZADOS_EJECUTIVOS);
  var fila = tabla.filas.filter(function (f) { return String(f['Correo']).trim().toLowerCase() === ej.correo; })[0];
  actualizarFila_(tabla, fila, { 'Carpeta (ID)': id });
  ej.carpetaId = id;
  return estadoCarpeta_(ej);
}

/** Estado de la carpeta propia del ejecutivo para mostrarlo en el panel. */
function estadoCarpeta_(ej) {
  var base = { conectada: false, url: '', perdida: false, dueno: correoDueno_() };
  if (!ej.carpetaId) return base;
  try { base.url = DriveApp.getFolderById(ej.carpetaId).getUrl(); base.conectada = true; }
  catch (_) { base.perdida = true; }
  return base;
}

/** Cuenta que opera el servicio (la que debe tener acceso de Editor a la carpeta del ejecutivo). */
function correoDueno_() {
  try { return String(Session.getEffectiveUser().getEmail()) || 'la cuenta administradora'; } catch (_) { return 'la cuenta administradora'; }
}

/** Crea un enlace de firma y el documento pendiente en la carpeta del ejecutivo. */
function crearEnlace(cliente) {
  var ej = exigirEjecutivo_();
  var nombreCliente = limpiarTexto_(cliente, 120);
  if (nombreCliente.length < 2) throw new Error('Escriba el nombre o razón social del cliente.');
  var base = PropertiesService.getScriptProperties().getProperty('URL_FORMULARIO');
  if (!base) throw new Error('Falta configurar la dirección del formulario (propiedad URL_FORMULARIO).');

  var lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    var ahora = new Date();
    var vence = new Date(ahora.getTime() + diasVigencia_() * 86400000);
    var folio = nuevoFolio_(ahora);
    var token = nuevoToken_();
    var doc = crearDocumentoPendiente_(ej, folio, nombreCliente, vence);
    var tabla = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
    var fila = {
      'Token': token, 'Folio': folio, 'Ejecutivo (correo)': ej.correo, 'Ejecutivo (nombre)': ej.nombre,
      'Cliente': nombreCliente, 'Estado': 'PENDIENTE', 'Creado': ahora.toISOString(), 'Vence': vence.toISOString(),
      'Firmado': '', 'Documento (ID)': doc.id, 'Documento (enlace)': doc.url, 'PDF (enlace)': ''
    };
    // Las columnas se escriben en el orden real de la hoja.
    escribirFila_(tabla.hoja, tabla.hoja.getLastRow() + 1, tabla.encabezados.map(function (et) { return fila[et] === undefined ? '' : fila[et]; }));
    return { folio: folio, url: base.replace(/#.*$/, '') + '#t=' + token, vence: vence.toISOString(), cliente: nombreCliente };
  } finally {
    lock.releaseLock();
  }
}

/** Cancela un enlace pendiente del propio ejecutivo. */
function cancelarEnlace(folio) {
  var ej = exigirEjecutivo_();
  var lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    var tabla = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
    var e = tabla.filas.filter(function (f) { return f['Folio'] === folio && f['Ejecutivo (correo)'] === ej.correo; })[0];
    if (!e) throw new Error('No encontré esa ficha entre las suyas.');
    if (estadoVigente_(e) !== 'PENDIENTE') throw new Error('Sólo se pueden cancelar las fichas pendientes.');
    actualizarFila_(tabla, e, { 'Estado': 'CANCELADA' });
    renombrarDocumento_(e['Documento (ID)'], nombreArchivo_(folio, 'CANCELADA', e['Cliente']));
    return fichasDe_(ej.correo);
  } finally {
    lock.releaseLock();
  }
}

/** Fichas del ejecutivo, de la más reciente a la más antigua (sin tokens). */
function fichasDe_(correo) {
  var tabla = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
  marcarVencidas_(tabla);
  return tabla.filas
    .filter(function (f) { return f['Ejecutivo (correo)'] === correo; })
    .sort(function (a, b) { return a['Creado'] < b['Creado'] ? 1 : -1; })
    .slice(0, 100)
    .map(function (f) {
      return { folio: f['Folio'], cliente: f['Cliente'], estado: f['Estado'], creado: f['Creado'], vence: f['Vence'],
        firmado: f['Firmado'], documento: f['Documento (enlace)'], pdf: f['PDF (enlace)'] };
    });
}

/* ------------------------- consulta del cliente ------------------------- */

/** Lo que ve el cliente al abrir su enlace. No expone datos más allá de lo necesario. */
function consultarEnlace_(token) {
  if (typeof token !== 'string' || !/^[a-f0-9]{64}$/.test(token)) {
    return { ok: false, estado: 'INVALIDO', mensaje: mensajeEstado_('INVALIDO') };
  }
  var tabla = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
  var e = buscarPorToken_(tabla, token);
  if (!e) return { ok: false, estado: 'INVALIDO', mensaje: mensajeEstado_('INVALIDO') };
  var estado = estadoVigente_(e);
  if (estado === 'VENCIDA' && e['Estado'] === 'PENDIENTE') {
    actualizarFila_(tabla, e, { 'Estado': 'VENCIDA' });
    try { renombrarDocumento_(e['Documento (ID)'], nombreArchivo_(e['Folio'], 'VENCIDA', e['Cliente'])); } catch (_) {}
  }
  if (estado !== 'PENDIENTE') return { ok: false, estado: estado, mensaje: mensajeEstado_(estado) };
  return { ok: true, folio: e['Folio'], cliente: e['Cliente'], ejecutivo: e['Ejecutivo (nombre)'], vence: e['Vence'] };
}

/* ------------------------------ utilidades ------------------------------ */

function nuevoToken_() {
  return (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '').toLowerCase();   // 64 caracteres hex
}

function diasVigencia_() {
  var n = Number(PropertiesService.getScriptProperties().getProperty('DIAS_VIGENCIA'));
  return n >= 1 && n <= 90 ? Math.floor(n) : DIAS_VIGENCIA_PREDETERMINADO;
}

function buscarPorToken_(tabla, token) {
  for (var i = 0; i < tabla.filas.length; i++) {
    if (tabla.filas[i]['Token'] === token) return tabla.filas[i];
  }
  return null;
}

/** Estado real: un enlace pendiente cuya fecha ya pasó cuenta como VENCIDA. */
function estadoVigente_(e) {
  if (e['Estado'] === 'PENDIENTE' && Date.parse(e['Vence']) < Date.now()) return 'VENCIDA';
  return e['Estado'];
}

function marcarVencidas_(tabla) {
  tabla.filas.forEach(function (e) {
    if (e['Estado'] === 'PENDIENTE' && estadoVigente_(e) === 'VENCIDA') {
      actualizarFila_(tabla, e, { 'Estado': 'VENCIDA' });
      try { renombrarDocumento_(e['Documento (ID)'], nombreArchivo_(e['Folio'], 'VENCIDA', e['Cliente'])); } catch (_) {}
    }
  });
}

function mensajeEstado_(estado) {
  switch (estado) {
    case 'FIRMADA': return 'Esta ficha ya fue firmada. Si necesita corregir algo, comuníquese con su ejecutivo de MAXIRent.';
    case 'VENCIDA': return 'Este enlace venció. Pida uno nuevo a su ejecutivo de MAXIRent.';
    case 'CANCELADA': return 'Este enlace fue cancelado. Pida uno nuevo a su ejecutivo de MAXIRent.';
    default: return 'Este enlace no es válido. Pida uno nuevo a su ejecutivo de MAXIRent.';
  }
}
