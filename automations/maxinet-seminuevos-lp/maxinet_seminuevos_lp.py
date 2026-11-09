"""
Automatización: login + lectura del reporte "Días en Seminuevos" desde Maxinet vía requests (sin navegador ni Excel) y
reemplazo de las columnas A:AB de la pestaña "ENVIOS SEMINUEVOS" de la Base LP copia ("Copia de BASE LP_AUTOMATIZADO").

Endpoint confirmado a partir del JS real de Maxinet (reporte-dias-seminuevos.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/includes/flota/reporte-dias-sn.php   body: Estatus
            respuesta: {"data": [[28 celdas], ...]}
    El botón "Excel" de la página sólo exporta lo que trajo ese mismo POST, así que no se descarga ningún archivo.
    Estatus: 1 = ACTIVAS (102 filas al 2026-11-02), 0 = OFF_FLEET (con filas repetidas), 2 = TODAS (una fila por placa).
    Se usa TODAS: la hoja guarda el historial de unidades vendidas (OFF_FLEET) y las cuentas por mes, año y
    sucursal (MES y AÑO, AC:AD) se hacen sobre todo ese historial; con ACTIVAS ese historial se perdería.

Qué contiene la pestaña: las 28 columnas del reporte (A:AB) con los mismos nombres y en el mismo orden, en el orden de la
vista de Maxinet (BOOKED_ON descendente, sin fecha al final). En cada corrida se reemplazan completas: no hay `append`
ni datos viejos; una unidad que Maxinet deja de listar sale de la hoja. Las columnas AC:AD (MES y AÑO, fórmulas sobre la
fecha de ingreso a seminuevos) no se tocan: sólo se extienden hacia abajo, con la misma fórmula, si la tabla crece. Se copia
el formato de la fila 2 al resto de las filas (la hoja ya lo tiene por columna; así también lo reciben las filas nuevas).

Tipos: fechas como número de serie, días como número entero, importes como número decimal y todo lo demás como texto sin
espacios sobrantes; vacío donde Maxinet no trae dato. Se escribe con value_input_option=RAW.

Salvaguardas (FORZAR=1 las omite): la corrida se detiene SIN escribir si el reporte cambia de ancho o una columna no tiene
la forma esperada (fecha, entero, importe), si una placa se repite, si la hoja no existe o tiene otro encabezado (alguien
movió columnas), si Maxinet no trae ninguna fila, o si trae menos del 80% de las filas que ya estaban en la hoja (con 30
o más): probable respuesta incompleta. Se escribe primero (update) y se limpia lo que sobra después, nunca al revés. Al
final se comprueba que no haya placas repetidas y que MES y AÑO tengan fórmula en la última fila.

Los logs sólo llevan conteos: no se registran clientes ni placas.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID (la Base LP copia), WORKSHEET_SEMINUEVOS_LP (por defecto "ENVIOS SEMINUEVOS"),
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
log = logging.getLogger("maxinet_seminuevos_lp")

# Se copia el formato de la fila 2 al resto de las filas con copyPaste: si esa fila quedó oculta por un filtro de la hoja
# (o todas), Google rechaza la copia. El módulo común reintenta con una fila visible o con el filtro suspendido.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_comun", "lib"))
import filtros_sheets  # noqa: E402

filtros_sheets.instalar()

# Orden confirmado en el HTML real de reporte-dias-seminuevos.php; coincide con A1:AB1 de la hoja
COLUMNAS = [
    "Placa", "Seminuevos", "Dias en SN", "Ult. Renta", "Dias ult. renta", "SN Maxinet", "Venta", "Dias en Exhib.",
    "Gasto SN", "Garantía", "Recup.", "Total", "Job", "BSite", "CurrentSite", "Model", "Group", "Status Vehicle", "Make",
    "Booking Previa", "Cliente Previa", "ReturnDate Previa", "Booking Ult. Renta", "Cliente Ult. Renta",
    "PUSite Ult. Renta", "PUDate Ult. Renta", "Estatus ult. renta", "BOOKED_ON",
]
ANCHO = len(COLUMNAS)                                       # 28 (A:AB)

FECHAS = {"Seminuevos", "Ult. Renta", "SN Maxinet", "Venta", "ReturnDate Previa", "PUDate Ult. Renta", "BOOKED_ON"}
ENTEROS = {"Dias en SN", "Dias ult. renta", "Dias en Exhib."}
IMPORTES = {"Gasto SN", "Garantía", "Recup.", "Total"}

COL_PLACA = COLUMNAS.index("Placa")
COL_ESTATUS = COLUMNAS.index("Status Vehicle")
COL_BOOKED_ON = COLUMNAS.index("BOOKED_ON")

ESTATUS_TODAS = "2"                                         # filtro de la página: 1 ACTIVAS, 0 OFF_FLEET, 2 TODAS
HOJA_POR_DEFECTO = "ENVIOS SEMINUEVOS"
ULT_COL_DATOS = "AB"
COL_DERIVADAS_INI, COL_DERIVADAS_FIN = 28, 30               # AC:AD (índice base 0 [28, 30)): MES y AÑO
COL_ESTADO = 32                                             # AF: una columna libre de por medio, a la derecha de MES/AÑO
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 300                                           # la consulta de TODAS tarda ~90 s en Maxinet
REINTENTOS = 3
UMBRAL_SALVAGUARDA = 0.8
MINIMO_PARA_SALVAGUARDA = 30
PLACA_RE = re.compile(r"^[A-Za-z0-9-]{4,12}$")
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ENTERO_RE = re.compile(r"^-?\d+$")
IMPORTE_RE = re.compile(r"^-?\d+(\.\d+)?$")
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
    """El reporte con el filtro TODAS (una fila por placa: activas y fuera de flota)."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(f"{base_url}/includes/flota/reporte-dias-sn.php", data={"Estatus": ESTATUS_TODAS},
                        timeout=TIMEOUT_SEG)
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


