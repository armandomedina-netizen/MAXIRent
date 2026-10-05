"""
Automatización por hora del BALANCE de Entregas / Retornos LP.

Reproduce, sin navegador, el proceso que Nuvia documentó en su skill
"balance-entregas-retornos-lp": baja de Maxinet (vía requests) los reportes
del periodo (del día 1 del mes en curso a hoy, hora CDMX) y los carga en las
pestañas del BALANCE.

    ONHIRE           <- LP > Entregas / Retornos, Tipo = ENTREGAS  (A:O)
    RETORNOS         <- LP > Entregas / Retornos, Tipo = RETORNOS  (A:O)
    REPORTE MAXINET  <- LP > Solicitudes de traslado, filtrando por Fecha
                        Entrega/Recolección: primero Entregas y debajo
                        Recolecciones (43 columnas desde Folio)
    P:R de ONHIRE y RETORNOS: fórmulas STATUS MAXINET, FLOTA MES ANTERIOR y
                        COMPARATIVO, extendidas hasta la última fila.

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

HOJA_ONHIRE = "ONHIRE"
HOJA_RETORNOS = "RETORNOS"
HOJA_REPORTE = "REPORTE MAXINET"
HOJA_FLOTA_ANTERIOR = "FLOTA MES ANTERIOR"
HOJA_FLOTA_ACTUAL = "FLOTA ACTUAL"

ENCABEZADO_ER = [
    "NO CLIENTE", "CLIENTE", "RESERVA", "ESTATUS", "PUDATE", "RETURNDATE", "DIAS", "EFECTO 0",
    "EJECUTIVO", "FOLIO TRASLADO", "TIPO TRASLADO", "EJECUTIVO PROHIRE", "PLACA", "GRUPO", "MODELO",
    "STATUS MAXINET", "FLOTA MES ANTERIOR", "COMPARTIVO",
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
]

FORMULA_P = "=XLOOKUP(C{r},'REPORTE MAXINET'!$I:$I,'REPORTE MAXINET'!$E:$E,\"\")"
FORMULA_Q = "=XLOOKUP(M{r},'FLOTA MES ANTERIOR'!$C:$C,'FLOTA MES ANTERIOR'!$J:$J,\"\")"
FORMULA_R = '=IF(B{r}=Q{r},"CAMBIO DE RESERVA","POSIBLE ENTREGA")'


def _hoy_cdmx() -> date:
    return datetime.now(ZONA_CDMX).date()


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
        hoja.update(values=[ENCABEZADO_ER], range_name="A1", value_input_option="RAW")

    previas = len([c for c in hoja.col_values(1)[1:] if c.strip()])
    valores = [convertir_fila_er(f) for f in filas]
    ultima = len(valores) + 1
    if valores:
        hoja.update(values=valores, range_name=f"A2:O{ultima}", value_input_option="RAW")
        formulas = [[FORMULA_P.format(r=r), FORMULA_Q.format(r=r), FORMULA_R.format(r=r)] for r in range(2, ultima + 1)]
        hoja.update(values=formulas, range_name=f"P2:R{ultima}", value_input_option="USER_ENTERED")
    if previas > len(valores):
        hoja.batch_clear([f"A{ultima + 1}:R{hoja.row_count}"])
    libro.batch_update({"requests": _peticiones_formato(hoja, [(ER_FECHAS, {"type": "DATE", "pattern": "yyyy-mm-dd"})], ultima)})
    log.info("%s: %d filas escritas en A2:O%d (P:R extendidas; antes había %d)", nombre_hoja, len(valores), ultima, previas)


def cargar_reporte_maxinet(libro, entregas: list, recolecciones: list) -> None:
    hoja = _hoja_o_crear(libro, HOJA_REPORTE, 1000, len(ENCABEZADO_REPORTE))
    valores = [convertir_fila_traslado(f) for f in entregas + recolecciones]
    _asegurar_tamano(hoja, len(valores) + 2, len(ENCABEZADO_REPORTE))
    if hoja.row_values(1)[:len(ENCABEZADO_REPORTE)] != ENCABEZADO_REPORTE:
        hoja.update(values=[ENCABEZADO_REPORTE], range_name="A1", value_input_option="RAW")

    previas = len([c for c in hoja.col_values(1)[1:] if c.strip()])
    ultima = len(valores) + 1
    if valores:
        hoja.update(values=valores, range_name=f"A2:AQ{ultima}", value_input_option="RAW")
    if previas > len(valores):
        hoja.batch_clear([f"A{ultima + 1}:AQ{hoja.row_count}"])
    libro.batch_update({"requests": _peticiones_formato(hoja, RT_FORMATOS, ultima)})
    log.info("%s: %d solicitudes escritas (%d entregas, %d recolecciones; antes había %d)",
             HOJA_REPORTE, len(valores), len(entregas), len(recolecciones), previas)


def _mes_de_serial(serial) -> str:
    return (EPOCH_SHEETS + timedelta(days=int(serial))).strftime("%Y-%m")


def archivar_mes_cerrado(libro, hoy: date) -> None:
    """Si RETORNOS todavía trae devoluciones de un mes anterior, guarda
    ONHIRE, RETORNOS y REPORTE MAXINET de ese mes como valores en pestañas
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


