"""
Automatización: login + lectura del reporte "Unidades en Proceso de Venta" (venta de seminuevos) desde Maxinet vía
requests (sin navegador) y reescritura de la pestaña "Unidades en Proceso de Venta" de la Base LP copia
("BASE LP_AUTOMATIZADO").

Endpoint confirmado a partir del HTML/JS reales de Maxinet (Unidades-Venta.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/unidades-venta-all.php   body: Estatus (1 Abierto, 10 Propuesta, 0 Cerrado,
            11 Rechazo, 2 Todo), Desde, Hasta (sólo con Cerrado, en la página; aquí van vacíos)
            respuesta: {"data": [[47 celdas], ...]}, una fila por unidad (Id).
    De las 47 celdas, la primera es el botón "Detalle" (HTML) y la segunda una columna oculta y vacía: ninguna se
    copia. Las otras 45 son las columnas de la tabla, en el mismo orden que la página (ENCABEZADO).

Qué se carga: por omisión el estatus Abierto (1), que ya incluye las unidades en Propuesta (el estatus 10 es un
subconjunto de él: las mismas filas). ESTATUS_UNIDADES_VENTA permite otro o varios, separados por coma (se
desduplica por Id). En cada corrida se reescribe la pestaña completa (no hay `append`): una unidad que se vende,
se da de baja o cambia de estatus sale o se actualiza en la hoja.

Tipos: las fechas van como número de serie con formato yyyy-mm-dd; los precios, el MOI y la depreciación como número
con formato de moneda ($#,##0.00) (Maxinet manda varios como texto "$ 208,000.00"); kilómetros, % de utilización, año,
meses de uso e Id como número; todo lo demás como texto, sin interpretarlo, con value_input_option=RAW. "Estatus A"
llega con una etiqueta de color (<span style="color:orange;">Propuesta</span>): se guarda el texto visible. El
"# Cliente" (#4799998) es texto.

El encabezado de la fila 1 es de quien armó la hoja: si ya está con los 45 nombres de la tabla no se toca (ni su
formato); si está vacío se escribe; si es otro, la corrida se detiene SIN escribir. La pestaña debe existir: no se crea.
A la derecha de los datos, con una columna libre de por medio, se anota la hora de la última actualización.

Salvaguardas (FORZAR=1 omite sólo la del 80%): la corrida se detiene SIN escribir si el reporte cambia de ancho, si
sus columnas no cuadran (fechas, precios o números con otra forma en la gran mayoría de las filas: columnas
recorridas), si un Id viene vacío o repetido, si la pestaña no existe o tiene otro encabezado, si Maxinet no trae
ninguna fila, o si trae menos del 80% de las unidades que ya estaban en la hoja (con 30 o más). Se escribe primero
(update) y se limpia lo que sobra después, nunca al revés.

Los logs sólo llevan conteos: la tabla trae clientes, RFC y placas y no se registran.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID (la Base LP copia), WORKSHEET_UNIDADES_VENTA (por defecto "Unidades en Proceso de Venta"),
    ESTATUS_UNIDADES_VENTA (por defecto "1"), DRY_RUN, FORZAR (opcionales)
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
log = logging.getLogger("maxinet_unidades_venta")

# Orden confirmado en el HTML real de Unidades-Venta.php (y en la fila 1 de la pestaña)
ENCABEZADO = [
    "Id", "Placa", "Grupo", "Motivo envío", "Estatus A", "Estatus B", "Precio Compra", "Precio Venta Propuesto",
    "P.EBC Compra", "P.EBC Venta", "Costo Adecuaciones", "Precio Final Venta", "TT", "Precio Actual", "Asesor",
    "Categoría", "No. Serie", "Fecha Compra", "Fecha Venta", "Marca", "Modelo", "Modelo Oficial", "Año", "Km Prohire",
    "Km Visual", "Transmisión", "% Utilización", "# Cliente", "Cliente", "Nombre para facturación", "RFC",
    "Fecha Alta", "Fecha Liberado a TP", "Author", "Modelo Equivalente", "Bsite", "CurrentSite", "EntryDate",
    "Meses Uso", "MOI (sin iva)", "Precio caja", "Total MOI", "Dep. Mensual", "Dep. Acumulada",
    "Remanente ajustado 14%",
]
ANCHO_TABLA = len(ENCABEZADO)                              # 45 columnas de la tabla
PREFIJO = 2                                                # antes de ellas: botón "Detalle" y una columna oculta vacía
ANCHO_REPORTE = PREFIJO + ANCHO_TABLA                      # 47 celdas por fila

FECHA = {"Fecha Compra", "Fecha Venta", "Fecha Alta", "Fecha Liberado a TP", "EntryDate"}
DINERO = {
    "Precio Compra", "Precio Venta Propuesto", "P.EBC Compra", "P.EBC Venta", "Costo Adecuaciones",
    "Precio Final Venta", "TT", "Precio Actual", "MOI (sin iva)", "Precio caja", "Total MOI", "Dep. Mensual",
    "Dep. Acumulada", "Remanente ajustado 14%",
}
NUMEROS = {                                               # nombre -> formato de presentación
    "Id": "0", "Año": "0", "Meses Uso": "0", "Km Prohire": "#,##0", "Km Visual": "#,##0", "% Utilización": "0.00",
}
FORMATO_DINERO = "$#,##0.00"

COL_ID = ENCABEZADO.index("Id")

HOJA_POR_DEFECTO = "Unidades en Proceso de Venta"
ESTATUS_POR_DEFECTO = "1"
COL_ESTADO = ANCHO_TABLA + 2                               # una columna libre de por medio, a la derecha de los datos
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
UMBRAL_SALVAGUARDA = 0.8
MINIMO_PARA_SALVAGUARDA = 30
UMBRAL_COLUMNAS = 0.9                                      # forma esperada en al menos el 90% de lo que no está vacío
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMERO_RE = re.compile(r"^-?\d+(\.\d+)?$")
DINERO_RE = re.compile(r"^(-)?\s*\$?\s*(-)?\s*(\d[\d,]*(?:\.\d+)?)$")
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


def estatus_a_consultar() -> list:
    """Los estatus a pedir (ESTATUS_UNIDADES_VENTA, separados por coma); por omisión Abierto."""
    crudo = (os.environ.get("ESTATUS_UNIDADES_VENTA") or "").strip() or ESTATUS_POR_DEFECTO
    estatus = [e.strip() for e in crudo.split(",") if e.strip()]
    if not estatus or any(not ENTERO_RE.match(e) for e in estatus):
        raise RuntimeError(f"ESTATUS_UNIDADES_VENTA inválido ({crudo!r}): se esperan números separados por coma.")
    return estatus


def consultar(session: requests.Session, estatus: str) -> list:
    """El reporte de un estatus, como lo pide la página al filtrar."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(f"{base_url}/json/unidades-venta-all.php",
                        data={"Estatus": estatus, "Desde": "", "Hasta": ""}, timeout=TIMEOUT_SEG)
    cuerpo = _parse_json_bom(resp)
    if not isinstance(cuerpo, dict) or "data" not in cuerpo:
        raise RuntimeError("Maxinet cambió la respuesta del reporte de unidades en proceso de venta (ya no trae "
                           "'data'); no se escribió nada.")
    data = cuerpo["data"]
    if data in ("", None):
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"Maxinet devolvió un 'data' inesperado ({type(data).__name__}); no se escribió nada.")
    return data


