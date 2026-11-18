"""
Automatización diaria: login + lectura del reporte "2da - 3ra renta" (Corto Plazo) desde Maxinet vía requests
(sin navegador) y refresco del bloque del mes en curso en una pestaña de la Sheet "Base" del Tablero CP.

Endpoint confirmado a partir del JS real de Maxinet (cp-reporte-2-3-rentas.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/includes/reportescp/clientes-2-3-data-v2.php
            body: Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD, f_registro=0, tiporenta=0
            respuesta: {"data": [[18 valores, todo texto], ...]}: las 18 columnas de la tabla de la página.
    tiporenta=0 es "Ambas": entrega una fila por cada evento (No.Evento 2 = segunda renta, 3 = tercera renta), así que
    un mismo cliente puede salir dos veces. Desde/Hasta filtran por la fecha DEL EVENTO: la Fecha 2da renta para las
    filas de evento 2 y la Fecha 3ra renta para las de evento 3 (Hasta es inclusive). f_registro=0 es "sin filtro de
    antigüedad del cliente"; por decisión del usuario se deja como está (el filtro definitivo se define con el tablero
    de 2das y 3ras rentas).

Rango de fechas: del primer día del mes a AYER (hora Ciudad de México); si hoy es día 1, "ayer" cae en el mes anterior
y el rango es ese mes completo. Durante los primeros 3 días del mes se vuelve a escribir también el mes anterior.

Qué se escribe: se REFRESCA el bloque del mes. Cada corrida reemplaza, desde la primera fila cuya fecha de evento sea
>= inicio del bloque hasta el final, las columnas A:R por lo que entrega Maxinet, ordenado por (fecha del evento,
No.Evento, No. Cliente). Las filas anteriores (meses cerrados) no se tocan. La fila 1 se verifica contra las 18 columnas
esperadas; si no coincide, la corrida se detiene sin escribir. Si la pestaña no existe, se crea con esos encabezados.

Tipos de dato: fechas como fecha real (formato yyyy-mm-dd), No.Rentas y No.Evento como números, teléfonos como número
cuando son sólo dígitos (como en MKT), el resto como texto sin espacios sobrantes. Todo en modo RAW.

Los logs son públicos: nunca se registran nombres, correos ni teléfonos, sólo conteos y fechas.

Salvaguarda: si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más), la corrida se detiene
sin escribir (FORZAR=1 la omite).

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet "Base"),
    WORKSHEET_RENTAS_2_3_NAME (nombre o gid de la pestaña; por defecto "2DAS Y 3RAS RENTAS"),
    FECHA_DESDE, FECHA_HASTA, DRY_RUN, FORZAR (opcionales)
"""

import os
import re
import sys
import time
import json
import logging
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
log = logging.getLogger("maxinet_rentas_2_3_cp")


def _instalar_reintentos_gspread(cliente=HTTPClient) -> None:
    """Google Sheets limita las lecturas por minuto y esa cuota la comparten TODAS las automatizaciones que usan la
    misma cuenta de servicio. Un 429 se rechaza antes de procesarse, así que reintentar es seguro; los errores 5xx sólo
    se reintentan en lecturas (GET), para no duplicar una escritura. Es la misma regla del resto de las automatizaciones."""
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