def verificar_errores(libro) -> None:
    errores = {"#REF!", "#VALUE!", "#N/A", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!", "#ERROR!"}
    for nombre in (HOJA_ONHIRE, HOJA_RETORNOS):
        hoja = libro.worksheet(nombre)
        valores = hoja.get("P2:R", value_render_option="FORMATTED_VALUE")
        malas = sum(1 for fila in valores for c in fila if c in errores)
        sin_solicitud = sum(1 for fila in valores if fila and fila[0] == "")
        cambios = sum(1 for fila in valores if len(fila) > 2 and fila[2] == "CAMBIO DE RESERVA")
        posibles = sum(1 for fila in valores if len(fila) > 2 and fila[2] == "POSIBLE ENTREGA")
        log.info("%s: %d CAMBIO DE RESERVA, %d POSIBLE ENTREGA, %d reservas sin solicitud de traslado, %d errores en P:R",
                 nombre, cambios, posibles, sin_solicitud, malas)


def main():
    try:
        _instalar_reintentos_gspread()
        hoy = _hoy_cdmx()
        desde = hoy.replace(day=1)
        session = login_maxinet()

        entregas = descargar_entregas_retornos(session, desde, hoy, "ENTREGAS")
        retornos = descargar_entregas_retornos(session, desde, hoy, "RETORNOS")
        traslados_ent = descargar_traslados(session, desde, hoy, "entregas")
        traslados_rec = descargar_traslados(session, desde, hoy, "recolecciones")
        log.info("Maxinet %s a %s: %d entregas, %d retornos, %d solicitudes de entrega, %d de recolección",
                 desde, hoy, len(entregas), len(retornos), len(traslados_ent), len(traslados_rec))
        if not entregas and not retornos and hoy.day > 1:
            raise RuntimeError("Maxinet no regresó entregas ni retornos del mes; no se sobrescribe nada")

        libro = conectar_libro("SPREADSHEET_ID_BALANCE")
        libro_query = conectar_libro("SPREADSHEET_ID_QUERY")

        archivar_mes_cerrado(libro, hoy)
        rotar_flota_mes_anterior(libro, libro_query, hoy)
        cargar_reporte_maxinet(libro, traslados_ent, traslados_rec)
        cargar_entregas_retornos(libro, HOJA_ONHIRE, entregas)
        cargar_entregas_retornos(libro, HOJA_RETORNOS, retornos)
        verificar_errores(libro)
        log.info("BALANCE: actualización completada con éxito")
    except Exception:
        log.exception("Error en la actualización del BALANCE")
        sys.exit(1)


if __name__ == "__main__":
    main()
