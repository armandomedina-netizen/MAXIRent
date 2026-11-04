"""
Automatización: login + lectura del reporte "Ordenes de Mantenimiento LP" desde Maxinet vía requests (sin navegador)
y actualización POR ID de un Sheet propio con todas las órdenes que han ingresado a taller en el año.

Endpoint (el mismo de maxinet-mtto-ordenes, ver su docstring):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/lp-mtto-ordenes.php
            body: Criterio=INGRESO, Estatus=1, Desde, Hasta, valueCriterio (los campos del filtro de la página)
            respuesta: {"data": [[62 celdas HTML], ...]} o {"data": ""} si no hay filas.
    Estatus debe ir SIEMPRE con valor: con INGRESO devuelve exactamente las mismas órdenes con 1 que con 0, y con
    el campo vacío el servidor responde {"data": ""}.

Qué hace en cada corrida (diaria):
    1. Pide a Maxinet las órdenes con "Fecha Ingreso Taller" del 1 de enero del año a hoy (hora Ciudad de México);
       es una sola consulta de unos 10 segundos (unas 6,200 órdenes a principios de noviembre).
    2. Las compara por Id con lo que ya tiene la hoja.
    3. Actualiza en su lugar SÓLO las filas que cambiaron (estatus, fechas de entrega o cierre, costos...) y agrega
       al final las órdenes que ingresaron a taller y todavía no estaban. No borra ni reordena filas: una orden que
       Maxinet deje de mostrar conserva su última versión en la hoja.
    La ventana arranca el 1 de enero, o antes si la hoja tiene alguna orden sin cerrar con ingreso más antiguo (así,
    al cambiar de año, las órdenes que quedaron abiertas se siguen actualizando hasta que cierren).
    Las órdenes que aún no ingresan a taller (citas por aprobar, en revisión) no están en el filtro y no se agregan;
    entran a la hoja el día que ingresan.

Columnas: las 62 del reporte menos los 3 botones (Detalle, Hoja Cita, Bitácora): 59, con los nombres del reporte
(incluidos los datos de contacto, a petición expresa). Los valores se escriben tipados (fechas y horas como números
de serie, costos y días como números; todo lo demás como texto) con RAW, para que Sheets no reinterprete placas ni
folios. Al comparar, cada celda se normaliza (fecha, hora, número o texto), así que una celda guardada como texto
"2026-05-07" y otra como fecha igual no cuentan como cambio.

Salvaguardas (FORZAR=1 omite las de volumen; las de estructura siempre aplican): la corrida se detiene SIN escribir si
    - el reporte cambió de ancho o sus columnas no cuadran (Id, Fecha Alta, Fecha Ingreso Taller, placa),
    - la hoja tiene otro encabezado (alguien movió o renombró columnas) o repite algún Id,
    - Maxinet no trae ninguna orden, o le faltan más del 20% de las órdenes con ingreso en el rango que ya estaban en la
      hoja (con 30 o más): probable respuesta incompleta,
    - más del 30% de las filas de la hoja saldrían "cambiadas" (con 200 o más): casi seguro un cambio de formato en
      la hoja o en el reporte, no 'movimiento' real,
    - la columna Id de la hoja cambió mientras se preparaba la escritura (alguien ordenó o insertó filas): como se
      escribe por número de fila, no se arriesga a pisar otra orden.
Después de escribir se vuelve a leer la columna Id y la corrida falla si no quedó como se esperaba.

Los logs sólo llevan conteos y nombres de columnas: la tabla trae nombres, teléfonos y correos de clientes y no se
registran.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_MTTO_TALLER (el archivo de Sheets destino),
    WORKSHEET_MTTO_TALLER (nombre o gid de la pestaña; si no se define, el archivo debe tener una sola pestaña),
    FECHA_DESDE, FECHA_HASTA, DRY_RUN, FORZAR (opcionales)
"""

import os
import re
import sys
import json
import html
import time
import logging
import collections
import datetime as dt
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import gspread
from gspread.http_client import HTTPClient
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_mtto_taller")


