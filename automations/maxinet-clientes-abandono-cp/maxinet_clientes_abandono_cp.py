"""
Automatización diaria: login + lectura del reporte "Clientes - No. Rentas" (clientes en abandono, Corto Plazo) desde
Maxinet vía requests (sin navegador) y refresco del bloque del mes en curso en la pestaña "Clientes en abandono" del
Tablero CP (copia).

Endpoint confirmado a partir del JS real de Maxinet (cp-reporte-clientes-norentas.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/includes/reportescp/clientes-norentas-data.php
            body: Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD, NoRentas[]=1..4 (opcional, varias veces)
            respuesta: {"data": [[18 valores], ...]}: las 18 columnas de la tabla de la página. No.Rentas y Dias sin
            rentar llegan como número; el resto como texto.
    Desde/Hasta filtran por la Fecha registro del cliente (Hasta inclusive). Sin NoRentas[] el reporte trae TODOS los
    números de rentas (igual que la página sin casillas marcadas); con NoRentas[] sólo los marcados (4 = "4 o más").
    Con las fechas por defecto de la página (1-oct a hoy) el reporte trae el mismo total que muestra la página. Tarda
    ~30 segundos con el mes completo.

Rango de fechas (decidido por el usuario): del primer día del mes al día de la consulta (hora Ciudad de México).
Durante los primeros 3 días del mes se vuelve a escribir también el mes anterior completo.

Qué se escribe: se REFRESCA el bloque del mes. Cada corrida reemplaza, desde la primera fila con Fecha registro >= inicio
del bloque hasta el final, las columnas A:R por lo que entrega Maxinet, ordenado por (Fecha registro, No. Cliente). Como
los días sin rentar y el último movimiento cambian cada día, se reescribe el mes completo. Las filas anteriores (meses
cerrados) no se tocan. La fila 1 se verifica contra las 18 columnas esperadas; si no coincide, la corrida se detiene sin
escribir. Si la pestaña no existe, se crea con esos encabezados y el formato de BITACORA CP.

Tipos de dato: fechas como fecha real (yyyy-mm-dd), No.Rentas y Dias sin rentar como números, teléfonos como número
cuando son sólo dígitos (como en MKT), el resto como texto sin espacios sobrantes (Sin rentar desde es un texto de
rango: "-30 DIAS", "30+ DIAS"...). Todo en modo RAW.

Los logs son públicos: nunca se registran nombres, correos ni teléfonos, sólo conteos y fechas.

Salvaguarda: si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más), la corrida se detiene
sin escribir (FORZAR=1 la omite).

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_TABLERO_CP (Sheet del Tablero CP copia, el mismo de la Bitácora),
    WORKSHEET_CLIENTES_ABANDONO_NAME (nombre o gid de la pestaña; por defecto "Clientes en abandono"),
    NO_RENTAS (opcional: "1,2" filtra por número de rentas; vacío = todas), FECHA_DESDE, FECHA_HASTA, DRY_RUN, FORZAR
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
log = logging.getLogger("maxinet_clientes_abandono_cp")


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

# Mismo nombre y orden que la tabla de cp-reporte-clientes-norentas.php
COLUMNAS = [
    "No. Cliente", "Cliente", "Fecha registro", "No.Rentas", "Fecha ult.renta", "Dias sin rentar", "Sin rentar desde",
    "Suc.ult.renta", "Asesor ult.renta", "Grupo ult.renta", "Primer suc.", "Primer asesor", "Primer grupo renta",
    "ContactTelNo", "TelNo", "MobileNo", "ContactFaxNo", "Email",
]
IDX = {nombre: i for i, nombre in enumerate(COLUMNAS)}
IDX_CLIENTE, IDX_REGISTRO = IDX["No. Cliente"], IDX["Fecha registro"]
FECHAS = [IDX[c] for c in ("Fecha registro", "Fecha ult.renta")]
ENTEROS = [IDX[c] for c in ("No.Rentas", "Dias sin rentar")]
TELEFONOS = [IDX[c] for c in ("ContactTelNo", "TelNo", "MobileNo", "ContactFaxNo")]
FORMATO_FECHA = "yyyy-mm-dd"
ENDPOINT = "includes/reportescp/clientes-norentas-data.php"
FILA_INICIO_DATOS = 2
ULTIMA_COL = gspread.utils.rowcol_to_a1(1, len(COLUMNAS)).rstrip("1")      # "R"
NOMBRE_PESTANA = "Clientes en abandono"
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 900                      # el mes completo tarda ~30 segundos
REINTENTOS = 3
DIAS_MES_ANTERIOR = 3                  # los primeros días del mes se refresca también el mes anterior
FILAS_POR_ESCRITURA = 800
BASE_SERIAL = dt.date(1899, 12, 30)
FECHA_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
NUMERO_RE = re.compile(r"^-?\d+$")
NO_RENTAS_VALIDAS = ("1", "2", "3", "4")


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

    Principal: del primer día del mes de HOY al día de hoy (hora CDMX). Durante los primeros DIAS_MES_ANTERIOR días del
    mes se refresca además el mes anterior completo. FECHA_DESDE/FECHA_HASTA fijan un solo bloque (pruebas y
    recuperaciones)."""
    hoy = dt.datetime.now(ZONA).date()
    hasta = os.environ.get("FECHA_HASTA") or hoy.isoformat()
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


