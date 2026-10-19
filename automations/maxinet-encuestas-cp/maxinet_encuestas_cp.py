"""
Automatización diaria: login + lectura del reporte "Encuestas de Satisfacción CP"
desde Maxinet vía requests (sin navegador) y agregado incremental de las encuestas
nuevas debajo del último registro de la pestaña "ENCUESTAS" del Sheet "Base"
(copia de "h encuestas").

Endpoint confirmado a partir del HTML/JS reales de Maxinet
(mk-reporte-encuestas-satisfaccion-cp.php):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/includes/encuestasCP/esatisfaccion2026_data.php
            body: Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD, criterio=FechaRespuesta,
            NoCliente="" (el filtro por cliente va deshabilitado).
            respuesta: {"data_ui": [[...], ...]} (a diferencia de otros reportes
            la lista NO viene bajo "data"). Cada fila trae una columna de
            acciones (lupa de detalle) al inicio y dos celdas con HTML: el nombre
            del cliente va dentro de un enlace; se limpia el HTML.

Columnas: se relacionan POR NOMBRE. Los encabezados de Maxinet salen de la tabla
de la página (se ignoran los comentarios HTML) y los de la hoja, de su fila 1. Se
requieren las 24 columnas de COLUMNAS (hoja C:Z). Si Maxinet cambia el orden, la
hoja se llena igual; si agrega columnas nuevas se ignoran (se avisa en el log); si
falta alguna de las 24 o las columnas de la hoja dejan de ser contiguas, la corrida
se detiene SIN escribir. Las columnas A (PERIODO) y B (RECLASIFICACION) son
FÓRMULAS y no se tocan; se verifica que existan en las filas escritas y, si falta
alguna, se copian desde la última fila previa (igual que el formato de C:Z).

Rango de fechas (decidido por el usuario): el mes corriente, igual que el
formulario por defecto: Desde = primer día del mes, Hasta = hoy (hora CDMX). Los
primeros 3 días del mes se incluye también el mes anterior. Cada corrida lee todo
el periodo y agrega sólo las encuestas que todavía no están en el Sheet.

Orden: el Sheet va ordenado por Fecha resp. ascendente y, dentro de cada día, en
el mismo orden en que las entrega Maxinet (confirmado contra el archivo de Nuvia,
108 de 108 días). Las encuestas nuevas se agregan así. Las que llegan con fecha
anterior al último registro se agregan al final y se avisa en el log.

Clave de una encuesta: (Fecha resp., Reserva); la Reserva sola se repite alguna
vez. Para las reservas con "$" se usa además (Fecha resp., Placa, Cliente), que atrapa
registros ya presentes cuyo ID quedó dañado por el formato del Sheet (ej. "$349357C"
guardado como 349357); no se usa para las demás porque dos encuestas distintas del
mismo cliente, placa y día son legítimas. Los registros ya pegados NUNCA se modifican (el Sheet guarda la foto
del momento: por ejemplo "Enc. Respondidas" cambia después en Maxinet).

IDs: los que empiezan con "$" se escriben como texto (ver ADR 0007); los numéricos
sin prefijo se escriben como número, igual que en el resto del Sheet.

NUNCA se usa append_rows(): la fila destino se calcula (última fila con Fecha + 1)
y se escribe con update(). Si hace falta se agregan filas a la hoja.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet "Base"),
    WORKSHEET_ENCUESTAS_NAME (por defecto "ENCUESTAS"),
    FECHA_DESDE, FECHA_HASTA, DRY_RUN (opcionales)
"""

import os
import re
import sys
import json
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
log = logging.getLogger("maxinet_encuestas_cp")

PAGINA = "mk-reporte-encuestas-satisfaccion-cp.php"
ENDPOINT = "includes/encuestasCP/esatisfaccion2026_data.php"
# Columnas requeridas, en el orden actual de la hoja (C:Z)
COLUMNAS = [
    "Fecha resp.", "Categoría", "Reserva", "Placa", "Tipo cliente", "No. Cliente", "Cliente",
    "Sucursal", "Asesor", "Enc. Respondidas", "Enc. Negativas", "Motivo de elegirnos",
    "Otro motivo", "Comparación", "Calificación (NPS)", "Comentario (NPS)",
    "¿Qué podríamos mejorar?", "Teléfono contacto", "Correo Contacto", "PUDate", "ReturnDate",
    "Tipo", "Tipo encuesta", "Número / correo envío",
]
C_FECHA, C_RESERVA, C_PLACA, C_CLIENTE = "Fecha resp.", "Reserva", "Placa", "Cliente"
FILA_ENCABEZADOS = 1
FILA_INICIO_DATOS = 2
DIAS_MES_ANTERIOR = 3
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BASE_SERIAL = dt.date(1899, 12, 30)
COL_FORMULAS = ("PERIODO", "RECLASIFICACION")


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
        raise