# Mismo nombre y orden que la tabla de cp-reporte-2-3-rentas.php
COLUMNAS = [
    "No. Cliente", "Cliente", "No.Rentas", "No.Evento", "Fecha 1ra renta", "Suc. 1ra renta", "Asesor 1ra renta",
    "Fecha 2da renta", "Suc. 2da renta", "Asesor 2da renta", "Fecha 3ra renta", "Suc. 3ra renta", "Asesor 3ra renta",
    "ContactTelNo", "TelNo", "MobileNo", "ContactFaxNo", "Email",
]
IDX = {nombre: i for i, nombre in enumerate(COLUMNAS)}
IDX_CLIENTE, IDX_EVENTO = IDX["No. Cliente"], IDX["No.Evento"]
IDX_FECHA_2, IDX_FECHA_3 = IDX["Fecha 2da renta"], IDX["Fecha 3ra renta"]
FECHAS = [IDX[c] for c in ("Fecha 1ra renta", "Fecha 2da renta", "Fecha 3ra renta")]
ENTEROS = [IDX["No.Rentas"], IDX["No.Evento"]]
TELEFONOS = [IDX[c] for c in ("ContactTelNo", "TelNo", "MobileNo", "ContactFaxNo")]
FORMATO_FECHA = "yyyy-mm-dd"
EVENTOS = (2, 3)
ENDPOINT = "includes/reportescp/clientes-2-3-data-v2.php"
TIPO_RENTA_AMBAS = "0"
SIN_FILTRO_REGISTRO = "0"
FILA_INICIO_DATOS = 2
ULTIMA_COL = gspread.utils.rowcol_to_a1(1, len(COLUMNAS)).rstrip("1")      # "R"
NOMBRE_PESTANA = "2DAS Y 3RAS RENTAS"
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 600
REINTENTOS = 3
DIAS_MES_ANTERIOR = 3                  # los primeros días del mes se refresca también el mes anterior
FILAS_POR_ESCRITURA = 800
BASE_SERIAL = dt.date(1899, 12, 30)
FECHA_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
NUMERO_RE = re.compile(r"^-?\d+$")


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # La respuesta trae datos de clientes: sólo se registra su tamaño
        log.error("Respuesta de Maxinet no es JSON válido (%d bytes)", len(texto))
        raise


def _nueva_sesion() -> requests.Session:
    """Reintenta con espera creciente si Maxinet corta la conexión o responde 502/503/504."""
    session = requests.Session()
    retry = Retry(total=REINTENTOS, connect=REINTENTOS, read=0, status=REINTENTOS,
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
        timeout=60,
    )
    data = _parse_json_bom(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")
    log.info("Login en Maxinet exitoso")
    return session


def bloques_a_refrescar() -> list[tuple[str, str]]:
    """Bloques de fechas (desde, hasta) que se vuelven a escribir en cada corrida, del más antiguo al más reciente.

    Principal: del primer día del mes de 'ayer' a ayer (hora CDMX). Durante los primeros DIAS_MES_ANTERIOR días del
    mes se refresca además el mes anterior completo. FECHA_DESDE/FECHA_HASTA fijan un solo bloque (pruebas y
    recuperaciones)."""
    ayer = dt.datetime.now(ZONA).date() - dt.timedelta(days=1)
    hasta = os.environ.get("FECHA_HASTA") or ayer.isoformat()
    h = dt.date.fromisoformat(hasta)
    if os.environ.get("FECHA_DESDE"):
        return [(os.environ["FECHA_DESDE"], hasta)]
    inicio = h.replace(day=1)
    bloques = []
    if h.day <= DIAS_MES_ANTERIOR:
        fin_prev = inicio - dt.timedelta(days=1)
        bloques.append((fin_prev.replace(day=1).isoformat(), fin_prev.isoformat()))
    bloques.append((inicio.isoformat(), hasta))
    return bloques


def descargar_rentas(session: requests.Session, desde: str, hasta: str) -> list[list]:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(
        f"{base_url}/{ENDPOINT}",
        data={"Desde": desde, "Hasta": hasta, "f_registro": SIN_FILTRO_REGISTRO, "tiporenta": TIPO_RENTA_AMBAS},
        timeout=TIMEOUT_SEG,
    )
    cuerpo = _parse_json_bom(resp)
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("data"), list):
        raise RuntimeError("Maxinet no devolvió la lista 'data' esperada en el reporte de 2das y 3ras rentas. No se escribió nada en el Sheet.")
    filas = normalizar_filas(cuerpo["data"])
    log.info("Datos descargados de Maxinet: %d filas (Desde=%s, Hasta=%s)", len(filas), desde, hasta)
    return filas


