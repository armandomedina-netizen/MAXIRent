"""
Automatización diaria (día vencido): login + descarga del reporte
"Generales Clientes Nuevos CP" desde Maxinet vía requests (sin navegador) y
agregado incremental de las filas nuevas debajo del último registro de la
pestaña "Reporte Generales Clientes Nuevo" de un Google Sheet.

Endpoint confirmado a partir del JS real de Maxinet
(generales-clientes-nuevos-cp.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
            body: email=<usuario>, password=<contraseña>
    Datos:  POST {MAXINET_BASE_URL}/json/clientes-nuevos-data.php
            body: Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD
            respuesta: dict {"data": [[...], ...]}. Desde 2026-10-08 cada fila
            trae 17 valores: una columna de acciones al inicio (enlace "Editar"
            o vacía) y luego las 16 de COLUMNAS, en ese orden. Antes eran 16.
            SUB_TOTAL llega numérico en texto ("1409.48"); el "$ " del
            navegador lo agrega el render de DataTables, no el servidor.

Regla de fechas (decidida por el usuario): el filtro es el mes corriente, igual
que el que trae el formulario por defecto: Desde = primer día del mes, Hasta =
hoy (hora Ciudad de México). Cada corrida lee todo el mes y agrega sólo lo que
todavía no está en el Sheet, así que también recoge a los clientes que Maxinet
registra con días de retraso. Los primeros 3 días del mes se incluye además el
mes anterior (un cliente creado el último día del mes se importa al día
siguiente). Los clientes de hoy se agregan con lo que haya a esa hora y los que
falten se completan en la corrida siguiente.

Estructura de la pestaña destino (confirmada contra el Sheet real):
    - Columna A (PERIODO) y columnas R:V (TIPO DE CLIENTE, RECLASIFICADO, año,
      MES...) son FÓRMULAS ya arrastradas de antemano hasta la fila 17441 --
      no son de esta automatización y NUNCA se tocan.
    - Los datos van en B:Q (16 columnas, mismo orden que COLUMNAS), debajo de
      la última fila con ClientNo en la columna B. Ese rango ya trae el
      formato de fecha/hora/moneda aplicado hasta abajo.

Filas nuevas: se calcula la fila exacta (última fila con dato en B + 1) y se
escribe con update() -- NUNCA con append_rows(), que en Sheets con formato o
fórmulas más abajo del último dato real decide mal dónde "termina la tabla"
(bug real ya sufrido en automations/automatización Gestoría).

Sin repetidos: se omiten filas cuyo ClientNo (col B) o BookingNo (col F) ya
exista en el Sheet o se repita dentro del reporte, y al final se valida todo
el Sheet; si aparece un repetido la corrida falla (exit 1).

Variables de entorno esperadas (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS
    GOOGLE_CREDS_PATH
    SPREADSHEET_ID_CLIENTES_NUEVOS
    WORKSHEET_CLIENTES_NUEVOS_NAME (por defecto "Reporte Generales Clientes Nuevo")
    FECHA_DESDE, FECHA_HASTA (opcionales; solo para pruebas/corridas manuales)
    DRY_RUN (opcional; solo informa lo que agregaría, sin escribir)
"""

import os
import sys
import re
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd
import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_clientes_nuevos_cp")

# Orden confirmado en el HTML real de generales-clientes-nuevos-cp.php
COLUMNAS = [
    "ClientNo", "CreationDate", "NoRentas", "Última Renta", "BookingNo",
    "RequiredGroup", "Name", "PUDate", "PUTime", "PUSite", "BOOKED BY",
    "SUB_TOTAL", "RegistrationNo", "CURRENT_REG_NO", "Método de Pago", "DateImport",
]

COL_INICIO = "B"
COL_FIN = "Q"
COL_CLAVE = 2        # B: ClientNo, define la "última fila con datos"
COL_BOOKING = 6      # F: BookingNo, para no duplicar
FILA_INICIO_DATOS = 2
ZONA = ZoneInfo("America/Mexico_City")
DIAS_MES_ANTERIOR = 3   # los primeros días del mes se incluye también el mes anterior (ver rango_fechas)
TIMEOUT_SEG = 90
REINTENTOS = 5
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_json_bom(resp: requests.Response):
    """Maxinet suele anteponer un BOM UTF-8 a sus respuestas JSON."""
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
        raise


