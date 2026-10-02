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
            respuesta: dict {"data": [[...16 valores...], ...]}, cada fila ya
            en el orden de COLUMNAS (sin columna de acciones al inicio).
            SUB_TOTAL llega numérico en texto ("1409.48"); el "$ " del
            navegador lo agrega el render de DataTables, no el servidor.

Regla de fechas ("día vencido", decidida por el usuario): se consulta
Desde = ayer, Hasta = hoy (hora Ciudad de México). Ej.: el 29 se consulta del
28 al 29 y el servidor devuelve los clientes creados el 28.

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
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
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


def _parse_json_bom(resp: requests.Response):
    """Maxinet suele anteponer un BOM UTF-8 a sus respuestas JSON."""
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
        raise


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


def rango_fechas() -> tuple[str, str]:
    """Día vencido: ayer -> hoy en hora CDMX (o el override de entorno)."""
    hoy = datetime.now(ZONA).date()
    desde = os.environ.get("FECHA_DESDE") or (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
    hasta = os.environ.get("FECHA_HASTA") or hoy.strftime("%Y-%m-%d")
    return desde, hasta


def descargar_clientes_nuevos(desde: str, hasta: str) -> pd.DataFrame:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    resp = session.post(
        f"{base_url}/json/clientes-nuevos-data.php",
        data={"Desde": desde, "Hasta": hasta},
    )
    payload = _parse_json_bom(resp)

    df = pd.DataFrame(payload["data"], columns=COLUMNAS)
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
    nombre = os.environ.get("WORKSHEET_CLIENTES_NUEVOS_NAME") or "Reporte Generales Clientes Nuevo"
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

    valores = [[_celda(r[c], c) for c in COLUMNAS] for _, r in df_nuevos.iterrows()]
    fila_inicio = ultima_fila + 1
    fila_fin = fila_inicio + len(valores) - 1
    rango = f"{COL_INICIO}{fila_inicio}:{COL_FIN}{fila_fin}"
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