def consultar_todos(session: requests.Session) -> list:
    """Filas de todos los estatus pedidos, sin repetir Id (la primera que aparezca)."""
    vistos, filas = set(), []
    for estatus in estatus_a_consultar():
        bloque = consultar(session, estatus)
        log.info("Estatus %s: %d unidades", estatus, len(bloque))
        for f in bloque:
            clave = str(f[PREFIJO]).strip() if len(f) > PREFIJO else None
            if clave is not None and clave in vistos:
                continue
            vistos.add(clave)
            filas.append(f)
    return filas


# -------------------------------------------------------- limpieza y tipos
def _texto(v) -> str:
    """Texto sin etiquetas HTML ni espacios sobrantes; el 'None' que imprime el reporte es vacío. Un 0 numérico es "0"."""
    if v is None:
        return ""
    s = html.unescape(re.sub(r"<[^>]*>", "", str(v))).replace("\xa0", " ").strip()
    return "" if s in ("None", "null", "NULL") else s


def _dinero(texto: str):
    """Número de un precio ('$ 208,000.00', '-$ 1,200.50', '1234.5'); None si no tiene esa forma."""
    m = DINERO_RE.match(texto)
    if not m:
        return None
    numero = float(m.group(3).replace(",", ""))
    return -numero if (m.group(1) or m.group(2)) else numero