def _instalar_reintentos_gspread(cliente=HTTPClient) -> None:
    """Google Sheets limita las lecturas por minuto por usuario y esa cuota la comparten TODAS las automatizaciones que
    usan la misma cuenta de servicio (entre las 8:05 y las 8:45 corren varias a la vez). Un 429 se rechaza antes de
    procesarse, así que reintentar es seguro; los errores 5xx sólo se reintentan en lecturas (GET), para no duplicar una
    escritura. Es la misma regla del resto de las automatizaciones."""
    if getattr(cliente.request, "_reintenta_429", False):
        return
    original = cliente.request

    def con_reintentos(self, method, *args, **kwargs):
        for intento in range(1, 7):
            try:
                return original(self, method, *args, **kwargs)
            except gspread.exceptions.APIError as e:
                codigo = getattr(e.response, "status_code", None)
                reintentable = codigo == 429 or (codigo in (500, 502, 503) and str(method).lower() == "get")
                if not reintentable or intento == 6:
                    raise
                espera = 20 * intento
                log.warning("Google Sheets respondió %s; reintento %d de 5 en %d s", codigo, intento, espera)
                time.sleep(espera)

    con_reintentos._reintenta_429 = True
    cliente.request = con_reintentos


_instalar_reintentos_gspread()

# Orden confirmado en el HTML real de lp-mtto-ordenes.php (las 3 primeras columnas son botones sin título)
COLUMNAS_REPORTE = [
    "", "", "",
    "Id", "Tipo ticket", "Estatus", "Tipo Servicio", "Sub Tipo", "No.Placa", "PUSite", "# Reserva", "# Cliente",
    "Nombre Cliente", "Grupo", "Marca", "Modelo", "Km.Actual", "Ciudad", "Taller",
    "Fecha Alta", "Hora Alta", "Fecha Prop.Cita", "Hora Prop.Cita", "Fecha Cita", "Hora Cita",
    "Fecha Ingreso Taller", "Dias Cte. Entr. Taller", "Hora Ingreso Taller", "Fecha Promesa", "Hora Promesa",
    "Fecha Diagnóstico", "Hora Diagnóstico", "Fecha T.Terminado", "Hora T.Terminado",
    "Fecha Entrega Cliente", "Dias Taller", "Hora Entrega Cliente", "Fecha Cierre", "Hora Cierre",
    "Fecha Reingreso", "Hora Reingreso", "Motivo Reingreso", "Facturado", "Pagado", "Costo Total",
    "Cobro cliente", "Monto cliente", "Costo Real", "Comentarios Cliente", "Diagnóstico",
    "Se ha realizado la afinación de esta unidad?", "CANTIDAD LLANTAS", "Responsable Alta",
    "Nombre Contacto", "Tel. Contacto", "Cel. Contacto", "Correo",
    "PUDate", "ReturnDate", "Asesor", "Origen", "IdApp",
]
ANCHO_REPORTE = len(COLUMNAS_REPORTE)                      # 62
IDX_BOTONES = (0, 1, 2)
IDX_SALIDA = [i for i in range(ANCHO_REPORTE) if i not in IDX_BOTONES]
ENCABEZADO = [COLUMNAS_REPORTE[i] for i in IDX_SALIDA]    # las 59 columnas de la hoja

FECHAS = {n for n in ENCABEZADO if n.startswith("Fecha ") or n in ("PUDate", "ReturnDate")}
HORAS = {n for n in ENCABEZADO if n.startswith("Hora ")}
NUMEROS = {"Id", "Km.Actual", "Dias Cte. Entr. Taller", "Dias Taller", "Costo Total", "Monto cliente",
           "Costo Real", "CANTIDAD LLANTAS", "IdApp"}
COSTOS = ("Costo Total", "Monto cliente", "Costo Real")
TELEFONOS = {"Tel. Contacto", "Cel. Contacto"}
MULTILINEA = {"Diagnóstico", "Comentarios Cliente"}          # los únicos textos con saltos de línea; el resto va en una línea

