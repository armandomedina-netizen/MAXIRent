"""
Automatización: login + lectura del "Proyector de Mantenimientos" (LP) desde Maxinet vía requests (sin navegador) y
reescritura de la pestaña "Proyección de Mantenimientos(DATA)" de la Base LP copia ("BASE LP_AUTOMATIZADO").

Endpoint confirmado a partir del JS real de Maxinet (lp-mtto-proyector-mtto.php -> DataTable ajax `tableProyector`):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  GET  {MAXINET_BASE_URL}/includes/mttoLP/lp-mtto-proyeccionmtto-data.php   (sin parámetros)
            respuesta: {"dataReservas": [[16 celdas], ...]}, una fila por placa con regla de mantenimiento (unas 800).
    Las primeras 15 celdas son las 15 columnas de la tabla, en el mismo orden que la página. La celda 16 NO es una
    columna: es un código (0, 2 o 3) que la página sólo usa para pintar de color "Fecha Prox. Mtto" (2 = ya vencida,
    3 = sin mantenimiento previo, 0 = vigente) y se deduce de las propias fechas; no se copia a la hoja.

Qué contiene la pestaña: la tabla del proyector tal como viene en Maxinet, una fila por placa. En cada corrida se
reescribe completa (no hay `append`): un mantenimiento que desaparece del proyector sale de la hoja y los semáforos
de vencimiento ("VENCIDO", "MAYOR A 1 MES", "KMS EN 0") y las fechas se refrescan. Se conserva el orden en que
Maxinet entrega las filas (por Fecha Renta).

Tipos: "FECHA RENTA", "Fecha Ult.Mtto" y "Fecha Prox. Mtto" van como número de serie con formato yyyy-mm-dd;
"Fecha Sig. Mtto" mezcla en Maxinet fechas con los textos de semáforo, así que las fechas van como fecha y los textos
como texto; los kilómetros y el % de vencimiento como número (con los mismos decimales y separador de miles que la
página); todo lo demás se copia como texto, sin interpretarlo, con value_input_option=RAW. "ESTATUS" llega como un
enlace HTML a la orden de mantenimiento (<a href="...">CITA APROBADA</a>): se guarda el texto visible. Los textos van
sin espacios de relleno (Maxinet rellena el nombre del cliente y algunas placas).

El encabezado de la fila 1 es de quien armó la hoja: si ya está con los 15 nombres de la tabla no se toca (ni su
formato); si está vacío se escribe; si es otro, la corrida se detiene SIN escribir. La pestaña debe existir: no se
crea (otras pestañas del libro dependen de ella).

Salvaguardas (FORZAR=1 omite sólo la del 80%): la corrida se detiene SIN escribir si el reporte cambia de ancho, si
sus columnas no cuadran (fechas, kilómetros o el código de color con otra forma en la gran mayoría de las filas:
columnas recorridas), si una Placa viene vacía o repetida, si la pestaña no existe o tiene otro encabezado, si Maxinet
no trae ninguna fila, o si trae menos del 80% de las placas que ya estaban en la hoja (con 30 o más). Se escribe
primero (update) y se limpia lo que sobra después, nunca al revés.

Los logs sólo llevan conteos: la tabla trae clientes y placas y no se registran.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID (la Base LP copia), WORKSHEET_MTTO_PROYECTOR (por defecto "Proyección de Mantenimientos(DATA)"),
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
log = logging.getLogger("maxinet_mtto_proyector")

# Orden confirmado en el HTML real de lp-mtto-proyector-mtto.php (y en la fila 1 de la pestaña)
ENCABEZADO = [
    "FECHA RENTA", "GRUPO", "PLACA", "ESTATUS", "TIPO UNIDAD", "CLIENTE", "ULTIMA UBICACION",
    "Odometro ult.Mtto", "Km. de Regla", "Km. Max p/Mtto", "Km Recorridos desde Ult. Mtto", "% Vencimiento",
    "Fecha Sig. Mtto", "Fecha Ult.Mtto", "Fecha Prox. Mtto",
]
ANCHO_TABLA = len(ENCABEZADO)                              # 15 columnas de la tabla
ANCHO_REPORTE = ANCHO_TABLA + 1                            # + el código de color que la página no muestra
COL_CODIGO_COLOR = ANCHO_TABLA                             # índice de esa celda 16

FECHA = {"FECHA RENTA", "Fecha Ult.Mtto", "Fecha Prox. Mtto"}
FECHA_O_TEXTO = {"Fecha Sig. Mtto"}                        # fecha cuando falta menos de un mes; si no, el texto del semáforo
NUMEROS = {
    "Odometro ult.Mtto": "#,##0.00", "Km. de Regla": "#,##0", "Km. Max p/Mtto": "#,##0.00",
    "Km Recorridos desde Ult. Mtto": "#,##0.00", "% Vencimiento": "0.00",
}                                                          # nombre -> formato de presentación, como lo muestra la página

COL_PLACA = ENCABEZADO.index("PLACA")

HOJA_POR_DEFECTO = "Proyección de Mantenimientos(DATA)"
COL_ESTADO = ANCHO_TABLA + 2                               # una columna libre de por medio, a la derecha de los datos
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
UMBRAL_SALVAGUARDA = 0.8
MINIMO_PARA_SALVAGUARDA = 30
UMBRAL_COLUMNAS = 0.9                                      # forma esperada en al menos el 90% de lo que no está vacío
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMERO_RE = re.compile(r"^-?\d+(\.\d+)?$")
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
    """El proyector tal como lo carga la página: una consulta sin parámetros."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.get(f"{base_url}/includes/mttoLP/lp-mtto-proyeccionmtto-data.php", timeout=TIMEOUT_SEG)
    cuerpo = _parse_json_bom(resp)
    if not isinstance(cuerpo, dict) or "dataReservas" not in cuerpo:
        raise RuntimeError("Maxinet cambió la respuesta del proyector de mantenimiento (ya no trae 'dataReservas'); "
                           "no se escribió nada.")
    data = cuerpo["dataReservas"]
    if data in ("", None):
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"Maxinet devolvió un 'dataReservas' inesperado ({type(data).__name__}); no se escribió nada.")
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
    if nombre in NUMEROS:
        return bool(NUMERO_RE.match(texto))
    return True


