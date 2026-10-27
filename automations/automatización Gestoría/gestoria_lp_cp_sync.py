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
            body: Estatus=, Desde=, Hasta=, placa=, alerta_evento=,
            tipoTicketId=, FromSite=, cargo_cliente=0 -- es el botón "Ver
            Todo" de la página: TODOS los tickets, abiertos y cerrados.
            (Hasta el 2026-10-12 se pedía Estatus=ABIERTO; eso dejaba fuera
            los tickets de VERIFICACIÓN/TRÁMITES que se abren y se cierran en
            menos de un minuto, que nunca aparecen como abiertos en ninguna
            corrida y el original de Nuvia sí registra.) A diferencia de los
            otros reportes de Maxinet ya automatizados, esta respuesta NO
            trae BOM y es un dict con llave "data" = lista de OBJETOS (no
            listas), confirmado contra el servidor real el 2026-09-28.

Lógica de sincronización (decidida por el usuario, no inventada aquí):
    1. Todo folio que venga en Maxinet, con cualquier estatus, y que NO exista
       todavía en el Sheet -> se agrega como fila nueva, pegada debajo de la
       última fila con datos (ordenados por Folio ascendente), con el estatus
       y la fecha de cierre que traiga Maxinet.
    2. Todo folio que SÍ exista en el Sheet, cuyo Estatus actual ahí no sea
       ya "CERRADO", y que Maxinet muestre como CERRADO o ya no muestre (si
       lo borraron) -> se marca como "CERRADO" en la columna B.
    3. Columna AI "Cerrado": si la fila queda CERRADO y AI está vacía, se
       llena con la fecha de cierre de Maxinet (`estatus_created_at`). Nunca
       se sobrescribe un valor que ya tenga AI. Ninguna fórmula depende de
       esa columna (revisado el 2026-10-12).
    4. Caso inverso (Sheet ya dice CERRADO pero Maxinet lo muestra ABIERTO)
       -> NO se reabre; sólo se avisa en el log con el conteo. El usuario no
       pidió esa regla y no hay que adivinarla.
    5. Campos de análisis de una fila ya existente (CAMPOS_REFRESCABLES: fecha del
       evento, tipo, cliente, sucursal, Site, BSite y PUSite): se corrigen con
       lo que diga Maxinet hoy, porque Maxinet los reclasifica o corrige después
       de que la fila entró al Sheet y la pestaña ÍNDICE SINIESTRALIDAD, BDATOS y el
       dashboard GESTORÍA del TABLERO LP cuentan con ellos. Sólo se escribe si Maxinet trae un valor
       (nunca se borra una celda porque Maxinet venga vacío) y, en la fecha, si el
       año es verosímil (un "26" tecleado llega como 0026 y se lee como 2026, igual
       que Google Sheets; cualquier otro año imposible se ignora). Si un campo cambiaría en
       más de la mitad de las filas se omite y se avisa (señal de que Maxinet
       cambió de formato).
    6. Correcciones manuales: la pestaña CORRECCIONES (FOLIO, CAMPO, VALOR, MOTIVO) fija el
       valor de un campo de un folio por encima de lo que diga Maxinet, para los casos en
       que Maxinet trae un dato equivocado (la sucursal de los folios 1062, 1104, 1359 y
       1530) y el equipo lo corrigió a mano. Sin esa pestaña el refresco de la regla 5
       volvería a escribir el valor de Maxinet en cada corrida. CAMPO admite SUCURSAL, TIPO,
       CLIENTE, SITE, BSITE y PUSITE (CAMPOS_CORREGIBLES); una fila con un campo no admitido
       o sin valor se ignora y se avisa. Si la pestaña no existe no pasa nada.
    El resto de las columnas de una fila ya existente (días, cargo adicional,
    factura, conductor...) no se actualizan.
    La columna "Alerta Siniestro" (campo `alerta_evento` de Maxinet) existe
    en el reporte pero NO en este Sheet -- se ignora a propósito, tal como
    indicó el usuario, dejándola documentada aquí por si se agrega después.