COL_ID = ENCABEZADO.index("Id")
COL_ESTATUS = ENCABEZADO.index("Estatus")
COL_PLACA = ENCABEZADO.index("No.Placa")
COL_FECHA_ALTA = ENCABEZADO.index("Fecha Alta")
COL_INGRESO = ENCABEZADO.index("Fecha Ingreso Taller")
# Estatus en los que la orden ya no se mueve: si todas las de la hoja están aquí, la ventana no necesita retroceder
ESTATUS_FINALES = ("CERRADO", "CANCELADO", "CITA RECHAZADA")

ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
UMBRAL_AUSENTES = 0.2
UMBRAL_CAMBIOS = 0.3
MINIMO_AUSENTES = 30
MINIMO_CAMBIOS = 200
TROZO_RANGOS = 300                                         # rangos por llamada a batch_update
TROZO_FILAS = 1000                                         # filas por rango de altas
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HORA_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
NUMERO_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
BASE_SERIAL = dt.date(1899, 12, 30)
MARCA_ACTUALIZADO = "ACTUALIZADO (hora CDMX)"


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 200 caracteres: %r", texto[:200])
        raise


def _nueva_sesion() -> requests.Session:
    """Reintenta con espera creciente si Maxinet corta la conexión o responde 502/503/504."""
    session = requests.Session()
    retry = Retry(total=REINTENTOS, connect=REINTENTOS, read=REINTENTOS, status=REINTENTOS,
                  backoff_factor=2, status_forcelist=(502, 503, 504), allowed_methods=None)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def login_maxinet() -> requests.Session:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = _nueva_sesion()
    resp = session.post(
        f"{base_url}/includes/users/AccessValidate.php",
        data={"email": os.environ["MAXINET_USER"], "password": os.environ["MAXINET_PASS"]},
        timeout=TIMEOUT_SEG,
    )
    data = _parse_json_bom(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")
    log.info("Login en Maxinet exitoso")
    return session


def ventana(hoy: dt.date = None, pendiente_desde: str = None) -> tuple[str, str]:
    """(desde, hasta) ISO por Fecha Ingreso Taller: del 1 de enero del año a HOY (hora CDMX), o desde el ingreso de la
    orden sin cerrar más antigua de la hoja si es anterior. FECHA_DESDE/FECHA_HASTA fijan el rango (pruebas)."""
    hoy = hoy or dt.datetime.now(ZONA).date()
    hasta = os.environ.get("FECHA_HASTA") or hoy.isoformat()
    inicio_anio = dt.date.fromisoformat(hasta).replace(month=1, day=1).isoformat()
    desde = os.environ.get("FECHA_DESDE") or min(d for d in (inicio_anio, pendiente_desde) if d)
    return desde, hasta


def consultar(session: requests.Session, criterio: str, estatus: str = "1", desde: str = "", hasta: str = "") -> list[list]:
    """Una consulta del filtro de la página. Estatus siempre con valor (ver docstring del módulo)."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(
        f"{base_url}/json/lp-mtto-ordenes.php",
        data={"Criterio": criterio, "Estatus": estatus, "Desde": desde, "Hasta": hasta, "valueCriterio": ""},
        timeout=TIMEOUT_SEG,
    )
    data = _parse_json_bom(resp).get("data")
    if data in ("", None):
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"Maxinet devolvió un 'data' inesperado ({type(data).__name__}); no se escribió nada.")
    return data


# -------------------------------------------------------- limpieza y tipos
def _texto(v) -> str:
    """Texto sin etiquetas HTML ni espacios sobrantes; el 'None' que imprime el reporte es vacío."""
    if v is None:
        return ""
    s = html.unescape(re.sub(r"<[^>]*>", "", str(v))).replace("\xa0", " ").strip()
    return "" if s in ("None", "null", "NULL") else s


def normalizar_filas(filas: list[list]) -> list[list[str]]:
    """Las 62 celdas de cada fila ya limpias. Un ancho distinto, o columnas que no cuadren (Id sin forma de número,
    fechas sin forma de fecha, placa vacía), detienen la corrida SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO_REPORTE}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de órdenes: llegaron filas de {sorted(anchos)} columnas y se "
            f"esperan {ANCHO_REPORTE}. No se escribió nada en el Sheet; revisar json/lp-mtto-ordenes.php y ajustar "
            f"COLUMNAS_REPORTE."
        )
    out = []
    for f in filas:
        fila = [_texto(v) for v in f]
        orden = fila[IDX_SALIDA[COL_ID]]
        alta, ingreso = fila[IDX_SALIDA[COL_FECHA_ALTA]], fila[IDX_SALIDA[COL_INGRESO]]
        if (not orden.isdigit() or not FECHA_RE.match(alta) or not FECHA_RE.match(ingreso)
                or not fila[IDX_SALIDA[COL_PLACA]]):
            raise RuntimeError(
                f"Las columnas del reporte de órdenes no cuadran (Id={orden[:20]!r}, Fecha Alta={alta[:20]!r}, "
                f"Fecha Ingreso Taller={ingreso[:20]!r}). No se escribió nada en el Sheet."
            )
        out.append(fila)
    return out


