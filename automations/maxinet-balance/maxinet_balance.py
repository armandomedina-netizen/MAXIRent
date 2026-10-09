"""
Automatización por hora del BALANCE de Entregas / Retornos LP.

Reproduce, sin navegador, el proceso que Nuvia documentó en su skill
"balance-entregas-retornos-lp": baja de Maxinet (vía requests) los reportes
del periodo (del día 1 del mes en curso a hoy, hora CDMX) y los carga en las
pestañas del BALANCE.

    ONHIRE           <- LP > Entregas / Retornos, Tipo = ENTREGAS  (A:O)
    RETORNOS         <- LP > Entregas / Retornos, Tipo = RETORNOS  (A:O)
    SOLICITUDES ENTREGAS / RECOLECCIONES <- LP > Solicitudes de traslado, filtrando por Fecha
                        Entrega/Recolección: primero Entregas y debajo
                        Recolecciones (43 columnas desde Folio). Esta
                        descarga llega hasta hoy + SOLICITUDES_DIAS_FUTUROS
                        (7 por omisión), como el pegado de Nuvia, para
                        incluir las solicitudes ya programadas.
    PRONÓSTICO ENTREGAS: entregas y recolecciones de los próximos 7 días
                        (fórmulas de Nuvia sobre SOLICITUDES); se crea si
                        falta y se corrigen sus fórmulas si alguien las cambia.
    P:R de ONHIRE y RETORNOS: fórmulas STATUS MAXINET, FLOTA MES ANTERIOR y
                        COMPARATIVO, extendidas hasta la última fila.
    S de ONHIRE y RETORNOS: EJECUTIVO REAL (columna H de EJECUTIVOS buscada
                        por cliente en la pestaña EJECUTIVO), como en el archivo
                        de Nuvia.
    BALANCE: dos bloques (entregas nuevas y recolecciones por ejecutivo y día)
                        con la estructura que Nuvia dejó el 6-oct.

Endpoints (confirmados contra el HTML real de cada página):
    POST {MAXINET_BASE_URL}/includes/reportesLP/reporte-entregas-retornos.php
         Desde, Hasta, Tipo = ENTREGAS | RETORNOS
    POST {MAXINET_BASE_URL}/includes/traslados/lp-traslados-solicitudes.php
         criterio = fecha_entrega_recoleccion, Desde, Hasta,
         tipoSolicitud = entregas | recolecciones, valueCriterio vacío
         (con ese criterio el parámetro Estatus no filtra nada)

Además de lo que dice el skill:
    - FLOTA MES ANTERIOR se rota sola el primer día de cada mes: una pestaña
      oculta FLOTA ACTUAL guarda la flota ON HIRE (placa y cliente, tomada de
      la pestaña QUERY de la copia de CLIENTES ACTIVOS) y al cambiar de mes
      pasa a FLOTA MES ANTERIOR, que es lo que usa la columna Q.
    - Al cambiar de mes, las pestañas del mes que cierra se guardan como
      valores en pestañas ocultas ("RETORNOS 2026-09"...): Nuvia empieza de
      cero cada mes y ese historial no existe en su archivo.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH
    SPREADSHEET_ID_BALANCE  -> copia automatizada del BALANCE (destino)
    SPREADSHEET_ID_QUERY    -> copia automatizada de CLIENTES ACTIVOS (QUERY)
    SOLICITUDES_DIAS_FUTUROS -> días después de hoy que abarca la descarga
                               de SOLICITUDES (opcional, 7 por omisión)
"""

import os
import re
import sys
import json
import time
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import gspread
from gspread.exceptions import APIError
from gspread.http_client import HTTPClient
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_balance")

ZONA_CDMX = ZoneInfo("America/Mexico_City")
EPOCH_SHEETS = date(1899, 12, 30)
EPOCH_SHEETS_DT = datetime(1899, 12, 30)

HOJA_BALANCE = "BALANCE"
HOJA_ONHIRE = "ONHIRE"
HOJA_RETORNOS = "RETORNOS"
HOJA_REPORTE = "SOLICITUDES ENTREGAS / RECOLECCIONES"
HOJA_FLOTA_ANTERIOR = "FLOTA MES ANTERIOR"
HOJA_FLOTA_ACTUAL = "FLOTA ACTUAL"
HOJA_PRONOSTICO = "PRONÓSTICO ENTREGAS"

SOLICITUDES_DIAS_FUTUROS_DEFAULT = 7

ENCABEZADO_ER = [
    "NO CLIENTE", "CLIENTE", "RESERVA", "ESTATUS", "PUDATE", "RETURNDATE", "DIAS", "EFECTO 0",
    "EJECUTIVO", "FOLIO TRASLADO", "TIPO TRASLADO", "EJECUTIVO PROHIRE", "PLACA", "GRUPO", "MODELO",
    "STATUS MAXINET", "FLOTA MES ANTERIOR", "COMPARTIVO", "EJECUTIVO REAL",
]
ENCABEZADO_REPORTE = [
    "Folio", "Responsable", "Fecha Solicitud", "Área", "Tipo Solicitud", "Motivo", "Req. Remolque",
    "Estatus", "Reserva", "# Cliente", "Cliente", "Grupo", "Placa", "Vehículo", "Placa Reemplazo",
    "Vehículo Reemplazo", "Fecha Ent.", "Fecha Rec.", "Hora Ent./Rec.", "Fecha Finalizado",
    "Hora Finalizado", "Estatus Ent./Rec.", "Fecha PROHIRE", "Hora PROHIRE", "Estatus reserva",
    "Edo.Origen", "Cd.Origen", "Edo.Destino", "Cd.Destino", "Proveedor", "Costo TrasladoOficial",
    "Costo Cliente", "Costo TrasladoDiferencia", "¿Aplica cargo a cliente (DEL o COL)? *",
    "Justificación(SIN CARGO)", "Evidencia(SIN CARGO)", "Cargo cliente regreso",
    "Requiere verificación", "Site", "Booked_by", "Requiere accesorios", "Aplica cargo a cliente",
    "Seguimientos",
]
ENCABEZADO_FLOTA = [
    "Rental No", "Order Ref", "Reg No", "Fleet ID", "PU Site", "Return Site", "PU Date",
    "Return Date", "Status", "Name", "Booking No", "Client No",
]

