"""
Automatización diaria: login + lectura del reporte "Clientes Potenciales CP"
desde Maxinet vía requests (sin navegador) y agregado incremental de los
clientes nuevos debajo del último registro de la pestaña "Reporte Clientes
Potenciales CP" del Sheet del Tablero CP.

Endpoint confirmado a partir del JS real de Maxinet
(generales-clientes-frecuentes-cp.php -> DataTable ajax):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/clientesFrecuentesCPData.php
            body: Periodo=mm/yyyy  (el mismo valor que el filtro "Mes")
            respuesta: {"data": [[8 valores], ...]} sin columna de acciones.
    El mes del filtro corresponde al mes de "PUDate 3ra. Renta" (confirmado
    contra el Sheet: columna FECHA = mes de PUDate 3ra. Renta).

Qué columnas se toman: se mapean POR NOMBRE DE ENCABEZADO contra la fila 1 del
Sheet (ClientNo, CreationDate, No. Rentas, Fecha Última Renta, PUSite 3ra.
Renta, PUDate 3ra. Renta, BOOKED BY 3ra. Renta, DateImport -> hoy B:I). Si
falta algún encabezado o las columnas no son contiguas, la corrida falla en
vez de escribir en un lugar equivocado.

Estructura de la pestaña (confirmada contra el Sheet real):
    - A (FECHA) y J:M (STATUS, RECLASIFICADO, AÑO, MES) son FÓRMULAS. No se
      sobrescriben: tras pegar los datos se verifica que esas fórmulas existan
      hasta la última fila con datos y, si falta alguna, se copian desde la
      última fila que sí las tiene.
    - Los formatos de fecha de B:I se copian de la última fila previa, porque
      las filas vacías de abajo no los traen pre-aplicados.

Periodos a consultar (el reporte filtra por mes): el mes en curso y, durante
los primeros días del mes, también el anterior (un cliente con 3ra. renta el
último día del mes se importa al día siguiente y ya cae en el mes anterior).

Sin repetidos: se omite todo ClientNo que ya exista en el Sheet o se repita en
el reporte, y al final se valida todo el Sheet; si hay un ClientNo repetido la
corrida falla (exit 1). Los registros ya pegados NUNCA se modifican, aunque
Maxinet actualice después su No. Rentas o Fecha Última Renta.

NUNCA se usa append_rows(): la fila destino se calcula (última fila con
ClientNo + 1) y se escribe con update().

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet del Tablero CP),
    WORKSHEET_CLIENTES_POTENCIALES_NAME, PERIODOS (opc.), DRY_RUN (opc.)
"""

import os
import sys
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_clientes_potenciales_cp")

# Orden de las columnas que devuelve Maxinet (= encabezados de la tabla)
COLUMNAS = [
    "ClientNo", "CreationDate", "No. Rentas", "Fecha Última Renta",
    "PUSite 3ra. Renta", "PUDate 3ra. Renta", "BOOKED BY 3ra. Renta", "DateImport",
]
COLUMNAS_FORMULA = [1, 10, 11, 12, 13]   # A, J, K, L, M (1-indexado)
FILA_ENCABEZADOS = 1
FILA_INICIO_DATOS = 2
DIAS_MES_ANTERIOR = 7   # primeros N días del mes: consultar también el mes anterior
ZONA = ZoneInfo("America/Mexico_City")


def _parse_json_bom(resp: requests.Response):
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


def periodos_a_consultar() -> list[str]:
    """Meses (mm/yyyy) a consultar, en orden cronológico."""
    manual = os.environ.get("PERIODOS")
    if manual:
        return [p.strip() for p in manual.split(",") if p.strip()]
    hoy = datetime.now(ZONA).date()
    periodos = []
    if hoy.day <= DIAS_MES_ANTERIOR:
        anio, mes = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
        periodos.append(f"{mes:02d}/{anio}")
    periodos.append(f"{hoy.month:02d}/{hoy.year}")
    return periodos


def descargar_clientes_potenciales(periodos: list[str]) -> pd.DataFrame:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    partes = []
    for periodo in periodos:
        resp = session.post(f"{base_url}/json/clientesFrecuentesCPData.php", data={"Periodo": periodo})
        filas = _parse_json_bom(resp)["data"]
        log.info("Periodo %s: %d filas en Maxinet", periodo, len(filas))
        partes.append(pd.DataFrame(filas, columns=COLUMNAS))
    df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLUMNAS)

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
    nombre = os.environ.get("WORKSHEET_CLIENTES_POTENCIALES_NAME") or "Reporte Clientes Potenciales CP"
    return sh.worksheet(nombre)


def mapear_columnas(worksheet) -> tuple[int, int]:
    """Busca cada columna de Maxinet por nombre en la fila de encabezados.
    Devuelve (col_inicio, col_fin) 1-indexadas; falla si falta alguna o si no
    son contiguas y en el mismo orden."""
    encabezados = [h.strip() for h in worksheet.row_values(FILA_ENCABEZADOS)]
    try:
        posiciones = [encabezados.index(c) + 1 for c in COLUMNAS]
    except ValueError as e:
        raise RuntimeError(f"Encabezado de Maxinet no encontrado en el Sheet: {e}") from e
    esperado = list(range(posiciones[0], posiciones[0] + len(COLUMNAS)))
    if posiciones != esperado:
        raise RuntimeError(f"Las columnas del Sheet no son contiguas/ordenadas como en Maxinet: {posiciones}")
    return posiciones[0], posiciones[-1]


