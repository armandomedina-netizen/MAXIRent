"""
Automatización diaria: login + descarga del reporte "Gestoría LP & CP"
(tickets de trámites, siniestros, corralón, daños, etc.) desde Maxinet vía
requests (sin navegador), y sincronización incremental contra la pestaña
"GESTORIA CP - LP" de un Google Sheet dedicado (copia automatizada, no el
Sheet original que usa el equipo a mano).

Endpoint confirmado a partir del JS real de Maxinet
(lp-gestoria-v2-reporte.php -> vendor/DataTables ajax config):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
            body: email=<usuario>, password=<contraseña>
    Datos:  POST {MAXINET_BASE_URL}/api/postventa/gestoria/
            body: Estatus=ABIERTO, Desde=, Hasta=, placa=, alerta_evento=,
            tipoTicketId=, FromSite=, cargo_cliente=0 -- mismos valores que
            trae el formulario por default al abrir la liga (filtro
            "Abierto", sin restricción de fecha). A diferencia de los otros
            reportes de Maxinet ya automatizados, esta respuesta NO trae BOM
            y es un dict con llave "data" = lista de OBJETOS (no listas),
            confirmado contra el servidor real el 2026-09-28.

Lógica de sincronización (decidida por el usuario, no inventada aquí):
    1. Todo folio que venga en el fetch de Maxinet (Estatus=ABIERTO) y que
       NO exista todavía en el Sheet -> se agrega como fila nueva, pegada
       debajo de la última fila con datos (ordenados por Folio ascendente,
       igual que el orden que ya tiene el Sheet).
    2. Todo folio que SÍ exista en el Sheet, cuyo Estatus actual ahí no sea
       ya "CERRADO", y que YA NO aparezca en el fetch de Maxinet (Estatus=
       ABIERTO) -> se marca como "CERRADO" en la columna B, sin tocar el
       resto de la fila.
    3. Caso inverso (Sheet ya dice CERRADO pero Maxinet lo sigue mostrando
       ABIERTO) -> NO se reabre. El usuario no pidió esa regla y no hay que
       adivinarla.
    La columna "Alerta Siniestro" (campo `alerta_evento` de Maxinet) existe
    en el reporte pero NO en este Sheet -- se ignora a propósito, tal como
    indicó el usuario, dejándola documentada aquí por si se agrega después.

Pestaña "2026" (histórico de eventos, mismo Sheet):
    Es un log de solo altas, sin columna de Estatus -- el usuario solo pidió
    insertar ahí un subconjunto de columnas (Folio, Fecha del Evento, Tipo,
    Placa, Cliente, Sucursal, Site, BSite) cada vez que haya un evento nuevo.
    No se marca nada como CERRADO en esta pestaña (no tiene esa columna) y
    no se toca ninguna fila existente. El folio nuevo se detecta de forma
    independiente al de "GESTORIA CP - LP" (comparando contra los folios que
    YA están en "2026", no contra los que se acaban de agregar en esta misma
    corrida) para que, si por lo que sea un folio quedó agregado en un Sheet
    pero no en el otro en una corrida anterior, la siguiente corrida lo
    complete solo.

Requiere:
    pip install -r requirements.txt

Variables de entorno esperadas (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS  -> mismas credenciales que
        automations/maxinet-sync y automations/maxinet-query-sync
    GOOGLE_CREDS_PATH          -> ruta al JSON de la cuenta de servicio
    SPREADSHEET_ID_GESTORIA    -> ID del Google Sheet destino (copia
        automatizada, no el original que usa el equipo)
    WORKSHEET_GESTORIA_NAME    -> nombre de la pestaña principal (default
        "GESTORIA CP - LP")
    WORKSHEET_HISTORICO_NAME   -> nombre de la pestaña histórico (default
        "2026")
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

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gestoria_lp_cp_sync")

# Orden de columnas del Sheet, A -> AI (35 columnas), y su campo equivalente
# en la respuesta de Maxinet. Confirmado 1 a 1 contra el `columns:` real del
# DataTable y contra una fila real de la API (folio 1623, 2026-09-28).
# NOTA: se omite a propósito el campo `alerta_evento` (columna "Alerta
# Siniestro" en Maxinet) porque el Sheet no la tiene todavía.
COLUMNAS_SHEET = [
    "id",                       # A  Folio
    "estatus",                  # B  Estatus
    "fecha_evento",              # C  Fecha del Evento
    "diasCorralon",              # D  Días Corralón
    "diasTicket",                 # E  Días Ticket
    "gestorUserName",            # F  Gestor Asignado
    "nombreTipo",                 # G  Tipo
    "cargoCliente",               # H  Cargo Cliente
    "cargoAdicionalId",           # I  Folio Cargo Adicc.
    "estatusCgoAdicName",         # J  Estatus Cargo Adicc.
    "NoFactura",                  # K  Número Factura
    "estatusFacturacion",         # L  Estatus Facturación
    "MontoTotalFact",             # M  Monto Factura
    "registrationNo",             # N  Placa
    "bookingNo",                  # O  Reserva
    "ClientName",                 # P  Cliente
    "categoriaVehicle",           # Q  Categoría
    "Make",                       # R  Marca
    "Model",                      # S  Modelo
    "FromSite",                   # T  Sucursal
    "Site",                       # U  Site
    "BSite",                      # V  BSite
    "PUSite",                     # W  PUSite
    "nombreGiro",                 # X  Giro
    "aplica_corralon",            # Y  Aplica Corralón
    "nombreCorralon",             # Z  Nombre Corralón
    "fecha_ingreso_corralon",     # AA Fecha Ingreso Corralón
    "fecha_salida_corralon",      # AB Fecha Salida Corralón
    "nombre_conductor",           # AC Nombre Conductor
    "edad_conductor",             # AD Edad Conductor
    "estado_civil",               # AE Estado Civil
    "nombreEstado",               # AF Estado
    "nombreMunicipio",            # AG Municipio
    "created_at",                 # AH Creado
    "estatus_created_at",         # AI Cerrado
]

FOLIO_COL = "id"
ESTATUS_COL = "estatus"

COL_INICIO = "A"
COL_FIN = "AI"
FILA_ENCABEZADO = 1
FILA_INICIO_DATOS = 2

# Pestaña "2026": histórico de solo-alta, columnas A -> H, mismo orden que
# los encabezados reales ya confirmados contra el Sheet.
COLUMNAS_HISTORICO = [
    "id",             # A Folio
    "fecha_evento",   # B Fechadel Evento
    "nombreTipo",     # C Tipo
    "registrationNo", # D Placa
    "ClientName",     # E Cliente
    "FromSite",       # F Sucursal
    "Site",           # G Site
    "BSite",          # H BSite
]


def _parse_json(resp: requests.Response):
    """A diferencia de los reportes viejos de Maxinet, este endpoint no
    antepone BOM UTF-8, pero se prueba con utf-8-sig de todos modos por
    si acaso (mismo patrón defensivo que las otras automatizaciones)."""
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
        raise


def login_maxinet() -> requests.Session:
    """Inicia sesión en Maxinet y devuelve una sesión con la cookie válida."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    usuario = os.environ["MAXINET_USER"].strip()
    contrasena = os.environ["MAXINET_PASS"]

    session = requests.Session()
    resp = session.post(
        f"{base_url}/includes/users/AccessValidate.php",
        data={"email": usuario, "password": contrasena},
    )
    data = _parse_json(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")

    log.info("Login en Maxinet exitoso")
    return session


def descargar_gestoria_abiertos() -> pd.DataFrame:
    """
    Pide al endpoint de Gestoría LP & CP los tickets con Estatus=ABIERTO,
    sin ningún otro filtro -- mismos valores que trae el formulario por
    default al abrir la liga. Devuelve TODOS los tickets abiertos sin
    importar su fecha (incluye tickets viejos que llevan meses sin cerrar).
    """
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")

    session = login_maxinet()
    resp = session.post(
        f"{base_url}/api/postventa/gestoria/",
        data={
            "Estatus": "ABIERTO",
            "Desde": "",
            "Hasta": "",
            "placa": "",
            "alerta_evento": "",
            "tipoTicketId": "",
            "FromSite": "",
            "cargo_cliente": 0,
        },
    )
    payload = _parse_json(resp)
    filas = payload.get("data", [])
    log.info("Tickets ABIERTO descargados de Maxinet: %d", len(filas))

    df = pd.DataFrame(filas)
    for col in COLUMNAS_SHEET:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNAS_SHEET]

    # Mismo bug ya conocido en automations/maxinet-sync y
    # automations/maxinet-query-sync: pandas 3.x puede inferir columnas de
    # texto con dtype "string" además del "object" clásico.
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].str.strip()

    df[FOLIO_COL] = pd.to_numeric(df[FOLIO_COL], errors="coerce").astype("Int64")
    return df