def _serie_fecha(texto: str) -> int | None:
    """Número de serie de una fecha ISO, o None si no es una fecha válida. Un año de dos dígitos (0026, tecleado sin el
    '20') se lee como 20xx, igual que lo guardó Sheets en las celdas que ya tenía el archivo; los demás años raros se
    conservan como lo que son (2206, 3026), también como en el archivo."""
    if not FECHA_RE.match(texto):
        return None
    try:
        d = dt.date.fromisoformat(texto)
        if d.year < 100:
            d = d.replace(year=d.year + 2000)
    except ValueError:
        return None
    return (d - BASE_SERIAL).days


def _colapsar(texto: str) -> str:
    """Espacios, tabuladores y saltos de línea repetidos como un solo espacio, sin espacios en los bordes."""
    return re.sub(r"\s+", " ", texto).strip()


def _forma_texto(nombre: str, texto: str) -> str:
    """Texto como lo guarda el archivo: una línea (espacios repetidos colapsados) salvo los campos de varias líneas, que
    sólo normalizan el salto de línea de Windows (CRLF) al de Sheets (LF)."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return texto if nombre in MULTILINEA else re.sub(r"\s+", " ", texto)


def _valor(nombre: str, texto: str):
    """Valor tipado de una celda: fecha y hora como número de serie, números como número, el resto como texto.
    Lo que no tenga la forma esperada (una fecha que no existe, una hora de 25:99) se conserva como texto."""
    if texto == "":
        return ""
    if nombre in FECHAS:
        serie = _serie_fecha(texto)
        return texto if serie is None else serie
    if nombre in HORAS:
        m = HORA_RE.match(texto)
        if m and int(m[1]) < 24 and int(m[2]) < 60 and int(m[3] or 0) < 60:
            return (int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)) / 86400
        return texto
    if nombre in NUMEROS:
        t = texto.replace(",", "")
        if NUMERO_RE.match(t):
            return float(t) if "." in t else int(t)
    return _forma_texto(nombre, texto)


def a_fila_hoja(fila: list[str]) -> list:
    """Las 59 columnas de la hoja, tipadas, a partir de las 62 limpias."""
    return [_valor(ENCABEZADO[k], fila[i]) for k, i in enumerate(IDX_SALIDA)]


def _es_numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def canonico(nombre: str, v):
    """Forma comparable de una celda, sea del reporte o de la hoja: la misma orden con el mismo dato da el mismo valor
    aunque la hoja guarde la fecha como texto, el teléfono como número o los espacios y saltos de línea de otra forma."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return ""
    if nombre in FECHAS:
        if _es_numero(v):
            return int(v)
        t = str(v).strip()
        serie = _serie_fecha(t)
        return t if serie is None else serie
    if nombre in HORAS:
        if _es_numero(v):
            return round(v * 86400)
        t = str(v).strip()
        m = HORA_RE.match(t)
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0) if m else t
    if nombre in NUMEROS:
        if _es_numero(v):
            return round(float(v), 4)
        t = str(v).strip().replace(",", "")
        return round(float(t), 4) if NUMERO_RE.match(t) else str(v).strip()
    t = str(int(v)) if _es_numero(v) and float(v).is_integer() else _colapsar(str(v))
    if nombre in TELEFONOS and re.fullmatch(r"[0-9]+", t):
        return t.lstrip("0") or "0"          # Maxinet manda 0000000000 donde no hay teléfono y Sheets lo guarda como 0
    return t


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