def _celda(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor)
    # "=", "+", "@" se interpretarían como fórmula; "$..." como moneda
    if texto.startswith(("=", "+", "@", "$")):
        return "'" + texto
    return texto


def _col_letra(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n).rstrip("1")


def _duplicados(valores: list[str]) -> set[str]:
    vistos, dups = set(), set()
    for v in valores:
        v = v.strip()
        if v:
            (dups if v in vistos else vistos).add(v)
    return dups


def validar_sin_repetidos(worksheet, col_clave: int):
    dups = _duplicados(worksheet.col_values(col_clave)[FILA_INICIO_DATOS - 1:])
    if dups:
        raise RuntimeError(f"ClientNo repetido en el Sheet ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin ClientNo repetidos en el Sheet")


def asegurar_formulas_y_formato(worksheet, col_ini, col_fin, fila_ini, fila_fin, fila_modelo):
    """Copia desde fila_modelo (última fila previa con datos): las fórmulas de
    A y J:M solo en las filas donde falten, y el formato de B:I en las nuevas."""
    sid = worksheet.id
    requests_api = []

    def rango(c1, c2, r1, r2):
        return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2,
                "startColumnIndex": c1 - 1, "endColumnIndex": c2}

    # Formato de los datos nuevos
    requests_api.append({"copyPaste": {
        "source": rango(col_ini, col_fin, fila_modelo, fila_modelo),
        "destination": rango(col_ini, col_fin, fila_ini, fila_fin),
        "pasteType": "PASTE_FORMAT"}})

    # Fórmulas faltantes (columna por columna, sin tocar las que ya existen)
    for col in COLUMNAS_FORMULA:
        letra = _col_letra(col)
        actuales = worksheet.get(f"{letra}{fila_ini}:{letra}{fila_fin}", value_render_option="FORMULA")
        for i in range(fila_fin - fila_ini + 1):
            if i >= len(actuales) or not actuales[i] or not str(actuales[i][0]).startswith("="):
                fila = fila_ini + i
                log.warning("Falta fórmula en %s%d, se copia desde la fila %d", letra, fila, fila_modelo)
                requests_api.append({"copyPaste": {
                    "source": rango(col, col, fila_modelo, fila_modelo),
                    "destination": rango(col, col, fila, fila),
                    "pasteType": "PASTE_FORMULA"}})
    worksheet.spreadsheet.batch_update({"requests": requests_api})


def agregar_filas_nuevas(worksheet, df: pd.DataFrame) -> int:
    col_ini, col_fin = mapear_columnas(worksheet)
    col_clave = col_ini   # ClientNo
    col_b = worksheet.col_values(col_clave)
    ultima_fila = max((i for i, v in enumerate(col_b, start=1) if v.strip() and i >= FILA_INICIO_DATOS),
                      default=FILA_INICIO_DATOS - 1)
    existentes = {v.strip() for v in col_b[FILA_INICIO_DATOS - 1:]}

    antes = len(df)
    df = df.drop_duplicates(subset=["ClientNo"])
    if antes - len(df):
        log.warning("ClientNo repetidos dentro del reporte de Maxinet, se conserva el primero: %d", antes - len(df))

    df_nuevos = df[~df["ClientNo"].isin(existentes)]
    if len(df) - len(df_nuevos):
        log.info("Filas omitidas por ClientNo ya existente en el Sheet: %d", len(df) - len(df_nuevos))
    if df_nuevos.empty:
        log.info("No hay filas nuevas que agregar.")
        return 0

    valores = [[_celda(r[c]) for c in COLUMNAS] for _, r in df_nuevos.iterrows()]
    fila_inicio = ultima_fila + 1
    fila_fin = fila_inicio + len(valores) - 1
    rango = f"{_col_letra(col_ini)}{fila_inicio}:{_col_letra(col_fin)}{fila_fin}"

    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se agregarían %d filas en %s:", len(valores), rango)
        for v in valores:
            log.info("   %s", v)
        return 0

    worksheet.update(range_name=rango, values=valores, value_input_option="USER_ENTERED")
    log.info("Filas nuevas agregadas: %d en %s (última fila previa: %d)", len(valores), rango, ultima_fila)
    asegurar_formulas_y_formato(worksheet, col_ini, col_fin, fila_inicio, fila_fin, ultima_fila)
    return len(valores)


def main():
    try:
        periodos = periodos_a_consultar()
        df = descargar_clientes_potenciales(periodos)
        worksheet = conectar_sheet()
        n = agregar_filas_nuevas(worksheet, df)
        validar_sin_repetidos(worksheet, mapear_columnas(worksheet)[0])
        log.info("Automatización completada con éxito (%d filas nuevas)", n)
    except Exception:
        log.exception("Error en la automatización de Clientes Potenciales CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
