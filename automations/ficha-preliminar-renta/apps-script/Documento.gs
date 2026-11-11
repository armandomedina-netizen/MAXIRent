/* =====================================================================
   CÓDIGO 3 DE 5 · CARPETAS Y DOCUMENTO
   Nombre del archivo en Apps Script: 3-Documento   (tipo: Script, .gs)
   Carpetas de Drive, documento pendiente, documento firmado (renombrado) y PDF de histórico.
   ===================================================================== */
/**
 * Carpetas de Drive y documento de la ficha.
 *
 * Dónde se guardan las fichas de un ejecutivo, en este orden de preferencia:
 *   1. Su propia carpeta de Drive, si la conectó desde el panel (conectarCarpeta):
 *        <su carpeta>/Pendientes    documentos esperando la firma del cliente
 *        <su carpeta>/Firmadas      documento firmado (Google Docs) + su PDF
 *   2. Si no la ha conectado (o dejó de compartirla), una carpeta dentro de la raíz del servicio,
 *      compartida con él en modo lectura:
 *        Ejecutivos/<Nombre (correo)>/Pendientes y /Firmadas
 * Siempre, además, en la raíz "Fichas preliminares de renta":
 *   Historial/   copia en PDF de toda ficha firmada
 *   Firmas/      imagen de cada firma
 *
 * Nombres: "FP-AAAAMMDD-NNN - PENDIENTE DE FIRMA - Cliente"
 *          "FP-AAAAMMDD-NNN - FIRMADA - Razón social - AAAA-MM-DD"
 * El mismo archivo cambia de nombre y de carpeta cuando el cliente firma.
 */

var NOMBRE_RAIZ = 'Fichas preliminares de renta';
var AZUL = '#05394B', NARANJA = '#F47721', NARANJA_T = '#EE8022', CAMPO = '#E5F4FB', BORDE = '#B9D8E8', ROJO = '#920000';
var MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

/* ------------------------------- carpetas ------------------------------- */

function carpeta_(padre, nombre) {
  var it = padre.getFoldersByName(nombre);
  return it.hasNext() ? it.next() : padre.createFolder(nombre);
}

function carpetaRaiz_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('CARPETA_RAIZ_ID');
  if (id) { try { return DriveApp.getFolderById(id); } catch (_) {} }
  var f = DriveApp.createFolder(NOMBRE_RAIZ);
  props.setProperty('CARPETA_RAIZ_ID', f.getId());
  return f;
}

/** Carpetas del ejecutivo: la de su propio Drive si está conectada y accesible; si no, la compartida. */
function carpetasEjecutivo_(ej) {
  if (ej.carpetaId) {
    try {
      var suya = DriveApp.getFolderById(ej.carpetaId);
      return { propia: suya, pendientes: carpeta_(suya, 'Pendientes'), firmadas: carpeta_(suya, 'Firmadas'), enSuDrive: true };
    } catch (_) { console.error('No se pudo usar la carpeta propia del ejecutivo; se usa la carpeta compartida.'); }
  }
  var contenedor = carpeta_(carpetaRaiz_(), 'Ejecutivos');
  var nombre = nombreSeguro_(ej.nombre + ' (' + ej.correo + ')');
  var it = contenedor.getFoldersByName(nombre);
  var nueva = !it.hasNext();
  var propia = nueva ? contenedor.createFolder(nombre) : it.next();
  if (nueva) { try { propia.addViewer(ej.correo); } catch (_) { console.error('No se pudo compartir la carpeta del ejecutivo.'); } }
  return { propia: propia, pendientes: carpeta_(propia, 'Pendientes'), firmadas: carpeta_(propia, 'Firmadas'), enSuDrive: false };
}