# Reporte Entregas / Retornos: A:O. Índices que no son texto.
ER_FECHAS = (4, 5)      # PUDATE, RETURNDATE
ER_ENTEROS = (6, 9)     # DIAS, FOLIO TRASLADO (viene como enlace HTML)
ER_FORMATOS = [
    (ER_FECHAS, {"type": "DATE", "pattern": "yyyy-mm-dd"}),
    ((6,), {"type": "NUMBER", "pattern": "0"}),   # DIAS
]

# Reporte de traslados (43 columnas desde Folio, índice 0).
RT_FECHA_HORA = (2,)
RT_FECHAS = (16, 17, 19, 22)
RT_HORAS = (18, 20, 23)
RT_COSTOS = (30, 31, 32)
RT_ENTEROS = (0,)
RT_FORMATOS = [
    (RT_FECHA_HORA, {"type": "DATE_TIME", "pattern": "yyyy-mm-dd h:mm"}),
    (RT_FECHAS, {"type": "DATE", "pattern": "yyyy-mm-dd"}),
    (RT_HORAS, {"type": "TIME", "pattern": "h:mm"}),
    (RT_COSTOS, {"type": "CURRENCY", "pattern": '#,##0.00"$"'}),
    (RT_ENTEROS, {"type": "NUMBER", "pattern": "0"}),
]

FORMULA_P = "=XLOOKUP(C{r},'SOLICITUDES ENTREGAS / RECOLECCIONES'!$I:$I,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$E:$E,\"\")"
FORMULA_Q = "=XLOOKUP(M{r},'FLOTA MES ANTERIOR'!$C:$C,'FLOTA MES ANTERIOR'!$J:$J,\"\")"
# Nuvia guarda R distinto en cada pestaña: en ONHIRE vacía si no hay flota
# anterior (Q) y en RETORNOS vacía si no hay placa (M).
FORMULA_R = {
    "ONHIRE": '=IF(Q{r}="","",IF(B{r}=Q{r},"CAMBIO DE RESERVA","POSIBLE ENTREGA"))',
    "RETORNOS": '=IF(M{r}="","",IF(B{r}=Q{r},"CAMBIO DE RESERVA","POSIBLE ENTREGA"))',
}
# Ejecutivo de la cuenta: columna H ("EJECUTIVO KAM") del libro DATA EJECUTIVOS DE
# CUENTAS, pestaña EJECUTIVOS, que la pestaña EJECUTIVO del BALANCE importa con
# IMPORTRANGE. Nuvia la llama EJECUTIVO REAL; ni EJECUTIVO ni EJECUTIVO PROHIRE
# del reporte de Maxinet sirven para el BALANCE.
FORMULA_S = '=IF(M{r}="","",XLOOKUP(B{r},EJECUTIVO!$B:$B,EJECUTIVO!$H:$H,"SIN ASIGNACIÓN"))'