Guardia: si Maxinet devuelve menos de la mitad de los folios que ya tiene el
    Sheet (sesión vencida, mantenimiento, respuesta vacía) la corrida aborta
    sin escribir; de lo contrario cerraría casi todo por ausencia.

Uso:
    python gestoria_lp_cp_sync.py             corrida normal
    python gestoria_lp_cp_sync.py --dry-run   sólo informa qué cambiaría

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
(columna C), y AM devuelve "OK" si el año es 2025 o 2026. Hoy ninguna fórmula las
usa (alimentaban las pestañas RESUMEN y 2026, que ya no existen).

Pestañas de apoyo (hojas_apoyo.py; ninguna se crea sola, si falta se omite con un aviso):
    FUENTES            sello de la última corrida (B3:B8) junto a la tabla de procedencia que
                       escribe una persona: de dónde sale cada bloque y qué es manual.
    ALERTAS DE DATOS   datos dudosos del reporte de Maxinet (fecha imposible, posible duplicado,
                       sucursal vacía); se reescribe en cada corrida (anomalias.py).
    REVISAR NOMBRES    nombres de cliente nuevos que parecen una cuenta interna; una persona marca
                       ESTADO = INTERNA o CLIENTE y el sync agrega a 'NO SON CLIENTES' los internos
                       (cuentas_internas.py). El patrón de cuentas internas vive en
                       'ÍNDICE SINIESTRALIDAD'!B2 y lo usa también BDATOS!B2.
    La antigua pestaña "2026" (histórico con XLOOKUP por fila) ya no existe: su paso de
    mantenimiento se retiró el 2026-10-27. Una pestaña "2026" nueva, si se vuelve a necesitar,
    debe ser una sola fórmula de derrame sobre BDATOS, sin nada que arrastrar.

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
import re
import sys
import html
import json
import time
import logging
import unicodedata
from datetime import date

import requests
import pandas as pd
import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import anomalias  # noqa: E402  (junto a este archivo)
import hojas_apoyo  # noqa: E402

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
CERRADO_COL = "estatus_created_at"

COL_INICIO = "A"
COL_FIN = "AI"
COL_CERRADO = "AI"
IDX_ESTATUS = 1   # columna B
IDX_CERRADO = 34  # columna AI
FILA_ENCABEZADO = 1
FILA_INICIO_DATOS = 2

# Guardia contra una respuesta vacía o parcial de Maxinet (ver docstring).
MIN_FRACCION_MAXINET = 0.5
# Tope de rangos por llamada a batch_update.
TAMANO_LOTE = 400

# Campos de filas ya cargadas que se refrescan desde Maxinet en cada corrida:
# {índice de columna: (letra, campo de Maxinet)}. Sólo los que usan las pestañas
# de análisis; ver la regla 5 del docstring.
CAMPOS_REFRESCABLES = {
    2: ("C", "fecha_evento"),
    6: ("G", "nombreTipo"),
    15: ("P", "ClientName"),
    19: ("T", "FromSite"),
    20: ("U", "Site"),
    21: ("V", "BSite"),
    22: ("W", "PUSite"),
}
PESTANA_CORRECCIONES = "CORRECCIONES"
# Nombre que se escribe en la columna CAMPO de la pestaña CORRECCIONES (sin acentos, en mayúsculas)
# -> índice de columna en CAMPOS_REFRESCABLES. La fecha del evento no se admite: Maxinet la corrige solo.
CAMPOS_CORREGIBLES = {"SUCURSAL": 19, "TIPO": 6, "CLIENTE": 15, "SITE": 20, "BSITE": 21, "PUSITE": 22}
MAX_FRACCION_REFRESCO = 0.5  # un campo que cambiaría en más de la mitad de las filas se omite...
MIN_FILAS_GUARDIA = 50       # ...siempre que haya al menos esta cantidad de filas comparadas
ANIO_MIN_FECHA = 2020


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


