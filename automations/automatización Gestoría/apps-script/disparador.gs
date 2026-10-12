/**
 * Disparo puntual de la sincronización de Gestoría LP & CP: lanza el workflow
 * "Gestoria LP & CP Sync" de GitHub Actions cada hora dentro del horario laboral y avisa por correo
 * si la última corrida exitosa es demasiado vieja. Los `schedule` de GitHub se retrasan hasta 6 horas;
 * un workflow_dispatch por API arranca en segundos (ver docs/decisions/0003 y 0005).
 *
 * Activación (una sola vez), en el mismo proyecto de Apps Script de las demás automatizaciones:
 *   1. Pegar este archivo. La propiedad del script GITHUB_TOKEN (token fine-grained del repositorio con
 *      permiso Actions de lectura y escritura) es la misma que ya usan los otros disparadores.
 *   2. Ejecutar probarDisparoGestoria: debe aparecer una corrida nueva en la pestaña Actions de GitHub.
 *   3. Ejecutar crearDisparadorGestoria: crea un disparador cada hora para ejecutarGestoria.
 * Si el proyecto ya tiene una función ejecutarGestoria, borrar la anterior: no pueden convivir dos.
 *
 * La función es independiente de los demás reportes: un error o un retraso aquí no afecta al Query Sync,
 * al tablero LP ni al Balance, y viceversa. La sincronización es idempotente y el workflow serializa las
 * corridas (concurrency), así que un disparo duplicado o un cron de respaldo que coincida no hacen daño.
 */

/** Configuración agrupada en un solo objeto para que sus nombres no choquen con los de otros archivos. */
const GESTORIA_LP_CP = {
  REPO: 'armandomedina-netizen/MAXIRent',
  WORKFLOW: 'gestoria-lp-cp-sync.yml',
  RAMA: 'main',
  PROPIEDAD_TOKEN: 'GITHUB_TOKEN',
  ZONA: 'America/Mexico_City',
  // Días (1 = lunes ... 7 = domingo) y horas (0-23, inclusive) en que se dispara y se vigila.
  DIAS: [1, 2, 3, 4, 5, 6],
  HORA_INICIO: 8,
  HORA_FIN: 19,
  // Reintentos del disparo ante errores de red o 5xx de GitHub (un 4xx no se reintenta: es token o permisos).
  INTENTOS: 3,
  // Vigilante: correo si la última corrida exitosa tiene más de TOLERANCIA_HORAS dentro del horario,
  // y como máximo uno cada HORAS_ENTRE_AVISOS para no llenar la bandeja.
  TOLERANCIA_HORAS: 3,
  HORAS_ENTRE_AVISOS: 6,
  PROPIEDAD_ULTIMO_AVISO: 'GESTORIA_ULTIMO_AVISO'
};

/** True si el instante cae en un día y una hora del horario (hora de ZONA, no la del proyecto). */
function gestoriaDentroDeHorario_(instante) {
  const dia = Number(Utilities.formatDate(instante, GESTORIA_LP_CP.ZONA, 'u'));
  const hora = Number(Utilities.formatDate(instante, GESTORIA_LP_CP.ZONA, 'H'));
  return GESTORIA_LP_CP.DIAS.indexOf(dia) !== -1 &&
    hora >= GESTORIA_LP_CP.HORA_INICIO && hora <= GESTORIA_LP_CP.HORA_FIN;
}

function gestoriaToken_() {
  const token = PropertiesService.getScriptProperties().getProperty(GESTORIA_LP_CP.PROPIEDAD_TOKEN);
  if (!token) {
    throw new Error('Falta la propiedad ' + GESTORIA_LP_CP.PROPIEDAD_TOKEN + ' del script.');
  }
  return token;
}