def _forma_esperada(nombre: str, texto: str) -> bool:
    if nombre in FECHA:
        return bool(FECHA_RE.match(texto))
    if nombre in DINERO:
        return _dinero(texto) is not None
    if nombre in NUMEROS:
        return bool(NUMERO_RE.match(texto))
    return True


def normalizar_filas(filas: list) -> list:
    """Las 45 celdas de la tabla de cada fila, ya limpias. Un ancho distinto, columnas que no cuadran (fechas, precios
    o números sin su forma en casi todas las filas) o un Id vacío o repetido detienen la corrida SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO_REPORTE}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de unidades en proceso de venta: llegaron filas de {sorted(anchos)} "
            f"celdas y se esperan {ANCHO_REPORTE} ({ANCHO_TABLA} columnas más 2 de acciones). No se escribió nada en "
            f"el Sheet; revisar json/unidades-venta-all.php y ajustar ENCABEZADO.")
    out, ids = [], set()
    for f in filas:
        fila = [_texto(v) for v in f[PREFIJO:]]
        ident = fila[COL_ID]
        if not ident:
            raise RuntimeError("Una fila del reporte de unidades en proceso de venta viene sin Id; no se escribió nada en el Sheet.")
        if ident in ids:
            raise RuntimeError("Un Id viene repetido en el reporte de unidades en proceso de venta; no se escribió nada en el Sheet.")
        ids.add(ident)
        out.append(fila)
    for k, nombre in enumerate(ENCABEZADO):
        if nombre not in FECHA and nombre not in DINERO and nombre not in NUMEROS:
            continue
        llenas = [fila[k] for fila in out if fila[k] != ""]
        buenas = sum(1 for t in llenas if _forma_esperada(nombre, t))
        if llenas and buenas < UMBRAL_COLUMNAS * len(llenas):
            raise RuntimeError(
                f"Las columnas del reporte de unidades en proceso de venta no cuadran ('{nombre}' sin la forma "
                f"esperada en {len(llenas) - buenas} de {len(llenas)} filas con dato). No se escribió nada en el Sheet.")
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
    """Valor tipado: fechas como número de serie, precios y medidas como número. Todo lo demás, el texto tal cual. Lo
    que no tenga la forma esperada (por ejemplo una fecha 0000-00-00) se conserva como texto."""
    if texto == "":
        return ""
    if nombre in DINERO:
        numero = _dinero(texto)
        return texto if numero is None else (int(numero) if numero.is_integer() else numero)
    if nombre in NUMEROS:
        if not NUMERO_RE.match(texto):
            return texto
        numero = float(texto)
        return int(numero) if numero.is_integer() else numero
    if nombre in FECHA:
        serie = _serial(texto)
        return texto if serie is None else serie
    return texto


def a_fila_hoja(fila: list) -> list:
    """Las 45 columnas de la hoja, tipadas, a partir de las 45 limpias."""
    return [_valor(ENCABEZADO[k], fila[k]) for k in range(ANCHO_TABLA)]


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


ULT_COL = _col_a1(ANCHO_TABLA)                              # "AS"


def nombre_hoja() -> str:
    return (os.environ.get("WORKSHEET_UNIDADES_VENTA") or "").strip().strip("\"'").strip() or HOJA_POR_DEFECTO


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
    """La pestaña de destino. No se crea: si alguien la renombró o la borró es mejor detenerse que dejar los datos en
    una pestaña nueva que nadie usa."""
    try:
        return _con_reintento(lambda: libro.worksheet(nombre))
    except gspread.exceptions.WorksheetNotFound:
        raise RuntimeError(
            f"No existe la pestaña {nombre} en el libro; no se escribió nada (la automatización no la crea). "
            f"Revisar el nombre o WORKSHEET_UNIDADES_VENTA.") from None


def _leer_hoja(hoja) -> tuple:
    """(encabezado, filas con datos) de la pestaña; ([], []) si está vacía."""
    todo = _con_reintento(lambda: hoja.get(f"A1:{ULT_COL}", value_render_option="UNFORMATTED_VALUE"))
    if not todo:
        return [], []
    filas = []
    for f in todo[1:]:
        f = list(f) + [""] * (ANCHO_TABLA - len(f))
        if str(f[COL_ID]).strip() != "":
            filas.append(f)
    return list(todo[0]), filas


def _clave(v) -> str:
    """Forma comparable de una celda: 3065 (lo que devuelve Sheets) y 3065.0 (lo que se escribe) son lo mismo."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return format(float(v), ".6f").rstrip("0").rstrip(".")
    return str(v).strip()