def conectar_sheet_gestoria():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID_GESTORIA"])
    # os.environ.get(..., default) no aplica el default si la variable existe
    # pero está vacía (ej. un GitHub Secret configurado sin valor) -- por eso
    # se checa explícitamente en vez de confiar solo en el default de get().
    nombre_pestana = os.environ.get("WORKSHEET_GESTORIA_NAME") or "GESTORIA CP - LP"
    return sh.worksheet(nombre_pestana)


def conectar_sheet_historico():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID_GESTORIA"])
    nombre_pestana = os.environ.get("WORKSHEET_HISTORICO_NAME") or "2026"
    return sh.worksheet(nombre_pestana)


def leer_folios_existentes(worksheet):
    """
    Lee las columnas A (Folio) y B (Estatus) del Sheet completo y devuelve
    un dict {folio: (fila, estatus_actual)}. No lee el resto de columnas:
    esta automatización nunca actualiza datos de filas existentes, solo
    agrega filas nuevas o cambia la columna B a CERRADO.
    """
    valores = worksheet.get(f"A{FILA_INICIO_DATOS}:B")
    existentes = {}
    for i, fila in enumerate(valores):
        num_fila = FILA_INICIO_DATOS + i
        if not fila or not fila[0]:
            continue
        try:
            folio = int(str(fila[0]).strip())
        except ValueError:
            continue
        estatus_actual = fila[1].strip() if len(fila) > 1 and fila[1] else ""
        existentes[folio] = (num_fila, estatus_actual)
    return existentes