function gestoriaPeticion_(metodo, ruta, cuerpo) {
  const opciones = {
    method: metodo,
    headers: {
      Authorization: 'Bearer ' + gestoriaToken_(),
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    muteHttpExceptions: true
  };
  if (cuerpo) {
    opciones.contentType = 'application/json';
    opciones.payload = JSON.stringify(cuerpo);
  }
  return UrlFetchApp.fetch(
    'https://api.github.com/repos/' + GESTORIA_LP_CP.REPO + '/actions/workflows/' + GESTORIA_LP_CP.WORKFLOW + ruta,
    opciones
  );
}

/**
 * Lanza el workflow por workflow_dispatch. Reintenta ante errores de red y 5xx; lanza un error (con sólo el
 * código de respuesta) si GitHub no contesta 204 después de los intentos o si responde un 4xx.
 */
function gestoriaLanzarWorkflow_() {
  gestoriaToken_(); // falla de inmediato si falta la propiedad, sin reintentos inútiles
  let ultimoError = null;
  for (let intento = 1; intento <= GESTORIA_LP_CP.INTENTOS; intento++) {
    let codigo = null;
    try {
      codigo = gestoriaPeticion_('post', '/dispatches', { ref: GESTORIA_LP_CP.RAMA }).getResponseCode();
    } catch (e) {
      ultimoError = e; // error de red: se reintenta
    }
    if (codigo === 204) {
      return;
    }
    if (codigo !== null) {
      ultimoError = new Error('GitHub respondió ' + codigo + ' al lanzar el workflow.');
      if (codigo < 500) {
        throw ultimoError; // 4xx: token o permisos, reintentar no sirve
      }
    }
    if (intento < GESTORIA_LP_CP.INTENTOS) {
      Utilities.sleep(5000 * intento);
    }
  }
  throw ultimoError;
}

/**
 * Horas desde la última corrida exitosa del workflow (cualquier origen: Apps Script, cron o manual), o
 * null si GitHub no tiene ninguna.
 */
function gestoriaHorasDesdeUltimoExito_() {
  const respuesta = gestoriaPeticion_('get', '/runs?status=success&per_page=1');
  const codigo = respuesta.getResponseCode();
  if (codigo !== 200) {
    throw new Error('GitHub respondió ' + codigo + ' al consultar las corridas.');
  }
  const corridas = JSON.parse(respuesta.getContentText()).workflow_runs || [];
  if (corridas.length === 0) {
    return null;
  }
  return (Date.now() - new Date(corridas[0].updated_at).getTime()) / 3600000;
}

/**
 * Envía un correo (a quien ejecuta el script) si la última corrida exitosa pasó de la tolerancia. Un aviso
 * como máximo cada HORAS_ENTRE_AVISOS, guardado en las propiedades del script.
 */
function gestoriaVigilar_() {
  const horas = gestoriaHorasDesdeUltimoExito_();
  if (horas !== null && horas <= GESTORIA_LP_CP.TOLERANCIA_HORAS) {
    return;
  }
  const propiedades = PropertiesService.getScriptProperties();
  const ultimo = Number(propiedades.getProperty(GESTORIA_LP_CP.PROPIEDAD_ULTIMO_AVISO) || 0);
  if ((Date.now() - ultimo) / 3600000 < GESTORIA_LP_CP.HORAS_ENTRE_AVISOS) {
    return;
  }
  const antiguedad = horas === null ? 'no hay ninguna corrida exitosa registrada' : 'hace ' + horas.toFixed(1) + ' horas';
  MailApp.sendEmail(
    Session.getEffectiveUser().getEmail(),
    'Gestoría LP & CP: la sincronización no corre',
    'La última corrida exitosa del workflow ' + GESTORIA_LP_CP.WORKFLOW + ' fue ' + antiguedad +
      ' (tolerancia: ' + GESTORIA_LP_CP.TOLERANCIA_HORAS + ' h en horario laboral).\n\n' +
      'Revisar: https://github.com/' + GESTORIA_LP_CP.REPO + '/actions/workflows/' + GESTORIA_LP_CP.WORKFLOW + '\n' +
      'Causas comunes: token de GitHub vencido o revocado, secrets del repositorio, Maxinet caído.'
  );
  propiedades.setProperty(GESTORIA_LP_CP.PROPIEDAD_ULTIMO_AVISO, String(Date.now()));
}

/** Función del disparador horario: lanza el workflow y vigila, sólo dentro del horario. */
function ejecutarGestoria() {
  if (!gestoriaDentroDeHorario_(new Date())) {
    console.log('Fuera del horario: no se lanza ni se vigila.');
    return;
  }
  let errorDisparo = null;
  try {
    gestoriaLanzarWorkflow_();
    console.log('Workflow de Gestoría lanzado.');
  } catch (e) {
    errorDisparo = e;
    console.error(e.message);
  }
  try {
    gestoriaVigilar_();
  } catch (e) {
    console.error('Vigilante: ' + e.message);
  }
  if (errorDisparo) {
    throw errorDisparo;
  }
}

/** Lanza el workflow sin mirar el horario, para comprobar desde el editor el token y el workflow. */
function probarDisparoGestoria() {
  gestoriaLanzarWorkflow_();
  console.log('Workflow de Gestoría lanzado a mano.');
}

/** Muestra cuántas horas han pasado desde la última corrida exitosa, sin enviar nada. */
function probarVigilanteGestoria() {
  const horas = gestoriaHorasDesdeUltimoExito_();
  console.log(horas === null ? 'No hay corridas exitosas.' : 'Última corrida exitosa hace ' + horas.toFixed(1) + ' h.');
}

/** Crea el disparador cada hora para ejecutarGestoria; borra antes los que ya existían, así que se puede repetir. */
function crearDisparadorGestoria() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'ejecutarGestoria'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('ejecutarGestoria').timeBased().everyHours(1).create();
}
