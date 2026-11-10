/**
 * Ficha preliminar para renta vehicular (MAXIRent): enlaces de firma y receptor.
 *
 * Flujo:
 *  1. Un ejecutivo autorizado abre el panel (despliegue "Ejecutivos"), escribe el cliente y
 *     obtiene un enlace único. En ese momento se crea el documento "PENDIENTE DE FIRMA" en su
 *     carpeta de Drive.
 *  2. El ejecutivo comparte el enlace con el cliente.
 *  3. El cliente abre el enlace, llena la ficha y firma. El enlace sirve una sola vez.
 *  4. El receptor guarda los datos, completa el documento, lo renombra a "FIRMADA", lo mueve a la
 *     carpeta "Firmadas" del ejecutivo, deja una copia en PDF en "Historial" y avisa al ejecutivo.
 *
 * Archivos del proyecto: Code.gs (rutas y firma), Enlaces.gs (ejecutivos y enlaces),
 * Documento.gs (Drive y documento), Setup.gs (configuración y autoprueba), Logo.gs, Panel.html.
 *
 * No se registran datos de la ficha en los logs.
 */

var HOJA_FICHAS = 'Fichas';
var HOJA_ENLACES = 'Enlaces';
var HOJA_EJECUTIVOS = 'Ejecutivos';
var ENCABEZADOS_FICHAS = ['Folio', 'Fecha de recepción', 'Fecha de llenado', 'Ejecutivo', 'Firmante',
  'Documento firmado', 'PDF firmado', 'Firma (archivo)', 'Datos (JSON)'];
var ENCABEZADOS_ENLACES = ['Token', 'Folio', 'Ejecutivo (correo)', 'Ejecutivo (nombre)', 'Cliente', 'Estado',
  'Creado', 'Vence', 'Firmado', 'Documento (ID)', 'Documento (enlace)', 'PDF (enlace)'];
var ENCABEZADOS_EJECUTIVOS = ['Correo', 'Nombre', 'Activo', 'Carpeta (ID)'];

var DIAS_VIGENCIA_PREDETERMINADO = 7;
var MIN_MS_LLENADO = 10000;      // un humano no llena 33 campos en menos de 10 s
var MAX_CAMPOS = 60;
var MAX_TEXTO = 300;
var MAX_FIRMA = 400000;          // caracteres del PNG en base64

/* ---------------------------- rutas web ---------------------------- */

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.accion === 'consultar') return respuesta_(consultarEnlace_(p.t));
  // Despliegue para ejecutivos (acceso sólo dentro de la organización): se identifica por correo.
  if (correoActual_()) {
    return HtmlService.createHtmlOutputFromFile('Panel').setTitle('Fichas de firma · MAXIRent');
  }
  return respuesta_({ ok: true, mensaje: 'Servicio de fichas activo' });
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(25000);
    return respuesta_(recibirFicha_(JSON.parse(e.postData.contents)));
  } catch (ex) {
    console.error('Error al recibir una ficha: ' + (ex && ex.name));
    return respuesta_({ ok: false, mensaje: 'No se pudo guardar la ficha. Intente de nuevo en unos minutos.' });
  } finally {
    try { lock.releaseLock(); } catch (_) {}
  }
}

/* --------------------------- firma del cliente --------------------------- */

