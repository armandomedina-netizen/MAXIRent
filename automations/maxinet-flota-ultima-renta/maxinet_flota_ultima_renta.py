"""
Automatización: login + lectura del reporte "Flota Última Renta Cliente" desde Maxinet vía requests (sin navegador) y
reescritura de la pestaña "Reporte Flota Ultima Renta" del libro del Tablero LP.

Endpoint confirmado a partir del JS real de Maxinet (reporte-flota-ultima-renta-cliente.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  GET  {MAXINET_BASE_URL}/includes/flota/reporte-flota-ultima-renta.php   (sin parámetros)
            respuesta: {"data": [[20 celdas], ...]}, una fila por placa de la flota (tarda unos 30 segundos).
    A diferencia de otros reportes, las filas NO traen una primera celda con un botón: las 20 celdas son las 20
    columnas de la tabla, en el mismo orden que la página.

Qué contiene la pestaña: el estado de la flota tal como viene en Maxinet, una fila por placa. En cada corrida se
reescribe completa (no hay `append`: no hay duplicados ni estados viejos); una placa que Maxinet deja de mostrar sale
de la hoja. Se conserva el orden en que Maxinet entrega las filas.

Tipos: las tres fechas (PUDate Ult. Renta Cliente, ReturnDate Ult. Renta Cliente y ReturnDate Ult. Renta) van como
número de serie con formato yyyy-mm-dd; "Dias desde Ult. Renta Cliente", "Dias no disponibles" y "Odómetro" como
número entero (el Odómetro con separador de miles); todo lo demás se copia como texto, sin interpretarlo, con
value_input_option=RAW (las placas pueden empezar con "@" y los Booking con "#"). Los textos van sin espacios de
relleno (Maxinet rellena "Estatus ult. renta Cliente" a ancho fijo).

El encabezado de la fila 1 es de quien armó la hoja: si ya está con los 20 nombres de la tabla no se toca (ni su
formato); si está vacío se escribe; si es otro, la corrida se detiene SIN escribir.

Salvaguardas (FORZAR=1 omite sólo la del 80%): la corrida se detiene SIN escribir si el reporte cambia de ancho, si
sus columnas no cuadran (fechas, días u odómetro con otra forma en la gran mayoría de las filas: columnas
recorridas), si una Placa viene vacía o repetida, si la hoja tiene otro encabezado, si Maxinet no trae ninguna
fila, o si trae menos del 80% de las placas que ya estaban en la hoja (con 30 o más). Se escribe primero (update) y
se limpia lo que sobra después, nunca al revés.

Los logs sólo llevan conteos: la tabla trae clientes y placas y no se registran.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_SECUNDARIO (el libro del Tablero LP), WORKSHEET_FLOTA_ULTIMA_RENTA (por defecto
    "Reporte Flota Ultima Renta"), DRY_RUN, FORZAR (opcionales)
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
log = logging.getLogger("maxinet_flota_ultima_renta")

# Orden confirmado en el HTML real de reporte-flota-ultima-renta-cliente.php (y en la fila 1 de la pestaña)
ENCABEZADO = [
    "Placa", "BSite", "CurrentSite", "PUDate Ult. Renta Cliente", "ReturnDate Ult. Renta Cliente",
    "Dias desde Ult. Renta Cliente", "Dias no disponibles", "Semáforo dias no disp.", "Odómetro",
    "Semáforo Odómetro", "Group", "Status Vehicle", "Make", "Model", "Booking Ult. Renta Cliente",
    "Cliente Ult. Renta", "PUSite Ult. Renta Cliente", "Estatus ult. renta Cliente", "ReturnDate Ult. Renta",
    "Name Ult. Renta",
]
ANCHO_REPORTE = len(ENCABEZADO)                            # 20

FECHA = {"PUDate Ult. Renta Cliente", "ReturnDate Ult. Renta Cliente", "ReturnDate Ult. Renta"}
ENTEROS = {"Dias desde Ult. Renta Cliente", "Dias no disponibles", "Odómetro"}
FORMATO_ENTERO = {"Dias desde Ult. Renta Cliente": "0", "Dias no disponibles": "0", "Odómetro": "#,##0"}

COL_PLACA = ENCABEZADO.index("Placa")

HOJA_POR_DEFECTO = "Reporte Flota Ultima Renta"
COL_ESTADO = len(ENCABEZADO) + 2                           # una columna libre de por medio, a la derecha de los datos
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
UMBRAL_SALVAGUARDA = 0.8
MINIMO_PARA_SALVAGUARDA = 30
UMBRAL_COLUMNAS = 0.9                                      # forma esperada en al menos el 90% de lo que no está vacío
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ENTERO_RE = re.compile(r"^\d+$")
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


def consultar(session: requests.Session) -> list:
    """El reporte tal como lo carga la página: una consulta sin parámetros."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.get(f"{base_url}/includes/flota/reporte-flota-ultima-renta.php", timeout=TIMEOUT_SEG)
    data = _parse_json_bom(resp).get("data")
    if data in ("", None):
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"Maxinet devolvió un 'data' inesperado ({type(data).__name__}); no se escribió nada.")
    return data


