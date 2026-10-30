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

Rango de fechas (decidido por el usuario): del primer día del mes a AYER (hora Ciudad de
México); si hoy es día 1, "ayer" cae en el mes anterior y el rango es ese mes completo.
Durante los primeros 3 días del mes se vuelve a escribir también el mes anterior, para que sus
últimos días cierren con los estatus finales; cada mes se consulta por separado. IMPORTANTE: el
rango no es sólo cuestión de velocidad. El campo "Cumpleaños" depende de él: Maxinet sólo trae la
fecha de nacimiento cuando el cumpleaños cae en el periodo consultado (con el rango del 1 al 14
de octubre devuelve 63 valores, los mismos que pegó Nuvia; con enero a octubre, ~13,000).

Estructura de la pestaña (confirmada contra el Sheet real y el original de Nuvia):
    - A:P (16 columnas, mismos nombres que el reporte) son los datos; van ordenados estrictamente
      por Fecha y Hr.Entrega (cero quiebres en el archivo de Nuvia).
    - Q:X (MES, MES, AÑO, ENTREGAS, RECEPCION, reclasificado, ENTREGAS, NOMINA) son FÓRMULAS
      pre-arrastradas hasta la fila ~65,000: NO se tocan. Si el bloque crece se verifica que existan
      en las filas nuevas y, si falta alguna, se copia desde la última fila previa; el formato de A:P
      también se copia de la última fila previa.

Qué se escribe: se REFRESCA el bloque del mes. Cada corrida reemplaza, desde la primera fila con
Fecha >= inicio del bloque hasta el final, las columnas A:P por lo que entrega Maxinet, ordenado
por (Fecha, Hr.Entrega). Es lo que hace Nuvia al volver a pegar el mes en curso y es necesario:
una entrega se pega como ON HIRE y días después cambia a CHECKED IN o RETURNED, con su gasolina
de recepción; si no se refresca, las recepciones y los indicadores quedan subcontados (el 22-oct
el Sheet tenía 723 entregas del mes en ON HIRE contra 257 en Maxinet, y 1,091 recepciones contra
1,568). También entran en su lugar las entregas que Maxinet registra con retraso. Los meses
cerrados (filas anteriores al bloque) quedan congelados, igual que en el archivo de Nuvia.
Salvaguarda: si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más), la
corrida se detiene sin escribir (FORZAR=1 la omite).

El bloque se escribe de un solo golpe con update(); NUNCA con append_rows() (la hoja tiene fórmulas
y formato muy por debajo del último dato). Al final se valida que no haya Reservas repetidas.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet "Base"),
    WORKSHEET_ENTREGAS_NAME (por defecto "ENTREGAS"),
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
log = logging.getLogger("maxinet_entregas_cp")


def _instalar_reintentos_gspread(cliente=HTTPClient) -> None:
    """Google Sheets limita las lecturas por minuto por usuario y esa cuota la comparten TODAS las automatizaciones que
    usan la misma cuenta de servicio (entre las 8:05 y las 8:30 corren varias a la vez). Un 429 se rechaza antes de
    procesarse, así que reintentar es seguro; los errores 5xx sólo se reintentan en lecturas (GET), para no duplicar una
    escritura. Es la misma regla del sync de LP."""
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
DIAS_MES_ANTERIOR = 3                  # los primeros días del mes se refresca también el mes anterior
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


def bloques_a_refrescar() -> list[tuple[str, str]]:
    """Bloques de fechas (desde, hasta) que se vuelven a escribir en cada corrida, del más antiguo al más reciente.

    Principal: del primer día del mes de 'ayer' a ayer (hora CDMX). Durante los primeros DIAS_MES_ANTERIOR
    días del mes se refresca además el mes anterior completo, para que sus últimos días terminen de cerrar
    con los estatus finales. Cada mes se consulta por separado porque el campo Cumpleaños depende del rango
    de la consulta. FECHA_DESDE/FECHA_HASTA fijan un solo bloque (pruebas y recuperaciones)."""
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
def resolver_pestana(libro, referencia: str):
    """La pestaña del libro por gid (si la referencia es un número) o por nombre. Nuvia renombra pestañas;
    el gid no cambia. Los logs son públicos: si falta, el error sólo dice cuántas pestañas tiene el libro."""
    referencia = str(referencia).strip()
    try:
        return libro.get_worksheet_by_id(int(referencia)) if referencia.isdigit() else libro.worksheet(referencia)
    except gspread.exceptions.WorksheetNotFound:
        raise gspread.exceptions.WorksheetNotFound(
            f"{referencia} (el libro tiene {len(libro.worksheets())} pestañas; si la renombraron, usa su gid en el secret)") from None


def conectar_sheet():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_CLIENTES_NUEVOS"])
    nombre = (os.environ.get("WORKSHEET_ENTREGAS_NAME") or "").strip().strip("\"'").strip() or "ENTREGAS"
    return resolver_pestana(sh, nombre)


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