def _forma_valida(nombre: str, texto: str) -> bool:
    """Una celda vacía siempre es válida; las demás deben tener la forma de su columna."""
    if texto == "":
        return True
    if nombre in FECHAS:
        return bool(FECHA_RE.match(texto))
    if nombre in ENTEROS:
        return bool(ENTERO_RE.match(texto))
    if nombre in IMPORTES:
        return bool(IMPORTE_RE.match(texto))
    return True


def normalizar_filas(filas: list[list]) -> list[list[str]]:
    """Las 28 celdas de cada fila ya limpias. Un ancho distinto, una columna que no cuadra (placa sin forma de placa,
    fecha, entero o importe con otra forma) o una placa repetida detienen la corrida SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de seminuevos: llegaron filas de {sorted(anchos)} columnas y se "
            f"esperan {ANCHO}. No se escribió nada en el Sheet; revisar includes/flota/reporte-dias-sn.php y ajustar COLUMNAS.")
    out, placas = [], set()
    for n, f in enumerate(filas, 1):
        fila = [_texto(v) for v in f]
        if not PLACA_RE.match(fila[COL_PLACA]):
            raise RuntimeError(
                f"Las columnas del reporte de seminuevos no cuadran (fila {n}: la columna Placa no tiene forma de "
                f"placa). No se escribió nada en el Sheet.")
        for nombre, texto in zip(COLUMNAS, fila):
            if not _forma_valida(nombre, texto):
                raise RuntimeError(
                    f"Las columnas del reporte de seminuevos no cuadran (fila {n}: la columna {nombre} no tiene la "
                    f"forma esperada). No se escribió nada en el Sheet.")
        placa = fila[COL_PLACA].upper()
        if placa in placas:
            raise RuntimeError(f"La placa {fila[COL_PLACA]} viene repetida en el reporte de seminuevos; no se escribió nada en el Sheet.")
        placas.add(placa)
        out.append(fila)
    return out


def _valor(nombre: str, texto: str):
    """Valor tipado: fechas como número de serie, días como entero, importes como decimal; lo demás, el texto tal cual.
    Lo que no tenga la forma esperada (una fecha 0000-00-00 o con año fuera de 2000-2100) se conserva como texto."""
    if texto == "":
        return ""
    if nombre in FECHAS:
        try:
            d = dt.date.fromisoformat(texto)
        except ValueError:
            return texto
        return (d - BASE_SERIAL).days if 2000 <= d.year <= 2100 else texto
    if nombre in ENTEROS:
        return int(texto) if ENTERO_RE.match(texto) else texto
    if nombre in IMPORTES:
        return float(texto) if IMPORTE_RE.match(texto) else texto
    return texto


def a_fila_hoja(fila: list[str]) -> list:
    """Las 28 columnas de la hoja, tipadas, a partir de las 28 limpias."""
    return [_valor(COLUMNAS[k], fila[k]) for k in range(ANCHO)]


def ordenar_como_maxinet(filas: list[list]) -> list[list]:
    """El orden de la vista de Maxinet y de la hoja: BOOKED_ON descendente y las filas sin fecha al final. El orden
    es estable: las filas con la misma fecha conservan el orden en que las entregó Maxinet."""
    def clave(f):
        v = f[COL_BOOKED_ON]
        return (0, -v) if isinstance(v, int) and not isinstance(v, bool) else (1, 0)
    return sorted(filas, key=clave)


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


def nombre_hoja() -> str:
    return (os.environ.get("WORKSHEET_SEMINUEVOS_LP") or "").strip().strip("\"'").strip() or HOJA_POR_DEFECTO


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


def obtener_hoja(libro, nombre: str):
    """La pestaña, o None si no existe. No se crea: tiene formato propio."""
    try:
        return _con_reintento(lambda: libro.worksheet(nombre))
    except gspread.exceptions.WorksheetNotFound:
        return None


def _leer_hoja(hoja) -> tuple[list, list, int]:
    """(encabezado, filas con placa, número de la última fila con datos) de las columnas A:AB."""
    todo = _con_reintento(lambda: hoja.get(f"A1:{ULT_COL_DATOS}", value_render_option="UNFORMATTED_VALUE")) if hoja else []
    if not todo:
        return [], [], 0
    filas = [list(f) + [""] * (ANCHO - len(f)) for f in todo[1:] if f and str(f[0]).strip() != ""]
    return list(todo[0]), filas, len(todo)


def _ultima_fila_con_formulas(hoja) -> int:
    """Número de la última fila (de la 2 en adelante) con algo en AC:AD; 0 si no hay ninguna."""
    rango = f"{_col_a1(COL_DERIVADAS_INI + 1)}1:{_col_a1(COL_DERIVADAS_FIN)}"
    celdas = _con_reintento(lambda: hoja.get(rango, value_render_option="FORMULA"))
    ultima = 0
    for i, fila in enumerate(celdas, 1):
        if i >= 2 and any(str(c).strip() for c in fila):
            ultima = i
    return ultima


def _resumen_y_salvaguarda(viejas: list, nuevas: list) -> dict:
    """Altas, bajas y cambios por placa, y la salvaguarda contra respuestas incompletas."""
    def placa(f):
        return str(f[COL_PLACA]).strip().upper()

    def canon(f):                                           # 0 y 0.0 son lo mismo; el resto se compara como texto
        return [round(float(x), 4) if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x).strip() for x in f]
    ant = {placa(f): f for f in viejas}
    act = {placa(f): f for f in nuevas}
    res = {
        "antes": len(viejas), "despues": len(nuevas),
        "altas": sum(1 for k in act if k not in ant), "bajas": sum(1 for k in ant if k not in act),
        "cambios": sum(1 for k in act if k in ant and canon(act[k]) != canon(ant[k])),
        "activas": sum(1 for f in nuevas if f[COL_ESTATUS] != "OFF_FLEET"),
    }
    if not os.environ.get("FORZAR") and len(viejas) >= MINIMO_PARA_SALVAGUARDA \
            and len(nuevas) < UMBRAL_SALVAGUARDA * len(viejas):
        raise RuntimeError(
            f"Maxinet trae {len(nuevas)} unidades y la hoja tiene {len(viejas)}: menos del 80%. Probable respuesta "
            f"incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    return res


def _pedidos_de_formato_y_formulas(hoja, ultima: int, ult_formula: int) -> list:
    """Copia el formato de la fila 2 al resto de las filas con datos y extiende MES y AÑO con la misma fórmula de la
    última fila que la tiene. Si la tabla se acortó, limpia MES y AÑO de las filas que sobran."""
    def rango(fila_ini, fila_fin, col_ini, col_fin):          # filas en base 1, [fila_ini, fila_fin]
        return {"sheetId": hoja.id, "startRowIndex": fila_ini - 1, "endRowIndex": fila_fin,
                "startColumnIndex": col_ini, "endColumnIndex": col_fin}
    pedidos = []
    if ultima >= 3:
        pedidos.append({"copyPaste": {"source": rango(2, 2, 0, COL_DERIVADAS_FIN),
                                      "destination": rango(3, ultima, 0, COL_DERIVADAS_FIN), "pasteType": "PASTE_FORMAT"}})
    if ult_formula >= 2 and ultima > ult_formula:
        pedidos.append({"copyPaste": {"source": rango(ult_formula, ult_formula, COL_DERIVADAS_INI, COL_DERIVADAS_FIN),
                                      "destination": rango(ult_formula + 1, ultima, COL_DERIVADAS_INI, COL_DERIVADAS_FIN),
                                      "pasteType": "PASTE_NORMAL"}})
    return pedidos


def refrescar(hoja, libro, nombre: str, filas: list[list]) -> dict:
    """Reemplaza A:AB de la pestaña con la tabla de Maxinet. `hoja` es None si no existe."""
    if hoja is None:
        raise RuntimeError(
            f"No existe la pestaña {nombre} en el libro; no se creó nada (tiene formato propio). "
            f"Revisar si alguien la renombró o ajustar WORKSHEET_SEMINUEVOS_LP.")
    encabezado, viejas, ultima_vieja = _leer_hoja(hoja)
    if [str(h).strip() for h in encabezado[:ANCHO]] != COLUMNAS:
        raise RuntimeError(
            f"La pestaña {nombre} tiene un encabezado distinto al esperado (alguien movió o cambió columnas); "
            f"no se escribió nada. Revisar la hoja o ajustar COLUMNAS.")
    if not filas:
        raise RuntimeError("Maxinet no trajo ninguna unidad; no se escribió nada.")
    r = _resumen_y_salvaguarda(viejas, filas)
    log.info("Hoja %s: filas %d -> %d | altas %d, bajas %d, con cambios %d | fuera de flota %d, activas %d",
             nombre, r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"], r["despues"] - r["activas"], r["activas"])
    ultima = len(filas) + 1
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reemplazarían A2:%s%d (%d unidades) (no se escribió nada).", ULT_COL_DATOS, ultima, len(filas))
        return r

    if ultima > hoja.row_count:
        _con_reintento(lambda: hoja.add_rows(ultima - hoja.row_count + 100))
    if hoja.col_count < COL_ESTADO:
        _con_reintento(lambda: hoja.add_cols(COL_ESTADO - hoja.col_count))
    ult_formula = _ultima_fila_con_formulas(hoja)
    _con_reintento(lambda: hoja.update(range_name=f"A2:{ULT_COL_DATOS}{ultima}", values=filas, value_input_option="RAW"))
    pedidos = _pedidos_de_formato_y_formulas(hoja, ultima, ult_formula)
    if pedidos:
        _con_reintento(lambda: libro.batch_update({"requests": pedidos}))
    sobrantes = []
    if ultima_vieja > ultima:                               # la hoja quedó más corta: limpiar lo que sobra
        sobrantes.append(f"A{ultima + 1}:{ULT_COL_DATOS}{ultima_vieja}")
    if ult_formula > ultima:
        sobrantes.append(f"{_col_a1(COL_DERIVADAS_INI + 1)}{ultima + 1}:{_col_a1(COL_DERIVADAS_FIN)}{ult_formula}")
    if sobrantes:
        _con_reintento(lambda: hoja.batch_clear(sobrantes))
    if ult_formula == 0:
        log.warning("MES y AÑO (AC:AD) no tienen fórmulas en la hoja: no se pueden extender.")
    ahora = dt.datetime.now(ZONA).strftime("%Y-%m-%d %H:%M")
    col = _col_a1(COL_ESTADO)
    _con_reintento(lambda: hoja.update(
        range_name=f"{col}1:{col}2", value_input_option="RAW", values=[["ACTUALIZADO (hora CDMX)"], [ahora]]))
    log.info("Hoja reemplazada: %d unidades en A2:%s%d", len(filas), ULT_COL_DATOS, ultima)
    return r


def validar(hoja):
    """Ninguna placa debe repetirse en la hoja y MES y AÑO deben tener fórmula en la última fila con datos."""
    placas = _con_reintento(lambda: hoja.col_values(1))
    vistos, dups = set(), set()
    for v in placas[1:]:
        k = str(v).strip().upper()
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Placa repetida en la hoja ({len(dups)}): {sorted(dups)[:10]}")
    ultima = len(placas)
    while ultima > 1 and not str(placas[ultima - 1]).strip():
        ultima -= 1
    rango = f"{_col_a1(COL_DERIVADAS_INI + 1)}{ultima}:{_col_a1(COL_DERIVADAS_FIN)}{ultima}"
    derivadas = _con_reintento(lambda: hoja.get(rango, value_render_option="FORMULA"))
    if not derivadas or len(derivadas[0]) < COL_DERIVADAS_FIN - COL_DERIVADAS_INI or not all(str(c).strip() for c in derivadas[0]):
        raise RuntimeError(f"MES y AÑO (AC:AD) no tienen fórmula en la última fila con datos ({ultima}): esas unidades quedarían sin mes ni año.")
    log.info("Validación OK: sin placas repetidas y con MES y AÑO hasta la fila %d", ultima)


def main():
    try:
        session = login_maxinet()
        limpias = normalizar_filas(consultar(session))
        log.info("Datos descargados de Maxinet: %d unidades", len(limpias))
        filas = ordenar_como_maxinet([a_fila_hoja(f) for f in limpias])
        libro = conectar_libro()
        nombre = nombre_hoja()
        hoja = obtener_hoja(libro, nombre)
        r = refrescar(hoja, libro, nombre, filas)
        if not os.environ.get("DRY_RUN"):
            validar(_con_reintento(lambda: libro.worksheet(nombre)))
        log.info("Automatización completada con éxito (%d unidades)", r["despues"])
    except Exception:
        log.exception("Error en la automatización de Envíos a Seminuevos")
        sys.exit(1)


if __name__ == "__main__":
    main()
