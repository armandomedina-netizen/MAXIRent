"""
Automatización diaria: login + lectura del reporte "Prospectos CP" (leads externos) desde Maxinet vía
requests (sin navegador) y refresco del bloque del mes en curso en la pestaña "MKT" del Sheet "Base"
(copia de "h encuestas").

Endpoint confirmado a partir del JS real de Maxinet (mk-reporte-leads-externos.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/includes/comercialCP/cp-leads-externos.php
            body: Estatus=2 (TODO), Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD, permisoEditaCerrado=0
            Desde/Hasta filtran por Fecha Registro y Hasta es inclusive.
            respuesta: {"data": [[42 valores], ...]}: dos columnas de acción en HTML (Detalle / Editar /
            Contactar / Reasignar, que llevan el id del lead) y las 40 columnas de la pestaña MKT.
    Tarda ~2 minutos con el mes completo. NO se llama importleads.php (el botón "Recargar" de la página),
    que escribe en Maxinet.

Rango de fechas (decidido por el usuario): del primer día del mes a AYER (hora Ciudad de México); si hoy es
día 1, "ayer" cae en el mes anterior y el rango es ese mes completo. Durante los primeros 3 días del mes se
vuelve a escribir también el mes anterior, para que sus últimos leads terminen de cerrar. Cada mes se consulta
por separado.

Qué se escribe: se REFRESCA el bloque del mes. Cada corrida reemplaza, desde la primera fila con Fecha Registro
>= inicio del bloque hasta el final, las columnas A:AN por lo que entrega Maxinet, ordenado por (Fecha Registro,
id del lead). Los estatus, cierres y reservas de los leads cambian con los días, por eso se reescribe el mes
completo. Las filas anteriores al bloque (meses cerrados) no se tocan. La fila 1 (encabezados) nunca se toca y
se verifica que coincida con las 40 columnas esperadas; si no coincide, la corrida se detiene sin escribir.

Tipos de dato (mismos que deja Nuvia al pegar la tabla): fechas como fecha y hora reales, No.Intento, Días
Renta, subtotales y garantía como números, Teléfono como número cuando son sólo dígitos, el resto como texto
sin espacios sobrantes. Todo se escribe en modo RAW: lo que capturan los clientes (nombre, comentarios) nunca
se interpreta como fórmula.

Los logs son públicos: nunca se registran nombres, correos, teléfonos ni comentarios, sólo conteos y fechas.

Salvaguarda: si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más), la corrida se
detiene sin escribir (FORZAR=1 la omite).

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet "Base"),
    WORKSHEET_MKT_NAME (nombre o gid de la pestaña; por defecto "MKT"),
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
log = logging.getLogger("maxinet_mkt_leads_cp")


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

# Mismo orden que la tabla de mk-reporte-leads-externos.php y que la fila 1 de la pestaña MKT
COLUMNAS = [
    "Semáforo", "Atendido", "Contactado", "Estatus", "Validación", "Cierre", "Nombre", "Ejecutivo Asignado",
    "Fecha Registro", "Fecha Asignado", "Fecha Atendido", "No.Intento", "Fecha Ult.Intento", "Email", "Teléfono",
    "Base", "Medio Entrada", "Origen", "Anuncio", "Días Renta", "Modelo", "Forma Pago", "Cobertura",
    "Lugar entrega", "Lugar devolución", "Subtotal renta", "Garantía", "Responsable Atendido",
    "Motivo No Contactado", "Motivo No Califica", "Fecha cierre", "Motivo No Cierre", "Motivo Seguimiento",
    "Fecha envío cotización", "Uso Unidad", "No.Cliente", "Reserva", "Subtotal Prohire", "Estatus Reserva",
    "Comentarios",
]
COLUMNAS_ACCION = 2                    # Detalle/Editar/Contactar y Reasignar: HTML, no van al Sheet
ANCHO_MAXINET = COLUMNAS_ACCION + len(COLUMNAS)
IDX = {nombre: i for i, nombre in enumerate(COLUMNAS)}
IDX_REGISTRO = IDX["Fecha Registro"]
FECHAS_SEG = [IDX[c] for c in ("Fecha Registro", "Fecha Asignado", "Fecha Atendido", "Fecha Ult.Intento")]
FECHAS_MIN = [IDX[c] for c in ("Fecha cierre", "Fecha envío cotización")]
ENTEROS = [IDX[c] for c in ("No.Intento", "Días Renta")]
IMPORTES = [IDX[c] for c in ("Subtotal renta", "Garantía", "Subtotal Prohire")]
IDX_TELEFONO = IDX["Teléfono"]
FORMATO_FECHA_SEG, FORMATO_FECHA_MIN = "yyyy-mm-dd h:mm:ss", "yyyy-mm-dd h:mm"
ENDPOINT = "includes/comercialCP/cp-leads-externos.php"
ESTATUS_TODO = "2"
FILA_INICIO_DATOS = 2
ULTIMA_COL = gspread.utils.rowcol_to_a1(1, len(COLUMNAS)).rstrip("1")      # "AN"
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 900                      # el mes completo tarda ~2 minutos
REINTENTOS = 3
DIAS_MES_ANTERIOR = 3                  # los primeros días del mes se refresca también el mes anterior
FILAS_POR_ESCRITURA = 800              # el mes completo (~2,000 x 40) se manda en tandas
BASE_SERIAL = dt.date(1899, 12, 30)
FECHA_HORA_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?: (\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
ID_LEAD_RE = re.compile(r'attrid="(\d+)"|[?&]id=(\d+)', re.I)
NUMERO_RE = re.compile(r"^-?\d+(\.\d+)?$")


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # La respuesta puede traer datos de clientes: sólo se registra su tamaño
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

    Principal: del primer día del mes de 'ayer' a ayer (hora CDMX). Durante los primeros DIAS_MES_ANTERIOR
    días del mes se refresca además el mes anterior completo. FECHA_DESDE/FECHA_HASTA fijan un solo bloque
    (pruebas y recuperaciones)."""
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


