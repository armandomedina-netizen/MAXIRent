"""
Automatización: login + lectura de la tabla "Expedientes LP" (prospección, validaciones por área) desde Maxinet vía
requests (sin navegador) y reescritura de la pestaña "EXPEDIENTES LP" de la Base LP copia ("Copia de BASE LP_AUTOMATIZADO").

Endpoint confirmado a partir del JS real de Maxinet (lp-prospeccion-expedientes.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/includes/prospeccion/expedientesData.php
            body: Criterio, Estatus, Desde, Hasta, valueCriterio (los mismos campos del filtro de la página)
            respuesta: {"data": [[32 celdas HTML], ...]} o {"data": ""} si no hay filas.
    La página, al abrirse sin tocar el filtro, manda Criterio=ESTATUS, Estatus=1 ("Pendientes") y el resto vacío:
    ésa es la tabla que se copia, sin filtros. Con parámetros vacíos el servidor responde {"data": ""}. Los
    expedientes "Cerrados" (Estatus=0) sólo salen con un rango de fechas y no están en esa vista.

Qué contiene la pestaña: la tabla tal como viene en Maxinet. En cada corrida se reescribe completa (no hay
`append`: no hay duplicados ni estatus viejos); un expediente que Maxinet deja de mostrar como pendiente sale de la
hoja. Se conserva el orden en que Maxinet entrega las filas.

Columnas: las 32 celdas de la tabla menos la primera (el botón "Ver Expediente"): quedan las 31 columnas con los
nombres del reporte, incluidos los datos de contacto. Folio va como número y las fechas con hora como número de
serie; todo lo demás se copia como texto, sin interpretarlo, con value_input_option=RAW. "Fecha Facturación" NO es
una fecha en Maxinet (trae un número de día) y se deja tal cual.

Salvaguardas (FORZAR=1 las omite): la corrida se detiene SIN escribir si el reporte cambia de ancho o sus
columnas no cuadran (Folio, Fecha Registro), si Folio se repite, si la hoja tiene otro encabezado (alguien movió
columnas), si Maxinet no trae ninguna fila, o si trae menos del 80% de las filas que ya estaban en la hoja (con 30 o
más): probable respuesta incompleta. Se escribe primero (update) y se limpia lo que sobra después, nunca al revés.

Los logs sólo llevan conteos: la tabla trae nombres, correos y teléfonos de prospectos y no se registran.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID (la Base LP copia), WORKSHEET_EXPEDIENTES_LP (por defecto "EXPEDIENTES LP"),
    DRY_RUN, FORZAR (opcionales)
"""

import os
import re
import sys
import json
import html
import time
import logging
import datetime as dt
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_expedientes_lp")

# Orden confirmado en el HTML real de lp-prospeccion-expedientes.php (la primera columna es el botón sin título)
COLUMNAS_REPORTE = [
    "",
    "Folio", "Ejecutivo", "Fecha Registro", "Nombre", "Razón Social",
    "Validación CXC", "Fecha Validación CXC", "Responsable Val. CXC",
    "Validación Mtto", "Fecha Validación Mtto",
    "Validación Postventa", "Fecha Validación Postventa",
    "Validación Comercial", "Fecha Validación Comercial",
    "Validación Gerencia", "Fecha Validación Gcia",
    "Giro", "Uso de unidades", "Donde se enteró de Maxirent?",
    "Presentación con cliente", "Fecha de la presentación",
    "No. Cliente Prohire", "Fecha Facturación", "Plazo", "Plazo Renta", "Plazo Crédito",
    "Nombre(Compras)", "Email(Compras)", "Teléfono(Compras)", "Email(Contacto)", "Teléfono(Contacto)",
]
ANCHO_REPORTE = len(COLUMNAS_REPORTE)                      # 32
ENCABEZADO = COLUMNAS_REPORTE[1:]                          # las 31 columnas de la hoja