# -------------------------------------------------------- limpieza y tipos
def _texto(v) -> str:
    """Texto sin etiquetas HTML ni espacios sobrantes; el 'None' que imprime el reporte es vacío. Un 0 numérico es "0"."""
    if v is None:
        return ""
    s = html.unescape(re.sub(r"<[^>]*>", "", str(v))).replace("\xa0", " ").strip()
    return "" if s in ("None", "null", "NULL") else s


def _forma_esperada(nombre: str, texto: str) -> bool:
    if nombre in FECHA:
        return bool(FECHA_RE.match(texto))
    if nombre in ENTEROS:
        return bool(ENTERO_RE.match(texto))
    return True


def normalizar_filas(filas: list) -> list:
    """Las 20 celdas de cada fila ya limpias. Un ancho distinto, columnas que no cuadran (fechas, días u odómetro
    sin su forma en casi todas las filas) o una Placa vacía o repetida detienen la corrida SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO_REPORTE}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de flota última renta: llegaron filas de {sorted(anchos)} columnas y se "
            f"esperan {ANCHO_REPORTE}. No se escribió nada en el Sheet; revisar includes/flota/reporte-flota-ultima-renta.php "
            f"y ajustar ENCABEZADO.")
    out, placas = [], set()
    for f in filas:
        fila = [_texto(v) for v in f]
        placa = fila[COL_PLACA]
        if not placa:
            raise RuntimeError("Una fila del reporte de flota última renta viene sin Placa; no se escribió nada en el Sheet.")
        if placa in placas:
            raise RuntimeError("Una Placa viene repetida en el reporte de flota última renta; no se escribió nada en el Sheet.")
        placas.add(placa)
        out.append(fila)
    for k, nombre in enumerate(ENCABEZADO):
        if nombre not in FECHA and nombre not in ENTEROS:
            continue
        llenas = [fila[k] for fila in out if fila[k] != ""]
        buenas = sum(1 for t in llenas if _forma_esperada(nombre, t))
        if llenas and buenas < UMBRAL_COLUMNAS * len(llenas):
            raise RuntimeError(
                f"Las columnas del reporte de flota última renta no cuadran ('{nombre}' sin la forma esperada en "
                f"{len(llenas) - buenas} de {len(llenas)} filas con dato). No se escribió nada en el Sheet.")
    return out


def _valor(nombre: str, texto: str):
    """Valor tipado: fechas como número de serie y días y odómetro como entero. Todo lo demás, el texto tal cual. Lo
    que no tenga la forma esperada (por ejemplo una fecha 0000-00-00 o con año fuera de 2000-2100) se conserva como
    texto."""
    if texto == "":
        return ""
    if nombre in ENTEROS:
        return int(texto) if ENTERO_RE.match(texto) else texto
    if nombre in FECHA:
        if FECHA_RE.match(texto):
            try:
                d = dt.date.fromisoformat(texto)
            except ValueError:
                return texto
            return (d - BASE_SERIAL).days if 2000 <= d.year <= 2100 else texto
        return texto
    return texto


def a_fila_hoja(fila: list) -> list:
    """Las 20 columnas de la hoja, tipadas, a partir de las 20 limpias."""
    return [_valor(ENCABEZADO[k], fila[k]) for k in range(len(ENCABEZADO))]


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


ULT_COL = _col_a1(len(ENCABEZADO))                          # "T"


def nombre_hoja() -> str:
    return (os.environ.get("WORKSHEET_FLOTA_ULTIMA_RENTA") or "").strip().strip("\"'").strip() or HOJA_POR_DEFECTO


def conectar_libro():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_SECUNDARIO"])


def _con_reintento(fn, intentos: int = 5):
    """Reintenta ante la cuota de Google Sheets (429) o un error temporal del servidor; el sync del tablero
    escribe mucho en este mismo libro alrededor de las 8:00."""
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


def _leer_hoja(hoja) -> tuple:
    """(encabezado, filas con datos) de la pestaña; ([], []) si está vacía o no existe."""
    todo = _con_reintento(lambda: hoja.get(f"A1:{ULT_COL}", value_render_option="UNFORMATTED_VALUE")) if hoja else []
    if not todo:
        return [], []
    filas = [list(f) + [""] * (len(ENCABEZADO) - len(f)) for f in todo[1:] if f and str(f[COL_PLACA]).strip() != ""]
    return list(todo[0]), filas


def _resumen_y_salvaguarda(viejas: list, nuevas: list) -> dict:
    """Altas, bajas y cambios por Placa, y la salvaguarda contra respuestas incompletas."""
    ant = {str(f[COL_PLACA]).strip(): f for f in viejas}
    act = {str(f[COL_PLACA]).strip(): f for f in nuevas}
    res = {
        "antes": len(viejas), "despues": len(nuevas),
        "altas": sum(1 for k in act if k not in ant), "bajas": sum(1 for k in ant if k not in act),
        "cambios": sum(1 for k in act if k in ant and [str(x) for x in act[k]] != [str(x) for x in ant[k]]),
    }
    if not os.environ.get("FORZAR") and len(viejas) >= MINIMO_PARA_SALVAGUARDA \
            and len(nuevas) < UMBRAL_SALVAGUARDA * len(viejas):
        raise RuntimeError(
            f"Maxinet trae {len(nuevas)} placas y la hoja tiene {len(viejas)}: menos del 80%. Probable respuesta "
            f"incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    return res


def _formatos(hoja, filas_hoja: int) -> list:
    """Formato de fecha y de entero en las columnas de datos, sólo de la fila 2 en adelante (idempotente). No toca el
    encabezado ni la configuración de la hoja: son de quien la armó."""
    def formato(nombre, patron, tipo):
        k = ENCABEZADO.index(nombre)
        return {"repeatCell": {
            "range": {"sheetId": hoja.id, "startRowIndex": 1, "endRowIndex": filas_hoja,
                      "startColumnIndex": k, "endColumnIndex": k + 1},
            "fields": "userEnteredFormat.numberFormat",
            "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}}}}

    pedidos = [formato(n, "yyyy-mm-dd", "DATE") for n in sorted(FECHA)]
    pedidos += [formato(n, patron, "NUMBER") for n, patron in sorted(FORMATO_ENTERO.items())]
    return pedidos


def refrescar(hoja, libro, nombre: str, filas: list) -> dict:
    """Reescribe la pestaña con el reporte de Maxinet. `hoja` es None si todavía no existe."""
    encabezado, viejas = _leer_hoja(hoja)
    if encabezado and [str(h).strip() for h in encabezado[:len(ENCABEZADO)]] != ENCABEZADO:
        raise RuntimeError(
            f"La pestaña {nombre} tiene un encabezado distinto al esperado (alguien movió o cambió columnas); "
            f"no se escribió nada. Revisar la hoja o ajustar ENCABEZADO.")
    if not filas:
        raise RuntimeError("Maxinet no trajo ninguna placa; no se escribió nada.")
    r = _resumen_y_salvaguarda(viejas, filas)
    log.info("Hoja %s: filas %d -> %d | altas %d, bajas %d, con cambios %d",
             nombre, r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"])
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían A2:%s%d (%d placas) (no se escribió nada).", ULT_COL, len(filas) + 1, len(filas))
        return r

    hoja = hoja or obtener_hoja(libro, nombre, len(filas) + 1, crear=True)
    ultima_vieja = r["antes"] + 1
    ultima = len(filas) + 1
    if ultima > hoja.row_count:
        _con_reintento(lambda: hoja.add_rows(ultima - hoja.row_count + 200))
    if hoja.col_count < COL_ESTADO:
        _con_reintento(lambda: hoja.add_cols(COL_ESTADO - hoja.col_count))
    if not encabezado:                                       # hoja nueva o sin encabezado: se escribe; si ya lo trae, no se toca
        _con_reintento(lambda: hoja.update(range_name=f"A1:{ULT_COL}1", values=[ENCABEZADO], value_input_option="RAW"))
    _con_reintento(lambda: hoja.update(range_name=f"A2:{ULT_COL}{ultima}", values=filas, value_input_option="RAW"))
    if ultima_vieja > ultima:                               # la hoja quedó más corta: limpiar lo que sobra
        _con_reintento(lambda: hoja.batch_clear([f"A{ultima + 1}:{ULT_COL}{ultima_vieja}"]))
    ahora = dt.datetime.now(ZONA).strftime("%Y-%m-%d %H:%M")
    col = _col_a1(COL_ESTADO)
    _con_reintento(lambda: hoja.update(
        range_name=f"{col}1:{col}2", value_input_option="RAW", values=[["ACTUALIZADO (hora CDMX)"], [ahora]]))
    _con_reintento(lambda: libro.batch_update({"requests": _formatos(hoja, hoja.row_count)}))
    log.info("Hoja reescrita: %d placas en A2:%s%d", len(filas), ULT_COL, ultima)
    return r


def validar_sin_repetidos(hoja):
    """Ninguna Placa debe repetirse en la hoja; si ocurre, la corrida falla."""
    vistos, dups = set(), set()
    for v in _con_reintento(lambda: hoja.col_values(COL_PLACA + 1))[1:]:
        k = str(v).strip()
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Placa repetida en la hoja ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin Placas repetidas en la hoja")


def main():
    try:
        session = login_maxinet()
        limpias = normalizar_filas(consultar(session))
        log.info("Datos descargados de Maxinet: %d placas", len(limpias))
        filas = [a_fila_hoja(f) for f in limpias]
        libro = conectar_libro()
        nombre = nombre_hoja()
        hoja = obtener_hoja(libro, nombre, len(filas) + 1, crear=False)
        r = refrescar(hoja, libro, nombre, filas)
        if not os.environ.get("DRY_RUN"):
            validar_sin_repetidos(_con_reintento(lambda: libro.worksheet(nombre)))
        log.info("Automatización completada con éxito (%d placas)", r["despues"])
    except Exception:
        log.exception("Error en la automatización de Flota Última Renta")
        sys.exit(1)


if __name__ == "__main__":
    main()