# ---------------------------------------------------------------- Conversión de tipos
def _serie(texto: str, columna: str) -> float:
    """'2026-11-03' -> número de serie de Sheets."""
    m = FECHA_RE.match(texto)
    if not m:
        raise RuntimeError(f"La columna '{columna}' del reporte ya no trae fechas con la forma esperada "
                           f"({len(texto)} caracteres). No se escribió nada en el Sheet.")
    anio, mes, dia = (int(g) for g in m.groups())
    return float((dt.date(anio, mes, dia) - BASE_SERIAL).days)


def _entero(texto: str, columna: str) -> int:
    if not NUMERO_RE.match(texto):
        raise RuntimeError(f"La columna '{columna}' del reporte ya no trae números enteros "
                           f"({len(texto)} caracteres). No se escribió nada en el Sheet.")
    return int(texto)


def _telefono(texto: str):
    """Número si son sólo dígitos sin cero inicial (como en MKT); con prefijo, letras, ceros o más de 15 queda texto."""
    if re.fullmatch(r"[1-9]\d{0,14}", texto):
        return int(texto)
    return texto


def fecha_evento(fila: list) -> float:
    """Fecha del evento de una fila ya tipada: la de la 2da renta si No.Evento es 2, la de la 3ra si es 3."""
    return fila[IDX_FECHA_2] if fila[IDX_EVENTO] == 2 else fila[IDX_FECHA_3]


def normalizar_filas(filas: list[list]) -> list[list]:
    """Deja cada fila con exactamente las 18 columnas de COLUMNAS, tipadas y sin espacios sobrantes, ordenadas por
    (fecha del evento, No.Evento, No. Cliente) y sin eventos repetidos (mismo cliente y mismo evento). Un ancho
    distinto, un evento que no sea 2 ni 3 o fechas que no cuadran detienen la corrida SIN escribir nada."""
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos != {len(COLUMNAS)}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de 2das y 3ras rentas: llegaron filas de {sorted(anchos)} columnas y "
            f"se esperan {len(COLUMNAS)}. No se escribió nada en el Sheet; revisar {ENDPOINT} y ajustar COLUMNAS.")
    vistos, salida, repetidos = set(), [], 0
    for f in filas:
        datos = ["" if v is None else str(v).strip() for v in f]
        fila = list(datos)
        for j in ENTEROS:
            fila[j] = _entero(datos[j], COLUMNAS[j])
        if fila[IDX_EVENTO] not in EVENTOS:
            raise RuntimeError("El reporte de 2das y 3ras rentas trae un No.Evento distinto de 2 y 3. No se escribió nada en el Sheet.")
        for j in FECHAS:
            if datos[j]:
                fila[j] = _serie(datos[j], COLUMNAS[j])
        if fila[IDX_EVENTO] == 2 and not datos[IDX_FECHA_2] or fila[IDX_EVENTO] == 3 and not datos[IDX_FECHA_3]:
            raise RuntimeError("Hay eventos sin la fecha de su renta en el reporte de 2das y 3ras rentas. No se escribió nada en el Sheet.")
        for j in TELEFONOS:
            fila[j] = _telefono(datos[j]) if datos[j] else ""
        clave = (datos[IDX_CLIENTE], fila[IDX_EVENTO])
        if clave in vistos:
            repetidos += 1
            continue
        vistos.add(clave)
        salida.append(fila)
    if repetidos:
        log.warning("Maxinet repitió %d eventos (mismo cliente y No.Evento); se conserva uno de cada uno", repetidos)
    salida.sort(key=lambda r: (fecha_evento(r), r[IDX_EVENTO], r[IDX_CLIENTE]))
    return salida


# ---------------------------------------------------------------- Sheet
def _nombre_pestana() -> str:
    return (os.environ.get("WORKSHEET_RENTAS_2_3_NAME") or "").strip().strip("\"'").strip() or NOMBRE_PESTANA


