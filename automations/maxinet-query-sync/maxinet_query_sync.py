"""
Automatización cada hora: login + descarga del reporte "Cargo de Reservas"
desde Maxinet (vía requests, sin navegador) y reemplazo total de la base de
datos en la pestaña "QUERY" del Sheet "REPORTE TARIFA" (antes copia de
CLIENTES ACTIVOS (QUERY)).

Endpoint confirmado a partir del HTML/JS reales de Maxinet
(reporte-cargo-de-reservas.php):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
            body: email=<usuario>, password=<contraseña>
    Datos:  POST {MAXINET_BASE_URL}/includes/reportesLP/reporte-cargo_de_reservas.php
            body: Estatus=ONHIRE, Desde=Hasta=fecha de hoy (hora CDMX) --
            los mismos valores que trae el formulario por defecto y el botón
            "Excel": el snapshot diario de reservas ON HIRE que se pegaba a
            mano en "QUERY".
            respuesta: JSON estilo DataTables, "data" = lista de listas
            (cada fila ya viene en el orden de COLUMNAS, sin columna de
            acciones al inicio -- a diferencia del reporte de flota)

Requiere:
    pip install -r requirements.txt

Variables de entorno esperadas (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS  -> mismas credenciales que
        automations/maxinet-sync
    GOOGLE_CREDS_PATH     -> ruta al JSON de la cuenta de servicio de Google
    SPREADSHEET_ID_QUERY  -> ID del Google Sheet destino (pestaña "QUERY")
    WORKSHEET_QUERY_NAME  -> nombre de la pestaña (por defecto "QUERY")

Flujo (cada corrida):
    1. Login en Maxinet y descarga del reporte de hoy; sólo se limpian
       espacios de más en las columnas de texto.
    2. Reemplaza POR COMPLETO el bloque A2:O... de "QUERY" con los datos
       nuevos, sin encabezados. Primero escribe y luego limpia lo que sobre,
       para que el Sheet nunca quede vacío a media corrida. Los datos se
       escriben interpretados (fechas y números reales, no texto).
    3. Avisa en el log si alguna placa trae más de una línea RENT.

Desde el 12-oct el Sheet se rediseñó: "TARIFA (QUERY)", "RESUMEN RENTA
ACTIVAS" y las columnas P:R de "QUERY" son fórmulas matriciales que se
calculan solas sobre QUERY!A:O. Por eso el script ya NO escribe fuera de
A:O: no copia reglas del archivo de Nuvia, no extiende fórmulas por fila
ni ajusta TARIFA (escribir en P2 o en B2 de TARIFA bloquearía esos
derrames con #REF!).

PENDIENTE (sin implementar -- falta la regla exacta): si una misma reserva
trae DOS líneas de cargo "RENT" el mismo día para la misma placa, Nuvia
borra a mano la fila duplicada; no se sabe con qué regla decide cuál
conservar. No adivinarla; por ahora sólo se avisa en el log.
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

# Carga las variables desde un archivo ".env" junto a este script (uso local).
# En GitHub Actions no existe ese archivo y las variables ya vienen del
# entorno (Secrets), así que esta llamada simplemente no hace nada.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_query_sync")

# Mismo orden de columnas confirmado en el HTML real de
# reporte-cargo-de-reservas.php (sin columna de acciones al inicio)
COLUMNAS = [
    "BOOKINGNO", "BOOKED_BY", "CURRENT_REG_NO", "CLIENTE", "FECHA_DE_RESERVA",
    "ReturnDate", "CHARGE_FROM", "CHARGE_TO", "GRUPO", "MODELO",
    "PRECIO_COMPRA", "PRECIO_DIARIO", "CONCEPTO_CARGO", "STATUS", "Order Ref",
]


def _parse_json_bom(resp: requests.Response):
    """Maxinet antepone un BOM UTF-8 a sus respuestas JSON, lo que rompe
    resp.json() (mismo comportamiento ya confirmado en el reporte de flota)."""
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # Si Maxinet devuelve algo que no es JSON puro (ej. un warning de PHP
        # antepuesto a la respuesta, o una página de error/sesión vencida),
        # se deja el inicio de la respuesta en el log para poder diagnosticar
        # sin tener que adivinar.
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
        raise


def login_maxinet() -> requests.Session:
    """Inicia sesión en Maxinet y devuelve una sesión con la cookie válida."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    usuario = os.environ["MAXINET_USER"]
    contrasena = os.environ["MAXINET_PASS"]

    session = requests.Session()
    resp = session.post(
        f"{base_url}/includes/users/AccessValidate.php",
        data={"email": usuario, "password": contrasena},
    )
    data = _parse_json_bom(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")

    log.info("Login en Maxinet exitoso")
    return session


def descargar_cargo_de_reservas() -> pd.DataFrame:
    """
    Pide al endpoint de Cargo de Reservas los mismos valores que trae el
    formulario por defecto al abrir la liga (Estatus=ONHIRE, Desde=Hasta=
    fecha de hoy) -- el snapshot diario que ya se pegaba a mano en "QUERY".
    """
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    # El runner de GitHub está en UTC: después de las 18:00 de CDMX ya es
    # "mañana" y se pedía el reporte del día siguiente.
    hoy = datetime.now(ZoneInfo("America/Mexico_City")).strftime("%Y-%m-%d")

    session = login_maxinet()
    resp = session.post(
        f"{base_url}/includes/reportesLP/reporte-cargo_de_reservas.php",
        data={"Estatus": "ONHIRE", "Desde": hoy, "Hasta": hoy},
    )
    payload = _parse_json_bom(resp)

    df = pd.DataFrame(payload["data"], columns=COLUMNAS)
    log.info("Datos descargados de Maxinet: %d filas (Estatus=ONHIRE, fecha %s)", len(df), hoy)

    # Maxinet entrega varios campos de texto (ej. CLIENTE, STATUS, Order Ref)
    # rellenados con espacios al final (campo de ancho fijo en su origen,
    # mismo problema ya confirmado en el reporte de flota) -- si no se
    # limpia, cualquier fórmula del Sheet que compare texto exacto nunca
    # hace match contra el valor real (con espacios de más). OJO: pandas 3.x
    # puede inferir columnas de texto con su nuevo dtype "string" en vez del
    # "object" clásico -- is_object_dtype() por sí solo no las detecta (así
    # se nos coló sin limpiar STATUS/Order Ref en la primera corrida real,
    # mismo bug ya conocido en automations/maxinet-sync), por eso se checan
    # los dos.
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].str.strip()

    return df