def _fecha_serie(v) -> str:
    """Fecha ISO de una celda de la columna A (número de serie o texto)."""
    if isinstance(v, (int, float)):
        return (BASE_SERIAL + dt.timedelta(days=int(v))).isoformat()
    return str(v).strip()


def refrescar_bloque(worksheet, filas_mx: list[list], desde: str) -> dict:
    """Reemplaza, de la primera fila con Fecha >= desde hasta el final, el bloque de datos A:P por lo que
    entrega Maxinet (ordenado por Fecha y Hr.Entrega). Así los estatus, las gasolinas y el número de rentas del
    mes en curso se mantienen al día y las entregas que Maxinet registra con retraso entran en su lugar; es lo
    que hace Nuvia al volver a pegar el mes. Las filas anteriores al bloque (meses cerrados) no se tocan y las
    fórmulas de Q:X tampoco."""
    col_a = worksheet.col_values(1)
    ultima = max((i for i, v in enumerate(col_a, start=1) if i >= FILA_INICIO_DATOS and str(v).strip()),
                 default=FILA_INICIO_DATOS - 1)
    if ultima < FILA_INICIO_DATOS:
        raise RuntimeError("La pestaña no tiene datos; no se puede ubicar el bloque a refrescar.")
    fechas = worksheet.get(f"A{FILA_INICIO_DATOS}:A{ultima}", value_render_option="UNFORMATTED_VALUE")
    inicio = ultima + 1
    for i, f in enumerate(fechas):
        if f and _fecha_serie(f[0]) >= desde:
            inicio = FILA_INICIO_DATOS + i
            break
    viejas = worksheet.get(f"A{inicio}:P{ultima}", value_render_option="UNFORMATTED_VALUE") if inicio <= ultima else []
    nuevas = sorted(filas_mx, key=lambda r: (r[IDX_FECHA], _hora(str(r[IDX_HORA]))))     # estable

    # Salvaguarda: una respuesta incompleta de Maxinet no debe vaciar el mes
    if len(viejas) >= 30 and len(nuevas) < 0.8 * len(viejas) and not os.environ.get("FORZAR"):
        raise RuntimeError(f"Maxinet trae {len(nuevas)} entregas para el bloque y el Sheet tiene {len(viejas)}: menos del 80%. "
                           f"Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")

    # Resumen de cambios (por Fecha + Hr.Entrega + Reserva)
    def clave_hoja(r):
        r = list(r) + [""] * (len(COLUMNAS) - len(r))
        f, h = _fecha_hora_hoja(r)
        return (f, h, _norm_id(r[IDX_RESERVA])), str(r[13]).strip()
    ant = dict(clave_hoja(r) for r in viejas)
    act = {(r[IDX_FECHA], _hora(str(r[IDX_HORA])), _norm_id(r[IDX_RESERVA])): str(r[13]).strip() for r in nuevas}
    altas = [k for k in act if k not in ant]
    bajas = [k for k in ant if k not in act]
    cambios_estatus = sum(1 for k in act if k in ant and ant[k] != act[k])
    log.info("Bloque desde %s: filas %d -> %d | altas %d, bajas %d, estatus cambiados %d | ON HIRE %d -> %d",
             desde, len(viejas), len(nuevas), len(altas), len(bajas), cambios_estatus,
             sum(1 for v in ant.values() if v == "ON HIRE"), sum(1 for v in act.values() if v == "ON HIRE"))

    fila_ini, fila_fin = inicio, inicio + len(nuevas) - 1
    rango = f"A{fila_ini}:P{fila_fin}"
    resumen = {"altas": len(altas), "bajas": len(bajas), "estatus": cambios_estatus, "antes": len(viejas), "despues": len(nuevas)}
    if not nuevas:
        log.info("Maxinet no trae entregas para el bloque; no se escribió nada.")
        return resumen
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían %s (%d filas) (no se escribió nada).", rango, len(nuevas))
        return resumen

    valores = [[_celda(v) for v in fila] for fila in nuevas]
    if fila_fin > worksheet.row_count:
        worksheet.add_rows(fila_fin - worksheet.row_count + 100)
    worksheet.update(range_name=rango, values=valores, value_input_option="USER_ENTERED")
    if ultima > fila_fin:                                   # el bloque quedó más corto: limpiar lo que sobra
        worksheet.batch_clear([f"A{fila_fin + 1}:P{ultima}"])
    if fila_fin > ultima:                                   # filas nuevas más allá de las anteriores
        asegurar_formulas_y_formato(worksheet, ultima + 1, fila_fin, ultima)
    log.info("Bloque reescrito: %d entregas en %s (última fila anterior: %d)", len(nuevas), rango, ultima)
    return resumen


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
        filas, desde = [], None
        for d, h in bloques_a_refrescar():
            filas += descargar_entregas(d, h)
            desde = desde or d
        worksheet = conectar_sheet()
        r = refrescar_bloque(worksheet, filas, desde)
        validar_sin_repetidos(worksheet)
        log.info("Automatización completada con éxito (bloque de %d entregas desde %s)", r["despues"], desde)
    except Exception:
        log.exception("Error en la automatización de Entregas CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
