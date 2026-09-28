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

IMPORTANTE sobre cómo se agregan las filas nuevas:
    NO se usa `Worksheet.append_rows()`. Ese método le pide a la API de
    Sheets que decida sola dónde "termina la tabla", y en este Sheet
    específico esa detección está rota: la hoja tiene un `row_count` de
    ~2960 (heredado de formato/columnas auxiliares -- ver más abajo --
    aplicadas de antemano mucho más abajo del último dato real), así que
    `append_rows` insertó una fila nueva hasta la fila 2961 en vez de la
    1562 esperada (bug real, encontrado y corregido el 2026-09-28: la fila
    se tuvo que mover a mano de vuelta a su lugar). Por eso aquí se calcula
    la fila exacta donde debe ir cada folio nuevo (última fila con folio +
    1) y se escribe ahí con `update()`, nunca con `append_rows()`.

Columnas auxiliares AJ:AM en "GESTORIA CP - LP" (no tocar, no son de esta
automatización): AJ/AK/AL calculan mes/año a partir de la Fecha del Evento
(columna C), y AM devuelve "OK" si el año es 2025 o 2026. La pestaña
"2026" (histórico) usa esas columnas -- ver abajo.

Pestaña "2026" (histórico de eventos, mismo Sheet): -- NO LA TOCA ESTA
    AUTOMATIZACIÓN, A PROPÓSITO. El usuario pidió en algún momento agregar
    ahí Folio/Fecha/Tipo/Placa/Cliente/Sucursal/Site/BSite para cada evento
    nuevo, pero inspeccionando el Sheet real se encontró que esa pestaña ya
    hace exactamente eso SOLA, vía fórmulas:
        A2 = =UNIQUE(FILTER('GESTORIA CP - LP'!A:A,
                             'GESTORIA CP - LP'!AM:AM="OK"))
    Esta es una fórmula de array que se "derrama" (spill) automáticamente
    hacia abajo listando todo folio de "GESTORIA CP - LP" cuya columna AM
    diga "OK" (fecha del evento en 2025 o 2026). Las columnas B a H de esa
    misma pestaña ya vienen con fórmulas XLOOKUP precargadas fila por fila
    (arrastradas de antemano hasta la fila 1501) que traen el resto de los
    datos por Folio. En otras palabras: en cuanto una fila nueva en
    "GESTORIA CP - LP" tiene una fecha válida, aparece sola en "2026" --
    no hace falta escribir nada ahí.
    Se intentó automatizar esa pestaña el 2026-09-28 escribiendo el Folio
    directamente en su columna A, sin saber que era parte del rango de
    "derrame" de esa fórmula. En cuanto la fórmula necesitó crecer una fila
    más (porque se corrigió la fecha del folio 1624 y pasó a calificar como
    "OK"), chocó con el valor fijo que se había escrito ahí y toda la
    fórmula colapsó a #REF!, vaciando visualmente el histórico completo
    (sin pérdida real de datos: "GESTORIA CP - LP" nunca se tocó). Se
    corrigió borrando esa única celda y dejando que la fórmula se
    reexpandiera sola. No se debe volver a escribir nada en esa pestaña.

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
    #    Se calcula la fila exacta a mano (última fila con folio + 1) y se
    #    escribe con update() -- NUNCA con append_rows(): ese método deja
    #    que la API decida dónde "termina la tabla", y en este Sheet esa
    #    detección está rota por columnas auxiliares con formato aplicado
    #    muy por debajo del último dato real (ver docstring del módulo).
    df_nuevos = df_abiertos[~df_abiertos[FOLIO_COL].isin(existentes.keys())].copy()
    df_nuevos = df_nuevos.sort_values(FOLIO_COL, ascending=True)

    if len(df_nuevos) > 0:
        fila_inicio = FILA_INICIO_DATOS + len(existentes)
        fila_fin = fila_inicio + len(df_nuevos) - 1
        valores_nuevos = df_nuevos.fillna("").astype(str).values.tolist()
        worksheet.update(
            range_name=f"{COL_INICIO}{fila_inicio}:{COL_FIN}{fila_fin}",
            values=valores_nuevos,
            value_input_option="USER_ENTERED",
        )
        log.info(
            "Filas nuevas agregadas: %d en %s%d:%s%d (folios %s)",
            len(df_nuevos), COL_INICIO, fila_inicio, COL_FIN, fila_fin,
            sorted(df_nuevos[FOLIO_COL].tolist()),
        )
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


def main():
    try:
        df_abiertos = descargar_gestoria_abiertos()

        worksheet = conectar_sheet_gestoria()
        nuevos, cerrados = sincronizar_gestoria(worksheet, df_abiertos)

        log.info("Automatización completada con éxito (%d nuevos, %d cerrados)", nuevos, cerrados)
    except Exception:
        log.exception("Error en la automatización de Gestoría LP & CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