ULT_COL = _col_a1(len(ENCABEZADO))                          # "BG"
COL_ESTADO = _col_a1(len(ENCABEZADO) + 2)                   # una columna libre de por medio, a la derecha de los datos


def resolver_pestana(libro):
    """La pestaña por gid (si el secret es un número) o por nombre; sin secret, la única pestaña del archivo. Los logs
    son públicos: si falta, el error sólo dice cuántas pestañas tiene el libro."""
    ref = (os.environ.get("WORKSHEET_MTTO_TALLER") or "").strip().strip("\"'").strip()
    if not ref:
        hojas = libro.worksheets()
        if len(hojas) == 1:
            return hojas[0]
        raise RuntimeError(f"El archivo tiene {len(hojas)} pestañas: define WORKSHEET_MTTO_TALLER con el nombre o el gid "
                           f"de la pestaña de órdenes.")
    try:
        return libro.get_worksheet_by_id(int(ref)) if ref.isdigit() else libro.worksheet(ref)
    except gspread.exceptions.WorksheetNotFound:
        raise gspread.exceptions.WorksheetNotFound(
            f"{ref} (el archivo tiene {len(libro.worksheets())} pestañas; si la renombraron, usa su gid en el secret)") from None


def conectar_libro():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_MTTO_TALLER"])


def _id_hoja(v):
    """Id de una celda de la hoja (número, o texto con dígitos); None si no es un Id."""
    if _es_numero(v):
        return int(v) if float(v).is_integer() else None
    t = str(v).strip()
    return int(t) if t.isdigit() else None


def _ids_columna(hoja) -> dict[int, int]:
    """{número de fila: Id} de la columna A completa (sin el encabezado)."""
    out = {}
    for n, f in enumerate(hoja.get("A1:A", value_render_option="UNFORMATTED_VALUE"), start=1):
        i = _id_hoja(f[0]) if n > 1 and f else None
        if i is not None:
            out[n] = i
    return out


def leer_hoja(hoja):
    """(existentes, ultima, vacia): existentes = {Id: (número de fila, 59 valores)}, ultima = última fila con contenido
    (1 si sólo hay encabezado; una fila ajena, como un total al pie, también cuenta, para no pisarla al agregar) y
    vacia = la pestaña no tiene ni encabezado. Detiene la corrida si el encabezado no es el esperado o si algún Id se
    repite."""
    todo = hoja.get(f"A1:{ULT_COL}", value_render_option="UNFORMATTED_VALUE")
    if not todo:
        return {}, 1, True
    encabezado = [str(h).strip() for h in todo[0]][:len(ENCABEZADO)]
    if encabezado != ENCABEZADO:
        distintas = [i + 1 for i in range(len(ENCABEZADO)) if (encabezado[i] if i < len(encabezado) else None) != ENCABEZADO[i]]
        raise RuntimeError(
            f"La pestaña tiene un encabezado distinto al esperado (difieren las columnas {distintas[:10]}); alguien "
            f"movió o renombró columnas. No se escribió nada; revisar la hoja o ajustar COLUMNAS_REPORTE.")
    existentes, repetidos, ultima = {}, set(), 1
    for n, f in enumerate(todo[1:], start=2):
        if any(str(c).strip() for c in f):
            ultima = n
        i = _id_hoja(f[0]) if f else None
        if i is None:
            continue
        if i in existentes:
            repetidos.add(i)
        existentes[i] = (n, list(f) + [""] * (len(ENCABEZADO) - len(f)))
    if repetidos:
        raise RuntimeError(f"La hoja repite {len(repetidos)} Id (por ejemplo {sorted(repetidos)[:5]}): no se puede "
                           f"actualizar por Id sin saber cuál fila es la buena. No se escribió nada.")
    return existentes, ultima, False