def descargar_leads(desde: str, hasta: str) -> list[list]:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    resp = session.post(
        f"{base_url}/{ENDPOINT}",
        data={"Estatus": ESTATUS_TODO, "Desde": desde, "Hasta": hasta, "permisoEditaCerrado": "0"},
        timeout=TIMEOUT_SEG,
    )
    cuerpo = _parse_json_bom(resp)
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("data"), list):
        raise RuntimeError("Maxinet no devolvió la lista 'data' esperada en el reporte de leads. No se escribió nada en el Sheet.")
    filas = normalizar_filas(cuerpo["data"])
    log.info("Datos descargados de Maxinet: %d leads (Desde=%s, Hasta=%s)", len(filas), desde, hasta)
    return filas


# ---------------------------------------------------------------- Conversión de tipos
def _serie(texto: str, columna: str) -> float:
    """'2026-10-01 07:13:54' (o '... 07:13', o sólo la fecha) -> número de serie de Sheets (hora local, sin zona)."""
    m = FECHA_HORA_RE.match(texto)
    if not m:
        raise RuntimeError(f"La columna '{columna}' del reporte de leads ya no trae fechas con la forma esperada "
                           f"({len(texto)} caracteres). No se escribió nada en el Sheet.")
    anio, mes, dia, hh, mm, ss = m.groups()
    dias = (dt.date(int(anio), int(mes), int(dia)) - BASE_SERIAL).days
    return dias + (int(hh or 0) * 3600 + int(mm or 0) * 60 + int(ss or 0)) / 86400


def _numero(texto: str):
    """Entero si el texto es un entero, decimal si trae punto; '$' y ',' se ignoran. Si no es número, queda texto."""
    limpio = re.sub(r"[$,\s]", "", texto)
    if not NUMERO_RE.match(limpio):
        return texto
    return float(limpio) if "." in limpio else int(limpio)