FECHA = {"Fecha Registro"}
FECHA_HORA = {"Fecha Validación CXC", "Fecha Validación Mtto", "Fecha Validación Postventa",
              "Fecha Validación Comercial", "Fecha Validación Gcia", "Fecha de la presentación"}
NUMEROS = {"Folio"}

COL_FOLIO = ENCABEZADO.index("Folio")
COL_FECHA_REGISTRO = ENCABEZADO.index("Fecha Registro")

HOJA_POR_DEFECTO = "EXPEDIENTES LP"
COL_ESTADO = len(ENCABEZADO) + 2                           # una columna libre de por medio, a la derecha de los datos
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
UMBRAL_SALVAGUARDA = 0.8
MINIMO_PARA_SALVAGUARDA = 30
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FECHA_HORA_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$")
BASE_SERIAL = dt.date(1899, 12, 30)


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido (%d caracteres).", len(texto))
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


def consultar(session: requests.Session) -> list[list]:
    """La tabla con los valores por defecto del filtro de la página (Pendientes, sin fechas)."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(
        f"{base_url}/includes/prospeccion/expedientesData.php",
        data={"Criterio": "ESTATUS", "Estatus": "1", "Desde": "", "Hasta": "", "valueCriterio": ""},
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
    """Las 32 celdas de cada fila ya limpias. Un ancho distinto, columnas que no cuadran (Folio sin forma de
    número, Fecha Registro sin forma de fecha) o un Folio repetido detienen la corrida SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO_REPORTE}:
        raise RuntimeError(
            f"Maxinet cambió el ancho de la tabla de expedientes: llegaron filas de {sorted(anchos)} columnas y se "
            f"esperan {ANCHO_REPORTE}. No se escribió nada en el Sheet; revisar includes/prospeccion/expedientesData.php "
            f"y ajustar COLUMNAS_REPORTE.")
    out, folios = [], set()
    for f in filas:
        fila = [_texto(v) for v in f]
        folio, registro = fila[1 + COL_FOLIO], fila[1 + COL_FECHA_REGISTRO]
        if not folio.isdigit() or not FECHA_RE.match(registro):
            raise RuntimeError(
                f"Las columnas de la tabla de expedientes no cuadran (Folio={folio[:20]!r}, Fecha Registro="
                f"{registro[:20]!r}). No se escribió nada en el Sheet.")
        if folio in folios:
            raise RuntimeError(f"El Folio {folio} viene repetido en la tabla de expedientes; no se escribió nada en el Sheet.")
        folios.add(folio)
        out.append(fila)
    return out


def _valor(nombre: str, texto: str):
    """Valor tipado: Folio como número; fechas y fechas con hora como número de serie. Todo lo demás, el texto tal
    cual. Lo que no tenga la forma esperada (por ejemplo una fecha 0000-00-00 o con año fuera de 2000-2100) se
    conserva como texto."""
    if texto == "":
        return ""
    if nombre in NUMEROS:
        return int(texto) if texto.isdigit() else texto
    if nombre in FECHA:
        if FECHA_RE.match(texto):
            try:
                d = dt.date.fromisoformat(texto)
            except ValueError:
                return texto
            return (d - BASE_SERIAL).days if 2000 <= d.year <= 2100 else texto
        return texto
    if nombre in FECHA_HORA:
        m = FECHA_HORA_RE.match(texto)
        if m:
            try:
                d = dt.date.fromisoformat(m[1])
            except ValueError:
                return texto
            h, mi, s = int(m[2]), int(m[3]), int(m[4] or 0)
            if 2000 <= d.year <= 2100 and h < 24 and mi < 60 and s < 60:
                return (d - BASE_SERIAL).days + (h * 3600 + mi * 60 + s) / 86400
        return texto
    return texto


def a_fila_hoja(fila: list[str]) -> list:
    """Las 31 columnas de la hoja, tipadas, a partir de las 32 limpias."""
    return [_valor(ENCABEZADO[k], fila[k + 1]) for k in range(len(ENCABEZADO))]


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