/** Se llama con el candado tomado. Devuelve {ok, folio, documento} o {ok:false, mensaje}. */
function recibirFicha_(p) {
  var error = validar_(p);
  if (error) return { ok: false, mensaje: error };

  var tabla = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
  var enlace = buscarPorToken_(tabla, p.token);
  if (!enlace) return { ok: false, mensaje: 'Este enlace no es válido. Pida uno nuevo a su ejecutivo.' };
  var estado = estadoVigente_(enlace);
  if (estado !== 'PENDIENTE') return { ok: false, mensaje: mensajeEstado_(estado) };

  // El enlace sirve una sola vez: se marca como firmado antes de generar nada.
  var ahora = new Date();
  actualizarFila_(tabla, enlace, { 'Estado': 'FIRMADA', 'Firmado': ahora.toISOString() });

  var urlFirma = guardarFirma_(enlace['Folio'], p.firma);
  var fichas = hojaCon_(HOJA_FICHAS, ENCABEZADOS_FICHAS);
  var resultado = { ok: true, folio: enlace['Folio'], documento: true };
  var docUrl = '', pdfUrl = '';
  try {
    var archivos = generarDocumentoFirmado_(enlace, p, ahora);
    docUrl = archivos.docUrl; pdfUrl = archivos.pdfUrl;
    actualizarFila_(tabla, enlace, { 'Documento (enlace)': docUrl, 'PDF (enlace)': pdfUrl });
  } catch (ex) {
    // Los datos ya están a salvo; el documento se puede rehacer con regenerarDocumento('FP-...').
    console.error('No se pudo generar el documento firmado: ' + (ex && ex.name));
    resultado.documento = false;
  }
  guardarFilaFicha_(fichas, enlace, ahora, p, urlFirma, docUrl, pdfUrl);
  avisarFirma_(enlace, p, docUrl, resultado.documento);
  return resultado;
}

/** Devuelve un mensaje de error, o '' si la ficha es válida. */
function validar_(p) {
  if (!p || typeof p !== 'object') return 'Solicitud no válida.';
  if (p.web) return 'Solicitud no válida.';                                   // campo trampa
  if (typeof p.token !== 'string' || !/^[a-f0-9]{64}$/.test(p.token)) return 'Este enlace no es válido. Pida uno nuevo a su ejecutivo.';
  if (!(Number(p.tiempoMs) >= MIN_MS_LLENADO)) return 'Solicitud no válida.';
  if (!Array.isArray(p.campos) || p.campos.length < 1 || p.campos.length > MAX_CAMPOS) return 'Solicitud no válida.';
  var ids = {};
  for (var i = 0; i < p.campos.length; i++) {
    var c = p.campos[i];
    if (!Array.isArray(c) || c.length !== 3) return 'Solicitud no válida.';
    if (!/^[a-z0-9_]{1,40}$/.test(String(c[0])) || ids[c[0]]) return 'Solicitud no válida.';
    ids[c[0]] = true;
    if (typeof c[1] !== 'string' || !c[1] || c[1].length > 120) return 'Solicitud no válida.';
    var v = c[2];
    if (typeof v === 'number') { if (!isFinite(v)) return 'Solicitud no válida.'; }
    else if (typeof v !== 'string' || !v.trim() || v.length > MAX_TEXTO) return 'Falta información en la ficha.';
  }
  if (!ids['s_nombre']) return 'Falta el nombre o razón social.';
  if (typeof p.firmante !== 'string' || p.firmante.trim().length < 2 || p.firmante.length > MAX_TEXTO) return 'Falta el nombre de quien firma.';
  if (typeof p.firma !== 'string' || p.firma.indexOf('data:image/png;base64,') !== 0 || p.firma.length > MAX_FIRMA) return 'Falta la firma.';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(p.fechaLlenado))) return 'Solicitud no válida.';
  return '';
}

function guardarFilaFicha_(hoja, enlace, ahora, p, urlFirma, docUrl, pdfUrl) {
  var encabezados = leerEncabezados_(hoja);
  p.campos.forEach(function (c) {
    if (encabezados.indexOf(c[1]) === -1) {
      encabezados.push(c[1]);
      hoja.getRange(1, encabezados.length).setValue(c[1]).setFontWeight('bold').setBackground('#05394B').setFontColor('#FFFFFF').setWrap(true);
    }
  });
  var fila = encabezados.map(function () { return ''; });
  function poner(et, v) { fila[encabezados.indexOf(et)] = v; }
  poner('Folio', enlace['Folio']);
  poner('Fecha de recepción', formato_(ahora, 'yyyy-MM-dd HH:mm:ss'));
  poner('Fecha de llenado', p.fechaLlenado);
  poner('Ejecutivo', enlace['Ejecutivo (correo)']);
  poner('Firmante', p.firmante.trim());
  poner('Documento firmado', docUrl);
  poner('PDF firmado', pdfUrl);
  poner('Firma (archivo)', urlFirma);
  poner('Datos (JSON)', JSON.stringify(p.campos));
  p.campos.forEach(function (c) { poner(c[1], typeof c[2] === 'string' ? c[2].trim() : c[2]); });
  escribirFila_(hoja, hoja.getLastRow() + 1, fila);
}

