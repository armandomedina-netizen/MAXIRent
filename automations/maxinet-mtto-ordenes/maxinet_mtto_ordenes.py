"""
Automatización: login + lectura del reporte "Ordenes de Mantenimiento LP" desde Maxinet vía requests
(sin navegador) y reescritura de la pestaña "ORDENES MTTO" de la Base LP copia ("Copia de BASE LP_AUTOMATIZADO").

Endpoint confirmado a partir del JS real de Maxinet (lp-mtto-ordenes.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/lp-mtto-ordenes.php
            body: Criterio, Estatus, Desde, Hasta, valueCriterio (los mismos campos del filtro de la página)
            respuesta: {"data": [[62 celdas HTML], ...]} o {"data": ""} si no hay filas.
    IMPORTANTE: Estatus debe ir SIEMPRE con valor (la página manda el del selector aunque esté deshabilitado
    cuando se filtra por fecha); con Estatus vacío el servidor responde {"data": ""}.
        - Criterio=ALTA, Estatus=1, Desde, Hasta  -> órdenes dadas de alta en el rango (cualquier estatus).
        - Criterio=ESTATUS, Estatus=1             -> TODAS las órdenes abiertas, sin importar su fecha de alta.

Qué contiene la pestaña (decidido con el usuario): sólo el MES CORRIENTE más las órdenes que siguen abiertas,
para que la hoja no crezca sin límite. En cada corrida se reescribe completa con lo que entrega Maxinet:
    - Mes corriente: del día 1 a AYER (hora Ciudad de México), por fecha de alta. Si hoy es día 1, "ayer"
      cae en el mes anterior y el rango es ese mes completo.
    - Órdenes abiertas de cualquier mes, para que su estatus esté al día aunque se hayan dado de alta antes.
    Las órdenes cerradas o canceladas de meses anteriores salen de la hoja al cambiar de mes.

Columnas: las 62 del reporte menos los 3 botones (Detalle, Hoja Cita, Bitácora) y los 4 datos personales de
contacto (Nombre Contacto, Tel. Contacto, Cel. Contacto, Correo): quedan 55, con los nombres del reporte. Los
valores se escriben tipados (fechas y horas como números de serie, costos y días como números; todo lo demás
como texto) con value_input_option=RAW, de modo que Sheets no reinterprete ninguna placa ni folio.

Salvaguardas (FORZAR=1 las omite): la corrida se detiene SIN escribir si
    - el reporte cambió de ancho o sus columnas no cuadran (Id, Fecha Alta, Placa),
    - la hoja tiene otro encabezado (alguien movió columnas),
    - Maxinet trae menos del 80% de las órdenes de alta del rango que ya estaban en la hoja, o menos del 80% de
      las órdenes abiertas que ya estaban (con 30 o más de cada una): probable respuesta incompleta.
Se escribe primero (update) y se limpia lo que sobra después, nunca al revés, para que la hoja no se vea vacía.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID (la Base LP copia), WORKSHEET_MTTO_ORDENES (por defecto "ORDENES MTTO"),
    FECHA_DESDE, FECHA_HASTA, DRY_RUN, FORZAR (opcionales)
"""

import os
import re
import sys
import json
import html
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
log = logging.getLogger("maxinet_mtto_ordenes")