def _telefono(texto: str):
    """Número si son sólo dígitos (como lo deja Nuvia); con prefijo ('p:+52...') o con cero inicial queda texto."""
    if re.fullmatch(r"[1-9]\d{0,14}", texto):
        return int(texto)
    return texto


def id_lead(celda) -> int | None:
    m = ID_LEAD_RE.search(celda or "")
    return int(m[1] or m[2]) if m else None


def normalizar_filas(filas: list[list]) -> list[list]:
    """Deja cada fila con exactamente las 40 columnas de COLUMNAS, tipadas y sin espacios sobrantes, ordenadas
    por (Fecha Registro, id del lead) y sin leads repetidos. Un ancho distinto o fechas que no cuadran detienen
    la corrida SIN escribir nada."""
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos != {ANCHO_MAXINET}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de leads: llegaron filas de {sorted(anchos)} columnas y se esperan "
            f"{ANCHO_MAXINET} ({COLUMNAS_ACCION} de acción y {len(COLUMNAS)} de datos). No se escribió nada en el "
            f"Sheet; revisar {ENDPOINT} y ajustar COLUMNAS.")
    vistos, con_id = set(), []
    repetidos = 0
    for f in filas:
        lid = id_lead(f[0])
        if lid is not None:
            if lid in vistos:
                repetidos += 1
                continue
            vistos.add(lid)
        datos = ["" if v is None else str(v).strip() for v in f[COLUMNAS_ACCION:]]
        fila = list(datos)
        for j in FECHAS_SEG + FECHAS_MIN:
            if datos[j]:
                fila[j] = _serie(datos[j], COLUMNAS[j])
        if not datos[IDX_REGISTRO]:
            raise RuntimeError("Hay leads sin Fecha Registro en el reporte. No se escribió nada en el Sheet.")
        for j in ENTEROS:
            fila[j] = _numero(datos[j]) if datos[j] else ""
        for j in IMPORTES:
            fila[j] = _numero(datos[j]) if datos[j] else ""
        fila[IDX_TELEFONO] = _telefono(datos[IDX_TELEFONO]) if datos[IDX_TELEFONO] else ""
        con_id.append((fila[IDX_REGISTRO], lid if lid is not None else 0, fila))
    if repetidos:
        log.warning("Maxinet repitió %d leads (mismo id); se conserva uno de cada uno", repetidos)
    con_id.sort(key=lambda t: (t[0], t[1]))                  # estable
    return [t[2] for t in con_id]


# ---------------------------------------------------------------- Sheet
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
    nombre = (os.environ.get("WORKSHEET_MKT_NAME") or "").strip().strip("\"'").strip() or "MKT"
    return resolver_pestana(sh, nombre)


def _a_serie_hoja(v) -> float:
    """Fecha Registro de una fila ya escrita (número de serie, o texto con la misma forma que Maxinet)."""
    if isinstance(v, (int, float)):
        return float(v)
    return _serie(str(v).strip(), "Fecha Registro")


def verificar_encabezados(worksheet):
    fila1 = worksheet.get(f"A1:{ULTIMA_COL}1")
    actuales = [str(c).strip() for c in (fila1[0] if fila1 else [])]
    if actuales != COLUMNAS:
        distintas = [i + 1 for i in range(max(len(actuales), len(COLUMNAS)))
                     if (actuales[i] if i < len(actuales) else None) != (COLUMNAS[i] if i < len(COLUMNAS) else None)]
        raise RuntimeError(f"Los encabezados de la pestaña ya no coinciden con las {len(COLUMNAS)} columnas del reporte "
                           f"(difieren las columnas {distintas[:10]}). No se escribió nada.")