# Pestaña BALANCE (estructura de Nuvia del 6-oct): dos bloques, cada uno con la
# lista de ejecutivos (UNIQUE) y una columna por día del mes.
BALANCE_COL_INICIO = 3     # C
BALANCE_DIAS = 31          # C:AG
BALANCE_FILAS_EJEC = 8     # filas 2-9 (entregas) y 11-18 (retornos)
BALANCE_FILA_RETORNOS = 10
# Resaltado de Nuvia en BALANCE (días con al menos un movimiento), sobre las
# filas de ejecutivos de cada bloque, desde la columna A hasta el día 31.
BALANCE_RESALTADO = {
    "condition": {"type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "1"}]},
    "format": {"backgroundColor": {"red": 1, "green": 0.7529412}, "textFormat": {"bold": True}},
}

# PRONÓSTICO ENTREGAS: fórmulas de Nuvia tal cual (A1, F1, A3, F3). C1 y H1
# suman hasta la fila 1000, como dicen los textos de A1 y F1 (en su archivo
# sólo suman C3:C9 y H3:H35). A3 y F3 se derraman hacia abajo: nada se escribe
# debajo de ellas.
_FILTRO_PRONOSTICO = (
    "=IFERROR(QUERY(FILTER({{'SOLICITUDES ENTREGAS / RECOLECCIONES'!K2:K,'SOLICITUDES ENTREGAS / RECOLECCIONES'!L2:L,"
    "'SOLICITUDES ENTREGAS / RECOLECCIONES'!R2:R}}, TRIM(UPPER('SOLICITUDES ENTREGAS / RECOLECCIONES'!E2:E))=\"{tipo}\", "
    "TRIM(UPPER('SOLICITUDES ENTREGAS / RECOLECCIONES'!H2:H))<>\"TRASLADO CANCELADO\", "
    "'SOLICITUDES ENTREGAS / RECOLECCIONES'!R2:R>=TODAY(), 'SOLICITUDES ENTREGAS / RECOLECCIONES'!R2:R<=TODAY()+7), "
    "\"select Col1, Col2, count(Col1), Col3 group by Col1, Col2, Col3 order by Col3, Col1 label count(Col1) ''\", 0),"
    "\"Sin movimientos\")"
)
PRONOSTICO_CELDAS = {
    "A1": '="ENTREGAS: "&SUM(C3:C)&" placas en próximos 7 días"',
    "C1": "=SUM(C3:C1000)",
    "F1": '="RECOLECCIONES: "&SUM(H3:H)&" placas en próximos 7 días"',
    "H1": "=SUM(H3:H1000)",
    "A3": _FILTRO_PRONOSTICO.format(tipo="ENTREGA (NUEVO)"),
    "F3": _FILTRO_PRONOSTICO.format(tipo="RECOLECCION"),
}
PRONOSTICO_ENCABEZADO = ["CLIENTE", "GRUPO", "PLACAS", "FECHA", "", "CLIENTE", "GRUPO", "PLACAS", "FECHA"]


def _hoy_cdmx() -> date:
    return datetime.now(ZONA_CDMX).date()


def _dias_futuros_solicitudes() -> int:
    """Días después de hoy que abarca la descarga de SOLICITUDES. Nuvia pega
    también las solicitudes ya programadas (Fecha Rec. futura), que usan la
    columna P de RETORNOS y la pestaña PRONÓSTICO ENTREGAS."""
    valor = os.environ.get("SOLICITUDES_DIAS_FUTUROS", "").strip()
    if not valor:
        return SOLICITUDES_DIAS_FUTUROS_DEFAULT
    if not re.fullmatch(r"\d+", valor):
        raise ValueError("SOLICITUDES_DIAS_FUTUROS debe ser un entero de 0 en adelante")
    return int(valor)


def _instalar_reintentos_gspread() -> None:
    """Google Sheets limita las lecturas por minuto por usuario y esa cuota
    la comparten todos los procesos que usan la misma cuenta de servicio. Un
    429 se rechaza antes de procesarse, así que reintentar es seguro; los
    errores 5xx sólo se reintentan en lecturas (GET), para no duplicar una
    escritura."""
    original = HTTPClient.request

    def con_reintentos(self, method, *args, **kwargs):
        for intento in range(1, 7):
            try:
                return original(self, method, *args, **kwargs)
            except APIError as e:
                codigo = getattr(e.response, "status_code", None)
                reintentable = codigo == 429 or (codigo in (500, 502, 503) and str(method).lower() == "get")
                if not reintentable or intento == 6:
                    raise
                espera = 20 * intento
                log.warning("Google Sheets respondió %s; reintento %d de 5 en %d s", codigo, intento, espera)
                time.sleep(espera)

    HTTPClient.request = con_reintentos


def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 300 caracteres: %r", texto[:300])
        raise


def _post_con_reintentos(session: requests.Session, url: str, data: dict, intentos: int = 3):
    for n in range(1, intentos + 1):
        try:
            return session.post(url, data=data, timeout=120)
        except (requests.ConnectionError, requests.Timeout):
            if n == intentos:
                raise
            log.warning("Maxinet cortó la conexión (intento %d de %d); reintentando", n, intentos)
            time.sleep(5 * n)


def login_maxinet() -> requests.Session:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = requests.Session()
    resp = session.post(
        f"{base_url}/includes/users/AccessValidate.php",
        data={"email": os.environ["MAXINET_USER"], "password": os.environ["MAXINET_PASS"]},
    )
    data = _parse_json_bom(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")
    log.info("Login en Maxinet exitoso")
    return session


def descargar_entregas_retornos(session: requests.Session, desde: date, hasta: date, tipo: str) -> list:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = _post_con_reintentos(
        session, f"{base_url}/includes/reportesLP/reporte-entregas-retornos.php",
        {"Desde": desde.isoformat(), "Hasta": hasta.isoformat(), "Tipo": tipo},
    )
    return _parse_json_bom(resp)["data"]


def descargar_traslados(session: requests.Session, desde: date, hasta: date, tipo_solicitud: str) -> list:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = _post_con_reintentos(
        session, f"{base_url}/includes/traslados/lp-traslados-solicitudes.php",
        {
            "criterio": "fecha_entrega_recoleccion", "Estatus": "1",
            "Desde": desde.isoformat(), "Hasta": hasta.isoformat(), "valueCriterio": "",
            "tipoSolicitud": tipo_solicitud, "permisoVerCostosLogistica": 0,
        },
    )
    return _parse_json_bom(resp)["data"]


def _sin_html(valor) -> str:
    if valor is None:
        return ""
    return re.sub(r"<[^>]+>", "", str(valor)).strip()


def _serial_fecha(texto: str):
    try:
        return (datetime.strptime(texto[:10], "%Y-%m-%d").date() - EPOCH_SHEETS).days
    except ValueError:
        return texto


def _serial_hora(texto: str):
    try:
        horas, minutos = texto.split(":")[:2]
        return (int(horas) * 60 + int(minutos)) / 1440
    except ValueError:
        return texto


def convertir_fila_er(fila: list) -> list:
    """Fila del reporte Entregas / Retornos -> A:O con los tipos del pegado
    manual (fechas y enteros reales, textos recortados)."""
    salida = []
    for i in range(15):
        texto = _sin_html(fila[i]) if i < len(fila) else ""
        if texto == "":
            salida.append("")
        elif i in ER_FECHAS:
            salida.append(_serial_fecha(texto))
        elif i in ER_ENTEROS and re.fullmatch(r"-?\d+", texto):
            salida.append(int(texto))
        else:
            salida.append(texto)
    return salida


def convertir_fila_traslado(fila: list) -> list:
    """Fila del reporte de traslados -> 43 columnas desde Folio (se
    descartan las columnas Detalle y PDF)."""
    salida = []
    for i, valor in enumerate(fila[2:45]):
        texto = _sin_html(valor)
        if texto == "":
            salida.append("")
            continue
        try:
            if i in RT_FECHA_HORA:
                salida.append((datetime.strptime(texto, "%Y-%m-%d %H:%M") - EPOCH_SHEETS_DT).total_seconds() / 86400)
            elif i in RT_FECHAS:
                salida.append(_serial_fecha(texto))
            elif i in RT_HORAS:
                salida.append(_serial_hora(texto))
            elif i in RT_COSTOS:
                salida.append(float(texto.replace("$", "").replace(",", "")))
            elif i in RT_ENTEROS and re.fullmatch(r"\d+", texto):
                salida.append(int(texto))
            else:
                salida.append(texto)
        except ValueError:
            salida.append(texto)
    return salida


def conectar_libro(variable: str):
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds).open_by_key(os.environ[variable])


def _hoja_o_crear(libro, nombre: str, filas: int, columnas: int, oculta: bool = False):
    try:
        return libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        hoja = libro.add_worksheet(title=nombre, rows=filas, cols=columnas)
        if oculta:
            libro.batch_update({"requests": [{
                "updateSheetProperties": {"properties": {"sheetId": hoja.id, "hidden": True}, "fields": "hidden"},
            }]})
        log.info("Creada la pestaña %s", nombre)
        return hoja


def _peticiones_formato(hoja, indices_formato: list, ultima_fila: int) -> list:
    peticiones = []
    for indices, formato in indices_formato:
        for idx in indices:
            peticiones.append({"repeatCell": {
                "range": {"sheetId": hoja.id, "startRowIndex": 1, "endRowIndex": max(ultima_fila, 2),
                          "startColumnIndex": idx, "endColumnIndex": idx + 1},
                "cell": {"userEnteredFormat": {"numberFormat": formato}},
                "fields": "userEnteredFormat.numberFormat",
            }})
    return peticiones


def _quitar_tipos_de_tabla(libro, hoja) -> None:
    """Si la pestaña tiene una tabla de Sheets con tipos de columna, se los
    quita: un tipo de columna se impone a cualquier formato y en la copia
    venían desfasados del diseño anterior (PUDATE, RETURNDATE y DIAS como
    texto, DIAS como fecha), así que las fechas se guardaban como texto. Los
    formatos de estas pestañas los pone el script; la tabla y sus datos se
    conservan."""
    meta = libro.fetch_sheet_metadata(params={"fields": "sheets(properties(sheetId),tables(tableId,columnProperties))"})
    peticiones = []
    for s in meta.get("sheets", []):
        if s["properties"]["sheetId"] != hoja.id:
            continue
        for tabla in s.get("tables", []):
            columnas = tabla.get("columnProperties", [])
            if not any(c.get("columnType") not in (None, "COLUMN_TYPE_UNSPECIFIED") for c in columnas):
                continue
            nuevas = [{**c, "columnType": "COLUMN_TYPE_UNSPECIFIED"} for c in columnas]
            peticiones.append({"updateTable": {"table": {"tableId": tabla["tableId"], "columnProperties": nuevas},
                                               "fields": "columnProperties"}})
    if peticiones:
        libro.batch_update({"requests": peticiones})
        log.info("%s: se quitaron los tipos de columna de %d tabla(s) para que valgan los formatos del script", hoja.title, len(peticiones))


def _resetear_formato(libro, hoja, filas: int, columnas: int) -> None:
    """Quita el formato y las celdas combinadas que haya dejado el diseño
    anterior de una pestaña que se reconstruye (por ejemplo un formato de
    fecha en una columna de folios, o una fila combinada que se traga lo que
    se escribe en ella)."""
    rango = {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": filas,
             "startColumnIndex": 0, "endColumnIndex": columnas}
    libro.batch_update({"requests": [
        {"unmergeCells": {"range": rango}},
        {"repeatCell": {"range": rango, "cell": {}, "fields": "userEnteredFormat"}},
    ]})


def _asegurar_tamano(hoja, filas: int, columnas: int) -> None:
    if hoja.row_count < filas:
        hoja.add_rows(filas - hoja.row_count + 200)
    if hoja.col_count < columnas:
        hoja.add_cols(columnas - hoja.col_count)


def cargar_entregas_retornos(libro, nombre_hoja: str, filas: list) -> None:
    """Reemplaza A2:O de ONHIRE o RETORNOS y extiende P:R. Primero escribe
    y luego limpia lo que sobre, para que la hoja nunca quede vacía a media
    corrida; el encabezado de la fila 1 se respeta si ya existe."""
    hoja = _hoja_o_crear(libro, nombre_hoja, 1000, len(ENCABEZADO_ER))
    _asegurar_tamano(hoja, len(filas) + 2, len(ENCABEZADO_ER))
    if hoja.row_values(1)[:len(ENCABEZADO_ER)] != ENCABEZADO_ER:
        if any(c.strip() for c in hoja.row_values(1)):
            log.warning("%s: el encabezado no coincide con el formato nuevo; se reconstruye toda la hoja", nombre_hoja)
            hoja.clear()
            _resetear_formato(libro, hoja, hoja.row_count, hoja.col_count)
        hoja.update(values=[ENCABEZADO_ER], range_name="A1", value_input_option="RAW")

    previas = len([c for c in hoja.col_values(1)[1:] if c.strip()])
    valores = [convertir_fila_er(f) for f in filas]
    ultima = len(valores) + 1
    # El formato va antes que los valores: un número escrito en una celda con
    # formato de texto se guarda como texto, y cambiar el formato después no
    # lo convierte.
    _quitar_tipos_de_tabla(libro, hoja)
    libro.batch_update({"requests": _peticiones_formato(hoja, ER_FORMATOS, ultima)})
    if valores:
        hoja.update(values=valores, range_name=f"A2:O{ultima}", value_input_option="RAW")
        formulas = [
            [FORMULA_P.format(r=r), FORMULA_Q.format(r=r), FORMULA_R[nombre_hoja].format(r=r), FORMULA_S.format(r=r)]
            for r in range(2, ultima + 1)
        ]
        hoja.update(values=formulas, range_name=f"P2:S{ultima}", value_input_option="USER_ENTERED")
    if previas > len(valores):
        hoja.batch_clear([f"A{ultima + 1}:S{hoja.row_count}"])
    log.info("%s: %d filas escritas en A2:O%d (P:S extendidas; antes había %d)", nombre_hoja, len(valores), ultima, previas)


def cargar_reporte_maxinet(libro, entregas: list, recolecciones: list) -> None:
    hoja = _hoja_o_crear(libro, HOJA_REPORTE, 1000, len(ENCABEZADO_REPORTE))
    valores = [convertir_fila_traslado(f) for f in entregas + recolecciones]
    _asegurar_tamano(hoja, len(valores) + 2, len(ENCABEZADO_REPORTE))
    if hoja.row_values(1)[:len(ENCABEZADO_REPORTE)] != ENCABEZADO_REPORTE:
        if any(c.strip() for c in hoja.row_values(1)):
            log.warning("%s: el encabezado no coincide con el formato nuevo; se reconstruye toda la hoja", HOJA_REPORTE)
            hoja.clear()
            _resetear_formato(libro, hoja, hoja.row_count, hoja.col_count)
        hoja.update(values=[ENCABEZADO_REPORTE], range_name="A1", value_input_option="RAW")

    previas = len([c for c in hoja.col_values(1)[1:] if c.strip()])
    ultima = len(valores) + 1
    _quitar_tipos_de_tabla(libro, hoja)
    libro.batch_update({"requests": _peticiones_formato(hoja, RT_FORMATOS, ultima)})
    if valores:
        hoja.update(values=valores, range_name=f"A2:AQ{ultima}", value_input_option="RAW")
    if previas > len(valores):
        hoja.batch_clear([f"A{ultima + 1}:AQ{hoja.row_count}"])
    log.info("%s: %d solicitudes escritas (%d entregas, %d recolecciones; antes había %d)",
             HOJA_REPORTE, len(valores), len(entregas), len(recolecciones), previas)


def _mes_de_serial(serial) -> str:
    return (EPOCH_SHEETS + timedelta(days=int(serial))).strftime("%Y-%m")


def archivar_mes_cerrado(libro, hoy: date) -> None:
    """Si RETORNOS todavía trae devoluciones de un mes anterior, guarda
    ONHIRE, RETORNOS y SOLICITUDES de ese mes como valores en pestañas
    ocultas antes de que se sobrescriban."""
    try:
        fechas = libro.worksheet(HOJA_RETORNOS).get("F2:F", value_render_option="UNFORMATTED_VALUE")
    except gspread.WorksheetNotFound:
        return
    series = [f[0] for f in fechas if f and isinstance(f[0], (int, float))]
    if not series:
        return
    mes_datos = _mes_de_serial(max(series))
    if mes_datos >= hoy.strftime("%Y-%m"):
        return
    existentes = {w.title for w in libro.worksheets()}
    for nombre in (HOJA_ONHIRE, HOJA_RETORNOS, HOJA_REPORTE):
        destino = f"{nombre} {mes_datos}"
        if destino in existentes or nombre not in existentes:
            continue
        valores = libro.worksheet(nombre).get_all_values(value_render_option="UNFORMATTED_VALUE")
        valores = [[c for c in fila[:15 if nombre != HOJA_REPORTE else 43]] for fila in valores if any(str(c).strip() for c in fila)]
        copia = _hoja_o_crear(libro, destino, len(valores) + 10, 43, oculta=True)
        copia.update(values=valores, range_name="A1", value_input_option="RAW")
        log.info("Archivado el mes %s: %s (%d filas)", mes_datos, destino, len(valores) - 1)


def _flota_desde_query(libro_query) -> list:
    """Flota ON HIRE en el formato de FLOTA MES ANTERIOR (12 columnas), una
    fila por placa, tomada de la línea RENT de la pestaña QUERY."""
    filas = libro_query.worksheet(os.environ.get("WORKSHEET_QUERY_NAME", "QUERY").strip()).get("A2:O", value_render_option="UNFORMATTED_VALUE")
    por_placa = {}
    for f in filas:
        f = list(f) + [""] * (15 - len(f))
        placa = str(f[2]).strip()
        if not placa or str(f[12]).strip() != "RENT":
            continue
        por_placa[placa] = [
            "", str(f[14]).strip(), placa, "", "", "", _serial_fecha(str(f[4])) if f[4] != "" else "",
            _serial_fecha(str(f[5])) if f[5] != "" else "", "ON HIRE", str(f[3]).strip(), str(f[0]).strip(), "",
        ]
    return sorted(por_placa.values(), key=lambda x: x[2])


def rotar_flota_mes_anterior(libro, libro_query, hoy: date) -> None:
    """Mantiene FLOTA ACTUAL con la flota de la última corrida y, el primer
    día de un mes nuevo, la pasa a FLOTA MES ANTERIOR (lo que usa la columna
    Q de ONHIRE y RETORNOS). El mes de los datos de FLOTA ACTUAL va en N1."""
    mes_actual = hoy.strftime("%Y-%m")
    hoja_actual = _hoja_o_crear(libro, HOJA_FLOTA_ACTUAL, 1500, 14, oculta=True)
    mes_guardado = str(hoja_actual.acell("N1").value or "").strip()

    if mes_guardado and mes_guardado < mes_actual:
        previas = hoja_actual.get("A2:L", value_render_option="UNFORMATTED_VALUE")
        if previas:
            anterior = _hoja_o_crear(libro, HOJA_FLOTA_ANTERIOR, 1000, len(ENCABEZADO_FLOTA))
            _asegurar_tamano(anterior, len(previas) + 2, len(ENCABEZADO_FLOTA))
            anterior.update(values=[ENCABEZADO_FLOTA], range_name="A1", value_input_option="RAW")
            anterior.update(values=previas, range_name=f"A2:L{len(previas) + 1}", value_input_option="RAW")
            sobrantes = anterior.row_count
            if sobrantes > len(previas) + 1:
                anterior.batch_clear([f"A{len(previas) + 2}:L{sobrantes}"])
            log.info("FLOTA MES ANTERIOR actualizada con la flota de %s (%d placas)", mes_guardado, len(previas))

    flota = _flota_desde_query(libro_query)
    if not flota:
        log.warning("La pestaña QUERY no trajo flota ON HIRE; FLOTA ACTUAL no se actualiza")
        return
    _asegurar_tamano(hoja_actual, len(flota) + 2, 14)
    hoja_actual.update(values=[ENCABEZADO_FLOTA], range_name="A1", value_input_option="RAW")
    hoja_actual.update(values=flota, range_name=f"A2:L{len(flota) + 1}", value_input_option="RAW")
    if hoja_actual.row_count > len(flota) + 1:
        hoja_actual.batch_clear([f"A{len(flota) + 2}:L{hoja_actual.row_count}"])
    hoja_actual.update(values=[[mes_actual]], range_name="N1", value_input_option="RAW")
    log.info("FLOTA ACTUAL: %d placas ON HIRE (mes %s)", len(flota), mes_actual)


def _formulas_balance(hoy: date) -> tuple:
    """Valores y fórmulas de BALANCE A1:AG18 como las tiene Nuvia: la lista de
    ejecutivos sale de UNIQUE sobre la columna S ("EJECUTIVO REAL") de ONHIRE
    y RETORNOS; cada celda cuenta las entregas nuevas (ONHIRE, STATUS MAXINET
    = ENTREGA (NUEVO)) o las recolecciones (RETORNOS, STATUS MAXINET =
    RECOLECCION) de ese ejecutivo ese día. Las filas de ejecutivos que sobran
    quedan vacías (IF sobre la columna A) para que un COUNTIFS con criterio
    vacío no cuente celdas en blanco."""
    columnas = BALANCE_COL_INICIO + BALANCE_DIAS - 1
    primer_dia = (hoy.replace(day=1) - EPOCH_SHEETS).days
    letra = lambda n: gspread.utils.rowcol_to_a1(1, n)[:-1]
    ultima = letra(columnas)
    primera = letra(BALANCE_COL_INICIO)

    filas = {}
    filas[1] = ["=UNIQUE(ONHIRE!S:S)", "TOTAL DE ENTREGAS"] + [primer_dia + k for k in range(BALANCE_DIAS)]
    for r in range(2, 2 + BALANCE_FILAS_EJEC):
        fila = [None, f'=IF($A{r}="","",SUM({primera}{r}:{ultima}{r}))']
        for c in range(BALANCE_COL_INICIO, columnas + 1):
            col = letra(c)
            fila.append(f'=IF($A{r}="","",COUNTIFS(ONHIRE!$S:$S,$A{r},ONHIRE!$E:$E,{col}$1,ONHIRE!$P:$P,"ENTREGA (NUEVO)"))')
        filas[r] = fila
    h = BALANCE_FILA_RETORNOS
    filas[h] = ["=UNIQUE(RETORNOS!S:S)", "TOTAL DE RETORNOS"] + [f"={letra(c)}1" for c in range(BALANCE_COL_INICIO, columnas + 1)]
    for r in range(h + 1, h + 1 + BALANCE_FILAS_EJEC):
        fila = [None, f'=IF($A{r}="","",SUM({primera}{r}:{ultima}{r}))']
        for c in range(BALANCE_COL_INICIO, columnas + 1):
            col = letra(c)
            fila.append(f'=IF($A{r}="","",COUNTIFS(RETORNOS!$S:$S,$A{r},RETORNOS!$F:$F,{col}${h},RETORNOS!$P:$P,"RECOLECCION"))')
        filas[r] = fila
    return filas, columnas


def actualizar_balance(libro, hoy: date) -> None:
    """Deja la pestaña BALANCE con la estructura de Nuvia y los días del mes
    en curso (C1 es el día 1). Cada corrida sólo reescribe si la estructura
    cambió o si cambió el mes; si la pestaña está protegida sólo avisa."""
    try:
        hoja = libro.worksheet(HOJA_BALANCE)
        filas, columnas = _formulas_balance(hoy)
        actual = hoja.get("A1:C1", value_render_option="FORMULA")
        actual = actual[0] if actual else []
        esperado = [filas[1][0], filas[1][1], filas[1][2]]
        if actual[:3] == esperado:
            return
        _asegurar_tamano(hoja, 2 + 2 * (BALANCE_FILAS_EJEC + 1), columnas)
        hoja.batch_clear([f"A1:AH{hoja.row_count}"])
        _resetear_formato(libro, hoja, hoja.row_count, hoja.col_count)
        # fila 1 y fila 10 primero (UNIQUE), luego el resto
        valores = []
        for r in sorted(filas):
            valores.append([("" if v is None else v) for v in filas[r]])
        # el bloque 1 ocupa filas 1-9 y el de retornos empieza en la fila 10
        hoja.update(values=valores[:1 + BALANCE_FILAS_EJEC], range_name="A1", value_input_option="USER_ENTERED")
        hoja.update(values=valores[1 + BALANCE_FILAS_EJEC:], range_name=f"A{BALANCE_FILA_RETORNOS}", value_input_option="USER_ENTERED")
        fmt_fecha = {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}, "textFormat": {"bold": True}}
        fmt_negrita = {"textFormat": {"bold": True}}
        peticiones = []
        for fila_idx, ancho_ini in ((0, BALANCE_COL_INICIO - 1), (BALANCE_FILA_RETORNOS - 1, BALANCE_COL_INICIO - 1)):
            peticiones.append({"repeatCell": {
                "range": {"sheetId": hoja.id, "startRowIndex": fila_idx, "endRowIndex": fila_idx + 1,
                          "startColumnIndex": ancho_ini, "endColumnIndex": columnas},
                "cell": {"userEnteredFormat": fmt_fecha}, "fields": "userEnteredFormat(numberFormat,textFormat)"}})
            peticiones.append({"repeatCell": {
                "range": {"sheetId": hoja.id, "startRowIndex": fila_idx, "endRowIndex": fila_idx + 1,
                          "startColumnIndex": 0, "endColumnIndex": 2},
                "cell": {"userEnteredFormat": fmt_negrita}, "fields": "userEnteredFormat.textFormat"}})
        libro.batch_update({"requests": peticiones})
        log.info("BALANCE: estructura reconstruida para %s", hoy.strftime("%Y-%m"))
    except (gspread.WorksheetNotFound, APIError) as e:
        log.warning("BALANCE: no se pudo actualizar la pestaña (%s)", type(e).__name__)