function avisarFirma_(enlace, p, docUrl, documentoOk) {
  var props = PropertiesService.getScriptProperties();
  var para = [enlace['Ejecutivo (correo)'], props.getProperty('NOTIFICAR_A')].filter(function (x) { return x; });
  if (!para.length) return;
  try {
    var razon = '';
    p.campos.forEach(function (c) { if (c[0] === 's_nombre') razon = String(c[2]); });
    MailApp.sendEmail(para.join(','), 'Ficha firmada ' + enlace['Folio'],
      'Su cliente ' + razon + ' firmó la ficha preliminar ' + enlace['Folio'] + '.\n\n' +
      (documentoOk && docUrl ? 'Documento firmado: ' + docUrl + '\n' : 'El documento firmado se está preparando; la ficha ya quedó registrada en la hoja de resultados.\n') +
      'Hoja de resultados: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl());
  } catch (_) { console.error('No se pudo enviar el aviso por correo.'); }
}

/* ----------------------------- utilidades ----------------------------- */

function correoActual_() {
  try { return String(Session.getActiveUser().getEmail() || '').toLowerCase(); } catch (_) { return ''; }
}

function respuesta_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function formato_(fecha, patron) {
  return Utilities.formatDate(fecha, Session.getScriptTimeZone(), patron);
}

function limpiarTexto_(s, max) {
  return String(s == null ? '' : s).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
}

function nuevoFolio_(fecha) {
  var ymd = formato_(fecha, 'yyyyMMdd');
  var props = PropertiesService.getScriptProperties();
  var clave = 'seq_' + ymd;
  var n = Number(props.getProperty(clave) || 0) + 1;
  props.setProperty(clave, String(n));
  return 'FP-' + ymd + '-' + ('00' + n).slice(-3);
}

/* Tablas en hojas: una fila = un objeto indexado por encabezado. */

function hojaCon_(nombre, encabezados) {
  var libro = SpreadsheetApp.getActiveSpreadsheet();
  var hoja = libro.getSheetByName(nombre) || libro.insertSheet(nombre);
  var actuales = leerEncabezados_(hoja);
  encabezados.forEach(function (et) {
    if (actuales.indexOf(et) === -1) {
      actuales.push(et);
      hoja.getRange(1, actuales.length).setValue(et).setFontWeight('bold').setBackground('#05394B').setFontColor('#FFFFFF').setWrap(true);
    }
  });
  hoja.setFrozenRows(1);
  return hoja;
}

function leerEncabezados_(hoja) {
  var ultima = hoja.getLastColumn();
  if (ultima < 1) return [];
  return hoja.getRange(1, 1, 1, ultima).getValues()[0].filter(function (x) { return x !== ''; }).map(String);
}

function leerTabla_(nombre, encabezados) {
  var hoja = hojaCon_(nombre, encabezados);
  var enc = leerEncabezados_(hoja);
  var filas = [];
  var total = hoja.getLastRow();
  if (total > 1) {
    var valores = hoja.getRange(2, 1, total - 1, enc.length).getValues();
    valores.forEach(function (v, i) {
      var o = { _fila: i + 2 };
      enc.forEach(function (et, j) { o[et] = v[j] === '' || v[j] == null ? '' : String(v[j]); });
      filas.push(o);
    });
  }
  return { hoja: hoja, encabezados: enc, filas: filas };
}

function actualizarFila_(tabla, fila, cambios) {
  Object.keys(cambios).forEach(function (et) {
    fila[et] = cambios[et];
    var col = tabla.encabezados.indexOf(et) + 1;
    var celda = tabla.hoja.getRange(fila._fila, col);
    celda.setNumberFormat('@').setValue(cambios[et]);
  });
}

/** Escribe una fila con formato texto (evita que "=..." se evalúe o que un teléfono pierda ceros). */
function escribirFila_(hoja, nroFila, valores) {
  var formatos = valores.map(function (v) { return typeof v === 'number' ? '#,##0' : '@'; });
  hoja.getRange(nroFila, 1, 1, valores.length).setNumberFormats([formatos]).setValues([valores]);
}