def _cliente_gspread():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def conectar_libro_destino():
    return _cliente_gspread().open_by_key(os.environ["SPREADSHEET_ID_QUERY"])


def conectar_sheet_query(libro):
    return libro.worksheet(os.environ.get("WORKSHEET_QUERY_NAME", "QUERY"))


# Rango fijo de datos: sin encabezados, desde A2 hasta O... (15 columnas,
# igual orden que COLUMNAS).
COL_INICIO = "A"
COL_FIN = "O"
FILA_INICIO_DATOS = 2
# Buffer de filas a limpiar antes de escribir, por si el reporte de hoy trae
# menos filas que el anterior (evita dejar datos viejos "pegados" abajo)
MAX_FILAS_BUFFER = 5000

# Columnas que en el Sheet original son números (no fechas ni texto)
COLUMNAS_NUMERICAS = ("PRECIO_COMPRA", "PRECIO_DIARIO")


def _valores_para_hoja(df: pd.DataFrame) -> list:
    """
    Arma las filas a escribir con tipos reales: PRECIO_COMPRA/PRECIO_DIARIO
    como número y todo lo demás como texto (las fechas viajan como
    "AAAA-MM-DD" y Sheets las interpreta como fecha al escribir con
    USER_ENTERED). Los nulos van como "" (un NaN no es JSON válido y la
    API de Sheets rechaza la petición -- bug ya confirmado en
    automations/maxinet-sync).
    """
    df = df.copy()
    for col in COLUMNAS_NUMERICAS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.astype(object).where(df.notna(), "")

    def _celda(v):
        # USER_ENTERED trata como fórmula un texto que empiece con = + -
        if isinstance(v, str) and v[:1] in ("=", "+", "-"):
            return "'" + v
        return v

    return [[_celda(v) for v in fila] for fila in df.values.tolist()]

def _asegurar_filas(worksheet, fila_necesaria: int):
    if fila_necesaria > worksheet.row_count:
        worksheet.add_rows(fila_necesaria - worksheet.row_count)


def avisar_duplicados_rent(df: pd.DataFrame):
    """Solo avisa (no borra): placas con más de una línea RENT el mismo día."""
    rent = df[df["CONCEPTO_CARGO"].str.strip().str.upper() == "RENT"]
    dup = rent[rent.duplicated("CURRENT_REG_NO", keep=False)]
    if len(dup):
        # Solo el conteo: el repo es público y los logs de Actions los puede ver
        # cualquiera con cuenta de GitHub, así que no se imprimen placas ni
        # números de reserva. Para ubicarlas: filtrar RENT repetidos en QUERY!C.
        log.warning("%d placa(s) traen más de una línea RENT; falta definir la regla para cuál conservar",
                    dup["CURRENT_REG_NO"].nunique())


def actualizar_query(worksheet, df_nuevo: pd.DataFrame):
    """
    Reemplaza POR COMPLETO el bloque de datos A2:O... con el reporte
    descargado: el reporte de Maxinet reemplaza al anterior tal cual. Primero
    ESCRIBE los datos nuevos encima y después limpia sólo lo que sobre por
    debajo (A:O), así el Sheet nunca queda vacío ni con errores a media
    corrida.
    """
    n_filas = len(df_nuevo)
    if n_filas == 0:
        log.warning("El reporte de Maxinet vino vacío -- no se toca QUERY para no borrar los datos buenos.")
        return

    # raw=False = USER_ENTERED: con el modo "raw" las fechas y los precios
    # quedaban guardados como texto.
    fila_final = FILA_INICIO_DATOS + n_filas - 1
    _asegurar_filas(worksheet, fila_final)
    rango_datos = f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{fila_final}"
    worksheet.update(values=_valores_para_hoja(df_nuevo), range_name=rango_datos, raw=False)
    log.info("QUERY actualizado: %d filas escritas en %s", n_filas, rango_datos)

    worksheet.batch_clear([f"{COL_INICIO}{fila_final + 1}:{COL_FIN}{fila_final + MAX_FILAS_BUFFER}"])


def main():
    try:
        df_nuevo = descargar_cargo_de_reservas()
        avisar_duplicados_rent(df_nuevo)
        actualizar_query(conectar_sheet_query(conectar_libro_destino()), df_nuevo)
        log.info("Automatización completada con éxito")
    except Exception:
        log.exception("Error en la automatización de Cargo de Reservas")
        sys.exit(1)


if __name__ == "__main__":
    main()