def normalizar_filas(filas: list) -> list:
    """Las 15 celdas de la tabla de cada fila, ya limpias. Un ancho distinto, columnas que no cuadran (fechas,
    kilómetros o código de color sin su forma en casi todas las filas) o una Placa vacía o repetida detienen la corrida
    SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO_REPORTE}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del proyector de mantenimiento: llegaron filas de {sorted(anchos)} celdas y se "
            f"esperan {ANCHO_REPORTE} ({ANCHO_TABLA} columnas más el código de color). No se escribió nada en el Sheet; "
            f"revisar includes/mttoLP/lp-mtto-proyeccionmtto-data.php y ajustar ENCABEZADO.")
    out, placas, codigos = [], set(), []
    for f in filas:
        fila = [_texto(v) for v in f[:ANCHO_TABLA]]
        placa = fila[COL_PLACA]
        if not placa:
            raise RuntimeError("Una fila del proyector de mantenimiento viene sin Placa; no se escribió nada en el Sheet.")
        if placa in placas:
            raise RuntimeError("Una Placa viene repetida en el proyector de mantenimiento; no se escribió nada en el Sheet.")
        placas.add(placa)
        out.append(fila)
        codigos.append(_texto(f[COL_CODIGO_COLOR]))
    for k, nombre in enumerate(ENCABEZADO):
        if nombre not in FECHA and nombre not in NUMEROS:
            continue
        llenas = [fila[k] for fila in out if fila[k] != ""]
        buenas = sum(1 for t in llenas if _forma_esperada(nombre, t))
        if llenas and buenas < UMBRAL_COLUMNAS * len(llenas):
            raise RuntimeError(
                f"Las columnas del proyector de mantenimiento no cuadran ('{nombre}' sin la forma esperada en "
                f"{len(llenas) - buenas} de {len(llenas)} filas con dato). No se escribió nada en el Sheet.")
    llenos = [c for c in codigos if c != ""]
    if llenos and sum(1 for c in llenos if ENTERO_RE.match(c)) < UMBRAL_COLUMNAS * len(llenos):
        raise RuntimeError("La última celda del proyector de mantenimiento (código de color) ya no es un número en la "
                           "mayoría de las filas: las columnas se recorrieron. No se escribió nada en el Sheet.")
    return out


def _serial(texto: str):
    """Número de serie de una fecha yyyy-mm-dd; None si no es una fecha válida de 2000 a 2100."""
    if not FECHA_RE.match(texto):
        return None
    try:
        d = dt.date.fromisoformat(texto)
    except ValueError:
        return None
    return (d - BASE_SERIAL).days if 2000 <= d.year <= 2100 else None


def _valor(nombre: str, texto: str):
    """Valor tipado: fechas como número de serie y kilómetros y % como número. Todo lo demás, el texto tal cual. Lo que
    no tenga la forma esperada (por ejemplo una fecha 0000-00-00 o un semáforo en la columna mixta) se conserva como
    texto."""
    if texto == "":
        return ""
    if nombre in NUMEROS:
        if not NUMERO_RE.match(texto):
            return texto
        return float(texto) if "." in texto else int(texto)
    if nombre in FECHA or nombre in FECHA_O_TEXTO:
        serie = _serial(texto)
        return texto if serie is None else serie
    return texto


def a_fila_hoja(fila: list) -> list:
    """Las 15 columnas de la hoja, tipadas, a partir de las 15 limpias."""
    return [_valor(ENCABEZADO[k], fila[k]) for k in range(ANCHO_TABLA)]


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


ULT_COL = _col_a1(ANCHO_TABLA)                              # "O"


def nombre_hoja() -> str:
    return (os.environ.get("WORKSHEET_MTTO_PROYECTOR") or "").strip().strip("\"'").strip() or HOJA_POR_DEFECTO


def conectar_libro():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID"])


def _con_reintento(fn, intentos: int = 5):
    """Reintenta ante la cuota de Google Sheets (429) o un error temporal del servidor; el sync de la base escribe
    mucho en este mismo libro alrededor de las 8:00."""
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
    """La pestaña de destino. No se crea: otras pestañas del libro dependen de ella, y si alguien la renombró o la
    borró es mejor detenerse que dejar los datos en una pestaña nueva que nadie usa."""
    try:
        return _con_reintento(lambda: libro.worksheet(nombre))
    except gspread.exceptions.WorksheetNotFound:
        raise RuntimeError(
            f"No existe la pestaña {nombre} en el libro; no se escribió nada (la automatización no la crea). "
            f"Revisar el nombre o WORKSHEET_MTTO_PROYECTOR.") from None


def _leer_hoja(hoja) -> tuple:
    """(encabezado, filas con datos) de la pestaña; ([], []) si está vacía."""
    todo = _con_reintento(lambda: hoja.get(f"A1:{ULT_COL}", value_render_option="UNFORMATTED_VALUE"))
    if not todo:
        return [], []
    filas = []
    for f in todo[1:]:
        f = list(f) + [""] * (ANCHO_TABLA - len(f))
        if str(f[COL_PLACA]).strip() != "":
            filas.append(f)
    return list(todo[0]), filas


def _clave(v) -> str:
    """Forma comparable de una celda: 55194 (lo que devuelve Sheets) y 55194.0 (lo que se escribe) son lo mismo."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return format(float(v), ".6f").rstrip("0").rstrip(".")
    return str(v).strip()