def filtro_no_rentas() -> list[str]:
    """NO_RENTAS="1,2" -> ["1", "2"] (casillas de 'Número de rentas' de la página; 4 = '4 o más'). Vacío = todas.
    Un valor fuera de 1 a 4 detiene la corrida."""
    crudo = (os.environ.get("NO_RENTAS") or "").strip().strip("\"'")
    valores = [v.strip() for v in crudo.split(",") if v.strip()]
    malos = [v for v in valores if v not in NO_RENTAS_VALIDAS]
    if malos:
        raise RuntimeError(f"NO_RENTAS sólo acepta valores de 1 a 4 separados por coma (llegaron {len(malos)} no válidos).")
    return sorted(set(valores))


def descargar_clientes(session: requests.Session, desde: str, hasta: str) -> list[list]:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    datos = {"Desde": desde, "Hasta": hasta}
    rentas = filtro_no_rentas()
    if rentas:
        datos["NoRentas[]"] = rentas
    resp = session.post(f"{base_url}/{ENDPOINT}", data=datos, timeout=TIMEOUT_SEG)
    cuerpo = _parse_json_bom(resp)
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("data"), list):
        raise RuntimeError("Maxinet no devolvió la lista 'data' esperada en el reporte de clientes en abandono. No se escribió nada en el Sheet.")
    filas = normalizar_filas(cuerpo["data"])
    log.info("Datos descargados de Maxinet: %d clientes (Desde=%s, Hasta=%s)", len(filas), desde, hasta)
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


def normalizar_filas(filas: list[list]) -> list[list]:
    """Deja cada fila con exactamente las 18 columnas de COLUMNAS, tipadas y sin espacios sobrantes, ordenadas por
    (Fecha registro, No. Cliente) y sin clientes repetidos. Un ancho distinto, fechas o números que no cuadran, o un
    cliente sin Fecha registro detienen la corrida SIN escribir nada."""
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos != {len(COLUMNAS)}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de clientes en abandono: llegaron filas de {sorted(anchos)} columnas y "
            f"se esperan {len(COLUMNAS)}. No se escribió nada en el Sheet; revisar {ENDPOINT} y ajustar COLUMNAS.")
    vistos, salida, repetidos = set(), [], 0
    for f in filas:
        datos = ["" if v is None else str(v).strip() for v in f]
        if not datos[IDX_REGISTRO]:
            raise RuntimeError("Hay clientes sin Fecha registro en el reporte de clientes en abandono. No se escribió nada en el Sheet.")
        if datos[IDX_CLIENTE] in vistos:
            repetidos += 1
            continue
        vistos.add(datos[IDX_CLIENTE])
        fila = list(datos)
        for j in ENTEROS:
            fila[j] = _entero(datos[j], COLUMNAS[j])
        for j in FECHAS:
            if datos[j]:
                fila[j] = _serie(datos[j], COLUMNAS[j])
        for j in TELEFONOS:
            fila[j] = _telefono(datos[j]) if datos[j] else ""
        salida.append(fila)
    if repetidos:
        log.warning("Maxinet repitió %d clientes (mismo No. Cliente); se conserva uno de cada uno", repetidos)
    salida.sort(key=lambda r: (r[IDX_REGISTRO], r[IDX_CLIENTE]))
    return salida


# ---------------------------------------------------------------- Sheet
def _nombre_pestana() -> str:
    return (os.environ.get("WORKSHEET_CLIENTES_ABANDONO_NAME") or "").strip().strip("\"'").strip() or NOMBRE_PESTANA


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
    log.info("La pestaña no existía: se creó con los %d encabezados y el formato de las demás hojas de Maxinet del Tablero", len(COLUMNAS))
    return ws


# Formato de las demás hojas de datos de Maxinet del Tablero (el de BITACORA CP): cuadrícula oculta, fila 1 fija con el
# encabezado en negritas sobre naranja y todo centrado en Calibri 11. Se aplica sólo cuando la pestaña se crea, para no
# pisar los cambios que se le hagan después.
COLOR_ENCABEZADO = {"red": 1, "green": 0.6}
ANCHOS = {"No. Cliente": 100, "Cliente": 300, "Fecha registro": 110, "No.Rentas": 80, "Dias sin rentar": 100, "Email": 260}
ANCHO_POR_DEFECTO = 125
FUENTE = {"fontFamily": "Calibri", "fontSize": 11}