ULT_COL = _col_a1(len(ENCABEZADO))                          # "AE"


def nombre_hoja() -> str:
    return (os.environ.get("WORKSHEET_EXPEDIENTES_LP") or "").strip().strip("\"'").strip() or HOJA_POR_DEFECTO


def conectar_libro():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID"])


def _con_reintento(fn, intentos: int = 5):
    """Reintenta ante la cuota de Google Sheets (429) o un error temporal del servidor; el sync del tablero
    escribe mucho en la misma Base alrededor de las 8:00."""
    for n in range(1, intentos + 1):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            codigo = getattr(getattr(e, "response", None), "status_code", None)
            if codigo not in (429, 500, 502, 503) or n == intentos:
                raise
            espera = 20 * n
            log.warning("Google Sheets respondió %s; reintento %d de %d en %d s", codigo, n, intentos - 1, espera)
            time.sleep(espera)


def obtener_hoja(libro, nombre: str, filas_necesarias: int, crear: bool):
    """La pestaña, o None si no existe y no se debe crear (DRY_RUN). Se crea con espacio para las filas."""
    try:
        return _con_reintento(lambda: libro.worksheet(nombre))
    except gspread.exceptions.WorksheetNotFound:
        if not crear:
            return None
        hoja = _con_reintento(lambda: libro.add_worksheet(
            title=nombre, rows=max(1000, filas_necesarias + 300), cols=COL_ESTADO + 1))
        log.info("Creada la pestaña %s", nombre)
        return hoja


def _leer_hoja(hoja) -> tuple[list, list]:
    """(encabezado, filas con datos) de la pestaña; ([], []) si está vacía o no existe."""
    todo = _con_reintento(lambda: hoja.get(f"A1:{ULT_COL}", value_render_option="UNFORMATTED_VALUE")) if hoja else []
    if not todo:
        return [], []
    filas = [list(f) + [""] * (len(ENCABEZADO) - len(f)) for f in todo[1:] if f and str(f[0]).strip() != ""]
    return list(todo[0]), filas