def refrescar_bloque(worksheet, nuevas: list[list], desde: str) -> dict:
    """Reemplaza, de la primera fila con Fecha Registro >= desde hasta el final, el bloque A:AN por lo que entrega
    Maxinet (ya ordenado). Las filas anteriores al bloque (meses cerrados) no se tocan."""
    verificar_encabezados(worksheet)
    ini_serie = float((dt.date.fromisoformat(desde) - BASE_SERIAL).days)
    col = worksheet.get(f"{gspread.utils.rowcol_to_a1(FILA_INICIO_DATOS, IDX_REGISTRO + 1)}:"
                        f"{gspread.utils.rowcol_to_a1(worksheet.row_count, IDX_REGISTRO + 1)}",
                        value_render_option="UNFORMATTED_VALUE")
    fechas = [(_a_serie_hoja(f[0]) if f and f[0] != "" else None) for f in col]
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
        raise RuntimeError(f"Hay {len(anteriores_en_el_bloque)} filas con Fecha Registro anterior al {desde} después del "
                           f"inicio del bloque (la pestaña no está ordenada por fecha). No se escribió nada.")
    viejas = max(0, ultima - inicio + 1)

    if viejas >= 30 and len(nuevas) < 0.8 * viejas and not os.environ.get("FORZAR"):
        raise RuntimeError(f"Maxinet trae {len(nuevas)} leads para el bloque y el Sheet tiene {viejas}: menos del 80%. "
                           f"Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    log.info("Bloque desde %s: filas %d -> %d | nuevas %d", desde, viejas, len(nuevas), max(0, len(nuevas) - viejas))

    fila_ini, fila_fin = inicio, inicio + len(nuevas) - 1
    resumen = {"antes": viejas, "despues": len(nuevas), "nuevas": max(0, len(nuevas) - viejas), "inicio": inicio}
    if not nuevas:
        log.info("Maxinet no trae leads para el bloque; no se escribió nada.")
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
    log.info("Bloque reescrito: %d leads en %s (última fila anterior: %d)", len(nuevas), rango, ultima)
    return resumen


def dar_formato_fechas(worksheet, fila_ini: int, fila_fin: int):
    """Formato de fecha y hora a las columnas de fecha del bloque (los valores son números de serie)."""
    def pedido(col, patron):
        return {"repeatCell": {
            "range": {"sheetId": worksheet.id, "startRowIndex": fila_ini - 1, "endRowIndex": fila_fin,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE_TIME", "pattern": patron}}},
            "fields": "userEnteredFormat.numberFormat"}}
    pedidos = [pedido(j, FORMATO_FECHA_SEG) for j in FECHAS_SEG] + [pedido(j, FORMATO_FECHA_MIN) for j in FECHAS_MIN]
    worksheet.spreadsheet.batch_update({"requests": pedidos})


def validar_orden(worksheet, inicio: int, cantidad: int):
    """El bloque escrito debe tener las filas esperadas y la Fecha Registro en orden ascendente."""
    if not cantidad:
        return
    col = worksheet.get(f"{gspread.utils.rowcol_to_a1(inicio, IDX_REGISTRO + 1)}:"
                        f"{gspread.utils.rowcol_to_a1(inicio + cantidad - 1, IDX_REGISTRO + 1)}",
                        value_render_option="UNFORMATTED_VALUE")
    fechas = [_a_serie_hoja(f[0]) for f in col if f and f[0] != ""]
    if len(fechas) != cantidad:
        raise RuntimeError(f"Tras escribir, el bloque tiene {len(fechas)} filas con Fecha Registro y se esperaban {cantidad}.")
    if fechas != sorted(fechas):
        raise RuntimeError("Tras escribir, la Fecha Registro del bloque no quedó en orden ascendente.")
    log.info("Validación OK: %d filas del bloque con Fecha Registro en orden", cantidad)


def main():
    try:
        filas, desde = [], None
        for d, h in bloques_a_refrescar():
            filas += descargar_leads(d, h)
            desde = desde or d
        filas.sort(key=lambda r: r[IDX_REGISTRO])
        worksheet = conectar_sheet()
        r = refrescar_bloque(worksheet, filas, desde)
        if not os.environ.get("DRY_RUN"):
            validar_orden(worksheet, r["inicio"], r["despues"])
        log.info("Automatización completada con éxito (bloque de %d leads desde %s)", r["despues"], desde)
    except Exception:
        log.exception("Error en la automatización de leads MKT CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
