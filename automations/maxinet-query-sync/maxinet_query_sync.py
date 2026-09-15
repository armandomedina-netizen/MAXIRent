"""
Automatización diaria: login + descarga del reporte "Cargo de Reservas"
desde Maxinet (vía requests, sin navegador) y reemplazo total de la base
de datos en la pestaña "QUERY" de un Google Sheet.

Endpoint confirmado a partir del HTML/JS reales de Maxinet
(reporte-cargo-de-reservas.php):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
            body: email=<usuario>, password=<contraseña>
    Datos:  POST {MAXINET_BASE_URL}/includes/reportesLP/reporte-cargo_de_reservas.php
            body: Estatus=ALL, Desde=2000-01-01, Hasta=2099-12-31
            (el formulario trae por defecto Estatus=ONHIRE y Desde=Hasta=
            hoy, pero eso solo trae las reservas ON HIRE del día -- "QUERY"
            alimenta otras pestañas del mismo Sheet, como "TARIFA (QUERY)",
            que esperan encontrar TODAS las reservas, históricas y activas.
            Se usa Estatus=ALL con un rango de fechas deliberadamente
            amplio para traer el histórico completo cada vez)
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

Flujo:
    1. Login en Maxinet.
    2. Descarga el reporte de Cargo de Reservas completo (Estatus=ALL, todo
       el rango de fechas) -- no se filtra ni transforma nada, el reporte
       ya viene tal cual.
    3. Reemplaza POR COMPLETO el bloque A2:O... de la pestaña "QUERY" con
       los datos nuevos, sin encabezados (no se hace merge/match por fila;
       el reporte de Maxinet reemplaza al anterior tal cual).
"""

import os
import sys
import json
import logging

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
    return json.loads(resp.content.decode("utf-8-sig"))


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


def descargar_cargo_de_reservas(session: requests.Session) -> pd.DataFrame:
    """
    Pide al endpoint de Cargo de Reservas con Estatus=ALL y un rango de
    fechas amplio (en vez de Estatus=ONHIRE / Desde=Hasta=hoy, que eran los
    valores por defecto del formulario).

    IMPORTANTE (corregido tras romper "TARIFA (QUERY)"/"TABLA RESUMEN" el
    2026-09-15): la pestaña "QUERY" no es un snapshot de "solo lo de hoy" --
    otras pestañas del mismo Sheet (ej. "TARIFA (QUERY)") le hacen FILTER/
    búsquedas esperando encontrar TODAS las reservas, históricas y activas.
    Con Estatus=ONHIRE + Desde=Hasta=hoy, cualquier reserva que no estuviera
    ON HIRE justo hoy desaparecía de "QUERY" y esas búsquedas fallaban con
    #N/A. Por eso aquí se pide Estatus=ALL con un rango de fechas
    deliberadamente amplio (2000-01-01 a 2099-12-31) para no depender de
    qué campo de fecha filtra realmente el reporte del lado de Maxinet.
    """
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")

    resp = session.post(
        f"{base_url}/includes/reportesLP/reporte-cargo_de_reservas.php",
        data={"Estatus": "ALL", "Desde": "2000-01-01", "Hasta": "2099-12-31"},
    )
    payload = _parse_json_bom(resp)

    df = pd.DataFrame(payload["data"], columns=COLUMNAS)
    log.info("Datos descargados de Maxinet: %d filas (Estatus=ALL, todo el histórico)", len(df))
    return df


def conectar_sheet_query():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID_QUERY"])
    nombre_pestana = os.environ.get("WORKSHEET_QUERY_NAME", "QUERY")
    return sh.worksheet(nombre_pestana)


# Rango fijo de datos: sin encabezados, desde A2 hasta O... (15 columnas,
# igual orden que COLUMNAS). A diferencia de automations/maxinet-sync, aquí
# no hay columnas con fórmulas propias que proteger a la derecha.
COL_INICIO = "A"
COL_FIN = "O"
FILA_INICIO_DATOS = 2
# Buffer de filas a limpiar antes de escribir, por si el reporte de hoy trae
# menos filas que el anterior (evita dejar datos viejos "pegados" abajo)
MAX_FILAS_BUFFER = 5000


def actualizar_query(worksheet, df_nuevo: pd.DataFrame):
    """
    Reemplaza POR COMPLETO el bloque de datos A2:O... con el reporte
    descargado hoy: no se hace merge/match por fila, el reporte de Maxinet
    reemplaza al anterior tal cual (decisión del usuario).
    """
    n_filas = len(df_nuevo)

    # 1. Limpiar todo el rango de datos posible (por si hoy hay menos filas
    #    que antes, para no dejar residuos de la corrida previa)
    rango_limpiar = f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{FILA_INICIO_DATOS + MAX_FILAS_BUFFER}"
    worksheet.batch_clear([rango_limpiar])

    if n_filas == 0:
        log.warning("El reporte de Maxinet vino vacío -- QUERY se dejó limpio, sin filas nuevas.")
        return

    # 2. Escribir los datos nuevos. fillna("") antes de astype(str): de lo
    #    contrario los valores nulos quedan como float NaN, que no es JSON
    #    válido y la API de Sheets rechaza la petición (mismo bug ya
    #    confirmado en automations/maxinet-sync).
    fila_final = FILA_INICIO_DATOS + n_filas - 1
    rango_datos = f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{fila_final}"
    worksheet.update(values=df_nuevo.fillna("").astype(str).values.tolist(), range_name=rango_datos)

    log.info("QUERY actualizado: %d filas escritas en %s", n_filas, rango_datos)


def main():
    try:
        session = login_maxinet()
        df_nuevo = descargar_cargo_de_reservas(session)

        worksheet = conectar_sheet_query()
        actualizar_query(worksheet, df_nuevo)

        log.info("Automatización completada con éxito")
    except Exception:
        log.exception("Error en la automatización diaria de Cargo de Reservas")
        sys.exit(1)


if __name__ == "__main__":
    main()
