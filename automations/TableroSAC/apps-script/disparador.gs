/**
 * Disparo exacto de la sincronización monday -> Google Sheets: lanza el workflow "Tablero SAC" de
 * GitHub Actions a las horas de TABLERO_SAC.HORARIO. Un disparador diario por cada hora distinta
 * llama a ejecutarTableroSac, que decide si ese día y esa hora corresponden al horario.
 */

/**
 * Configuración del disparador, agrupada en un solo objeto para que sus nombres no choquen con los
 * de otros archivos del mismo proyecto de Apps Script.
 */
const TABLERO_SAC = {
  REPO: 'armandomedina-netizen/MAXIRent',
  WORKFLOW: 'tablero-sac.yml',
  RAMA: 'main',
  // Propiedad del script que guarda el token fine-grained de GitHub (permiso Actions de lectura y escritura).
  PROPIEDAD_TOKEN: 'GITHUB_TOKEN',
  ZONA: 'America/Mexico_City',
  // Horas de corrida por día de la semana (1 = lunes ... 6 = sábado); el domingo no corre.
  HORARIO: {
    "1": [7, 9, 11, 13, 15, 17],
    "2": [7, 9, 11, 13, 15, 17],
    "3": [7, 9, 11, 13, 15, 17],
    "4": [7, 9, 11, 13, 15, 17],
    "5": [7, 9, 11, 13, 15, 17],
    "6": [7, 9, 11, 13, 14]
  }
};

/**
 * Devuelve el día de la semana (1 = lunes ... 7 = domingo) y la hora (0-23) de la corrida a la que
 * pertenece un instante. Google ejecuta los disparadores diarios dentro de ±15 minutos de la hora
 * indicada, así que se mira 20 minutos adelante: una ejecución a las 6:50 cuenta como la de las 7.
 */
function tableroSacCorridaNominal_(instante) {
  const adelantado = new Date(instante.getTime() + 20 * 60 * 1000);
  return {
    dia: Number(Utilities.formatDate(adelantado, TABLERO_SAC.ZONA, 'u')),
    hora: Number(Utilities.formatDate(adelantado, TABLERO_SAC.ZONA, 'H'))
  };
}

/**
 * Lanza el workflow por workflow_dispatch con el token de las propiedades del script. Lanza un error
 * si falta el token o si GitHub no responde 204; el mensaje trae sólo el código de respuesta.
 */
function tableroSacLanzarWorkflow_() {
  const token = PropertiesService.getScriptProperties().getProperty(TABLERO_SAC.PROPIEDAD_TOKEN);
  if (!token) {
    throw new Error('Falta la propiedad ' + TABLERO_SAC.PROPIEDAD_TOKEN + ' del script.');
  }
  const respuesta = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + TABLERO_SAC.REPO + '/actions/workflows/' + TABLERO_SAC.WORKFLOW + '/dispatches',
    {
      method: 'post',
      contentType: 'application/json',
      headers: {
        Authorization: 'Bearer ' + token,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
      },
      payload: JSON.stringify({ ref: TABLERO_SAC.RAMA }),
      muteHttpExceptions: true
    }
  );
  const codigo = respuesta.getResponseCode();
  if (codigo !== 204) {
    throw new Error('GitHub respondió ' + codigo + ' al lanzar el workflow.');
  }
}

/** Función de los disparadores: lanza el workflow si el instante actual corresponde a una hora del horario. */
function ejecutarTableroSac() {
  const corrida = tableroSacCorridaNominal_(new Date());
  if ((TABLERO_SAC.HORARIO[String(corrida.dia)] || []).indexOf(corrida.hora) === -1) {
    console.log('Fuera del horario: no se lanza el workflow.');
    return;
  }
  tableroSacLanzarWorkflow_();
  console.log('Workflow lanzado (día ' + corrida.dia + ', ' + corrida.hora + ' h).');
}

/** Lanza el workflow sin mirar el horario, para comprobar desde el editor el token y el workflow. */
function probarDisparoTableroSac() {
  tableroSacLanzarWorkflow_();
  console.log('Workflow lanzado a mano.');
}

/**
 * Comprueba que la zona horaria del proyecto tenga el mismo desfase que TABLERO_SAC.ZONA. Los
 * activadores diarios usan la zona del proyecto y el filtro del horario usa ZONA: si difieren, las
 * corridas llegarían a una hora que el filtro descarta. Compara desfases, así que America/Monterrey
 * y America/Mexico_City cuentan como iguales.
 */
function tableroSacVerificarZona_() {
  const ahora = new Date();
  const zonaProyecto = Session.getScriptTimeZone();
  if (Utilities.formatDate(ahora, zonaProyecto, 'Z') !== Utilities.formatDate(ahora, TABLERO_SAC.ZONA, 'Z')) {
    throw new Error('La zona horaria del proyecto (' + zonaProyecto + ') no coincide con la de TABLERO_SAC.ZONA (' + TABLERO_SAC.ZONA + ').');
  }
}

/**
 * Crea un disparador diario por cada hora distinta de TABLERO_SAC.HORARIO, con nearMinute(0) para
 * que Google lo ejecute entre 15 minutos antes y 15 después de la hora. Verifica antes la zona
 * horaria del proyecto y borra los disparadores que ya existían para ejecutarTableroSac, de modo
 * que se puede volver a ejecutar sin duplicarlos.
 */
function crearDisparadoresTableroSac() {
  tableroSacVerificarZona_();
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'ejecutarTableroSac'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });

  const horas = {};
  Object.keys(TABLERO_SAC.HORARIO).forEach(function (dia) {
    TABLERO_SAC.HORARIO[dia].forEach(function (h) { horas[h] = true; });
  });
  Object.keys(horas).map(Number).sort(function (a, b) { return a - b; }).forEach(function (h) {
    ScriptApp.newTrigger('ejecutarTableroSac').timeBased().everyDays(1).atHour(h).nearMinute(0).create();
  });
}