def _nueva_sesion() -> requests.Session:
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


def rango_fechas() -> tuple[str, str]:
    """Mes corriente: del primer día del mes a hoy (CDMX), o el override de entorno. Los primeros
    DIAS_MES_ANTERIOR días del mes se arranca desde el mes anterior."""
    hoy = dt.datetime.now(ZONA).date()
    hasta = os.environ.get("FECHA_HASTA") or hoy.isoformat()
    h = dt.date.fromisoformat(hasta)
    inicio = h.replace(day=1)
    if h.day <= DIAS_MES_ANTERIOR:
        inicio = (inicio - dt.timedelta(days=1)).replace(day=1)
    return os.environ.get("FECHA_DESDE") or inicio.isoformat(), hasta


def encabezados_pagina(html: str) -> list[str]:
    """Encabezados de la tabla principal (sin comentarios HTML ni etiquetas)."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    thead = html[html.find("<thead"):html.find("</thead>")]
    return [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<th[^>]*>(.*?)</th>", thead, flags=re.S)]


def _limpiar(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return re.sub(r"<[^>]+>", "", v).strip()
    return v


def normalizar_filas(filas: list[list], encabezados: list[str]) -> list[dict]:
    """Filas como dict {nombre de columna: valor limpio}. La primera columna de Maxinet es la de
    acciones (encabezado vacío). Valida que el ancho coincida con los encabezados y que estén las
    24 columnas requeridas; las columnas extra se ignoran."""
    if len(encabezados) < 2 or encabezados[0] != "":
        raise RuntimeError(f"La tabla de Maxinet cambió de estructura: encabezados {encabezados[:3]}... "
                           f"No se escribió nada en el Sheet.")
    nombres = encabezados[1:]
    faltan = [c for c in COLUMNAS if c not in nombres]
    if faltan:
        raise RuntimeError(f"Maxinet ya no entrega estas columnas: {faltan}. No se escribió nada en el Sheet.")
    extra = [n for n in nombres if n not in COLUMNAS]
    if extra:
        log.warning("Maxinet trae columnas que la hoja no usa y se ignoran: %s", extra)
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos != {len(encabezados)}:
        raise RuntimeError(f"Maxinet devolvió filas de {sorted(anchos)} columnas y la tabla tiene {len(encabezados)} "
                           f"encabezados. No se escribió nada en el Sheet.")
    out = []
    for f in filas:
        d = {nombres[j]: _limpiar(v) for j, v in enumerate(f[1:])}
        if not FECHA_RE.match(str(d[C_FECHA])) or not str(d[C_RESERVA]):
            raise RuntimeError(f"Las columnas de Maxinet no cuadran ({C_FECHA}={str(d[C_FECHA])[:30]!r}, "
                               f"{C_RESERVA}={str(d[C_RESERVA])[:30]!r}). No se escribió nada en el Sheet.")
        out.append(d)
    return out


def descargar_encuestas(desde: str, hasta: str) -> list[dict]:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    html = session.get(f"{base_url}/{PAGINA}", timeout=TIMEOUT_SEG).content.decode("utf-8", "replace")
    encabezados = encabezados_pagina(html)
    resp = session.post(f"{base_url}/{ENDPOINT}", data={"Desde": desde, "Hasta": hasta,
                                                        "criterio": "FechaRespuesta", "NoCliente": ""}, timeout=TIMEOUT_SEG)
    payload = _parse_json_bom(resp)
    datos = payload.get("data_ui", payload.get("data"))
    if datos is None:
        raise RuntimeError(f"La respuesta de Maxinet no trae la lista de encuestas (claves: {list(payload)[:5]}). "
                           f"No se escribió nada en el Sheet.")
    filas = normalizar_filas(datos, encabezados)
    log.info("Datos descargados de Maxinet: %d encuestas (Desde=%s, Hasta=%s)", len(filas), desde, hasta)
    return filas


# ------------------------------------------------------------------ Sheet
def _norm_id(v) -> str:
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return re.sub(r"[#$,.\s]", "", str(v)).lower()


def _celda(v):
    """'=', '+', '@' y '$' al inicio se fuerzan a texto (fórmula/moneda dañarían el dato)."""
    if isinstance(v, str) and v.startswith(("=", "+", "@", "$")):
        return "'" + v
    return v


def _fecha_hoja(v) -> str:
    if isinstance(v, (int, float)) and v:
        return (BASE_SERIAL + dt.timedelta(days=int(v))).isoformat()
    return str(v).strip()


def _col(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n).rstrip("1")


def conectar_sheet():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_CLIENTES_NUEVOS"])
    nombre = (os.environ.get("WORKSHEET_ENCUESTAS_NAME") or "").strip().strip("\"'").strip() or "ENCUESTAS"
    return sh.worksheet(nombre)


def mapear_columnas(ws) -> dict:
    """Posición (1-indexada) de cada columna requerida según el encabezado de la hoja. Deben quedar
    contiguas, para no pisar columnas con fórmulas."""
    enc = [h.strip() for h in ws.row_values(FILA_ENCABEZADOS)]
    try:
        pos = {c: enc.index(c) + 1 for c in COLUMNAS}
    except ValueError as e:
        raise RuntimeError(f"Falta un encabezado en la hoja: {e}. No se escribió nada.") from e
    ini, fin = min(pos.values()), max(pos.values())
    if fin - ini + 1 != len(COLUMNAS):
        raise RuntimeError(f"Las columnas de la hoja no son contiguas (de {_col(ini)} a {_col(fin)} hay "
                           f"{fin - ini + 1} y se esperan {len(COLUMNAS)}). No se escribió nada.")
    orden = [enc[j - 1] for j in range(ini, fin + 1)]
    return {"ini": ini, "fin": fin, "orden": orden, "enc": enc}


def leer_existentes(ws, mp: dict, ultima: int, desde: str):
    """Claves de las encuestas ya registradas del periodo consultado y la fecha del último registro."""
    primera = max(FILA_INICIO_DATOS, ultima - 3000)
    filas = ws.get(f"{_col(mp['ini'])}{primera}:{_col(mp['fin'])}{ultima}", value_render_option="UNFORMATTED_VALUE")
    idx = {n: i for i, n in enumerate(mp["orden"])}
    claves = set()
    for f in filas:
        f = list(f) + [""] * (len(mp["orden"]) - len(f))
        fecha = _fecha_hoja(f[idx[C_FECHA]])
        if fecha < desde:
            continue
        claves.add(("res", fecha, _norm_id(f[idx[C_RESERVA]])))
        claves.add(("fp", fecha, str(f[idx[C_PLACA]]).strip().upper(), str(f[idx[C_CLIENTE]]).strip().lower()))
    ult = _fecha_hoja(((list(filas[-1]) + [""] * len(mp["orden"]))[idx[C_FECHA]])) if filas else ""
    return claves, ult


def agregar_encuestas(ws, filas_mx: list[dict], desde: str) -> int:
    mp = mapear_columnas(ws)
    c_fecha = mp["ini"] + mp["orden"].index(C_FECHA)
    col = ws.col_values(c_fecha)
    ultima = max((i for i, v in enumerate(col, start=1) if i >= FILA_INICIO_DATOS and str(v).strip()),
                 default=FILA_INICIO_DATOS - 1)
    claves, ult_fecha = leer_existentes(ws, mp, ultima, desde) if ultima >= FILA_INICIO_DATOS else (set(), "")

    nuevas, ya, vistos = [], 0, set()
    for d in filas_mx:
        fecha = d[C_FECHA]
        k1 = ("res", fecha, _norm_id(d[C_RESERVA]))
        if k1 in vistos:                               # repetida dentro del propio reporte
            continue
        vistos.add(k1)
        existe = k1 in claves
        # Respaldo: una Reserva con "$" pudo quedar dañada en el Sheet (ej. 349357 por "$349357C"); se
        # reconoce por fecha + placa + cliente. Sólo para esas reservas: dos encuestas distintas del mismo
        # cliente, placa y día son legítimas.
        if not existe and str(d[C_RESERVA]).startswith("$"):
            existe = ("fp", fecha, str(d[C_PLACA]).strip().upper(), str(d[C_CLIENTE]).strip().lower()) in claves
        if existe:
            ya += 1
            continue
        nuevas.append(d)
    if ya:
        log.info("Encuestas omitidas por ya existir en el Sheet: %d", ya)
    if not nuevas:
        log.info("No hay encuestas nuevas que agregar.")
        return 0

    tarde = sum(1 for d in nuevas if ult_fecha and d[C_FECHA] < ult_fecha)
    if tarde:
        log.warning("Encuestas con fecha anterior al último registro (%s): %d; se agregan al final.", ult_fecha, tarde)
    # Fecha ascendente; dentro de cada día se conserva el orden de Maxinet (sort estable)
    nuevas = sorted(nuevas, key=lambda d: d[C_FECHA])
    valores = [[_celda(d[n]) if n in d else "" for n in mp["orden"]] for d in nuevas]
    fila_ini, fila_fin = ultima + 1, ultima + len(valores)
    rango = f"{_col(mp['ini'])}{fila_ini}:{_col(mp['fin'])}{fila_fin}"
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se agregarían %d encuestas en %s (no se escribió nada). Primera: %s | Última: %s",
                 len(valores), rango, nuevas[0][C_FECHA], nuevas[-1][C_FECHA])
        return 0
    if fila_fin > ws.row_count:
        ws.add_rows(fila_fin - ws.row_count + 100)
        log.info("Se agregaron filas a la hoja (ahora %d).", ws.row_count)
    ws.update(range_name=rango, values=valores, value_input_option="USER_ENTERED")
    log.info("Encuestas nuevas agregadas: %d en %s (última fila previa: %d)", len(valores), rango, ultima)
    asegurar_formulas_y_formato(ws, mp, fila_ini, fila_fin, ultima)
    return len(valores)


def asegurar_formulas_y_formato(ws, mp, fila_ini, fila_fin, fila_modelo):
    """Copia el formato de las columnas de datos y las fórmulas de PERIODO/RECLASIFICACION desde la última
    fila previa, sólo donde falten."""
    sid = ws.id

    def rango(c1, c2, r1, r2):
        return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2, "startColumnIndex": c1 - 1, "endColumnIndex": c2}

    pedidos = [{"copyPaste": {"source": rango(mp["ini"], mp["fin"], fila_modelo, fila_modelo),
                               "destination": rango(mp["ini"], mp["fin"], fila_ini, fila_fin), "pasteType": "PASTE_FORMAT"}}]
    for nombre in COL_FORMULAS:
        if nombre not in mp["enc"]:
            continue
        c = mp["enc"].index(nombre) + 1
        letra = _col(c)
        actuales = ws.get(f"{letra}{fila_ini}:{letra}{fila_fin}", value_render_option="FORMULA")
        faltan = [fila_ini + i for i in range(fila_fin - fila_ini + 1)
                  if i >= len(actuales) or not actuales[i] or not str(actuales[i][0]).startswith("=")]
        for fila in faltan:
            pedidos.append({"copyPaste": {"source": rango(c, c, fila_modelo, fila_modelo),
                                          "destination": rango(c, c, fila, fila), "pasteType": "PASTE_FORMULA"}})
        if faltan:
            log.info("Fórmula %s: se copió a %d filas que no la tenían.", nombre, len(faltan))
    ws.spreadsheet.batch_update({"requests": pedidos})


def validar_sin_repetidos(ws, mp):
    c_f, c_r = mp["ini"] + mp["orden"].index(C_FECHA), mp["ini"] + mp["orden"].index(C_RESERVA)
    ultima = len(ws.col_values(c_f))
    fechas = ws.get(f"{_col(c_f)}{FILA_INICIO_DATOS}:{_col(c_f)}{ultima}", value_render_option="UNFORMATTED_VALUE")
    res = ws.get(f"{_col(c_r)}{FILA_INICIO_DATOS}:{_col(c_r)}{ultima}", value_render_option="UNFORMATTED_VALUE")
    vistos, dups = set(), set()
    for f, r in zip(fechas, res):
        if f and r:
            k = (_fecha_hoja(f[0]), _norm_id(r[0]))
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Encuesta repetida (fecha, reserva) en el Sheet ({len(dups)}): {sorted(dups)[:5]}")
    log.info("Validación OK: sin encuestas repetidas en el Sheet")


def main():
    try:
        desde, hasta = rango_fechas()
        filas = descargar_encuestas(desde, hasta)
        ws = conectar_sheet()
        n = agregar_encuestas(ws, filas, desde)
        if n:
            validar_sin_repetidos(ws, mapear_columnas(ws))
        log.info("Automatización completada con éxito (%d encuestas nuevas)", n)
    except Exception:
        log.exception("Error en la automatización de Encuestas CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