def dar_formato_hoja(worksheet):
    """Deja la pestaña con el formato de las demás hojas de datos de Maxinet del Tablero."""
    n = len(COLUMNAS)
    sid = worksheet.id

    def rango(fila_ini, fila_fin=None):
        r = {"sheetId": sid, "startRowIndex": fila_ini, "startColumnIndex": 0, "endColumnIndex": n}
        if fila_fin is not None:
            r["endRowIndex"] = fila_fin
        return r

    pedidos = [
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenRowCount": 1, "hideGridlines": True}},
            "fields": "gridProperties.frozenRowCount,gridProperties.hideGridlines"}},
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
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_TABLERO_CP"])
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


def dar_formato_fechas(worksheet, fila_ini: int, fila_fin: int):
    """Formato de fecha a las columnas de fecha del bloque (los valores son números de serie)."""
    def pedido(col):
        return {"repeatCell": {
            "range": {"sheetId": worksheet.id, "startRowIndex": fila_ini - 1, "endRowIndex": fila_fin,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": FORMATO_FECHA}}},
            "fields": "userEnteredFormat.numberFormat"}}
    worksheet.spreadsheet.batch_update({"requests": [pedido(j) for j in FECHAS]})


def _fechas_registro_en_hoja(worksheet) -> list:
    """Fecha registro de cada fila de la hoja a partir de la fila 2 (None si la fila está vacía)."""
    col_a1 = gspread.utils.rowcol_to_a1(FILA_INICIO_DATOS, IDX_REGISTRO + 1).rstrip("0123456789")
    col = worksheet.get(f"{col_a1}{FILA_INICIO_DATOS}:{col_a1}{worksheet.row_count}", value_render_option="UNFORMATTED_VALUE")
    return [(_a_serie_hoja(f[0], "Fecha registro") if f and f[0] != "" else None) for f in col]


def refrescar_bloque(worksheet, nuevas: list[list], desde: str) -> dict:
    """Reemplaza, de la primera fila con Fecha registro >= desde hasta el final, el bloque A:R por lo que entrega
    Maxinet (ya ordenado). Las filas anteriores al bloque (meses cerrados) no se tocan."""
    verificar_encabezados(worksheet)
    ini_serie = float((dt.date.fromisoformat(desde) - BASE_SERIAL).days)
    fechas = _fechas_registro_en_hoja(worksheet)
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
        raise RuntimeError(f"Hay {len(anteriores_en_el_bloque)} filas con Fecha registro anterior al {desde} después del "
                           f"inicio del bloque (la pestaña no está ordenada por fecha). No se escribió nada.")
    viejas = max(0, ultima - inicio + 1)

    if viejas >= 30 and len(nuevas) < 0.8 * viejas and not os.environ.get("FORZAR"):
        raise RuntimeError(f"Maxinet trae {len(nuevas)} clientes para el bloque y el Sheet tiene {viejas}: menos del 80%. "
                           f"Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    log.info("Bloque desde %s: filas %d -> %d | nuevas %d", desde, viejas, len(nuevas), max(0, len(nuevas) - viejas))

    fila_ini, fila_fin = inicio, inicio + len(nuevas) - 1
    resumen = {"antes": viejas, "despues": len(nuevas), "nuevas": max(0, len(nuevas) - viejas), "inicio": inicio}
    if not nuevas:
        log.info("Maxinet no trae clientes para el bloque; no se escribió nada.")
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
    log.info("Bloque reescrito: %d clientes en %s (última fila anterior: %d)", len(nuevas), rango, ultima)
    return resumen


def validar_bloque(worksheet, inicio: int, cantidad: int):
    """El bloque escrito debe tener las filas esperadas y la Fecha registro en orden ascendente."""
    if not cantidad:
        return
    fechas = _fechas_registro_en_hoja(worksheet)
    bloque = fechas[inicio - FILA_INICIO_DATOS:inicio - FILA_INICIO_DATOS + cantidad]
    if len(bloque) != cantidad or any(f is None for f in bloque):
        raise RuntimeError(f"Tras escribir, el bloque tiene {sum(f is not None for f in bloque)} filas con Fecha registro y se esperaban {cantidad}.")
    if bloque != sorted(bloque):
        raise RuntimeError("Tras escribir, la Fecha registro del bloque no quedó en orden ascendente.")
    log.info("Validación OK: %d filas del bloque con Fecha registro en orden", cantidad)


def main():
    try:
        session = login_maxinet()
        filas, desde = [], None
        for d, h in bloques_a_refrescar():
            filas += descargar_clientes(session, d, h)
            desde = desde or d
        filas.sort(key=lambda r: (r[IDX_REGISTRO], r[IDX_CLIENTE]))
        worksheet = conectar_sheet()
        if worksheet is None:                               # DRY_RUN y la pestaña aún no existe
            log.info("DRY_RUN: %d filas desde %s listas para escribir.", len(filas), desde)
            return
        r = refrescar_bloque(worksheet, filas, desde)
        if not os.environ.get("DRY_RUN"):
            validar_bloque(worksheet, r["inicio"], r["despues"])
        log.info("Automatización completada con éxito (bloque de %d clientes desde %s)", r["despues"], desde)
    except Exception:
        log.exception("Error en la automatización de clientes en abandono CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