def _post_con_reintentos(session: requests.Session, url: str, data: dict, intentos: int = 3):
    """Maxinet a veces corta la conexión (ConnectionResetError, visto el 2026-10-21 en una corrida de
    Gestoría y el 2026-10-02 en el sync del tablero); un reintento corto suele bastar."""
    for n in range(1, intentos + 1):
        try:
            return session.post(url, data=data, timeout=120)
        except (requests.ConnectionError, requests.Timeout):
            if n == intentos:
                raise
            log.warning("Maxinet cortó la conexión (intento %d de %d); reintentando", n, intentos)
            time.sleep(5 * n)


def login_maxinet() -> requests.Session:
    """Inicia sesión en Maxinet y devuelve una sesión con la cookie válida."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    usuario = os.environ["MAXINET_USER"].strip()
    contrasena = os.environ["MAXINET_PASS"]

    session = requests.Session()
    resp = _post_con_reintentos(
        session,
        f"{base_url}/includes/users/AccessValidate.php",
        {"email": usuario, "password": contrasena},
    )
    data = _parse_json(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")

    log.info("Login en Maxinet exitoso")
    return session


def descargar_gestoria_todos() -> pd.DataFrame:
    """
    Pide al endpoint de Gestoría LP & CP todos los tickets (Estatus vacío,
    como el botón "Ver Todo" de la página), abiertos y cerrados, sin
    importar su fecha.
    """
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")

    session = login_maxinet()
    resp = _post_con_reintentos(
        session,
        f"{base_url}/api/postventa/gestoria/",
        {
            "Estatus": "",
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
    log.info("Tickets descargados de Maxinet: %d", len(filas))

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
            # Maxinet manda '&amp;' en algunos textos (ej. "JR3 PACK &amp; SHIP"):
            # el Sheet los tiene como '&', y escribirlos tal cual partiría un
            # cliente en dos variantes.
            df[col] = df[col].map(lambda v: html.unescape(v) if isinstance(v, str) else v)

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


def leer_bloque(worksheet):
    """Lee el bloque A:AI del Sheet (valores tal como se ven) en una sola llamada."""
    return worksheet.get(f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}")


def leer_filas_existentes(valores):
    """
    Recibe el bloque A:AI (ver leer_bloque) y devuelve un dict
    {folio: (fila, estatus_actual, cerrado_actual)}.
    """
    existentes = {}
    for i, fila in enumerate(valores):
        num_fila = FILA_INICIO_DATOS + i
        if not fila or not str(fila[0]).strip():
            continue
        try:
            folio = int(str(fila[0]).strip())
        except ValueError:
            continue
        estatus = fila[IDX_ESTATUS].strip().upper() if len(fila) > IDX_ESTATUS else ""
        cerrado = fila[IDX_CERRADO].strip() if len(fila) > IDX_CERRADO else ""
        existentes[folio] = (num_fila, estatus, cerrado)
    return existentes


def _escribir_en_lotes(worksheet, actualizaciones):
    for i in range(0, len(actualizaciones), TAMANO_LOTE):
        worksheet.batch_update(actualizaciones[i:i + TAMANO_LOTE], value_input_option="USER_ENTERED")


def _texto(valor) -> str:
    """Nulos de pandas (None, NaN, pd.NA) -> "" en vez de "nan"/"<NA>"."""
    return "" if pd.isna(valor) else str(valor).strip()


def _fecha_verosimil(iso: str):
    """'YYYY-MM-DD...' -> (año, mes, día) si el año es verosímil; None si Maxinet trae basura (ej. 0026)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return None
    anio, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if anio < 100:
        # Maxinet guarda un "26" tecleado como año 0026 (folios 1503 y 1683); Google Sheets lo lee como 2026.
        anio += 2000
    if not (ANIO_MIN_FECHA <= anio <= date.today().year + 1):
        return None
    return anio, mes, dia


def _clave_texto(texto: str) -> str:
    """'Sucursal ' -> 'SUCURSAL' (sin acentos ni espacios sobrantes) para comparar encabezados y nombres de campo."""
    sin = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin).strip().upper()


