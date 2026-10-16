"""
Automatización diaria: login + lectura del reporte "Entregas Diarias mensual
CP" desde Maxinet vía requests (sin navegador) y agregado incremental de las
entregas nuevas debajo del último registro de la pestaña "ENTREGAS" del Sheet
"Base" (copia de "h encuestas").

Endpoint confirmado a partir del JS real de Maxinet
(cp-reporte-entregas-diarias-mensual.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/entregasDiariasCPMensual.php
            body: FechaDesde=YYYY-MM-DD, FechaHasta=YYYY-MM-DD, Sucursal=""
            (vacío = todas). FechaHasta es inclusive.
            respuesta: {"data": [[18 valores], ...]}: las 16 columnas de la
            pestaña (Fecha ... Gas. Recepción) más "JOB Entrega" y "JOB
            Recepción", que se ignoran a propósito.

Rango de fechas (decidido por el usuario): del primer día del mes hasta AYER
(hora Ciudad de México). Si hoy es día 1, "ayer" cae en el mes anterior y el
rango es ese mes completo. IMPORTANTE: el rango NO es sólo una cuestión de
velocidad. El campo "Cumpleaños" depende de él: Maxinet sólo trae la fecha de
nacimiento cuando el cumpleaños cae en el periodo consultado (con el rango del
1 al 14 de octubre devuelve 63 valores, los mismos que pegó Nuvia; con enero a
octubre devuelve ~13,000). Un rango más ancho que el mes llenaría esa columna
con datos que el proceso manual nunca tuvo.

Estructura de la pestaña (confirmada contra el Sheet real y el original de
Nuvia):
    - A:P (16 columnas, mismos nombres que el reporte) son los datos; van
      ordenados estrictamente por Fecha y Hr.Entrega (cero quiebres en el
      archivo de Nuvia).
    - Q:X (MES, MES, AÑO, ENTREGAS, RECEPCION, reclasificado, ENTREGAS, NOMINA)
      son FÓRMULAS pre-arrastradas hasta la fila ~65,000: NO se tocan. Tras
      pegar se verifica que existan en las filas escritas y, si falta alguna,
      se copia desde la última fila previa. Los formatos de A:P también se
      copian de la última fila previa.

Qué se agrega: sólo lo posterior a lo ya registrado. Una fila es nueva si su
(Fecha, Hr.Entrega) es MAYOR que la del último registro del Sheet, o IGUAL y
no está ya en el Sheet. Así el orden cronológico se conserva y las filas ya
pegadas NUNCA se modifican (igual que el proceso manual, el Sheet guarda la
foto del momento: No. Rentas, estatus y placa cambian después en Maxinet).
Las entregas anteriores al último registro que no aparezcan en el Sheet
("rezagadas") NO se agregan, para no romper el orden; se avisan en el log.

Filas nuevas: se calcula la fila exacta (última fila con Fecha + 1) y se
escribe con update(); NUNCA con append_rows() (la hoja tiene fórmulas y
formato muy por debajo del último dato). Al final se valida que no haya
Reservas repetidas en el Sheet.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet "Base"),
    WORKSHEET_ENTREGAS_NAME (por defecto "ENTREGAS"),
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
log = logging.getLogger("maxinet_entregas_cp")

# Orden confirmado en el HTML real de cp-reporte-entregas-diarias-mensual.php
COLUMNAS = [
    "Fecha", "Hr.Entrega", "# Cliente", "Cliente", "Sucursal", "Asesor",
    "No. Rentas", "Cumpleaños", "Reserva", "Placa", "Grupo", "Entrega Dom.",
    "Recolección", "Estatus", "Gas. Entrega", "Gas. Recepción",
]
IDX_FECHA, IDX_HORA, IDX_CLIENTE, IDX_NOMBRE, IDX_RESERVA, IDX_PLACA = 0, 1, 2, 3, 8, 9
COLUMNAS_EXTRA_IGNORADAS = 2           # JOB Entrega, JOB Recepción
ANCHOS_VALIDOS = (len(COLUMNAS), len(COLUMNAS) + COLUMNAS_EXTRA_IGNORADAS)
COL_INICIO, COL_FIN = "A", "P"
COL_FORMULAS = range(17, 25)           # Q:X (1-indexado)
FILA_INICIO_DATOS = 2
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180                      # el reporte mensual tarda ~20 s
REINTENTOS = 5
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HORA_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
BASE_SERIAL = dt.date(1899, 12, 30)


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
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


def rango_fechas() -> tuple[str, str]:
    """Del primer día del mes de 'ayer' hasta ayer (hora CDMX), o el override de entorno."""
    ayer = dt.datetime.now(ZONA).date() - dt.timedelta(days=1)
    hasta = os.environ.get("FECHA_HASTA") or ayer.isoformat()
    desde = os.environ.get("FECHA_DESDE") or dt.date.fromisoformat(hasta).replace(day=1).isoformat()
    return desde, hasta


def normalizar_filas(filas: list[list]) -> list[list]:
    """Deja cada fila con exactamente las 16 columnas de COLUMNAS (texto sin
    espacios sobrantes, nulos como ""). Acepta 18 columnas (16 + JOB Entrega y
    JOB Recepción, que se descartan) o 16. Cualquier otro ancho, o columnas que
    no cuadren (Fecha sin forma de fecha, hora sin forma de hora, reserva o
    sucursal vacías), detienen la corrida SIN escribir nada."""
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos - set(ANCHOS_VALIDOS) or len(anchos) > 1:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de entregas: llegaron filas de {sorted(anchos)} columnas y se "
            f"esperan {ANCHOS_VALIDOS[0]} o {ANCHOS_VALIDOS[1]} (con JOB Entrega y JOB Recepción al final). "
            f"No se escribió nada en el Sheet; revisar json/entregasDiariasCPMensual.php y ajustar COLUMNAS."
        )
    out = []
    for f in filas:
        fila = [("" if v is None else (v.strip() if isinstance(v, str) else v)) for v in f[:len(COLUMNAS)]]
        if (not FECHA_RE.match(str(fila[IDX_FECHA])) or not HORA_RE.match(str(fila[IDX_HORA]))
                or not str(fila[IDX_RESERVA]) or not str(fila[4])):
            raise RuntimeError(
                f"Las columnas del reporte de entregas no cuadran (Fecha={str(fila[IDX_FECHA])[:30]!r}, "
                f"Hr.Entrega={str(fila[IDX_HORA])[:30]!r}, Reserva={str(fila[IDX_RESERVA])[:30]!r}). "
                f"No se escribió nada en el Sheet."
            )
        out.append(fila)
    return out


def descargar_entregas(desde: str, hasta: str) -> list[list]:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    resp = session.post(
        f"{base_url}/json/entregasDiariasCPMensual.php",
        data={"FechaDesde": desde, "FechaHasta": hasta, "Sucursal": ""},
        timeout=TIMEOUT_SEG,
    )
    filas = normalizar_filas(_parse_json_bom(resp)["data"])
    log.info("Datos descargados de Maxinet: %d entregas (Desde=%s, Hasta=%s)", len(filas), desde, hasta)
    return filas


# ------------------------------------------------------------------ Sheet
def conectar_sheet():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_CLIENTES_NUEVOS"])
    nombre = (os.environ.get("WORKSHEET_ENTREGAS_NAME") or "").strip().strip("\"'").strip() or "ENTREGAS"
    return sh.worksheet(nombre)


def _fecha_hora_hoja(fila: list) -> tuple[str, str]:
    """(Fecha ISO, 'HH:MM:SS') de una fila leída con UNFORMATTED_VALUE (números de serie)."""
    f, h = (list(fila) + ["", ""])[:2]
    if isinstance(f, (int, float)):
        f = (BASE_SERIAL + dt.timedelta(days=int(f))).isoformat()
    if isinstance(h, (int, float)):
        seg = round(h * 86400)
        h = f"{seg // 3600:02d}:{(seg % 3600) // 60:02d}:{seg % 60:02d}"
    return str(f).strip(), _hora(str(h).strip())


def _hora(h: str) -> str:
    partes = h.split(":")
    if len(partes) == 2:
        partes.append("00")
    return ":".join(p.zfill(2) for p in partes) if len(partes) == 3 else h


def _norm_id(v) -> str:
    """Compara IDs aunque Sheets haya convertido '$350588' en número."""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return re.sub(r"[#$,.\s]", "", str(v)).lower()


def _celda(valor):
    """Valor listo para USER_ENTERED: '=', '+', '@' y '$' al inicio se fuerzan a texto
    (Sheets los interpretaría como fórmula o moneda y dañaría el ID)."""
    if isinstance(valor, str) and valor.startswith(("=", "+", "@", "$")):
        return "'" + valor
    return valor


def _llaves(fila: list) -> list[tuple]:
    f, h = _fecha_hora_hoja(fila)
    return [("res", _norm_id(fila[IDX_RESERVA])), ("placa", f, h, str(fila[IDX_PLACA]).strip()),
            ("cli", f, h, _norm_id(fila[IDX_CLIENTE]), str(fila[IDX_NOMBRE]).strip().lower())]


def agregar_entregas(worksheet, filas_mx: list[list], desde: str) -> int:
    col_a = worksheet.col_values(1)
    ultima_fila = max((i for i, v in enumerate(col_a, start=1) if i >= FILA_INICIO_DATOS and str(v).strip()),
                      default=FILA_INICIO_DATOS - 1)
    if ultima_fila < FILA_INICIO_DATOS:
        raise RuntimeError("La pestaña no tiene datos; no se puede determinar el último registro.")
    ult = worksheet.get(f"{COL_INICIO}{ultima_fila}:{COL_FIN}{ultima_fila}", value_render_option="UNFORMATTED_VALUE")[0]
    ult_fecha, ult_hora = _fecha_hora_hoja(ult)
    log.info("Último registro del Sheet: fila %d, %s %s", ultima_fila, ult_fecha, ult_hora)

    # Filas ya registradas del periodo consultado (para empates y rezagadas)
    existentes = set()
    primera = max(FILA_INICIO_DATOS, ultima_fila - 5000)
    bloque = worksheet.get(f"{COL_INICIO}{primera}:{COL_FIN}{ultima_fila}", value_render_option="UNFORMATTED_VALUE")
    for fila in bloque:
        fila = list(fila) + [""] * (len(COLUMNAS) - len(fila))
        if _fecha_hora_hoja(fila)[0] >= desde:
            existentes.update(_llaves(fila))

    nuevas, rezagadas = [], []
    for fila in filas_mx:
        clave = (fila[IDX_FECHA], _hora(str(fila[IDX_HORA])))
        ya = any(k in existentes for k in _llaves(fila))
        if clave > (ult_fecha, ult_hora):
            nuevas.append(fila)
        elif clave == (ult_fecha, ult_hora) and not ya:
            nuevas.append(fila)
        elif clave < (ult_fecha, ult_hora) and not ya:
            rezagadas.append(fila)
    if rezagadas:
        log.warning("Entregas anteriores al último registro que no están en el Sheet y NO se agregan "
                    "para no romper el orden: %d (ej. %s)", len(rezagadas),
                    [(r[IDX_FECHA], r[IDX_HORA], r[IDX_RESERVA]) for r in rezagadas[:3]])
    if not nuevas:
        log.info("No hay entregas nuevas que agregar.")
        return 0

    nuevas.sort(key=lambda r: (r[IDX_FECHA], _hora(str(r[IDX_HORA])), str(r[IDX_RESERVA])))
    valores = [[_celda(v) for v in fila] for fila in nuevas]
    fila_ini = ultima_fila + 1
    fila_fin = fila_ini + len(valores) - 1
    rango = f"{COL_INICIO}{fila_ini}:{COL_FIN}{fila_fin}"
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se agregarían %d entregas en %s (no se escribió nada). Primera: %s | Última: %s",
                 len(valores), rango, nuevas[0][:3], nuevas[-1][:3])
        return 0
    worksheet.update(range_name=rango, values=valores, value_input_option="USER_ENTERED")
    log.info("Entregas nuevas agregadas: %d en %s (última fila previa: %d)", len(valores), rango, ultima_fila)
    asegurar_formulas_y_formato(worksheet, fila_ini, fila_fin, ultima_fila)
    return len(valores)


def asegurar_formulas_y_formato(worksheet, fila_ini, fila_fin, fila_modelo):
    """Copia el formato de A:P desde la última fila previa y las fórmulas de Q:X
    sólo donde falten (no pisa las que ya existen)."""
    sid = worksheet.id

    def rango(c1, c2, r1, r2):
        return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2, "startColumnIndex": c1 - 1, "endColumnIndex": c2}

    pedidos = [{"copyPaste": {"source": rango(1, 16, fila_modelo, fila_modelo),
                               "destination": rango(1, 16, fila_ini, fila_fin), "pasteType": "PASTE_FORMAT"}}]
    c1, c2 = COL_FORMULAS[0], COL_FORMULAS[-1]
    actuales = worksheet.get(f"{gspread.utils.rowcol_to_a1(fila_ini, c1)}:{gspread.utils.rowcol_to_a1(fila_fin, c2)}",
                             value_render_option="FORMULA")
    for i in range(fila_fin - fila_ini + 1):
        fila = actuales[i] if i < len(actuales) else []
        faltan = [c for j, c in enumerate(COL_FORMULAS) if j >= len(fila) or not str(fila[j]).startswith("=")]
        for c in faltan:
            log.warning("Falta fórmula en fila %d columna %d, se copia desde la fila %d", fila_ini + i, c, fila_modelo)
            pedidos.append({"copyPaste": {"source": rango(c, c, fila_modelo, fila_modelo),
                                          "destination": rango(c, c, fila_ini + i, fila_ini + i), "pasteType": "PASTE_FORMULA"}})
    worksheet.spreadsheet.batch_update({"requests": pedidos})


def validar_sin_repetidos(worksheet):
    """Ninguna Reserva debe repetirse en todo el Sheet; si ocurre, la corrida falla."""
    vistos, dups = set(), set()
    for v in worksheet.col_values(9)[FILA_INICIO_DATOS - 1:]:
        k = _norm_id(v)
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Reserva repetida en el Sheet ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin Reservas repetidas en el Sheet")


def main():
    try:
        desde, hasta = rango_fechas()
        filas = descargar_entregas(desde, hasta)
        worksheet = conectar_sheet()
        n = agregar_entregas(worksheet, filas, desde)
        validar_sin_repetidos(worksheet)
        log.info("Automatización completada con éxito (%d entregas nuevas)", n)
    except Exception:
        log.exception("Error en la automatización de Entregas CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