function nombreSeguro_(s) {
  return String(s).replace(/[\\\/:*?"<>|]/g, '').replace(/\s+/g, ' ').trim().slice(0, 90);
}

/** Nombre del archivo según su estado. */
function nombreArchivo_(folio, estado, cliente, fechaDia) {
  var et = estado === 'PENDIENTE' ? 'PENDIENTE DE FIRMA' : estado;
  var partes = [folio, et, nombreSeguro_(cliente).slice(0, 70)];
  if (fechaDia) partes.push(fechaDia);
  return partes.join(' - ');
}

function renombrarDocumento_(id, nombre) {
  if (!id) return;
  DriveApp.getFileById(id).setName(nombre);
}

function guardarFirma_(folio, dataUrl) {
  var blob = firmaBlob_(dataUrl).setName(folio + '.png');
  return carpeta_(carpetaRaiz_(), 'Firmas').createFile(blob).getUrl();
}

function firmaBlob_(dataUrl) {
  return Utilities.newBlob(Utilities.base64Decode(dataUrl.split(',')[1]), 'image/png', 'firma.png');
}

/* ----------------------------- documento pendiente ----------------------------- */

function crearDocumentoPendiente_(ej, folio, cliente, vence) {
  var carpetas = carpetasEjecutivo_(ej);
  var doc = DocumentApp.create(nombreArchivo_(folio, 'PENDIENTE', cliente));
  var body = doc.getBody();
  body.clear();
  margenes_(body);
  var titulo = encabezado_(body, 'FICHA PRELIMINAR PARA RENTA VEHICULAR', 'Folio ' + folio + '  ·  PENDIENTE DE FIRMA');
  parrafo_(body, '', 6);
  var datos = body.appendTable([
    ['Cliente', cliente],
    ['Ejecutivo', ej.nombre + ' (' + ej.correo + ')'],
    ['Vigencia del enlace', fechaLarga_(vence)]
  ]);
  estiloTabla_(datos, [150, 382], false);
  parrafo_(body, '', 6);
  parrafo_(body, 'Esta ficha espera la firma del cliente. Cuando la firme, este mismo documento se completa con sus datos, se renombra a FIRMADA y pasa a la carpeta Firmadas de su ejecutivo.', 9);
  cerrarEstilo_(body, titulo);
  doc.saveAndClose();
  var archivo = DriveApp.getFileById(doc.getId());
  archivo.moveTo(carpetas.pendientes);
  return { id: doc.getId(), url: archivo.getUrl() };
}

/* ------------------------------ documento firmado ------------------------------ */

/**
 * Completa el documento pendiente con los datos y la firma, lo renombra, lo mueve a Firmadas
 * y guarda su PDF en la carpeta del ejecutivo y en Historial. Devuelve {docUrl, pdfUrl}.
 */
function generarDocumentoFirmado_(enlace, p, fecha) {
  var ej = ejecutivoPorCorreo_(enlace['Ejecutivo (correo)'], false) || { correo: enlace['Ejecutivo (correo)'], nombre: enlace['Ejecutivo (nombre)'] };
  var carpetas = carpetasEjecutivo_(ej);
  var doc;
  try { doc = DocumentApp.openById(enlace['Documento (ID)']); }
  catch (_) { doc = DocumentApp.create(nombreArchivo_(enlace['Folio'], 'FIRMADA', enlace['Cliente'])); }   // el pendiente se borró
  armarDocumentoFirmado_(doc, enlace, p, fecha);
  doc.saveAndClose();

  var razon = '';
  p.campos.forEach(function (c) { if (c[0] === 's_nombre') razon = String(c[2]); });
  var nombre = nombreArchivo_(enlace['Folio'], 'FIRMADA', razon, formato_(fecha, 'yyyy-MM-dd'));
  var archivo = DriveApp.getFileById(doc.getId());
  archivo.setName(nombre);
  archivo.moveTo(carpetas.firmadas);

  var pdf = archivo.getAs('application/pdf').setName(nombre + '.pdf');
  var pdfEjecutivo = carpetas.firmadas.createFile(pdf);
  carpeta_(carpetaRaiz_(), 'Historial').createFile(pdf);
  actualizarIdDocumento_(enlace, doc.getId());
  return { docUrl: archivo.getUrl(), pdfUrl: pdfEjecutivo.getUrl() };
}

function actualizarIdDocumento_(enlace, id) {
  if (enlace['Documento (ID)'] === id) return;
  var tabla = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
  var fila = tabla.filas.filter(function (f) { return f['Folio'] === enlace['Folio']; })[0];
  if (fila) actualizarFila_(tabla, fila, { 'Documento (ID)': id });
}

function armarDocumentoFirmado_(doc, enlace, p, fecha) {
  var v = {};
  p.campos.forEach(function (c) { v[c[0]] = c[2]; });
  var body = doc.getBody();
  body.clear();
  margenes_(body);
  var titulo = encabezado_(body, 'FICHA PRELIMINAR PARA RENTA VEHICULAR', 'Folio ' + enlace['Folio'] + '  ·  FIRMADA el ' + fechaLarga_(fecha));

  seccion_(body, '01', 'Datos generales del solicitante');
  estiloTabla_(body.appendTable([
    ['Nombre completo o razón social', v['s_nombre']],
    ['Giro o actividad comercial', v['s_giro']],
    ['Ciudad y estado', v['s_ciudad']]
  ]), [190, 342], false);

  seccion_(body, '02', 'Contactos de la empresa');
  var roles = [['principal', 'Contacto principal (Solicitante)'], ['legal', 'Representante legal'], ['supervisor', 'Jefe(a) / Supervisor(a) Departamento de Pagos'],
    ['pagos', 'Contacto de pagos']];
  var filas = [['Contacto', 'Nombre', 'Teléfono', 'Correo electrónico', 'Puesto / Móvil']];
  roles.forEach(function (r) {
    var k = 'c_' + r[0] + '_';
    var extra = r[0] === 'principal' ? v[k + 'puesto'] : r[0] === 'legal' ? fmtTel_(v[k + 'movil']) : '';
    filas.push([r[1], v[k + 'nombre'], fmtTel_(v[k + 'tel']), v[k + 'mail'], extra || '']);
  });
  estiloTabla_(body.appendTable(filas), [112, 112, 70, 150, 88], true);

  seccion_(body, '03', 'Referencias comerciales (únicamente proveedores)');
  var refs = [['Referencia', 'Empresa proveedora', 'Contacto', 'Teléfono', 'Correo electrónico', 'Facturación mensual']];
  [1, 2].forEach(function (n) {
    var k = 'r' + n + '_';
    refs.push(['Proveedor ' + n, v[k + 'empresa'], v[k + 'contacto'], fmtTel_(v[k + 'tel']), v[k + 'mail'], '$' + fmtMonto_(v[k + 'fact']) + ' MXN']);
  });
  estiloTabla_(body.appendTable(refs), [62, 100, 90, 70, 120, 90], true);

  parrafo_(body, '', 6);
  parrafo_(body, 'Declaración de veracidad: declaro bajo protesta de decir verdad que los datos proporcionados son verídicos, corresponden a contactos oficiales y que las referencias indicadas son proveedores comerciales externos a nuestra plantilla laboral.', 9);

  var pf = body.appendParagraph('');
  var img = pf.appendInlineImage(firmaBlob_(p.firma));
  var ancho = 200, alto = Math.round(ancho * img.getHeight() / img.getWidth());
  img.setWidth(ancho).setHeight(alto);
  parrafo_(body, 'Firma de ' + p.firmante.trim() + '  ·  Solicitante o Rep. Legal', 9, true);
  parrafo_(body, 'Fecha de llenado: ' + fechaLarga_(new Date(p.fechaLlenado + 'T12:00:00')) + '. Firmada en línea desde el enlace emitido por ' +
    enlace['Ejecutivo (nombre)'] + ' (' + enlace['Ejecutivo (correo)'] + ') el ' + formato_(fecha, 'yyyy-MM-dd HH:mm') + '.', 8, false, '#3F6272');
  cerrarEstilo_(body, titulo);
}

/* ------------------------------- ayudas de formato ------------------------------- */

function margenes_(body) {
  body.setMarginTop(30).setMarginBottom(30).setMarginLeft(40).setMarginRight(40);
}

/** Estilo del texto de un párrafo (siempre por editAsText, que es lo que admite la API de Docs). */
function estilo_(par, tam, negrita, color, fuente) {
  var t = par.editAsText();
  if (tam) t.setFontSize(tam);
  t.setBold(!!negrita);
  if (color) t.setForegroundColor(color);
  if (fuente) t.setFontFamily(fuente);
  return par;
}

function parrafo_(body, txt, tam, negrita, color) {
  var p = body.appendParagraph(txt || ' ');
  estilo_(p, tam || 10, negrita, color || AZUL);
  return p.setSpacingAfter(2).setSpacingBefore(0);
}

function encabezado_(body, titulo, sub) {
  var t = body.appendTable([['', '']]);
  t.setBorderWidth(0);
  t.setColumnWidth(0, 175);
  t.setColumnWidth(1, 357);
  var a = t.getCell(0, 0), b = t.getCell(0, 1);
  [a, b].forEach(function (c) {
    c.setBackgroundColor(AZUL).setPaddingTop(12).setPaddingBottom(12).setPaddingLeft(14).setPaddingRight(14)
      .setVerticalAlignment(DocumentApp.VerticalAlignment.CENTER);
  });
  var logo = a.getChild(0).asParagraph().appendInlineImage(logoBlob_());
  logo.setWidth(150).setHeight(53);
  var p1 = b.getChild(0).asParagraph();
  p1.setText(titulo);
  estilo_(p1, 17, false, NARANJA_T).setSpacingAfter(4);
  estilo_(b.appendParagraph(sub), 9, false, '#FFFFFF');
  return p1;
}

function seccion_(body, num, texto) {
  parrafo_(body, '', 4).setSpacingAfter(0);
  var t = body.appendTable([[num, texto.toUpperCase()]]);
  t.setBorderWidth(0);
  t.setColumnWidth(0, 40);
  t.setColumnWidth(1, 492);
  var a = t.getCell(0, 0), b = t.getCell(0, 1);
  a.setBackgroundColor(NARANJA).setPaddingTop(4).setPaddingBottom(4).setPaddingLeft(10).setPaddingRight(6);
  b.setBackgroundColor(AZUL).setPaddingTop(4).setPaddingBottom(4).setPaddingLeft(10);
  a.editAsText().setBold(true).setFontSize(11).setForegroundColor('#FFFFFF');
  b.editAsText().setBold(true).setFontSize(9.5).setForegroundColor('#FFFFFF');
}

/** Tabla de datos: columna izquierda como etiqueta o primera fila como encabezado. */
function estiloTabla_(t, anchos, conEncabezado) {
  t.setBorderWidth(0.5).setBorderColor(BORDE);
  anchos.forEach(function (w, i) { t.setColumnWidth(i, w); });
  for (var r = 0; r < t.getNumRows(); r++) {
    for (var c = 0; c < t.getRow(r).getNumCells(); c++) {
      var cel = t.getCell(r, c);
      cel.setPaddingTop(3).setPaddingBottom(3).setPaddingLeft(6).setPaddingRight(6);
      var esEtiqueta = conEncabezado ? r === 0 : c === 0;
      cel.setBackgroundColor(esEtiqueta ? CAMPO : '#FFFFFF');
      cel.editAsText().setFontSize(8.5).setBold(esEtiqueta || (conEncabezado && c === 0)).setForegroundColor(AZUL);
    }
  }
}

/** Tipografía general y limpieza del párrafo vacío inicial. */
function cerrarEstilo_(body, titulo) {
  body.editAsText().setFontFamily('Montserrat');
  estilo_(titulo, 17, false, NARANJA_T, 'Impact');
  try {
    var primero = body.getChild(0);
    if (primero.getType() === DocumentApp.ElementType.PARAGRAPH && primero.asParagraph().getText() === '' && body.getNumChildren() > 1) primero.removeFromParent();
  } catch (_) {}
}

function fechaLarga_(fecha) {
  var d = fecha instanceof Date ? fecha : new Date(fecha);
  return Number(formato_(d, 'd')) + ' de ' + MESES[Number(formato_(d, 'M')) - 1] + ' de ' + formato_(d, 'yyyy');
}

function fmtMonto_(n) {
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function fmtTel_(t) {
  var d = String(t || '').replace(/\D/g, '');
  return d.length === 10 ? d.slice(0, 2) + ' ' + d.slice(2, 6) + ' ' + d.slice(6) : String(t || '');
}

function logoBlob_() {
  return Utilities.newBlob(Utilities.base64Decode(LOGO_BASE64), 'image/png', 'logo.png');
}