def leer_correcciones(libro) -> dict:
    """{(folio, índice de columna): valor} de la pestaña CORRECCIONES (FOLIO, CAMPO, VALOR, MOTIVO).
    Si la pestaña no existe devuelve {}. Una fila con folio inválido, campo no admitido o sin valor
    se ignora y se avisa: una corrección mal escrita no debe detener el sync."""
    nombre = os.environ.get("WORKSHEET_CORRECCIONES_NAME") or PESTANA_CORRECCIONES
    try:
        hoja = libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        return {}
    filas = hoja.get_all_values()
    if not filas:
        return {}
    cab = [_clave_texto(c) for c in filas[0]]
    try:
        i_folio, i_campo, i_valor = cab.index("FOLIO"), cab.index("CAMPO"), cab.index("VALOR")
    except ValueError:
        log.warning("La pestaña %s no tiene los encabezados FOLIO, CAMPO y VALOR; se ignora", nombre)
        return {}
    correcciones, ignoradas = {}, []
    for n, fila in enumerate(filas[1:], start=2):
        if not any(str(c).strip() for c in fila):
            continue
        get = lambda i: fila[i].strip() if len(fila) > i else ""
        try:
            folio = int(get(i_folio))
        except ValueError:
            ignoradas.append(n); continue
        idx = CAMPOS_CORREGIBLES.get(_clave_texto(get(i_campo)))
        valor = get(i_valor)
        if idx is None or not valor:
            ignoradas.append(n); continue
        correcciones[(folio, idx)] = valor
    if ignoradas:
        log.warning("%s: filas ignoradas por folio, campo o valor no válido: %s", nombre, ignoradas)
    return correcciones


def calcular_refrescos(valores, df_maxinet: pd.DataFrame, correcciones: dict = None):
    """
    Compara los campos de CAMPOS_REFRESCABLES de las filas existentes contra Maxinet
    y devuelve (actualizaciones, cambios_por_campo, folios_omitidos_por_fecha).
    Nunca propone borrar una celda ni escribir una fecha con año imposible. Un valor de
    `correcciones` ({(folio, índice de columna): valor}) manda sobre el de Maxinet.
    """
    correcciones = correcciones or {}
    mx = {int(r[FOLIO_COL]): r for _, r in df_maxinet.dropna(subset=[FOLIO_COL]).iterrows()}
    candidatos = {idx: [] for idx in CAMPOS_REFRESCABLES}
    fechas_malas = []
    filas_comparadas = 0
    for i, fila in enumerate(valores):
        num_fila = FILA_INICIO_DATOS + i
        if not fila or not str(fila[0]).strip():
            continue
        try:
            folio = int(str(fila[0]).strip())
        except ValueError:
            continue
        t = mx.get(folio)
        if t is None:
            continue
        filas_comparadas += 1
        for idx, (letra, campo) in CAMPOS_REFRESCABLES.items():
            actual = fila[idx].strip() if len(fila) > idx else ""
            nuevo = correcciones.get((folio, idx)) or _texto(t[campo])
            if not nuevo:
                continue  # Maxinet vacío: no se borra nada
            if campo == "fecha_evento":
                f = _fecha_verosimil(nuevo)
                if f is None:
                    fechas_malas.append(folio)
                    continue
                if actual != f"{f[2]}/{f[1]}/{f[0]}":  # el Sheet las muestra como d/M/yyyy
                    candidatos[idx].append((num_fila, f"{f[0]:04d}-{f[1]:02d}-{f[2]:02d}"))
            elif nuevo != actual:
                candidatos[idx].append((num_fila, nuevo))
    actualizaciones, conteo = [], {}
    for idx, (letra, campo) in CAMPOS_REFRESCABLES.items():
        cambios = candidatos[idx]
        if not cambios:
            continue
        if filas_comparadas >= MIN_FILAS_GUARDIA and len(cambios) > MAX_FRACCION_REFRESCO * filas_comparadas:
            log.warning(
                "Refresco omitido para %s (columna %s): cambiaría %d de %d filas; Maxinet pudo cambiar de formato.",
                campo, letra, len(cambios), filas_comparadas,
            )
            continue
        conteo[campo] = len(cambios)
        actualizaciones.extend({"range": f"{letra}{fila}", "values": [[valor]]} for fila, valor in cambios)
    return actualizaciones, conteo, fechas_malas


