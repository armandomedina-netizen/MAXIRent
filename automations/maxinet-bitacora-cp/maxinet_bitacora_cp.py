"""
Automatización diaria: login + lectura del reporte "Bitácora Entregas / Recolecciones CP" desde Maxinet vía
requests (sin navegador) y refresco del bloque del mes en curso en la pestaña "BITACORA CP" del Sheet del
Tablero CP copia.

Endpoint confirmado a partir del JS real de Maxinet (cp-bitacora-entregas-recolecciones.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/entregasRecoleccionesBitacora.php
            body: Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD, Sucursal="" (vacío = todas)
            Desde/Hasta filtran por Fecha Prom. (fecha promesa) y Hasta es inclusive.
            respuesta: {"data": [[38 valores], ...]}: una columna de acción en HTML (Comentarios) y las 37
            columnas de datos de la pestaña (A:AK).
    Tarda ~1 minuto con el mes completo.

Rango de fechas (decidido por el usuario): del primer día del mes a AYER (hora Ciudad de México); si hoy es
día 1, "ayer" cae en el mes anterior y el rango es ese mes completo. Durante los primeros 3 días del mes se
vuelve a escribir también el mes anterior, para que sus últimos servicios terminen de cerrar. Cada mes se
consulta por separado.

Qué se escribe: se REFRESCA el bloque del mes. Cada corrida reemplaza, desde la primera fila con Fecha Prom. >=
inicio del bloque hasta el final, las columnas A:AK por lo que entrega Maxinet, ordenado por (Fecha Prom., Hora
Prom., Reserva, Tipo Serv.). Los estatus, las fechas y horas reales y los motivos de retraso de un servicio cambian
con los días, por eso se reescribe el mes completo. Las filas anteriores al bloque (meses cerrados) no se tocan.
Las columnas AL:AO (AÑO, MES, Asesor móvil, PERIODO) son fórmulas: se escriben para las filas del bloque, con las
mismas de la copia de Nuvia, y nunca se borran. La fila 1 se verifica contra las 41 columnas esperadas; si no
coincide, la corrida se detiene sin escribir.

Tipos de dato (mismos que deja Nuvia al pegar la tabla): fechas y horas reales (fecha como número entero, hora
como fracción del día), costos y Dif. Dias como números, # Cliente, Reserva y Código Postal como número cuando
son sólo dígitos, el resto como texto sin espacios sobrantes. Todo se escribe en modo RAW (salvo las fórmulas): lo
que capturan clientes y ejecutivos (domicilios, comentarios) nunca se interpreta como fórmula.

Los logs son públicos: nunca se registran nombres, domicilios ni comentarios, sólo conteos y fechas.

Salvaguarda: si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más), la corrida se
detiene sin escribir (FORZAR=1 la omite).

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_TABLERO_CP (Sheet del Tablero CP copia),
    WORKSHEET_BITACORA_NAME (nombre o gid de la pestaña; por defecto "BITACORA CP"),
    FECHA_DESDE, FECHA_HASTA, DRY_RUN, FORZAR (opcionales)
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
log = logging.getLogger("maxinet_bitacora_cp")

# Mismo orden que la tabla de cp-bitacora-entregas-recolecciones.php y que A1:AK1 de la pestaña
COLUMNAS = [
    "Tipo Serv.", "Fecha Prom.", "Hora Prom.", "Fecha Real", "Hora Real", "Fecha GPS", "Hora GPS", "Semáforo",
    "Estatus Serv.", "Tiempo Trans.", "Estatus", "Reserva", "Tipo Cliente", "# Cliente", "Cliente", "Sucursal",
    "ReturnSite", "Asesor", "Asesor móvil", "Placa", "Grupo", "Cumpleaños", "Código Postal", "Costo Ent.Dom",
    "Costo Rec.", "Uber", "Order Ref.", "Dif. Dias", "Delivery Details", "Collection Details", "DefField_Text_13",
    "DefField_Text_14", "DefField_Text_15", "Motivo retraso", "Justificación retraso", "Responsable justificación",
    "Comentarios",
]
COLUMNAS_AUX = ["AÑO", "MES", "Asesor móvil", "PERIODO"]            # AL:AO, fórmulas
ENCABEZADOS = COLUMNAS + COLUMNAS_AUX
COLUMNAS_ACCION = 1                    # "Comentarios" (enlace HTML): no va al Sheet
ANCHO_MAXINET = COLUMNAS_ACCION + len(COLUMNAS)
IDX = {nombre: i for i, nombre in enumerate(COLUMNAS)}
IDX_PROMESA, IDX_HORA_PROMESA, IDX_RESERVA, IDX_TIPO = IDX["Fecha Prom."], IDX["Hora Prom."], IDX["Reserva"], IDX["Tipo Serv."]
FECHAS = [IDX[c] for c in ("Fecha Prom.", "Fecha Real", "Fecha GPS", "Cumpleaños")]
HORAS = [IDX[c] for c in ("Hora Prom.", "Hora Real", "Hora GPS")]
IMPORTES = [IDX[c] for c in ("Costo Ent.Dom", "Costo Rec.", "Uber")]
IDENTIFICADORES = [IDX[c] for c in ("Reserva", "# Cliente", "Código Postal")]   # número si son sólo dígitos
IDX_DIF_DIAS = IDX["Dif. Dias"]
# Formatos de las columnas con tipo (los mismos que ya trae la pestaña y la copia de Nuvia)
FORMATOS = {IDX["Fecha Prom."]: "d/M/yyyy", IDX["Fecha Real"]: "d/M/yyyy", IDX["Fecha GPS"]: "yyyy-mm-dd",
            IDX["Cumpleaños"]: "yyyy-mm-dd", IDX["Hora Prom."]: "h:mm:ss", IDX["Hora Real"]: "h:mm:ss",
            IDX["Hora GPS"]: "h:mm:ss", IDX["Costo Ent.Dom"]: '"$"#,##0.00', IDX["Costo Rec."]: '"$"#,##0.00',
            IDX["Uber"]: '"$"#,##0.00'}
FORMULAS_AUX = [                                                   # una por columna AL:AO, {r} = fila
    '=IF(B{r}="","", YEAR(B{r}))',
    '=IF(B{r}="","",TEXT(B{r},"MMMM"))',
    '=IF(B{r}="","", IF(S{r}="","SIN ASESOR",S{r}))',
    '=IF(B{r}="","",TEXT(B{r},"MMMM YYYY"))',
]
ENDPOINT = "json/entregasRecoleccionesBitacora.php"
FILA_INICIO_DATOS = 2
COL_PROMESA = gspread.utils.rowcol_to_a1(1, IDX_PROMESA + 1).rstrip("1")          # "B"
ULTIMA_COL_DATOS = gspread.utils.rowcol_to_a1(1, len(COLUMNAS)).rstrip("1")       # "AK"
PRIMERA_COL_AUX = gspread.utils.rowcol_to_a1(1, len(COLUMNAS) + 1).rstrip("1")    # "AL"
ULTIMA_COL = gspread.utils.rowcol_to_a1(1, len(ENCABEZADOS)).rstrip("1")          # "AO"
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 900                      # el mes completo tarda ~1 minuto
REINTENTOS = 3
DIAS_MES_ANTERIOR = 3                  # los primeros días del mes se refresca también el mes anterior
FILAS_POR_ESCRITURA = 800
BASE_SERIAL = dt.date(1899, 12, 30)
FECHA_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
HORA_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
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


def descargar_bitacora(desde: str, hasta: str) -> list[list]:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    resp = session.post(f"{base_url}/{ENDPOINT}", data={"Desde": desde, "Hasta": hasta, "Sucursal": ""}, timeout=TIMEOUT_SEG)
    cuerpo = _parse_json_bom(resp)
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("data"), list):
        raise RuntimeError("Maxinet no devolvió la lista 'data' esperada en la bitácora. No se escribió nada en el Sheet.")
    filas = normalizar_filas(cuerpo["data"])
    log.info("Datos descargados de Maxinet: %d servicios (Desde=%s, Hasta=%s)", len(filas), desde, hasta)
    return filas


# ---------------------------------------------------------------- Conversión de tipos
def _fecha(texto: str, columna: str) -> int:
    """'2026-10-01' -> número de serie de Sheets (entero)."""
    m = FECHA_RE.match(texto)
    if not m:
        raise RuntimeError(f"La columna '{columna}' de la bitácora ya no trae fechas con la forma esperada "
                           f"({len(texto)} caracteres). No se escribió nada en el Sheet.")
    return (dt.date(int(m[1]), int(m[2]), int(m[3])) - BASE_SERIAL).days


def _hora(texto: str, columna: str) -> float:
    """'06:00:00' -> fracción del día."""
    m = HORA_RE.match(texto)
    if not m:
        raise RuntimeError(f"La columna '{columna}' de la bitácora ya no trae horas con la forma esperada "
                           f"({len(texto)} caracteres). No se escribió nada en el Sheet.")
    return (int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)) / 86400


def _numero(texto: str):
    """Entero si el valor es entero (aunque traiga '.0000'), decimal si no; '$' y ',' se ignoran; si no es número, texto."""
    limpio = re.sub(r"[$,\s]", "", texto)
    if not NUMERO_RE.match(limpio):
        return texto
    valor = float(limpio)
    return int(valor) if valor == int(valor) else valor


def _identificador(texto: str):
    """Número si son sólo dígitos (como lo deja Nuvia); con '#', '$' o cero inicial queda texto."""
    return int(texto) if re.fullmatch(r"[1-9]\d{0,14}", texto) else texto


def normalizar_filas(filas: list[list]) -> list[list]:
    """Deja cada fila con exactamente las 37 columnas de COLUMNAS, tipadas y sin espacios sobrantes, ordenadas por
    (Fecha Prom., Hora Prom., Reserva, Tipo Serv.). Un ancho distinto, fechas u horas que no cuadran o servicios sin
    Fecha Prom. detienen la corrida SIN escribir nada."""
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos != {ANCHO_MAXINET}:
        raise RuntimeError(
            f"Maxinet cambió el ancho de la bitácora: llegaron filas de {sorted(anchos)} columnas y se esperan "
            f"{ANCHO_MAXINET} ({COLUMNAS_ACCION} de acción y {len(COLUMNAS)} de datos). No se escribió nada en el "
            f"Sheet; revisar {ENDPOINT} y ajustar COLUMNAS.")
    out = []
    for f in filas:
        datos = ["" if v is None else str(v).strip() for v in f[COLUMNAS_ACCION:]]
        if not datos[IDX_PROMESA]:
            raise RuntimeError("Hay servicios sin Fecha Prom. en la bitácora. No se escribió nada en el Sheet.")
        fila = list(datos)
        for j in FECHAS:
            if datos[j]:
                fila[j] = _fecha(datos[j], COLUMNAS[j])
        for j in HORAS:
            if datos[j]:
                fila[j] = _hora(datos[j], COLUMNAS[j])
        for j in IMPORTES + [IDX_DIF_DIAS]:
            if datos[j]:
                fila[j] = _numero(datos[j])
        for j in IDENTIFICADORES:
            if datos[j]:
                fila[j] = _identificador(datos[j])
        out.append(fila)
    out.sort(key=lambda r: (r[IDX_PROMESA], r[IDX_HORA_PROMESA] if r[IDX_HORA_PROMESA] != "" else -1,
                            str(r[IDX_RESERVA]), r[IDX_TIPO]))
    repetidos = len(out) - len({(str(r[IDX_RESERVA]), r[IDX_TIPO]) for r in out})
    if repetidos:
        log.warning("Hay %d servicios con la misma Reserva y Tipo Serv.; se conservan todos", repetidos)
    return out


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
    sh = gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID_TABLERO_CP"])
    nombre = (os.environ.get("WORKSHEET_BITACORA_NAME") or "").strip().strip("\"'").strip() or "BITACORA CP"
    return resolver_pestana(sh, nombre)


def _a_dia_hoja(v) -> int:
    """Fecha Prom. de una fila ya escrita (número de serie, o texto con la misma forma que Maxinet)."""
    if isinstance(v, (int, float)):
        return int(v)
    return _fecha(str(v).strip(), "Fecha Prom.")


def verificar_encabezados(worksheet):
    fila1 = worksheet.get(f"A1:{ULTIMA_COL}1")
    actuales = [str(c).strip() for c in (fila1[0] if fila1 else [])]
    if actuales != ENCABEZADOS:
        distintas = [i + 1 for i in range(max(len(actuales), len(ENCABEZADOS)))
                     if (actuales[i] if i < len(actuales) else None) != (ENCABEZADOS[i] if i < len(ENCABEZADOS) else None)]
        raise RuntimeError(f"Los encabezados de la pestaña ya no coinciden con las {len(ENCABEZADOS)} columnas esperadas "
                           f"(difieren las columnas {distintas[:10]}). No se escribió nada.")


def refrescar_bloque(worksheet, nuevas: list[list], desde: str) -> dict:
    """Reemplaza, de la primera fila con Fecha Prom. >= desde hasta el final, el bloque A:AK por lo que entrega Maxinet
    (ya ordenado) y deja las fórmulas AL:AO en esas filas. Las filas anteriores al bloque (meses cerrados) no se tocan."""
    verificar_encabezados(worksheet)
    ini_serie = (dt.date.fromisoformat(desde) - BASE_SERIAL).days
    col = worksheet.get(f"{COL_PROMESA}{FILA_INICIO_DATOS}:{COL_PROMESA}{worksheet.row_count}", value_render_option="UNFORMATTED_VALUE")
    fechas = [(_a_dia_hoja(f[0]) if f and f[0] != "" else None) for f in col]
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
        raise RuntimeError(f"Hay {len(anteriores_en_el_bloque)} filas con Fecha Prom. anterior al {desde} después del "
                           f"inicio del bloque (la pestaña no está ordenada por fecha). No se escribió nada.")
    viejas = max(0, ultima - inicio + 1)

    if viejas >= 30 and len(nuevas) < 0.8 * viejas and not os.environ.get("FORZAR"):
        raise RuntimeError(f"Maxinet trae {len(nuevas)} servicios para el bloque y el Sheet tiene {viejas}: menos del 80%. "
                           f"Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    log.info("Bloque desde %s: filas %d -> %d | nuevas %d", desde, viejas, len(nuevas), max(0, len(nuevas) - viejas))

    fila_ini, fila_fin = inicio, inicio + len(nuevas) - 1
    resumen = {"antes": viejas, "despues": len(nuevas), "nuevas": max(0, len(nuevas) - viejas), "inicio": inicio}
    if not nuevas:
        log.info("Maxinet no trae servicios para el bloque; no se escribió nada.")
        return resumen
    rango = f"A{fila_ini}:{ULTIMA_COL_DATOS}{fila_fin}"
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían %s (%d filas) (no se escribió nada).", rango, len(nuevas))
        return resumen

    if fila_fin > worksheet.row_count:
        worksheet.add_rows(fila_fin - worksheet.row_count + 200)
    for k in range(0, len(nuevas), FILAS_POR_ESCRITURA):
        tanda = nuevas[k:k + FILAS_POR_ESCRITURA]
        r1, r2 = fila_ini + k, fila_ini + k + len(tanda) - 1
        worksheet.update(range_name=f"A{r1}:{ULTIMA_COL_DATOS}{r2}", values=tanda, value_input_option="RAW")
        formulas = [[f.format(r=r) for f in FORMULAS_AUX] for r in range(r1, r2 + 1)]
        worksheet.update(range_name=f"{PRIMERA_COL_AUX}{r1}:{ULTIMA_COL}{r2}", values=formulas, value_input_option="USER_ENTERED")
    if ultima > fila_fin:                                   # el bloque quedó más corto: limpiar los datos que sobran
        worksheet.batch_clear([f"A{fila_fin + 1}:{ULTIMA_COL_DATOS}{ultima}"])
    dar_formato(worksheet, fila_ini, fila_fin)
    log.info("Bloque reescrito: %d servicios en %s (última fila anterior: %d)", len(nuevas), rango, ultima)
    return resumen


def dar_formato(worksheet, fila_ini: int, fila_fin: int):
    """Formato de fecha, hora e importe a las columnas con tipo del bloque."""
    def pedido(col, patron):
        tipo = "CURRENCY" if "$" in patron else ("TIME" if patron.startswith("h") else "DATE")
        return {"repeatCell": {
            "range": {"sheetId": worksheet.id, "startRowIndex": fila_ini - 1, "endRowIndex": fila_fin,
                      "startColumnIndex": col, "endColumnIndex": col + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}},
            "fields": "userEnteredFormat.numberFormat"}}
    worksheet.spreadsheet.batch_update({"requests": [pedido(j, p) for j, p in FORMATOS.items()]})


def validar_orden(worksheet, inicio: int, cantidad: int):
    """El bloque escrito debe tener las filas esperadas y la Fecha Prom. en orden ascendente."""
    if not cantidad:
        return
    col = worksheet.get(f"{COL_PROMESA}{inicio}:{COL_PROMESA}{inicio + cantidad - 1}", value_render_option="UNFORMATTED_VALUE")
    fechas = [_a_dia_hoja(f[0]) for f in col if f and f[0] != ""]
    if len(fechas) != cantidad:
        raise RuntimeError(f"Tras escribir, el bloque tiene {len(fechas)} filas con Fecha Prom. y se esperaban {cantidad}.")
    if fechas != sorted(fechas):
        raise RuntimeError("Tras escribir, la Fecha Prom. del bloque no quedó en orden ascendente.")
    log.info("Validación OK: %d filas del bloque con Fecha Prom. en orden", cantidad)


def main():
    try:
        filas, desde = [], None
        for d, h in bloques_a_refrescar():
            filas += descargar_bitacora(d, h)
            desde = desde or d
        filas.sort(key=lambda r: r[IDX_PROMESA])
        worksheet = conectar_sheet()
        r = refrescar_bloque(worksheet, filas, desde)
        if not os.environ.get("DRY_RUN"):
            validar_orden(worksheet, r["inicio"], r["despues"])
        log.info("Automatización completada con éxito (bloque de %d servicios desde %s)", r["despues"], desde)
    except Exception:
        log.exception("Error en la automatización de la Bitácora CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