def resolver_pestana(libro, referencia: str):
    """La pestaña del libro por gid (si la referencia es un número) o por nombre; si es un nombre y no existe, se crea
    con los encabezados (con DRY_RUN no se crea nada y devuelve None). Los logs son públicos: si falta un gid, el error
    sólo dice cuántas pestañas tiene el libro."""
    referencia = str(referencia).strip()
    try:
        return libro.get_worksheet_by_id(int(referencia)) if referencia.isdigit() else libro.worksheet(referencia)
    except gspread.exceptions.WorksheetNotFound:
        if referencia.isdigit():
            raise gspread.exceptions.WorksheetNotFound(
                f"{referencia} (el libro tiene {len(libro.worksheets())} pestañas; si la recrearon, actualiza el gid en el secret)") from None
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: la pestaña no existe y se crearía con los encabezados (no se escribió nada).")
        return None
    ws = libro.add_worksheet(title=referencia, rows=2000, cols=len(COLUMNAS))
    ws.update(range_name=f"A1:{ULTIMA_COL}1", values=[COLUMNAS], value_input_option="RAW")
    dar_formato_hoja(ws)
    log.info("La pestaña no existía: se creó con los %d encabezados y el formato de las demás hojas de la Base", len(COLUMNAS))
    return ws


# Formato de las demás hojas de datos de la Base (el de BD ENTREGAS): pestaña azul, cuadrícula oculta, fila 1 fija con el
# encabezado en negritas sobre naranja y todo centrado en Calibri 11. Se aplica sólo cuando la pestaña se crea, para no
# pisar los cambios que se le hagan después.
COLOR_PESTANA = {"blue": 1}
COLOR_ENCABEZADO = {"red": 1, "green": 0.6}
ANCHOS = {"No. Cliente": 100, "Cliente": 300, "No.Rentas": 80, "No.Evento": 80, "Email": 260}
ANCHO_POR_DEFECTO = 125
FUENTE = {"fontFamily": "Calibri", "fontSize": 11}


def dar_formato_hoja(worksheet):
    """Deja la pestaña con el formato de las demás hojas de datos de la Base."""
    n = len(COLUMNAS)
    sid = worksheet.id

    def rango(fila_ini, fila_fin=None):
        r = {"sheetId": sid, "startRowIndex": fila_ini, "startColumnIndex": 0, "endColumnIndex": n}
        if fila_fin is not None:
            r["endRowIndex"] = fila_fin
        return r

    pedidos = [
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "tabColor": COLOR_PESTANA,
            "gridProperties": {"frozenRowCount": 1, "hideGridlines": True}},
            "fields": "tabColor,gridProperties.frozenRowCount,gridProperties.hideGridlines"}},
        {"repeatCell": {"range": rango(0, 1), "cell": {"userEnteredFormat": {
            "backgroundColor": COLOR_ENCABEZADO, "horizontalAlignment": "CENTER", "verticalAlignment": "BOTTOM",
            "textFormat": {**FUENTE, "bold": True}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)"}},
        {"repeatCell": {"range": rango(1), "cell": {"userEnteredFormat": {
            "horizontalAlignment": "CENTER", "verticalAlignment": "BOTTOM", "textFormat": FUENTE}},
            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,textFormat)"}},
    ]
    for j, nombre in enumerate(COLUMNAS):
        pedidos.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": j, "endIndex": j + 1},
            "properties": {"pixelSize": ANCHOS.get(nombre, ANCHO_POR_DEFECTO)}, "fields": "pixelSize"}})
    for j in FECHAS:
        pedidos.append({"repeatCell": {"range": {**rango(1), "startColumnIndex": j, "endColumnIndex": j + 1},
                                       "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": FORMATO_FECHA}}},
                                       "fields": "userEnteredFormat.numberFormat"}})
    worksheet.spreadsheet.batch_update({"requests": pedidos})