def pendiente_desde(existentes: dict) -> str | None:
    """Fecha de ingreso (ISO) de la orden de la hoja sin cerrar más antigua, o None si todas están cerradas."""
    series = []
    for _, valores in existentes.values():
        estatus = str(valores[COL_ESTATUS]).strip().upper()
        ingreso = canonico("Fecha Ingreso Taller", valores[COL_INGRESO])
        if estatus not in ESTATUS_FINALES and isinstance(ingreso, int):
            series.append(ingreso)
    return (BASE_SERIAL + dt.timedelta(days=min(series))).isoformat() if series else None


def planear(existentes: dict, nuevas: list[list], desde: str, hasta: str) -> dict:
    """Qué hay que escribir: `cambios` [(fila, valores)] de órdenes ya en la hoja que difieren de Maxinet, `altas`
    [valores] de órdenes que no estaban, y las cuentas para el log y las salvaguardas."""
    cambios, altas, formatos = [], [], []
    por_columna = collections.Counter()
    for fila in sorted(nuevas, key=lambda f: f[COL_ID]):
        previo = existentes.get(fila[COL_ID])
        if previo is None:
            altas.append(fila)
            continue
        numero, valores = previo
        distintas = [k for k in range(len(ENCABEZADO))
                     if canonico(ENCABEZADO[k], valores[k]) != canonico(ENCABEZADO[k], fila[k])]
        if distintas:
            nueva = list(valores)                         # la celda que no cambió se queda como está en la hoja
            for k in distintas:
                nueva[k] = fila[k]
                if _formato(ENCABEZADO[k]) and _es_numero(fila[k]) and not _es_numero(valores[k]):
                    formatos.append((numero, k))          # fecha u hora que la orden recibe por primera vez
            cambios.append((numero, nueva))
            por_columna.update(ENCABEZADO[k] for k in distintas)
    ids_maxinet = {f[COL_ID] for f in nuevas}
    s_desde = (dt.date.fromisoformat(desde) - BASE_SERIAL).days
    s_hasta = (dt.date.fromisoformat(hasta) - BASE_SERIAL).days
    en_rango = [i for i, (_, v) in existentes.items()
                if isinstance(canonico("Fecha Ingreso Taller", v[COL_INGRESO]), int)
                and s_desde <= canonico("Fecha Ingreso Taller", v[COL_INGRESO]) <= s_hasta]
    return {
        "cambios": cambios, "altas": altas, "formatos": formatos, "por_columna": por_columna,
        "en_hoja": len(existentes), "en_maxinet": len(nuevas), "iguales": len(nuevas) - len(cambios) - len(altas),
        "en_rango": len(en_rango), "ausentes": sum(1 for i in en_rango if i not in ids_maxinet),
        "fuera_de_maxinet": sum(1 for i in existentes if i not in ids_maxinet),
    }