def sincronizar_gestoria(worksheet, df_maxinet: pd.DataFrame, dry_run: bool = False):
    valores = leer_bloque(worksheet)
    existentes = leer_filas_existentes(valores)
    mx = {
        int(r[FOLIO_COL]): (_texto(r[ESTATUS_COL]).upper(), _texto(r[CERRADO_COL]))
        for _, r in df_maxinet.dropna(subset=[FOLIO_COL]).iterrows()
    }

    # Guardia: una respuesta vacía o parcial de Maxinet cerraría casi todo
    # por ausencia (ver docstring del módulo).
    if existentes and len(mx) < MIN_FRACCION_MAXINET * len(existentes):
        raise RuntimeError(
            f"Maxinet devolvió {len(mx)} tickets y el Sheet tiene {len(existentes)}: "
            "se aborta sin escribir para no cerrar filas por una respuesta incompleta."
        )

    # 1. Folios nuevos (no existen todavía en el Sheet) -> agregar al final,
    #    ordenados por Folio ascendente. La fila de inicio se calcula a mano
    #    (última fila con folio + 1) y se escribe con update() -- NUNCA con
    #    append_rows(): ese método deja que la API decida dónde "termina la
    #    tabla", y en este Sheet esa detección está rota por columnas
    #    auxiliares con formato aplicado muy por debajo del último dato real
    #    (ver docstring del módulo).
    df_nuevos = df_maxinet[~df_maxinet[FOLIO_COL].isin(existentes.keys())].copy()
    df_nuevos = df_nuevos.dropna(subset=[FOLIO_COL]).sort_values(FOLIO_COL, ascending=True)

    if len(df_nuevos) > 0:
        ultima_fila = max((f for f, _, _ in existentes.values()), default=FILA_ENCABEZADO)
        fila_inicio = ultima_fila + 1
        fila_fin = fila_inicio + len(df_nuevos) - 1
        valores_nuevos = df_nuevos.fillna("").astype(str).values.tolist()
        if not dry_run:
            worksheet.update(
                range_name=f"{COL_INICIO}{fila_inicio}:{COL_FIN}{fila_fin}",
                values=valores_nuevos,
                value_input_option="USER_ENTERED",
            )
        log.info(
            "%sFilas nuevas: %d en %s%d:%s%d (folios %s; %d ya cerrados en Maxinet)",
            "[dry-run] " if dry_run else "", len(df_nuevos), COL_INICIO, fila_inicio, COL_FIN, fila_fin,
            sorted(int(f) for f in df_nuevos[FOLIO_COL]),
            int((df_nuevos[ESTATUS_COL].str.upper() == "CERRADO").sum()),
        )
    else:
        log.info("No hay folios nuevos que agregar.")

    # 2 y 3. Folios existentes: cerrar los que Maxinet muestra CERRADO o ya
    #    no muestra, y llenar AI (sólo si está vacía) en los que queden
    #    CERRADO. No se toca el caso inverso (reabrir): no fue pedido.
    actualizaciones = []
    n_cerrados = n_cerrado_fecha = n_reabiertos = 0
    for folio, (fila, estatus, cerrado_actual) in existentes.items():
        estatus_mx, cerrado_mx = mx.get(folio, (None, ""))
        if estatus != "CERRADO" and estatus_mx in (None, "CERRADO"):
            actualizaciones.append({"range": f"B{fila}", "values": [["CERRADO"]]})
            n_cerrados += 1
            estatus = "CERRADO"
        elif estatus == "CERRADO" and estatus_mx == "ABIERTO":
            n_reabiertos += 1
        if estatus == "CERRADO" and not cerrado_actual and cerrado_mx:
            actualizaciones.append({"range": f"{COL_CERRADO}{fila}", "values": [[cerrado_mx]]})
            n_cerrado_fecha += 1

    try:
        correcciones = leer_correcciones(worksheet.spreadsheet)
    except Exception as e:
        # Secundario: sin correcciones el refresco usa lo de Maxinet; se avisa y se sigue.
        log.warning("No se pudieron leer las correcciones manuales (%s: %s)", type(e).__name__, str(e)[:120])
        correcciones = {}
    if correcciones:
        log.info("Correcciones manuales cargadas: %d", len(correcciones))
    refrescos, conteo_refrescos, fechas_malas = calcular_refrescos(valores, df_maxinet, correcciones)
    actualizaciones.extend(refrescos)
    if fechas_malas:
        log.warning("Fechas de evento con año imposible en Maxinet (se conserva la del Sheet): folios %s", sorted(fechas_malas))

    if n_reabiertos:
        log.warning(
            "%d folios están CERRADO en el Sheet pero ABIERTO en Maxinet; no se reabren "
            "(no es parte de las reglas acordadas).", n_reabiertos,
        )
    if actualizaciones:
        if not dry_run:
            _escribir_en_lotes(worksheet, actualizaciones)
        log.info(
            "%sFolios marcados como CERRADO: %d | fechas de cierre (AI) llenadas: %d | campos refrescados desde Maxinet: %s",
            "[dry-run] " if dry_run else "", n_cerrados, n_cerrado_fecha, conteo_refrescos or "ninguno",
        )
    else:
        log.info("No hay folios para cerrar, fechas de cierre por llenar ni campos por refrescar.")

    return len(df_nuevos), n_cerrados, n_cerrado_fecha, sum(conteo_refrescos.values())