def conectar_sheet():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_CLIENTES_NUEVOS"])
    return resolver_pestana(sh, _nombre_pestana())


def _a_serie_hoja(v, columna: str) -> float:
    """Fecha ya escrita en la hoja (número de serie, o texto yyyy-mm-dd si alguien la pegó como texto)."""
    if isinstance(v, (int, float)):
        return float(v)
    return _serie(str(v).strip(), columna)


def verificar_encabezados(worksheet):
    fila1 = worksheet.get(f"A1:{ULTIMA_COL}1")
    actuales = [str(c).strip() for c in (fila1[0] if fila1 else [])]
    if actuales != COLUMNAS:
        distintas = [i + 1 for i in range(max(len(actuales), len(COLUMNAS)))
                     if (actuales[i] if i < len(actuales) else None) != (COLUMNAS[i] if i < len(COLUMNAS) else None)]
        raise RuntimeError(f"Los encabezados de la pestaña ya no coinciden con las {len(COLUMNAS)} columnas del reporte "
                           f"(difieren las columnas {distintas[:10]}). No se escribió nada.")


def _fechas_de_evento_en_hoja(worksheet) -> list:
    """Fecha del evento de cada fila de la hoja a partir de la fila 2 (None si la fila está vacía)."""
    c1 = gspread.utils.rowcol_to_a1(FILA_INICIO_DATOS, IDX_EVENTO + 1).rstrip("0123456789")
    c2 = gspread.utils.rowcol_to_a1(FILA_INICIO_DATOS, IDX_FECHA_3 + 1).rstrip("0123456789")
    col = worksheet.get(f"{c1}{FILA_INICIO_DATOS}:{c2}{worksheet.row_count}", value_render_option="UNFORMATTED_VALUE")
    off2, off3 = IDX_FECHA_2 - IDX_EVENTO, IDX_FECHA_3 - IDX_EVENTO
    salida = []
    for f in col:
        evento = f[0] if f else ""
        if evento == "":
            salida.append(None)
            continue
        pos = off2 if int(evento) == 2 else off3
        valor = f[pos] if len(f) > pos else ""
        if valor == "":
            raise RuntimeError("Hay filas de la pestaña sin la fecha de su evento. No se escribió nada.")
        salida.append(_a_serie_hoja(valor, "Fecha del evento"))
    return salida