def _nueva_sesion() -> requests.Session:
    """Sesión que reintenta con espera creciente si Maxinet corta la conexión
    o responde 502/503/504 (incluye POST, que urllib3 no reintenta por defecto)."""
    session = requests.Session()
    retry = Retry(
        total=REINTENTOS, connect=REINTENTOS, read=REINTENTOS, status=REINTENTOS,
        backoff_factor=2, status_forcelist=(502, 503, 504), allowed_methods=None,
    )
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
    """Mes corriente: del primer día del mes a hoy (hora CDMX), o el override de entorno.

    Los primeros DIAS_MES_ANTERIOR días del mes se arranca desde el primer día del mes
    anterior: un cliente creado el último día de un mes se importa a Maxinet al día
    siguiente y, sin esto, quedaría fuera de la ventana para siempre."""
    hoy = datetime.now(ZONA).date()
    hasta = os.environ.get("FECHA_HASTA") or hoy.isoformat()
    h = date.fromisoformat(hasta)
    inicio = h.replace(day=1)
    if h.day <= DIAS_MES_ANTERIOR:
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    desde = os.environ.get("FECHA_DESDE") or inicio.isoformat()
    return desde, hasta


def normalizar_filas(filas: list[list]) -> list[list]:
    """Deja cada fila con exactamente las 16 columnas de COLUMNAS.

    Maxinet puede anteponer una columna de acciones (enlace "Editar" en
    algunos clientes creados por la web, vacía en el resto); desde el
    2026-10-08 el reporte llega con 17 columnas. Esa primera columna se
    descarta. Cualquier otro ancho, o columnas que no cuadren con lo esperado,
    detienen la corrida SIN escribir nada: es preferible fallar que pegar
    datos corridos de columna en el Sheet.
    """
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    n = len(COLUMNAS)
    if anchos - {n, n + 1}:
        raise RuntimeError(
            f"Maxinet cambió el ancho del reporte: llegaron filas de {sorted(anchos)} columnas y se esperan "
            f"{n} (o {n + 1} con la columna de acciones al inicio). No se escribió nada en el Sheet; "
            f"revisar json/clientes-nuevos-data.php y ajustar COLUMNAS."
        )
    if len(anchos) > 1:
        raise RuntimeError(f"Maxinet devolvió filas de anchos mezclados {sorted(anchos)}. No se escribió nada en el Sheet.")
    if n + 1 in anchos:
        filas = [f[1:] for f in filas]
    for f in filas:
        # Control de alineación: ClientNo sin HTML y CreationDate con forma de fecha
        if not f[0] or "<" in str(f[0]) or not FECHA_RE.match(str(f[1] or "")):
            raise RuntimeError(
                f"Las columnas del reporte de Maxinet no cuadran (ClientNo={str(f[0])[:40]!r}, "
                f"CreationDate={str(f[1])[:40]!r}). No se escribió nada en el Sheet."
            )
    return filas


def descargar_clientes_nuevos(desde: str, hasta: str) -> pd.DataFrame:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    resp = session.post(
        f"{base_url}/json/clientes-nuevos-data.php",
        data={"Desde": desde, "Hasta": hasta},
        timeout=TIMEOUT_SEG,
    )
    payload = _parse_json_bom(resp)

    df = pd.DataFrame(normalizar_filas(payload["data"]), columns=COLUMNAS)
    log.info("Datos descargados de Maxinet: %d filas (Desde=%s, Hasta=%s)", len(df), desde, hasta)

    # Campos de texto de ancho fijo con espacios al final; pandas 3.x puede
    # inferirlos como dtype "string", por eso se checan ambos dtypes.
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].str.strip()
    return df


def conectar_sheet():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID_CLIENTES_NUEVOS"])
    # Un secret pegado con comillas o espacios no debe romper el nombre de la pestaña
    nombre = (os.environ.get("WORKSHEET_CLIENTES_NUEVOS_NAME") or "").strip().strip("\"'").strip() or "Reporte Generales Clientes Nuevo"
    return sh.worksheet(nombre)