def _resumen_y_salvaguarda(viejas: list, nuevas: list) -> dict:
    """Altas, bajas y cambios por Placa, y la salvaguarda contra respuestas incompletas."""
    ant = {str(f[COL_PLACA]).strip(): f for f in viejas}
    act = {str(f[COL_PLACA]).strip(): f for f in nuevas}
    res = {
        "antes": len(viejas), "despues": len(nuevas),
        "altas": sum(1 for k in act if k not in ant), "bajas": sum(1 for k in ant if k not in act),
        "cambios": sum(1 for k in act if k in ant and [_clave(x) for x in act[k]] != [_clave(x) for x in ant[k]]),
    }
    if not os.environ.get("FORZAR") and len(viejas) >= MINIMO_PARA_SALVAGUARDA \
            and len(nuevas) < UMBRAL_SALVAGUARDA * len(viejas):
        raise RuntimeError(
            f"Maxinet trae {len(nuevas)} placas y la hoja tiene {len(viejas)}: menos del 80%. Probable respuesta "
            f"incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    return res


def _formatos(hoja, filas_hoja: int) -> list:
    """Formato de fecha y de número en las columnas de datos, sólo de la fila 2 en adelante (idempotente). No toca el
    encabezado ni la configuración de la hoja: son de quien la armó."""
    def formato(nombre, patron, tipo):
        k = ENCABEZADO.index(nombre)
        return {"repeatCell": {
            "range": {"sheetId": hoja.id, "startRowIndex": 1, "endRowIndex": filas_hoja,
                      "startColumnIndex": k, "endColumnIndex": k + 1},
            "fields": "userEnteredFormat.numberFormat",
            "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}}}}

    pedidos = [formato(n, "yyyy-mm-dd", "DATE") for n in sorted(FECHA | FECHA_O_TEXTO)]
    pedidos += [formato(n, patron, "NUMBER") for n, patron in sorted(NUMEROS.items())]
    return pedidos


def refrescar(hoja, libro, nombre: str, filas: list) -> dict:
    """Reescribe la pestaña con el proyector de Maxinet."""
    encabezado, viejas = _leer_hoja(hoja)
    if encabezado and [str(h).strip() for h in encabezado[:ANCHO_TABLA]] != ENCABEZADO:
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

    ultima_vieja = r["antes"] + 1
    ultima = len(filas) + 1
    if ultima > hoja.row_count:
        _con_reintento(lambda: hoja.add_rows(ultima - hoja.row_count + 200))
    if hoja.col_count < COL_ESTADO:
        _con_reintento(lambda: hoja.add_cols(COL_ESTADO - hoja.col_count))
    if not encabezado:                                       # hoja sin encabezado: se escribe; si ya lo trae, no se toca
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
        hoja = obtener_hoja(libro, nombre)
        r = refrescar(hoja, libro, nombre, filas)
        if not os.environ.get("DRY_RUN"):
            validar_sin_repetidos(_con_reintento(lambda: libro.worksheet(nombre)))
        log.info("Automatización completada con éxito (%d placas)", r["despues"])
    except Exception:
        log.exception("Error en la automatización del proyector de mantenimientos")
        sys.exit(1)


if __name__ == "__main__":
    main()