def revisar_volumen(plan: dict) -> None:
    """Salvaguardas de volumen (FORZAR=1 las omite): respuesta incompleta de Maxinet o cambio masivo de formato."""
    if os.environ.get("FORZAR"):
        return
    if plan["en_rango"] >= MINIMO_AUSENTES and plan["ausentes"] > UMBRAL_AUSENTES * plan["en_rango"]:
        raise RuntimeError(
            f"A Maxinet le faltan {plan['ausentes']} de las {plan['en_rango']} órdenes con ingreso en el rango que ya "
            f"están en la hoja: más del 20%. Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir).")
    if plan["en_hoja"] >= MINIMO_CAMBIOS and len(plan["cambios"]) > UMBRAL_CAMBIOS * plan["en_hoja"]:
        raise RuntimeError(
            f"{len(plan['cambios'])} de las {plan['en_hoja']} filas de la hoja saldrían cambiadas: más del 30%. Casi "
            f"seguro es un cambio de formato en la hoja o en el reporte y no movimiento real; no se escribió nada. "
            f"Revisar con DRY_RUN=1 qué columnas difieren (FORZAR=1 para omitir).")


def _formato(nombre: str):
    """(tipo, patrón) de fecha u hora de una columna, como el que ya usa el archivo; None si no lleva (los costos, los días
    y los teléfonos están sin formato)."""
    return ("DATE", "yyyy-mm-dd") if nombre in FECHAS else ("TIME", "h:mm") if nombre in HORAS else None


def _pedido_formato(hoja, primera: int, ultima: int, k: int) -> dict:
    tipo, patron = _formato(ENCABEZADO[k])
    return {"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": primera - 1, "endRowIndex": ultima,
                                     "startColumnIndex": k, "endColumnIndex": k + 1},
                           "fields": "userEnteredFormat.numberFormat",
                           "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}}}}


def _formatos_altas(hoja, primera: int, ultima: int) -> list:
    """Formato de fecha y hora para las filas agregadas (idempotente; no toca las filas existentes)."""
    return [_pedido_formato(hoja, primera, ultima, k) for k, n in enumerate(ENCABEZADO) if _formato(n)]


def _formatos_celdas(hoja, celdas: list) -> list:
    """Formato para las fechas y horas que una orden que ya estaba en la hoja recibe por primera vez (por ejemplo al
    cerrarse): una celda vacía no tiene formato y el número de serie se vería como 46330."""
    return [_pedido_formato(hoja, n, n, k) for n, k in celdas]


def escribir(hoja, libro, existentes: dict, ultima: int, vacia: bool, plan: dict, desde: str, hasta: str) -> None:
    """Escribe los cambios en su lugar y las altas al final. Antes de escribir vuelve a leer la columna Id: si la hoja
    ya no es como se leyó (alguien ordenó o insertó filas), no escribe, porque se escribe por número de fila."""
    esperado = {n: i for i, (n, _) in existentes.items()}
    if _ids_columna(hoja) != esperado:
        raise RuntimeError("La columna Id de la hoja cambió mientras se preparaba la escritura (alguien ordenó o insertó "
                           "filas); no se escribió nada. Basta relanzar la corrida.")
    cambios, altas = plan["cambios"], plan["altas"]
    primera = ultima + 1
    if ultima + len(altas) > hoja.row_count:
        hoja.add_rows(ultima + len(altas) - hoja.row_count + 200)
    datos = []
    if vacia:
        datos.append({"range": f"A1:{ULT_COL}1", "values": [ENCABEZADO]})
    datos += [{"range": f"A{n}:{ULT_COL}{n}", "values": [fila]} for n, fila in cambios]
    for k in range(0, len(altas), TROZO_FILAS):
        bloque = altas[k:k + TROZO_FILAS]
        datos.append({"range": f"A{primera + k}:{ULT_COL}{primera + k + len(bloque) - 1}", "values": bloque})
    for k in range(0, len(datos), TROZO_RANGOS):
        hoja.batch_update(datos[k:k + TROZO_RANGOS], raw=True)
    pedidos = ((_formatos_altas(hoja, primera, primera + len(altas) - 1) if altas else [])
               + _formatos_celdas(hoja, plan["formatos"]))
    for k in range(0, len(pedidos), TROZO_RANGOS):
        libro.batch_update({"requests": pedidos[k:k + TROZO_RANGOS]})
    _marcar_actualizacion(hoja, desde, hasta)
    log.info("Escrito: %d filas actualizadas y %d órdenes nuevas (filas %d a %d)", len(cambios), len(altas),
             primera, primera + len(altas) - 1 if altas else primera - 1)

    esperado_final = dict(esperado)
    esperado_final.update({primera + k: f[COL_ID] for k, f in enumerate(altas)})
    final = _ids_columna(hoja)
    if final != esperado_final or len(set(final.values())) != len(final):
        raise RuntimeError("Validación fallida: la columna Id de la hoja no quedó como se esperaba después de escribir "
                           "(filas movidas o Ids repetidos). Revisar la hoja antes de la próxima corrida.")
    log.info("Validación OK: %d órdenes en la hoja, sin Ids repetidos y cada fila en su lugar", len(final))