def _celda(valor, col: str):
    """Valor listo para USER_ENTERED: nulos -> "", SUB_TOTAL -> número (el
    Sheet ya le da el formato de moneda), y sin riesgo de que un texto que
    empiece con '=' o '$' se interprete como fórmula/moneda."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if col == "SUB_TOTAL":
        try:
            return float(str(valor).replace("$", "").replace(",", "").strip())
        except ValueError:
            return str(valor)
    texto = str(valor)
    # "$349357B"-style IDs: Sheets los interpreta como moneda y los daña
    # (ej. "349,357.00$"), por eso también se fuerzan a texto.
    if texto.startswith(("=", "+", "@", "$")):
        return "'" + texto
    return texto


def _llave(nombre, creacion, placa) -> tuple:
    norm = lambda x: " ".join(str(x or "").split()).upper()
    return (norm(nombre), norm(creacion), norm(placa))


def _duplicados(valores: list[str]) -> set[str]:
    vistos, dups = set(), set()
    for v in valores:
        v = v.strip()
        if not v:
            continue
        (dups if v in vistos else vistos).add(v)
    return dups


def validar_sin_repetidos(worksheet):
    """Revisa TODO el Sheet: ClientNo (B) y BookingNo (F) no deben repetirse.
    Falla la corrida (exit 1) si encuentra alguno, para no dejar pasar datos
    erróneos sin que nadie se entere."""
    for col, nombre in ((COL_CLAVE, "ClientNo"), (COL_BOOKING, "BookingNo")):
        dups = _duplicados(worksheet.col_values(col)[FILA_INICIO_DATOS - 1:])
        if dups:
            raise RuntimeError(f"{nombre} repetido en el Sheet ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin ClientNo ni BookingNo repetidos en el Sheet")


def agregar_filas_nuevas(worksheet, df: pd.DataFrame) -> int:
    col_b = worksheet.col_values(COL_CLAVE)
    ultima_fila = max((i for i, v in enumerate(col_b, start=1) if v.strip()), default=FILA_INICIO_DATOS - 1)
    clientes_existentes = {v.strip() for v in col_b[FILA_INICIO_DATOS - 1:]}
    bookings_existentes = {v.strip() for v in worksheet.col_values(COL_BOOKING)[FILA_INICIO_DATOS - 1:]}
    # Llave compuesta de respaldo (Nombre + CreationDate + CURRENT_REG_NO):
    # atrapa registros ya presentes cuyo ID quedó dañado por el formato del
    # Sheet (ej. "$349357B" guardado como "349,357.00$").
    existentes_compuesta = {
        _llave(f[6], f[1], f[13])
        for f in worksheet.get(f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{ultima_fila}")
        if len(f) > 13
    }

    # Repetidos dentro del propio reporte descargado (mismo ClientNo o BookingNo)
    antes = len(df)
    df = df.drop_duplicates(subset=["ClientNo"]).drop_duplicates(subset=["BookingNo"])
    if antes - len(df):
        log.warning("Filas repetidas dentro del reporte de Maxinet, se conserva la primera: %d", antes - len(df))

    # Repetidos contra lo que ya existe en el Sheet (ClientNo O BookingNo)
    llaves = [_llave(n, c, r) for n, c, r in zip(df["Name"], df["CreationDate"], df["CURRENT_REG_NO"])]
    ya_existe = (
        df["ClientNo"].isin(clientes_existentes)
        | df["BookingNo"].isin(bookings_existentes)
        | pd.Series([k in existentes_compuesta for k in llaves], index=df.index)
    )
    df_nuevos = df[~ya_existe]
    if ya_existe.sum():
        log.info("Filas omitidas por ClientNo/BookingNo ya existente en el Sheet: %d", ya_existe.sum())

    if df_nuevos.empty:
        log.info("No hay filas nuevas que agregar.")
        return 0

    # Clientes con fecha de creación anterior al último registro: llegaron tarde a
    # Maxinet. Se agregan igual (no se pierden), debajo del último registro.
    ult = worksheet.get(f"C{ultima_fila}", value_render_option="UNFORMATTED_VALUE")
    if ult and ult[0] and isinstance(ult[0][0], (int, float)):
        ult_fecha = (date(1899, 12, 30) + timedelta(days=int(ult[0][0]))).isoformat()
        tarde = int((df_nuevos["CreationDate"] < ult_fecha).sum())
        if tarde:
            log.warning("Clientes que llegaron tarde a Maxinet (creados antes de %s): %d; se agregan al final.", ult_fecha, tarde)

    # Mismo orden que ya tiene el Sheet: fecha de creación y luego ClientNo
    # (Maxinet entrega por ClientNo, que no sigue la fecha de creación).
    df_nuevos = df_nuevos.sort_values(["CreationDate", "ClientNo"], kind="stable")
    valores = [[_celda(r[c], c) for c in COLUMNAS] for _, r in df_nuevos.iterrows()]
    fila_inicio = ultima_fila + 1
    fila_fin = fila_inicio + len(valores) - 1
    rango = f"{COL_INICIO}{fila_inicio}:{COL_FIN}{fila_fin}"

    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se agregarían %d filas en %s (no se escribió nada)", len(valores), rango)
        return 0
    worksheet.update(range_name=rango, values=valores, value_input_option="USER_ENTERED")
    log.info("Filas nuevas agregadas: %d en %s (última fila previa: %d)", len(valores), rango, ultima_fila)
    return len(valores)


def main():
    try:
        desde, hasta = rango_fechas()
        df = descargar_clientes_nuevos(desde, hasta)
        worksheet = conectar_sheet()
        n = agregar_filas_nuevas(worksheet, df)
        validar_sin_repetidos(worksheet)
        log.info("Automatización completada con éxito (%d filas nuevas)", n)
    except Exception:
        log.exception("Error en la automatización de Clientes Nuevos CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