def asegurar_resaltado_balance(libro) -> None:
    """Deja en BALANCE una sola regla de formato condicional, la de Nuvia
    (>= 1 en naranja y negrita), sobre las filas de ejecutivos de los dos
    bloques (2-9 y 11-18) desde la columna A hasta el día 31. Sólo escribe
    si las reglas actuales son distintas."""
    try:
        hoja = libro.worksheet(HOJA_BALANCE)
        meta = libro.fetch_sheet_metadata(params={"fields": "sheets(properties(sheetId,gridProperties),conditionalFormats)"})
        datos = next(s for s in meta["sheets"] if s["properties"]["sheetId"] == hoja.id)
        ultima_col = min(BALANCE_COL_INICIO + BALANCE_DIAS, datos["properties"]["gridProperties"]["columnCount"])
        rangos = [
            {"sheetId": hoja.id, "startRowIndex": inicio, "endRowIndex": inicio + BALANCE_FILAS_EJEC,
             "startColumnIndex": 0, "endColumnIndex": ultima_col}
            for inicio in (1, BALANCE_FILA_RETORNOS)
        ]
        actuales = datos.get("conditionalFormats", [])
        if (len(actuales) == 1 and actuales[0].get("ranges") == rangos
                and actuales[0].get("booleanRule", {}).get("condition") == BALANCE_RESALTADO["condition"]):
            return
        peticiones = [{"deleteConditionalFormatRule": {"sheetId": hoja.id, "index": i}} for i in reversed(range(len(actuales)))]
        peticiones.append({"addConditionalFormatRule": {"index": 0, "rule": {"ranges": rangos, "booleanRule": BALANCE_RESALTADO}}})
        libro.batch_update({"requests": peticiones})
        log.info("BALANCE: formato condicional ajustado a los bloques de ejecutivos (antes había %d regla(s))", len(actuales))
    except (gspread.WorksheetNotFound, APIError) as e:
        log.warning("BALANCE: no se pudo ajustar el formato condicional (%s)", type(e).__name__)