def _resumen_y_salvaguarda(viejas: list, nuevas: list) -> dict:
    """Altas, bajas y cambios por Id, y la salvaguarda contra respuestas incompletas."""
    ant = {_clave(f[COL_ID]): f for f in viejas}
    act = {_clave(f[COL_ID]): f for f in nuevas}
    res = {
        "antes": len(viejas), "despues": len(nuevas),
        "altas": sum(1 for k in act if k not in ant), "bajas": sum(1 for k in ant if k not in act),
        "cambios": sum(1 for k in act if k in ant and [_clave(x) for x in act[k]] != [_clave(x) for x in ant[k]]),
    }
    if not os.environ.get("FORZAR") and len(viejas) >= MINIMO_PARA_SALVAGUARDA \
            and len(nuevas) < UMBRAL_SALVAGUARDA * len(viejas):
        raise RuntimeError(
            f"Maxinet trae {len(nuevas)} unidades y la hoja tiene {len(viejas)}: menos del 80%. Probable respuesta "
            f"incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    return res


def _formatos(hoja, filas_hoja: int) -> list:
    """Formato de fecha, moneda y número en las columnas de datos, sólo de la fila 2 en adelante (idempotente). No toca
    el encabezado ni la configuración de la hoja: son de quien la armó."""
    def formato(nombre, patron, tipo):
        k = ENCABEZADO.index(nombre)
        return {"repeatCell": {
            "range": {"sheetId": hoja.id, "startRowIndex": 1, "endRowIndex": filas_hoja,
                      "startColumnIndex": k, "endColumnIndex": k + 1},
            "fields": "userEnteredFormat.numberFormat",
            "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}}}}

    pedidos = [formato(n, "yyyy-mm-dd", "DATE") for n in sorted(FECHA)]
    pedidos += [formato(n, FORMATO_DINERO, "CURRENCY") for n in sorted(DINERO)]
    pedidos += [formato(n, patron, "NUMBER") for n, patron in sorted(NUMEROS.items())]
    return pedidos


def refrescar(hoja, libro, nombre: str, filas: list) -> dict:
    """Reescribe la pestaña con el reporte de Maxinet."""
    encabezado, viejas = _leer_hoja(hoja)
    if encabezado and [str(h).strip() for h in encabezado[:ANCHO_TABLA]] != ENCABEZADO:
        raise RuntimeError(
            f"La pestaña {nombre} tiene un encabezado distinto al esperado (alguien movió o cambió columnas); "
            f"no se escribió nada. Revisar la hoja o ajustar ENCABEZADO.")
    if not filas:
        raise RuntimeError("Maxinet no trajo ninguna unidad; no se escribió nada.")
    r = _resumen_y_salvaguarda(viejas, filas)
    log.info("Hoja %s: filas %d -> %d | altas %d, bajas %d, con cambios %d",
             nombre, r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"])
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían A2:%s%d (%d unidades) (no se escribió nada).", ULT_COL, len(filas) + 1, len(filas))
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
    log.info("Hoja reescrita: %d unidades en A2:%s%d", len(filas), ULT_COL, ultima)
    return r


def validar_sin_repetidos(hoja):
    """Ningún Id debe repetirse en la hoja; si ocurre, la corrida falla."""
    vistos, dups = set(), set()
    for v in _con_reintento(lambda: hoja.col_values(COL_ID + 1))[1:]:
        k = str(v).strip()
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Id repetido en la hoja ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin Id repetidos en la hoja")


def main():
    try:
        session = login_maxinet()
        limpias = normalizar_filas(consultar_todos(session))
        log.info("Datos descargados de Maxinet: %d unidades", len(limpias))
        filas = [a_fila_hoja(f) for f in limpias]
        libro = conectar_libro()
        nombre = nombre_hoja()
        hoja = obtener_hoja(libro, nombre)
        r = refrescar(hoja, libro, nombre, filas)
        if not os.environ.get("DRY_RUN"):
            validar_sin_repetidos(_con_reintento(lambda: libro.worksheet(nombre)))
        log.info("Automatización completada con éxito (%d unidades)", r["despues"])
    except Exception:
        log.exception("Error en la automatización de unidades en proceso de venta")
        sys.exit(1)


if __name__ == "__main__":
    main()