def sincronizar_gestoria(worksheet, df_abiertos: pd.DataFrame):
    existentes = leer_folios_existentes(worksheet)
    folios_maxinet_abiertos = set(int(f) for f in df_abiertos[FOLIO_COL].dropna().tolist())

    # 1. Folios nuevos (no existen todavía en el Sheet) -> agregar al final,
    #    ordenados por Folio ascendente (mismo orden que ya tiene el Sheet).
    df_nuevos = df_abiertos[~df_abiertos[FOLIO_COL].isin(existentes.keys())].copy()
    df_nuevos = df_nuevos.sort_values(FOLIO_COL, ascending=True)

    if len(df_nuevos) > 0:
        valores_nuevos = df_nuevos.fillna("").astype(str).values.tolist()
        worksheet.append_rows(valores_nuevos, value_input_option="USER_ENTERED")
        log.info("Filas nuevas agregadas: %d (folios %s)", len(df_nuevos), sorted(df_nuevos[FOLIO_COL].tolist()))
    else:
        log.info("No hay folios nuevos que agregar.")

    # 2. Folios que YA NO aparecen como ABIERTO en Maxinet y que en el Sheet
    #    no estén ya marcados CERRADO -> marcar CERRADO en columna B.
    #    (No se toca el caso inverso: eso no fue pedido y no hay que
    #    adivinar la regla.)
    actualizaciones = []
    for folio, (num_fila, estatus_actual) in existentes.items():
        if folio in folios_maxinet_abiertos:
            continue
        if estatus_actual.upper() == "CERRADO":
            continue
        actualizaciones.append({"range": f"B{num_fila}", "values": [["CERRADO"]]})

    if actualizaciones:
        worksheet.batch_update(actualizaciones)
        log.info("Folios marcados como CERRADO: %d", len(actualizaciones))
    else:
        log.info("No hay folios para marcar como CERRADO.")

    return len(df_nuevos), len(actualizaciones)


def leer_folios_historico(worksheet) -> set:
    """Lee solo la columna A (Folio) de la pestaña histórico -- no tiene
    columna de Estatus, así que no hay nada más que leer."""
    valores = worksheet.get(f"A{FILA_INICIO_DATOS}:A")
    folios = set()
    for fila in valores:
        if not fila or not fila[0]:
            continue
        try:
            folios.add(int(str(fila[0]).strip()))
        except ValueError:
            continue
    return folios


def sincronizar_historico(worksheet, df_abiertos: pd.DataFrame):
    """
    Agrega al histórico "2026" los folios que aún no tenga, sin importar si
    ya se agregaron o no en esta misma corrida a "GESTORIA CP - LP" -- se
    compara directamente contra lo que ya existe en esta pestaña para que
    una corrida futura pueda completar solita cualquier folio que se haya
    quedado atrás. Solo agrega filas nuevas; nunca actualiza ni cierra nada
    aquí (la pestaña no tiene columna de Estatus).
    """
    existentes = leer_folios_historico(worksheet)
    df_nuevos = df_abiertos[~df_abiertos[FOLIO_COL].isin(existentes)].copy()
    df_nuevos = df_nuevos.sort_values(FOLIO_COL, ascending=True)

    if len(df_nuevos) == 0:
        log.info("Histórico '2026': no hay folios nuevos que agregar.")
        return 0

    df_nuevos = df_nuevos[COLUMNAS_HISTORICO]
    valores_nuevos = df_nuevos.fillna("").astype(str).values.tolist()
    worksheet.append_rows(valores_nuevos, value_input_option="USER_ENTERED")
    log.info(
        "Histórico '2026': filas nuevas agregadas: %d (folios %s)",
        len(df_nuevos),
        sorted(df_nuevos[FOLIO_COL].tolist()),
    )
    return len(df_nuevos)


def main():
    try:
        df_abiertos = descargar_gestoria_abiertos()

        worksheet = conectar_sheet_gestoria()
        nuevos, cerrados = sincronizar_gestoria(worksheet, df_abiertos)

        worksheet_historico = conectar_sheet_historico()
        nuevos_historico = sincronizar_historico(worksheet_historico, df_abiertos)

        log.info(
            "Automatización completada con éxito (%d nuevos, %d cerrados, %d agregados a histórico)",
            nuevos, cerrados, nuevos_historico,
        )
    except Exception:
        log.exception("Error en la automatización de Gestoría LP & CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