# Orden confirmado en el HTML real de lp-mtto-ordenes.php (las 3 primeras columnas son botones sin título)
COLUMNAS_REPORTE = [
    "", "", "",
    "Id", "Tipo ticket", "Estatus", "Tipo Servicio", "Sub Tipo", "No.Placa", "PUSite", "# Reserva", "# Cliente",
    "Nombre Cliente", "Grupo", "Marca", "Modelo", "Km.Actual", "Ciudad", "Taller",
    "Fecha Alta", "Hora Alta", "Fecha Prop.Cita", "Hora Prop.Cita", "Fecha Cita", "Hora Cita",
    "Fecha Ingreso Taller", "Dias Cte. Entr. Taller", "Hora Ingreso Taller", "Fecha Promesa", "Hora Promesa",
    "Fecha Diagnóstico", "Hora Diagnóstico", "Fecha T.Terminado", "Hora T.Terminado",
    "Fecha Entrega Cliente", "Dias Taller", "Hora Entrega Cliente", "Fecha Cierre", "Hora Cierre",
    "Fecha Reingreso", "Hora Reingreso", "Motivo Reingreso", "Facturado", "Pagado", "Costo Total",
    "Cobro cliente", "Monto cliente", "Costo Real", "Comentarios Cliente", "Diagnóstico",
    "Se ha realizado la afinación de esta unidad?", "CANTIDAD LLANTAS", "Responsable Alta",
    "Nombre Contacto", "Tel. Contacto", "Cel. Contacto", "Correo",
    "PUDate", "ReturnDate", "Asesor", "Origen", "IdApp",
]
ANCHO_REPORTE = len(COLUMNAS_REPORTE)                      # 62
IDX_BOTONES = (0, 1, 2)
COLUMNAS_CONTACTO = ("Nombre Contacto", "Tel. Contacto", "Cel. Contacto", "Correo")
IDX_SALIDA = [i for i in range(ANCHO_REPORTE)
              if i not in IDX_BOTONES and COLUMNAS_REPORTE[i] not in COLUMNAS_CONTACTO]
ENCABEZADO = [COLUMNAS_REPORTE[i] for i in IDX_SALIDA]    # las 55 columnas de la hoja

FECHAS = {n for n in ENCABEZADO if n.startswith("Fecha ") or n in ("PUDate", "ReturnDate")}
HORAS = {n for n in ENCABEZADO if n.startswith("Hora ")}
NUMEROS = {"Id", "Km.Actual", "Dias Cte. Entr. Taller", "Dias Taller", "Costo Total", "Monto cliente",
           "Costo Real", "CANTIDAD LLANTAS", "IdApp"}
COSTOS = ("Costo Total", "Monto cliente", "Costo Real")

COL_ID = ENCABEZADO.index("Id")
COL_ESTATUS = ENCABEZADO.index("Estatus")
COL_PLACA = ENCABEZADO.index("No.Placa")
COL_FECHA_ALTA = ENCABEZADO.index("Fecha Alta")
ESTATUS_CERRADOS = ("CERRADO", "CANCELADO")

HOJA_POR_DEFECTO = "ORDENES MTTO"
COL_ESTADO = len(ENCABEZADO) + 2                           # una columna libre de por medio, a la derecha de los datos
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SEG = 180
REINTENTOS = 5
UMBRAL_SALVAGUARDA = 0.8
MINIMO_PARA_SALVAGUARDA = 30
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HORA_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
NUMERO_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
BASE_SERIAL = dt.date(1899, 12, 30)


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 200 caracteres: %r", texto[:200])
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


def ventana(hoy: dt.date = None) -> tuple[str, str]:
    """(desde, hasta) ISO del mes corriente a AYER (hora CDMX). Si hoy es día 1, el mes anterior completo.
    FECHA_DESDE/FECHA_HASTA fijan el rango (pruebas y recuperaciones)."""
    hoy = hoy or dt.datetime.now(ZONA).date()
    ayer = hoy - dt.timedelta(days=1)
    hasta = os.environ.get("FECHA_HASTA") or ayer.isoformat()
    desde = os.environ.get("FECHA_DESDE") or dt.date.fromisoformat(hasta).replace(day=1).isoformat()
    return desde, hasta