def _resumen_y_salvaguarda(viejas: list, nuevas: list) -> dict:
    """Altas, bajas y cambios por Folio, y la salvaguarda contra respuestas incompletas."""
    def folio(f):
        v = f[COL_FOLIO]
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v).strip()
    ant = {folio(f): f for f in viejas}
    act = {folio(f): f for f in nuevas}
    res = {
        "antes": len(viejas), "despues": len(nuevas),
        "altas": sum(1 for k in act if k not in ant), "bajas": sum(1 for k in ant if k not in act),
        "cambios": sum(1 for k in act if k in ant and [str(x) for x in act[k]] != [str(x) for x in ant[k]]),
    }
    if not os.environ.get("FORZAR") and len(viejas) >= MINIMO_PARA_SALVAGUARDA \
            and len(nuevas) < UMBRAL_SALVAGUARDA * len(viejas):
        raise RuntimeError(
            f"Maxinet trae {len(nuevas)} expedientes y la hoja tiene {len(viejas)}: menos del 80%. Probable respuesta "
            f"incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    return res


def _formatos(hoja, filas_hoja: int) -> list:
    """Encabezado en negritas, panel inmovilizado y formatos de fecha y fecha con hora (idempotente)."""
    def formato(nombres, patron, tipo):
        return [{"repeatCell": {
            "range": {"sheetId": hoja.id, "startRowIndex": 1, "endRowIndex": filas_hoja,
                      "startColumnIndex": ENCABEZADO.index(n), "endColumnIndex": ENCABEZADO.index(n) + 1},
            "fields": "userEnteredFormat.numberFormat",
            "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}}}} for n in nombres]

    pedidos = [
        {"updateSheetProperties": {"properties": {"sheetId": hoja.id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1,
                                  "startColumnIndex": 0, "endColumnIndex": len(ENCABEZADO)},
                        "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                       "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}}}},
    ]
    pedidos += formato(sorted(FECHA), "yyyy-mm-dd", "DATE")
    pedidos += formato(sorted(FECHA_HORA), "yyyy-mm-dd hh:mm:ss", "DATE_TIME")
    return pedidos


def refrescar(hoja, libro, nombre: str, filas: list[list]) -> dict:
    """Reescribe la pestaña con la tabla de Maxinet. `hoja` es None si todavía no existe."""
    encabezado, viejas = _leer_hoja(hoja)
    if encabezado and [str(h).strip() for h in encabezado[:len(ENCABEZADO)]] != ENCABEZADO:
        raise RuntimeError(
            f"La pestaña {nombre} tiene un encabezado distinto al esperado (alguien movió o cambió columnas); "
            f"no se escribió nada. Revisar la hoja o ajustar COLUMNAS_REPORTE.")
    if not filas:
        raise RuntimeError("Maxinet no trajo ningún expediente; no se escribió nada.")
    r = _resumen_y_salvaguarda(viejas, filas)
    log.info("Hoja %s: filas %d -> %d | altas %d, bajas %d, con cambios %d",
             nombre, r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"])
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían A1:%s%d (%d expedientes) (no se escribió nada).", ULT_COL, len(filas) + 1, len(filas))
        return r

    hoja = hoja or obtener_hoja(libro, nombre, len(filas) + 1, crear=True)
    ultima_vieja = r["antes"] + 1
    ultima = len(filas) + 1
    if ultima > hoja.row_count:
        _con_reintento(lambda: hoja.add_rows(ultima - hoja.row_count + 200))
    _con_reintento(lambda: hoja.update(
        range_name=f"A1:{ULT_COL}{ultima}", values=[ENCABEZADO] + filas, value_input_option="RAW"))
    if ultima_vieja > ultima:                               # la hoja quedó más corta: limpiar lo que sobra
        _con_reintento(lambda: hoja.batch_clear([f"A{ultima + 1}:{ULT_COL}{ultima_vieja}"]))
    ahora = dt.datetime.now(ZONA).strftime("%Y-%m-%d %H:%M")
    col = _col_a1(COL_ESTADO)
    _con_reintento(lambda: hoja.update(
        range_name=f"{col}1:{col}2", value_input_option="RAW", values=[["ACTUALIZADO (hora CDMX)"], [ahora]]))
    _con_reintento(lambda: libro.batch_update({"requests": _formatos(hoja, hoja.row_count)}))
    log.info("Hoja reescrita: %d expedientes en A1:%s%d", len(filas), ULT_COL, ultima)
    return r


def validar_sin_repetidos(hoja):
    """Ningún Folio debe repetirse en la hoja; si ocurre, la corrida falla."""
    vistos, dups = set(), set()
    for v in _con_reintento(lambda: hoja.col_values(1))[1:]:
        k = str(v).strip()
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Folio repetido en la hoja ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin Folios repetidos en la hoja")


def main():
    try:
        session = login_maxinet()
        limpias = normalizar_filas(consultar(session))
        log.info("Datos descargados de Maxinet: %d expedientes", len(limpias))
        filas = [a_fila_hoja(f) for f in limpias]
        libro = conectar_libro()
        nombre = nombre_hoja()
        hoja = obtener_hoja(libro, nombre, len(filas) + 1, crear=False)
        r = refrescar(hoja, libro, nombre, filas)
        if not os.environ.get("DRY_RUN"):
            validar_sin_repetidos(_con_reintento(lambda: libro.worksheet(nombre)))
        log.info("Automatización completada con éxito (%d expedientes)", r["despues"])
    except Exception:
        log.exception("Error en la automatización de Expedientes LP")
        sys.exit(1)


if __name__ == "__main__":
    main()