def _marcar_actualizacion(hoja, desde: str, hasta: str) -> None:
    """Hora de la última corrida y ventana, fuera de los datos. Sólo escribe si esas cuatro celdas están vacías o ya
    son las de esta automatización (la primera lleva la marca); si hay otra cosa, no la pisa."""
    rango = f"{COL_ESTADO}1:{COL_ESTADO}4"
    filas = hoja.get(rango)
    con_algo = any(str(c).strip() for f in filas for c in f)
    es_nuestra = bool(filas and filas[0] and str(filas[0][0]).strip() == MARCA_ACTUALIZADO)
    if con_algo and not es_nuestra:
        log.warning("%s tiene contenido ajeno; no se escribió la hora de actualización", rango)
        return
    ahora = dt.datetime.now(ZONA).strftime("%Y-%m-%d %H:%M")
    hoja.batch_update([{"range": rango, "values": [[MARCA_ACTUALIZADO], [ahora], ["VENTANA (ingreso a taller)"],
                                                   [f"{desde} a {hasta}"]]}], raw=True)


def main():
    try:
        libro = conectar_libro()
        hoja = resolver_pestana(libro)
        existentes, ultima, vacia = leer_hoja(hoja)
        desde, hasta = ventana(pendiente_desde=pendiente_desde(existentes))
        log.info("Hoja: %d órdenes (última fila %d). Ventana por ingreso a taller: %s a %s", len(existentes), ultima, desde, hasta)
        session = login_maxinet()
        filas = normalizar_filas(consultar(session, "INGRESO", "1", desde, hasta))
        if not filas:
            raise RuntimeError("Maxinet no trajo ninguna orden con ingreso a taller en el rango; no se escribió nada.")
        log.info("Datos descargados de Maxinet: %d órdenes", len(filas))
        plan = planear(existentes, [a_fila_hoja(f) for f in filas], desde, hasta)
        revisar_volumen(plan)
        top = ", ".join(f"{c} {n}" for c, n in plan["por_columna"].most_common(8)) or "ninguna"
        log.info("Comparación: %d iguales, %d con cambios, %d nuevas | en la hoja y no en Maxinet: %d | "
                 "columnas con más cambios: %s", plan["iguales"], len(plan["cambios"]), len(plan["altas"]),
                 plan["fuera_de_maxinet"], top)
        if os.environ.get("DRY_RUN"):
            log.info("DRY_RUN: se actualizarían %d filas y se agregarían %d (no se escribió nada).",
                     len(plan["cambios"]), len(plan["altas"]))
            return
        if not plan["cambios"] and not plan["altas"]:
            log.info("Sin cambios que escribir: la hoja ya está al día.")
            _marcar_actualizacion(hoja, desde, hasta)
            return
        escribir(hoja, libro, existentes, ultima, vacia, plan, desde, hasta)
        log.info("Automatización completada con éxito (%d actualizadas, %d nuevas)", len(plan["cambios"]), len(plan["altas"]))
    except Exception:
        log.exception("Error en la automatización de Órdenes de Mantenimiento por ingreso a taller")
        sys.exit(1)


if __name__ == "__main__":
    main()
