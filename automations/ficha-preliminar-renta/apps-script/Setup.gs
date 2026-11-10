/**
 * Configuración inicial, autoprueba y reparaciones. Se ejecutan a mano desde el editor de Apps Script.
 */

/** Paso único de instalación: crea las hojas, la carpeta raíz y da de alta a quien la ejecuta como ejecutivo. */
function configurar() {
  hojaCon_(HOJA_EJECUTIVOS, ENCABEZADOS_EJECUTIVOS);
  hojaCon_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
  hojaCon_(HOJA_FICHAS, ENCABEZADOS_FICHAS);
  var raiz = carpetaRaiz_();
  var yo = correoActual_();
  var lista = leerTabla_(HOJA_EJECUTIVOS, ENCABEZADOS_EJECUTIVOS);
  if (yo && !lista.filas.some(function (f) { return String(f['Correo']).toLowerCase() === yo; })) {
    escribirFila_(lista.hoja, lista.hoja.getLastRow() + 1, [yo, yo, 'SI']);
  }
  console.log('Listo. Carpeta raíz en Drive: ' + raiz.getUrl());
  console.log('Siguiente: agregue a sus ejecutivos en la hoja "Ejecutivos" y guarde la propiedad URL_FORMULARIO.');
}

/**
 * Prueba de punta a punta con datos de ejemplo: crea un enlace, simula la firma del cliente y deja
 * los archivos en Drive. Requiere URL_FORMULARIO. Después se borra la ficha de prueba (ver README).
 */
function autoprueba() {
  configurar();
  var ej = exigirEjecutivo_();
  var enlace = crearEnlace('PRUEBA - Cliente de ejemplo SA de CV');
  var token = enlace.url.split('#t=')[1];
  console.log('Enlace creado: ' + enlace.folio + ' (' + enlace.url + ')');

  var consulta = consultarEnlace_(token);
  if (!consulta.ok) throw new Error('La consulta del enlace falló: ' + consulta.mensaje);

  var campos = [];
  function add(id, etiqueta, valor) { campos.push([id, etiqueta, valor]); }
  add('s_nombre', 'Nombre completo o razón social', 'Cliente de ejemplo SA de CV');
  add('s_giro', 'Giro o actividad comercial', 'Transporte de carga');
  add('s_ciudad', 'Ciudad y estado', 'Monterrey, Nuevo León');
  [['principal', 'Contacto principal (Solicitante)', ['nombre', 'puesto', 'tel', 'mail']],
   ['legal', 'Representante legal', ['nombre', 'tel', 'movil', 'mail']],
   ['supervisor', 'Jefe(a) / Supervisor(a) de cobranza', ['nombre', 'tel', 'mail']],
   ['cobranza', 'Contacto de cobranza', ['nombre', 'tel', 'mail']],
   ['pagos', 'Contacto de pagos', ['nombre', 'tel', 'mail']]].forEach(function (r) {
    r[2].forEach(function (f) {
      add('c_' + r[0] + '_' + f, r[1] + ' – ' + f, f === 'tel' || f === 'movil' ? '8112345678' : f === 'mail' ? 'prueba@example.test' : 'Dato de prueba');
    });
  });
  [1, 2].forEach(function (n) {
    add('r' + n + '_empresa', 'Referencia ' + n + ' – Empresa', 'Proveedor de prueba ' + n);
    add('r' + n + '_contacto', 'Referencia ' + n + ' – Contacto', 'Contacto de prueba');
    add('r' + n + '_tel', 'Referencia ' + n + ' – Teléfono', '8187654321');
    add('r' + n + '_fact', 'Referencia ' + n + ' – Facturación', 125000);
    add('r' + n + '_mail', 'Referencia ' + n + ' – Correo', 'proveedor@example.test');
  });
  add('f_firmante', 'Firmante', 'Persona de prueba');
  var png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

  var lock = LockService.getScriptLock();
  lock.waitLock(25000);
  var r;
  try {
    r = recibirFicha_({ token: token, campos: campos, firmante: 'Persona de prueba', firma: 'data:image/png;base64,' + png,
      fechaLlenado: formato_(new Date(), 'yyyy-MM-dd'), tiempoMs: 60000, web: '' });
  } finally { lock.releaseLock(); }
  console.log('Resultado: ' + JSON.stringify(r));
  if (!r.ok) throw new Error(r.mensaje);

  var otra = recibirFichaRepetida_(token, campos, png);
  console.log('Segundo intento con el mismo enlace (debe rechazarse): ' + otra);
  var fila = fichasDe_(ej.correo).filter(function (f) { return f.folio === enlace.folio; })[0];
  console.log('Documento firmado: ' + fila.documento);
  console.log('PDF firmado: ' + fila.pdf);
  console.log('Revise Drive: Ejecutivos > su carpeta > Firmadas. Después borre la ficha de prueba (filas de Enlaces y Fichas y los archivos).');
}

function recibirFichaRepetida_(token, campos, png) {
  var r = recibirFicha_({ token: token, campos: campos, firmante: 'Persona de prueba', firma: 'data:image/png;base64,' + png,
    fechaLlenado: formato_(new Date(), 'yyyy-MM-dd'), tiempoMs: 60000, web: '' });
  return r.ok ? 'ERROR: se aceptó' : 'rechazado (' + r.mensaje + ')';
}

/**
 * Rehace el documento y el PDF de una ficha ya firmada cuando la generación falló en su momento.
 * Uso: regenerarDocumento('FP-20261110-001')
 */
function regenerarDocumento(folio) {
  exigirEjecutivo_();
  var lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    var enlaces = leerTabla_(HOJA_ENLACES, ENCABEZADOS_ENLACES);
    var enlace = enlaces.filas.filter(function (f) { return f['Folio'] === folio; })[0];
    if (!enlace || enlace['Estado'] !== 'FIRMADA') throw new Error('No hay una ficha firmada con ese folio.');
    var fichas = leerTabla_(HOJA_FICHAS, ENCABEZADOS_FICHAS);
    var fila = fichas.filas.filter(function (f) { return f['Folio'] === folio; })[0];
    if (!fila) throw new Error('No se encontró la fila de la ficha.');
    var idFirma = (fila['Firma (archivo)'].match(/[-\w]{25,}/) || [])[0];
    var blob = DriveApp.getFileById(idFirma).getBlob();
    var p = { campos: JSON.parse(fila['Datos (JSON)']), firmante: fila['Firmante'],
      firma: 'data:image/png;base64,' + Utilities.base64Encode(blob.getBytes()), fechaLlenado: fila['Fecha de llenado'] };
    var archivos = generarDocumentoFirmado_(enlace, p, new Date(enlace['Firmado']));
    actualizarFila_(enlaces, enlace, { 'Documento (enlace)': archivos.docUrl, 'PDF (enlace)': archivos.pdfUrl });
    actualizarFila_(fichas, fila, { 'Documento firmado': archivos.docUrl, 'PDF firmado': archivos.pdfUrl });
    console.log('Documento regenerado: ' + archivos.docUrl);
  } finally { lock.releaseLock(); }
}