def refrescar_bloque(worksheet, nuevas: list[list], desde: str) -> dict:
    """Reemplaza, de la primera fila con fecha de evento >= desde hasta el final, el bloque A:R por lo que entrega
    Maxinet (ya ordenado). Las filas anteriores al bloque (meses cerrados) no se tocan."""
    verificar_encabezados(worksheet)
    ini_serie = float((dt.date.fromisoformat(desde) - BASE_SERIAL).days)
    fechas = _fechas_de_evento_en_hoja(worksheet)
    ultima = FILA_INICIO_DATOS - 1
    for i, f in enumerate(fechas):
        if f is not None:
            ultima = FILA_INICIO_DATOS + i
    inicio = ultima + 1
    for i, f in enumerate(fechas[:ultima - FILA_INICIO_DATOS + 1]):
        if f is not None and f >= ini_serie:
            inicio = FILA_INICIO_DATOS + i
            break
    anteriores_en_el_bloque = [f for f in fechas[inicio - FILA_INICIO_DATOS:ultima - FILA_INICIO_DATOS + 1]
                               if f is not None and f < ini_serie]
    if anteriores_en_el_bloque:
        raise RuntimeError(f"Hay {len(anteriores_en_el_bloque)} filas con fecha de evento anterior al {desde} después del "
                           f"inicio del bloque (la pestaña no está ordenada por fecha). No se escribió nada.")
    viejas = max(0, ultima - inicio + 1)

    if viejas >= 30 and len(nuevas) < 0.8 * viejas and not os.environ.get("FORZAR"):
        raise RuntimeError(f"Maxinet trae {len(nuevas)} filas para el bloque y el Sheet tiene {viejas}: menos del 80%. "
                           f"Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    log.info("Bloque desde %s: filas %d -> %d | nuevas %d", desde, viejas, len(nuevas), max(0, len(nuevas) - viejas))

    fila_ini, fila_fin = inicio, inicio + len(nuevas) - 1
    resumen = {"antes": viejas, "despues": len(nuevas), "nuevas": max(0, len(nuevas) - viejas), "inicio": inicio}
    if not nuevas:
        log.info("Maxinet no trae filas para el bloque; no se escribió nada.")
        return resumen
    rango = f"A{fila_ini}:{ULTIMA_COL}{fila_fin}"
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían %s (%d filas) (no se escribió nada).", rango, len(nuevas))
        return resumen

    if fila_fin > worksheet.row_count:
        worksheet.add_rows(fila_fin - worksheet.row_count + 200)
    for k in range(0, len(nuevas), FILAS_POR_ESCRITURA):
        tanda = nuevas[k:k + FILAS_POR_ESCRITURA]
        worksheet.update(range_name=f"A{fila_ini + k}:{ULTIMA_COL}{fila_ini + k + len(tanda) - 1}",
                         values=tanda, value_input_option="RAW")
    if ultima > fila_fin:                                   # el bloque quedó más corto: limpiar lo que sobra
        worksheet.batch_clear([f"A{fila_fin + 1}:{ULTIMA_COL}{ultima}"])
    dar_formato_fechas(worksheet, fila_ini, fila_fin)
    log.info("Bloque reescrito: %d filas en %s (última fila anterior: %d)", len(nuevas), rango, ultima)
    return resumen


def dar_formato_fechas(worksheet, fila_ini: int, fila_fin: int):
    """Formato de fecha a las columnas de fecha del bloque (los valores son números de serie)."""
    def pedido(col):
        return {"repeatCell": {
            "range": {"sheetId": worksheet.id, "startRowIndex": fila_ini - 1, "endRowIndex": fila_fin,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": FORMATO_FECHA}}},
            "fields": "userEnteredFormat.numberFormat"}}
    worksheet.spreadsheet.batch_update({"requests": [pedido(j) for j in FECHAS]})


def validar_bloque(worksheet, inicio: int, cantidad: int):
    """El bloque escrito debe tener las filas esperadas y la fecha del evento en orden ascendente."""
    if not cantidad:
        return
    fechas = _fechas_de_evento_en_hoja(worksheet)
    bloque = fechas[inicio - FILA_INICIO_DATOS:inicio - FILA_INICIO_DATOS + cantidad]
    if len(bloque) != cantidad or any(f is None for f in bloque):
        raise RuntimeError(f"Tras escribir, el bloque tiene {sum(f is not None for f in bloque)} filas con fecha de evento y se esperaban {cantidad}.")
    if bloque != sorted(bloque):
        raise RuntimeError("Tras escribir, la fecha del evento del bloque no quedó en orden ascendente.")
    log.info("Validación OK: %d filas del bloque con fecha de evento en orden", cantidad)


def main():
    try:
        session = login_maxinet()
        filas, desde = [], None
        for d, h in bloques_a_refrescar():
            filas += descargar_rentas(session, d, h)
            desde = desde or d
        filas.sort(key=lambda r: (fecha_evento(r), r[IDX_EVENTO], r[IDX_CLIENTE]))
        worksheet = conectar_sheet()
        if worksheet is None:                               # DRY_RUN y la pestaña aún no existe
            log.info("DRY_RUN: %d filas desde %s listas para escribir.", len(filas), desde)
            return
        r = refrescar_bloque(worksheet, filas, desde)
        if not os.environ.get("DRY_RUN"):
            validar_bloque(worksheet, r["inicio"], r["despues"])
        log.info("Automatización completada con éxito (bloque de %d filas desde %s)", r["despues"], desde)
    except Exception:
        log.exception("Error en la automatización de 2das y 3ras rentas CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