def _formato_pronostico(hoja) -> list:
    """Formato del archivo de Nuvia: títulos en verde (entregas) y naranja
    (recolecciones), encabezados en negrita, PLACAS centrado y FECHA como
    fecha. Sólo se aplica al crear la pestaña."""
    def rango(f0, f1, c0, c1):
        return {"sheetId": hoja.id, "startRowIndex": f0, "endRowIndex": f1, "startColumnIndex": c0, "endColumnIndex": c1}

    def celda(r, formato, campos):
        return {"repeatCell": {"range": r, "cell": {"userEnteredFormat": formato}, "fields": f"userEnteredFormat({campos})"}}

    verde = {"red": 0.20392157, "green": 0.65882355, "blue": 0.3254902}
    naranja = {"red": 1, "green": 0.42745098, "blue": 0.003921569}
    numero = {"numberFormat": {"type": "NUMBER", "pattern": "0"}, "horizontalAlignment": "CENTER"}
    fecha = {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}
    peticiones = [
        celda(rango(0, 1, 0, 4), {"backgroundColor": verde, "textFormat": {"bold": True}}, "backgroundColor,textFormat"),
        celda(rango(0, 1, 5, 12), {"backgroundColor": naranja, "textFormat": {"bold": True}}, "backgroundColor,textFormat"),
        celda(rango(0, 1, 2, 4), {"horizontalAlignment": "CENTER"}, "horizontalAlignment"),
        celda(rango(0, 1, 7, 8), {"horizontalAlignment": "CENTER"}, "horizontalAlignment"),
        celda(rango(1, 2, 0, 12), {"textFormat": {"bold": True}}, "textFormat"),
        celda(rango(1, 2, 3, 4), {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"},
              "horizontalAlignment,verticalAlignment,wrapStrategy"),
        celda(rango(2, 1000, 2, 3), numero, "numberFormat,horizontalAlignment"),
        celda(rango(2, 1000, 7, 8), numero, "numberFormat,horizontalAlignment"),
        celda(rango(2, 1000, 3, 4), {**fecha, "horizontalAlignment": "CENTER"}, "numberFormat,horizontalAlignment"),
        celda(rango(2, 1000, 8, 12), fecha, "numberFormat"),
    ]
    for col, ancho in enumerate([340, 100, 66, 100, 100, 342, 100, 100, 100, 100, 100, 100]):
        peticiones.append({"updateDimensionProperties": {
            "range": {"sheetId": hoja.id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
            "properties": {"pixelSize": ancho}, "fields": "pixelSize"}})
    return peticiones


def asegurar_pronostico(libro) -> None:
    """Crea PRONÓSTICO ENTREGAS (junto a SOLICITUDES, como en el archivo de
    Nuvia) si no existe y repone sus fórmulas y encabezados si cambiaron.
    Nunca escribe dentro del derrame de A3 y F3."""
    try:
        try:
            hoja = libro.worksheet(HOJA_PRONOSTICO)
            nueva = False
        except gspread.WorksheetNotFound:
            indice = next((w.index + 1 for w in libro.worksheets() if w.title == HOJA_REPORTE), None)
            hoja = libro.add_worksheet(title=HOJA_PRONOSTICO, rows=1000, cols=24, index=indice)
            nueva = True
        actuales = hoja.batch_get(["A1:I3"], value_render_option="FORMULA")[0]
        actuales = [list(f) + [""] * (9 - len(f)) for f in actuales] + [[""] * 9] * (3 - len(actuales))
        cambios = []
        for a1, formula in PRONOSTICO_CELDAS.items():
            fila, col = gspread.utils.a1_to_rowcol(a1)
            if actuales[fila - 1][col - 1] != formula:
                cambios.append({"range": a1, "values": [[formula]]})
        if actuales[1] != PRONOSTICO_ENCABEZADO:
            cambios.append({"range": "A2:I2", "values": [PRONOSTICO_ENCABEZADO]})
        if nueva:
            libro.batch_update({"requests": _formato_pronostico(hoja)})
        if cambios:
            hoja.batch_update(cambios, value_input_option="USER_ENTERED")
            log.info("%s: %s; %d rango(s) de fórmulas o encabezados escritos", HOJA_PRONOSTICO,
                     "pestaña creada" if nueva else "fórmulas repuestas", len(cambios))
    except APIError as e:
        log.warning("%s: no se pudo mantener la pestaña (%s)", HOJA_PRONOSTICO, type(e).__name__)


def verificar_errores(libro) -> None:
    errores = {"#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!", "#ERROR!"}
    for nombre in (HOJA_ONHIRE, HOJA_RETORNOS):
        hoja = libro.worksheet(nombre)
        valores = hoja.get("P2:S", value_render_option="FORMATTED_VALUE")
        malas = sum(1 for fila in valores for c in fila if c in errores)
        sin_kam = sum(1 for fila in valores if len(fila) < 4 or fila[3] in ("", "PENDIENTE", "SIN ASIGNACIÓN"))
        sin_solicitud = sum(1 for fila in valores if fila and fila[0] == "")
        cambios = sum(1 for fila in valores if len(fila) > 2 and fila[2] == "CAMBIO DE RESERVA")
        posibles = sum(1 for fila in valores if len(fila) > 2 and fila[2] == "POSIBLE ENTREGA")
        log.info("%s: %d CAMBIO DE RESERVA, %d POSIBLE ENTREGA, %d reservas sin solicitud de traslado, %d sin ejecutivo, %d errores en P:S",
                 nombre, cambios, posibles, sin_solicitud, sin_kam, malas)
    # BALANCE (p. ej. un UNIQUE de ejecutivos que ya no cabe en su bloque) y
    # el derrame del pronóstico.
    for rango in (f"{HOJA_BALANCE}!A1:AG18", f"'{HOJA_PRONOSTICO}'!A1:I1000"):
        try:
            valores = libro.values_get(rango, params={"valueRenderOption": "FORMATTED_VALUE"}).get("values", [])
        except APIError:
            continue
        malas = sum(1 for fila in valores for c in fila if c in errores)
        if malas:
            log.warning("%s: %d celdas con error", rango, malas)
    try:
        pron = libro.values_get(f"'{HOJA_PRONOSTICO}'!A1:I1", params={"valueRenderOption": "UNFORMATTED_VALUE"}).get("values", [[]])[0]
        pron += [""] * (8 - len(pron))
        log.info("%s: %s placas a entregar y %s a recolectar en los próximos 7 días", HOJA_PRONOSTICO, pron[2], pron[7])
    except APIError:
        pass


def main():
    try:
        _instalar_reintentos_gspread()
        hoy = _hoy_cdmx()
        desde = hoy.replace(day=1)
        hasta_solicitudes = hoy + timedelta(days=_dias_futuros_solicitudes())
        session = login_maxinet()

        entregas = descargar_entregas_retornos(session, desde, hoy, "ENTREGAS")
        retornos = descargar_entregas_retornos(session, desde, hoy, "RETORNOS")
        traslados_ent = descargar_traslados(session, desde, hasta_solicitudes, "entregas")
        traslados_rec = descargar_traslados(session, desde, hasta_solicitudes, "recolecciones")
        log.info("Maxinet %s a %s: %d entregas, %d retornos; solicitudes hasta %s: %d de entrega, %d de recolección",
                 desde, hoy, len(entregas), len(retornos), hasta_solicitudes, len(traslados_ent), len(traslados_rec))
        if not entregas and not retornos and hoy.day > 1:
            raise RuntimeError("Maxinet no regresó entregas ni retornos del mes; no se sobrescribe nada")

        libro = conectar_libro("SPREADSHEET_ID_BALANCE")
        libro_query = conectar_libro("SPREADSHEET_ID_QUERY")

        archivar_mes_cerrado(libro, hoy)
        rotar_flota_mes_anterior(libro, libro_query, hoy)
        cargar_reporte_maxinet(libro, traslados_ent, traslados_rec)
        cargar_entregas_retornos(libro, HOJA_ONHIRE, entregas)
        cargar_entregas_retornos(libro, HOJA_RETORNOS, retornos)
        actualizar_balance(libro, hoy)
        asegurar_resaltado_balance(libro)
        asegurar_pronostico(libro)
        verificar_errores(libro)
        log.info("BALANCE: actualización completada con éxito")
    except Exception:
        log.exception("Error en la actualización del BALANCE")
        sys.exit(1)


if __name__ == "__main__":
    main()