def actualizar_apoyo(worksheet, df_maxinet: pd.DataFrame, nuevos: int, cerrados: int, fechas: int,
                     refrescados: int, dry_run: bool = False) -> None:
    """Pestañas de apoyo del libro (ver hojas_apoyo.py): alertas de datos, nombres por revisar y el sello de
    la corrida en FUENTES. Va después de la sincronización y su falla no la invalida."""
    libro = worksheet.spreadsheet
    alertas = anomalias.detectar(df_maxinet, date.today())
    n_alertas = hojas_apoyo.escribir_alertas(libro, alertas, dry_run=dry_run)
    tickets = [(int(r[FOLIO_COL]), r["ClientName"]) for r in df_maxinet.to_dict("records")
               if pd.notna(r[FOLIO_COL]) and isinstance(r["ClientName"], str)]
    avisados, agregados, pendientes = hojas_apoyo.actualizar_revisar_nombres(libro, tickets, dry_run=dry_run)
    folios_hoja = len(leer_filas_existentes(leer_bloque(worksheet)))
    hojas_apoyo.escribir_estado(libro, {
        "ultima_sincronizacion": hojas_apoyo.ahora_cdmx(),
        "tickets_maxinet": len(df_maxinet),
        "folios_hoja": folios_hoja,
        "ultima_corrida": f"{nuevos} nuevos, {cerrados} cerrados, {fechas} fechas de cierre, {refrescados} campos refrescados",
        "alertas": n_alertas,
        "nombres_por_revisar": pendientes,
    }, dry_run=dry_run)
    log.info("%sApoyo: %d alertas de datos; nombres por revisar: %d (%d nuevos, %d agregados a la lista).",
             "[dry-run] " if dry_run else "", n_alertas, pendientes, avisados, agregados)


def main():
    dry_run = "--dry-run" in sys.argv
    try:
        df_maxinet = descargar_gestoria_todos()

        worksheet = conectar_sheet_gestoria()
        nuevos, cerrados, fechas, refrescados = sincronizar_gestoria(worksheet, df_maxinet, dry_run=dry_run)

        # Secundario: si falla (cuota, rango protegido) se avisa pero no se
        # considera fallida la sincronización principal, que ya terminó.
        try:
            actualizar_apoyo(worksheet, df_maxinet, nuevos, cerrados, fechas, refrescados, dry_run=dry_run)
        except Exception:
            log.exception("No se pudieron actualizar las pestañas de apoyo (FUENTES, ALERTAS DE DATOS, REVISAR NOMBRES)")

        log.info(
            "Automatización completada con éxito%s (%d nuevos, %d cerrados, %d fechas de cierre, %d campos refrescados)",
            " [dry-run: no se escribió nada]" if dry_run else "", nuevos, cerrados, fechas, refrescados,
        )
    except Exception:
        log.exception("Error en la automatización de Gestoría LP & CP")
        sys.exit(1)


if __name__ == "__main__":
    main()