def consultar(session: requests.Session, criterio: str, estatus: str = "1", desde: str = "", hasta: str = "") -> list[list]:
    """Una consulta del filtro de la página. Estatus siempre con valor (ver docstring del módulo)."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(
        f"{base_url}/json/lp-mtto-ordenes.php",
        data={"Criterio": criterio, "Estatus": estatus, "Desde": desde, "Hasta": hasta, "valueCriterio": ""},
        timeout=TIMEOUT_SEG,
    )
    data = _parse_json_bom(resp).get("data")
    if data in ("", None):
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"Maxinet devolvió un 'data' inesperado ({type(data).__name__}); no se escribió nada.")
    return data


# -------------------------------------------------------- limpieza y tipos
def _texto(v) -> str:
    """Texto sin etiquetas HTML ni espacios sobrantes; el 'None' que imprime el reporte es vacío."""
    if v is None:
        return ""
    s = html.unescape(re.sub(r"<[^>]*>", "", str(v))).replace("\xa0", " ").strip()
    return "" if s in ("None", "null", "NULL") else s


def normalizar_filas(filas: list[list]) -> list[list[str]]:
    """Las 62 celdas de cada fila ya limpias. Un ancho distinto, o columnas que no cuadren (Id sin forma de
    número, Fecha Alta sin forma de fecha, placa vacía), detienen la corrida SIN escribir nada."""
    anchos = {len(f) for f in filas}
    if anchos - {ANCHO_REPORTE}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte de órdenes: llegaron filas de {sorted(anchos)} columnas y se "
            f"esperan {ANCHO_REPORTE}. No se escribió nada en el Sheet; revisar json/lp-mtto-ordenes.php y ajustar "
            f"COLUMNAS_REPORTE."
        )
    out = []
    for f in filas:
        fila = [_texto(v) for v in f]
        orden = fila[IDX_SALIDA[COL_ID]]
        if (not orden.isdigit() or not FECHA_RE.match(fila[IDX_SALIDA[COL_FECHA_ALTA]])
                or not fila[IDX_SALIDA[COL_PLACA]]):
            raise RuntimeError(
                f"Las columnas del reporte de órdenes no cuadran (Id={orden[:20]!r}, "
                f"Fecha Alta={fila[IDX_SALIDA[COL_FECHA_ALTA]][:20]!r}). No se escribió nada en el Sheet."
            )
        out.append(fila)
    return out


def _valor(nombre: str, texto: str):
    """Valor tipado de una celda: fecha y hora como número de serie, números como número, el resto como texto.
    Lo que no tenga la forma esperada (por ejemplo una fecha con año 0026 tecleada mal) se conserva como texto."""
    if texto == "":
        return ""
    if nombre in FECHAS and FECHA_RE.match(texto):
        try:
            d = dt.date.fromisoformat(texto)
        except ValueError:
            return texto
        return (d - BASE_SERIAL).days if 2000 <= d.year <= 2100 else texto
    if nombre in HORAS:
        m = HORA_RE.match(texto)
        if m and int(m[1]) < 24 and int(m[2]) < 60 and int(m[3] or 0) < 60:
            return (int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)) / 86400
        return texto
    if nombre in NUMEROS:
        t = texto.replace(",", "")
        if NUMERO_RE.match(t):
            return float(t) if "." in t else int(t)
    return texto


def a_fila_hoja(fila: list[str]) -> list:
    """Las 55 columnas de la hoja, tipadas, a partir de las 62 limpias."""
    return [_valor(ENCABEZADO[k], fila[i]) for k, i in enumerate(IDX_SALIDA)]


def unir(en_ventana: list[list[str]], abiertas: list[list[str]]) -> list[list]:
    """Órdenes del rango más las abiertas, sin repetir Id (gana la primera), ordenadas por Id."""
    por_id = {}
    for fila in en_ventana + abiertas:
        por_id.setdefault(int(fila[IDX_SALIDA[COL_ID]]), fila)
    return [a_fila_hoja(por_id[i]) for i in sorted(por_id)]


# ------------------------------------------------------------------ Sheet
def _col_a1(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n)[:-1]


ULT_COL = _col_a1(len(ENCABEZADO))                          # "BC"


def nombre_hoja() -> str:
    return (os.environ.get("WORKSHEET_MTTO_ORDENES") or "").strip().strip("\"'").strip() or HOJA_POR_DEFECTO


def conectar_libro():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(os.environ["SPREADSHEET_ID"])


def obtener_hoja(libro, nombre: str, filas_necesarias: int, crear: bool):
    """La pestaña, o None si no existe y no se debe crear (DRY_RUN). Se crea con espacio para las filas."""
    try:
        return libro.worksheet(nombre)
    except gspread.exceptions.WorksheetNotFound:
        if not crear:
            return None
        hoja = libro.add_worksheet(title=nombre, rows=max(2000, filas_necesarias + 500), cols=COL_ESTADO + 1)
        log.info("Creada la pestaña %s", nombre)
        return hoja


def _leer_hoja(hoja) -> tuple[list, list]:
    """(encabezado, filas con datos) de la pestaña; ([], []) si está vacía."""
    todo = hoja.get(f"A1:{ULT_COL}", value_render_option="UNFORMATTED_VALUE") if hoja else []
    if not todo:
        return [], []
    filas = [list(f) + [""] * (len(ENCABEZADO) - len(f)) for f in todo[1:] if f and str(f[0]).strip() != ""]
    return list(todo[0]), filas


def _serie(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _resumen_y_salvaguarda(viejas: list, nuevas: list, desde: str, hasta: str) -> dict:
    """Altas, bajas y cambios de estatus por Id, y la salvaguarda contra respuestas incompletas."""
    ant = {int(f[COL_ID]): str(f[COL_ESTATUS]).strip() for f in viejas if _serie(f[COL_ID]) is not None}
    act = {int(f[COL_ID]): str(f[COL_ESTATUS]).strip() for f in nuevas}
    s_desde = (dt.date.fromisoformat(desde) - BASE_SERIAL).days
    s_hasta = (dt.date.fromisoformat(hasta) - BASE_SERIAL).days
    en_rango = lambda f: _serie(f[COL_FECHA_ALTA]) is not None and s_desde <= f[COL_FECHA_ALTA] <= s_hasta
    abierta = lambda estatus: estatus.upper() not in ESTATUS_CERRADOS
    viejas_rango = sum(1 for f in viejas if en_rango(f))
    nuevas_rango = sum(1 for f in nuevas if en_rango(f))
    viejas_abiertas = sum(1 for e in ant.values() if abierta(e))
    nuevas_abiertas = sum(1 for e in act.values() if abierta(e))
    res = {
        "antes": len(viejas), "despues": len(nuevas),
        "altas": sum(1 for i in act if i not in ant), "bajas": sum(1 for i in ant if i not in act),
        "estatus": sum(1 for i in act if i in ant and ant[i] != act[i]),
        "rango": nuevas_rango, "abiertas": nuevas_abiertas,
    }
    if not os.environ.get("FORZAR"):
        for etiqueta, viejo, nuevo in (("de alta en el rango", viejas_rango, nuevas_rango),
                                       ("abiertas", viejas_abiertas, nuevas_abiertas)):
            if viejo >= MINIMO_PARA_SALVAGUARDA and nuevo < UMBRAL_SALVAGUARDA * viejo:
                raise RuntimeError(
                    f"Maxinet trae {nuevo} órdenes {etiqueta} y la hoja tiene {viejo}: menos del 80%. Probable respuesta "
                    f"incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    return res


def _formatos(hoja, filas_hoja: int) -> list:
    """Formato de encabezado, panel inmovilizado y formatos de fecha, hora y costo (idempotente)."""
    def col(nombre):
        return ENCABEZADO.index(nombre)

    def rango(c, f1=1, f2=None):
        return {"sheetId": hoja.id, "startRowIndex": f1, "endRowIndex": f2 or filas_hoja,
                "startColumnIndex": c, "endColumnIndex": c + 1}

    def formato(nombres, tipo, patron):
        return [{"repeatCell": {"range": rango(col(n)), "fields": "userEnteredFormat.numberFormat",
                                "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}}}}
                for n in nombres]

    pedidos = [
        {"updateSheetProperties": {"properties": {"sheetId": hoja.id, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1,
                                  "startColumnIndex": 0, "endColumnIndex": len(ENCABEZADO)},
                        "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True},
                                                       "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}}}},
    ]
    pedidos += formato(sorted(FECHAS), "DATE", "yyyy-mm-dd")
    pedidos += formato(sorted(HORAS), "TIME", "hh:mm")
    pedidos += formato(COSTOS, "NUMBER", "#,##0.00")
    return pedidos


def refrescar(hoja, libro, nombre: str, filas: list[list], desde: str, hasta: str) -> dict:
    """Reescribe la pestaña con las órdenes de Maxinet. `hoja` es None si todavía no existe."""
    encabezado, viejas = _leer_hoja(hoja)
    if encabezado and [str(h).strip() for h in encabezado[:len(ENCABEZADO)]] != ENCABEZADO:
        raise RuntimeError(
            f"La pestaña {nombre} tiene un encabezado distinto al esperado (alguien movió o cambió columnas); "
            f"no se escribió nada. Revisar la hoja o ajustar COLUMNAS_REPORTE.")
    if not filas:
        raise RuntimeError("Maxinet no trajo ninguna orden (ni del rango ni abiertas); no se escribió nada.")
    r = _resumen_y_salvaguarda(viejas, filas, desde, hasta)
    log.info("Hoja %s: filas %d -> %d | altas %d, bajas %d, estatus cambiados %d | del rango %d, abiertas %d",
             nombre, r["antes"], r["despues"], r["altas"], r["bajas"], r["estatus"], r["rango"], r["abiertas"])
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reescribirían A1:%s%d (%d órdenes) (no se escribió nada).", ULT_COL, len(filas) + 1, len(filas))
        return r

    hoja = hoja or obtener_hoja(libro, nombre, len(filas) + 1, crear=True)
    ultima_vieja = r["antes"] + 1
    ultima = len(filas) + 1
    if ultima > hoja.row_count:
        hoja.add_rows(ultima - hoja.row_count + 200)
    hoja.update(range_name=f"A1:{ULT_COL}{ultima}", values=[ENCABEZADO] + filas, value_input_option="RAW")
    if ultima_vieja > ultima:                               # la hoja quedó más corta: limpiar lo que sobra
        hoja.batch_clear([f"A{ultima + 1}:{ULT_COL}{ultima_vieja}"])
    ahora = dt.datetime.now(ZONA).strftime("%Y-%m-%d %H:%M")
    hoja.update(range_name=f"{_col_a1(COL_ESTADO)}1:{_col_a1(COL_ESTADO)}4", value_input_option="RAW",
                values=[["ACTUALIZADO (hora CDMX)"], [ahora], ["VENTANA"], [f"{desde} a {hasta} + abiertas"]])
    libro.batch_update({"requests": _formatos(hoja, hoja.row_count)})
    log.info("Hoja reescrita: %d órdenes en A1:%s%d", len(filas), ULT_COL, ultima)
    return r


def validar_sin_repetidos(hoja):
    """Ningún Id debe repetirse en la hoja; si ocurre, la corrida falla."""
    vistos, dups = set(), set()
    for v in hoja.col_values(1)[1:]:
        k = str(v).strip()
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"Id repetido en la hoja ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin Ids repetidos en la hoja")


def main():
    try:
        desde, hasta = ventana()
        session = login_maxinet()
        en_ventana = normalizar_filas(consultar(session, "ALTA", "1", desde, hasta))
        abiertas = normalizar_filas(consultar(session, "ESTATUS", "1"))
        log.info("Datos descargados de Maxinet: %d órdenes de alta del %s al %s y %d abiertas",
                 len(en_ventana), desde, hasta, len(abiertas))
        filas = unir(en_ventana, abiertas)
        libro = conectar_libro()
        nombre = nombre_hoja()
        hoja = obtener_hoja(libro, nombre, len(filas) + 1, crear=False)
        r = refrescar(hoja, libro, nombre, filas, desde, hasta)
        if not os.environ.get("DRY_RUN"):
            validar_sin_repetidos(libro.worksheet(nombre))
        log.info("Automatización completada con éxito (%d órdenes: %d del rango y %d abiertas)",
                 r["despues"], r["rango"], r["abiertas"])
    except Exception:
        log.exception("Error en la automatización de Órdenes de Mantenimiento")
        sys.exit(1)


if __name__ == "__main__":
    main()
