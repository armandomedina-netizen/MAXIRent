"""
Automatización diaria: login + descarga de datos de flota desde Maxinet
(vía requests, sin navegador) y actualización de datos en un Google Sheet
(sin borrar columnas índice).

Endpoint confirmado a partir del HTML/JS reales de Maxinet:
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
            body: email=<usuario>, password=<contraseña>
    Datos:  POST {MAXINET_BASE_URL}/includes/gpsrt/reporte-flota-maxirent.php
            body: Desde=YYYY-MM-DD, Hasta=YYYY-MM-DD
            respuesta: JSON estilo DataTables, con "data" = lista de listas
            (cada fila es un array de valores, mismo orden que COLUMNAS)

Requiere:
    pip install requests pandas gspread google-auth google-auth-oauthlib

Variables de entorno esperadas (usar un gestor de secretos, nunca hardcodear):
    MAXINET_BASE_URL     -> ej: http://189.206.77.107:8888/maxinetv2
    MAXINET_USER         -> usuario de Maxinet (parte antes de @maxirent.com.mx)
    MAXINET_PASS         -> contraseña de Maxinet
    GOOGLE_CREDS_PATH        -> ruta al JSON de la cuenta de servicio de Google
    SPREADSHEET_ID           -> ID del primer Google Sheet (rango B:AN)
    WORKSHEET_NAME           -> pestaña dentro del primer Sheet
    SPREADSHEET_ID_SECUNDARIO -> ID del segundo archivo de Sheets (FLOTA LP / UTILIZACION V3)
    WORKSHEET_FLOTA_LP       -> nombre de la pestaña "FLOTA LP"
    WORKSHEET_UTILIZACION    -> nombre de la pestaña "UTILIZACION V3"
    WORKSHEET_GRUPO_AUTOS    -> nombre de la pestaña "UTI. GRUPO DE AUTOS V1"

Flujo completo de la automatización diaria:
    1. Login en Maxinet + descarga de datos de flota del día anterior.
    2. Sobrescribe el rango de DATOS B2:AN... del primer Sheet (columna A,
       la fila de encabezados reales (fila 1), y lo que está a la derecha
       de AN tienen su propia estructura fija -> no se tocan).
    3. Pega el mismo bloque de datos (incluyendo columna A vacía, desde
       A2:AN...) en la pestaña "FLOTA LP" del segundo archivo. La fila de
       encabezados reales (fila 1) tampoco se toca ahí.
    4. En la pestaña "UTILIZACION V3" (tablero tipo calendario, 1 columna
       por día): encuentra la columna de "ayer" en la fila 2, copia las
       fórmulas de la columna anterior hacia ella, y convierte la columna
       anterior a valores fijos (para no acumular peso en el archivo).

Estructura del primer Sheet (confirmada por el usuario):
    - Encabezados reales en la fila 1, columnas B a AN (39 columnas) -> son
      fijos del archivo, la automatización NUNCA los sobrescribe (aunque el
      orden o nombre de columnas del reporte de Maxinet cambiara, la
      estructura del Sheet manda).
    - Datos desde la fila 2 hacia abajo (inmediatamente debajo del
      encabezado, sin renglón en blanco de por medio).
    - La columna A y todo lo que esté a la derecha de AN tiene fórmulas
      propias del Sheet -> NUNCA se tocan.
    - Cada corrida SOBRESCRIBE por completo el bloque de datos (no se hace
      merge/match por fila; el reporte de Maxinet reemplaza al anterior).
"""

import os
import re
import sys
import json
import logging
from collections import Counter
from datetime import date, timedelta

import requests
import pandas as pd
import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

# Carga las variables desde un archivo ".env" junto a este script (uso local;
# en cada máquina, copiar env.mac o env.windows como ".env"). En GitHub
# Actions no existe ese archivo y las variables ya vienen del entorno
# (Secrets), así que esta llamada simplemente no hace nada.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_sync")

# Mismo orden de columnas confirmado en el HTML y en el Excel de ejemplo
# (la columna vacía inicial del reporte -checkbox/acciones- se descarta)
COLUMNAS = [
    "Fecha", "Estado", "Placa", "BSite", "CurrentSite", "Segmento",
    "Estatus Vehiculo", "Geocerca", "Odometro", "Km", "Nombre Geocerca",
    "Ultimo Msj", "Semaforo dias s/reportar", "Dias s/reportar",
    "No. Dispositivos", "RT", "VIRTUAL", "DELTA", "Ubicacion", "Grupo",
    "Marca", "Modelo", "Reserva Actual", "# Cliente Actual", "Cliente Actual",
    "PUSite Actual", "PUDate Actual", "ReturnDate Actual", "Booked_by",
    "Reserva Ult. Renta", "Cliente Ult. Renta", "PUDate Ult. Renta",
    "Proxima Reserva", "Cliente Prox. Reserva", "PUDate Prox. Reserva",
    "Memo Reserva actual", "Comentario", "Fecha Ult.Coment.",
    "Responsable Ult.Coment.",
]


def _parse_json_bom(resp: requests.Response):
    """Maxinet antepone un BOM UTF-8 a sus respuestas JSON, lo que rompe
    resp.json() (confirmado contra el servidor real)."""
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


def descargar_datos_flota(session: requests.Session) -> pd.DataFrame:
    """Pide al endpoint de datos el reporte del día anterior y arma un DataFrame."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    fecha_ayer = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    resp = session.post(
        f"{base_url}/includes/gpsrt/reporte-flota-maxirent.php",
        data={"Desde": fecha_ayer, "Hasta": fecha_ayer},
    )
    payload = _parse_json_bom(resp)

    # Confirmado contra el servidor real: la clave es "data", y cada fila
    # trae como primer elemento el link HTML del botón de comentarios
    # (checkbox/acciones de la tabla web) -> se descarta antes de armar el DF.
    filas = [fila[1:] for fila in payload["data"]]

    df = pd.DataFrame(filas, columns=COLUMNAS)
    log.info("Datos descargados de Maxinet: %d filas (fecha %s)", len(df), fecha_ayer)
    return df


def _obtener_clientes_rentas_lp() -> set:
    """Lee la columna T ('CLIENTES') de la pestaña 'Rentas activas detalle'
    (segundo archivo de Sheets) para diferenciar EN RENTA CLIENTE LP vs CP
    al reclasificar filas con Segmento 'OTROS' (confirmado con el equipo)."""
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID_SECUNDARIO"])
    ws = sh.worksheet("Rentas activas detalle")
    col_t = ws.col_values(20)  # columna T
    return {v.strip().upper() for v in col_t if v.strip()}


def leer_datos(df: pd.DataFrame) -> pd.DataFrame:
    """Punto de limpieza/transformación adicional si el reporte lo requiere."""
    # Maxinet entrega varios campos de texto (Segmento, Estatus Vehiculo, etc.)
    # rellenados con espacios al final (campo de ancho fijo en su origen).
    # Las fórmulas de UTILIZACION V3 comparan texto exacto (ej. COUNTIFS con
    # criterio "EN RENTA CLIENTE LP") y nunca hacían match contra el valor
    # real "EN RENTA CLIENTE LP  " (con espacios) -> se limpia aquí.
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].str.strip()

    # Regla del equipo: las placas de servicio (empiezan con "&SER") a veces
    # llegan de Maxinet con el Segmento/BSite/CurrentSite equivocado -> se
    # fuerzan siempre a "SERVICIOS" / "SE" / "SE".
    mask_servicios = df["Placa"].str.startswith("&SER", na=False)
    df.loc[mask_servicios, "Segmento"] = "SERVICIOS"
    df.loc[mask_servicios, "BSite"] = "SE"
    df.loc[mask_servicios, "CurrentSite"] = "SE"

    # Regla del equipo: Segmento "OTROS" con un cliente real asignado debe
    # reclasificarse a EN RENTA CLIENTE LP o CP, según si ese cliente aparece
    # en "Rentas activas detalle" (columna T = LP). Maxinet reutiliza este
    # mismo campo "Cliente Actual" para varios estatus internos de flota
    # (traslados, taller, baja, uso interno, etc.) que NO son clientes reales
    # -> se excluyen explícitamente para no reclasificarlos por error (caso
    # confirmado: unidad PN1269C con "T.PREVENTIVO LP" el 14-sep-2026).
    CONCEPTOS_NO_CLIENTE = {
        "TRASLADO",
        "T.CORRECTIVO CP", "T.CORRECTIVO LP",
        "T.PREVENTIVO CP", "T.PREVENTIVO LP",
        "TALLER", "TALLER EXTERNO", "TALLER FORANEO", "EXT. TALLER",
        "USO INTERNO", "USO INTERNO MECANICOS", "USO INTERNO GESTORIA", "USO INTERNO ALMACEN",
        "SEMINUEVOS", "PERDIDA TOTAL", "VENDIDO", "ROBADO", "RELEVOS",
        "ABUSO DE CONFIANZA", "SERVICIO EXTERNO",
    }
    cliente = df["Cliente Actual"].fillna("").str.strip()
    mask_otros_con_cliente = (
        (df["Segmento"] == "OTROS")
        & (cliente != "")
        & (~cliente.str.upper().isin(CONCEPTOS_NO_CLIENTE))
    )
    if mask_otros_con_cliente.any():
        clientes_lp = _obtener_clientes_rentas_lp()
        df.loc[mask_otros_con_cliente, "Segmento"] = cliente[mask_otros_con_cliente].str.upper().map(
            lambda c: "EN RENTA CLIENTE LP" if c in clientes_lp else "EN RENTA CLIENTE CP"
        )

    return df


def conectar_sheet():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID"])
    return sh.worksheet(os.environ["WORKSHEET_NAME"])


# Rango fijo de datos: encabezados reales en fila 1 (NUNCA se tocan), datos
# desde la fila 2 (inmediatamente debajo del encabezado, sin renglón en
# blanco de por medio). La columna A y todo lo que esté a la derecha de AN
# tiene fórmulas propias del Sheet y NUNCA debe tocarse.
COL_INICIO = "B"
COL_FIN = "AN"
FILA_INICIO_DATOS = 2
# Buffer de filas a limpiar antes de escribir, por si el reporte de hoy
# trae menos filas que el de ayer (evita dejar datos viejos "pegados" abajo)
MAX_FILAS_BUFFER = 5000


def actualizar_sheet(worksheet, df_nuevo: pd.DataFrame):
    """
    Sobrescribe el bloque de datos (B2:AN...) con la información nueva del día,
    sin tocar la columna A ni las columnas a la derecha de AN (que tienen
    fórmulas propias del Sheet). No se toca la fila de encabezados (fila 1):
    modificarla altera la estructura del archivo, que debe mantenerse fija
    tal como la definió el usuario, sin importar el orden/nombre de columnas
    que venga en el reporte de Maxinet.
    """
    n_filas = len(df_nuevo)

    # 1. Limpiar todo el rango de datos posible (por si hoy hay menos filas
    #    que ayer, para no dejar residuos de días anteriores)
    rango_limpiar = f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{FILA_INICIO_DATOS + MAX_FILAS_BUFFER}"
    worksheet.batch_clear([rango_limpiar])

    # 2. Escribir los datos nuevos
    # fillna("") antes de astype(str): de lo contrario los valores nulos
    # quedan como float NaN, que no es JSON válido y la API de Sheets
    # rechaza la petición (confirmado contra los datos reales).
    fila_final = FILA_INICIO_DATOS + n_filas - 1
    rango_datos = f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{fila_final}"
    worksheet.update(values=df_nuevo.fillna("").astype(str).values.tolist(), range_name=rango_datos)

    log.info("Sheet actualizado: %d filas escritas en %s", n_filas, rango_datos)


# =========================================================================
# SEGUNDO ARCHIVO DE GOOGLE SHEETS
# Contiene las pestañas "FLOTA LP" y "UTILIZACION V3"
# =========================================================================

def conectar_sheet_secundario(nombre_pestana: str):
    """Conecta al segundo archivo de Sheets (distinto del primero) y devuelve
    la pestaña solicitada."""
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SPREADSHEET_ID_SECUNDARIO"])
    return sh.worksheet(nombre_pestana)


def actualizar_sheet_flota_lp(worksheet, df_nuevo: pd.DataFrame):
    """
    Pega el bloque completo (incluyendo la columna A, tal como viene el
    reporte original) en la pestaña 'FLOTA LP': datos desde A2 (inmediatamente
    debajo del encabezado real, fila 1) hasta la fila final. La fila 1
    (encabezados) NUNCA se toca -- modificarla altera la estructura del
    archivo, que se mantiene fija sin importar el orden/nombre de columnas
    que venga en el reporte de Maxinet.
    """
    # La columna A del reporte original viene vacía (placeholder de
    # checkbox/acciones en la tabla web) -> la reproducimos aquí tal cual.
    df_con_columna_a = df_nuevo.copy()
    df_con_columna_a.insert(0, "", "")

    n_filas = len(df_con_columna_a)
    fila_inicio = 2
    fila_final = fila_inicio + n_filas - 1

    # Limpiar todo el rango de datos posible primero (por si el reporte de
    # hoy trae menos filas que el de ayer, para no dejar residuos pegados
    # abajo -- misma razón que en actualizar_sheet).
    rango_limpiar = f"A{fila_inicio}:AN{fila_inicio + MAX_FILAS_BUFFER}"
    worksheet.batch_clear([rango_limpiar])

    # Datos (fillna("") por la misma razón que en actualizar_sheet: NaN no
    # es JSON válido)
    worksheet.update(
        values=df_con_columna_a.fillna("").astype(str).values.tolist(),
        range_name=f"A{fila_inicio}:AN{fila_final}",
    )

    log.info("FLOTA LP actualizado: %d filas escritas (A%d:AN%d)", n_filas, fila_inicio, fila_final)


# =========================================================================
# "UTILIZACION V3": avance diario de la columna de fórmulas
# =========================================================================

FILA_FECHA_CALENDARIO = 2

# Fila 3 ("TOTAL ON HIRE", =IFERROR(SUM(B4:B6),"")) y filas 4-56 (métricas +
# agregados + VOR Cliente). NO es un simple corte "3 vs 4-39 vs 40-56": hay
# filas de agregado (sumas/porcentajes que referencian OTRAS filas de su
# propia columna, ej. fila 19 "=SUM(AZC8:AZC18)" o fila 25
# "=AZC22+AZC19+AZC3") MEZCLADAS entre las filas 4-39, no solo a partir de
# la 40 (confirmado contra el sheet real: filas 19, 24, 25, 28, 37 también
# son agregados). Por eso qué filas se congelan a valores se decide en
# tiempo real (ver _filas_a_congelar), no con un rango fijo -- congelar una
# fila de agregado por error deja un valor incorrecto para siempre y rompe
# en cascada cualquier otra fórmula que la referencie (ej. fila 46
# "=AZC22/AZC25").
FILA_TOTAL_ON_HIRE = 3
FILA_FORMULA_INICIO = 4
FILA_FORMULA_FIN = 56


MESES_ABREVIADOS = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
]


def _formatear_fecha_calendario(fecha) -> str:
    """Formatea la fecha como 'd-mmm' en español, sin año y sin cero a la
    izquierda (ej. 9-sep), tal como aparece realmente en la fila 2 de
    'UTILIZACION V3' (confirmado contra el sheet real: la columna AYT
    contiene '7-sep', no 'd/m/aaaa' como se asumía originalmente)."""
    return f"{fecha.day}-{MESES_ABREVIADOS[fecha.month - 1]}"


def _col_letra_a_indice(col_letra: str) -> int:
    """Convierte 'A' -> 0, 'B' -> 1, ..., 'AYT' -> índice correspondiente (0-based)."""
    indice = 0
    for char in col_letra.upper():
        indice = indice * 26 + (ord(char) - ord("A") + 1)
    return indice - 1


def _indice_a_col_letra(indice: int) -> str:
    """Convierte un índice 0-based de vuelta a letra de columna."""
    indice += 1
    letras = ""
    while indice > 0:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _encontrar_columna_por_fecha(worksheet, fecha_objetivo, col_referencia="AYT", rango_busqueda=10) -> int:
    """
    Busca en la fila 2 la columna cuya fecha coincide con fecha_objetivo,
    explorando alrededor de col_referencia (que es la última columna
    conocida con fórmulas activas).
    """
    fila_valores = worksheet.row_values(FILA_FECHA_CALENDARIO)
    idx_referencia = _col_letra_a_indice(col_referencia)
    fecha_str = _formatear_fecha_calendario(fecha_objetivo)

    # Explora desde un poco antes hasta un poco después de la columna de referencia,
    # ya que el avance es siempre de 1 columna por día.
    for offset in range(-rango_busqueda, rango_busqueda + 1):
        idx = idx_referencia + offset
        if 0 <= idx < len(fila_valores) and fila_valores[idx].strip() == fecha_str:
            return idx

    raise RuntimeError(
        f"No se encontró columna con fecha {fecha_str} cerca de {col_referencia}. "
        f"Verifica FORMATO_FECHA_CALENDARIO y la columna de referencia."
    )


def _es_autoreferencia(formula, col_letra: str, fila_fecha: int = FILA_FECHA_CALENDARIO) -> bool:
    """True si la fórmula referencia OTRA fila de su misma columna (aparte de
    la fila de fecha, que casi todos los COUNTIFS usan como criterio de
    filtro). Ese tipo de fórmula (sumas/porcentajes agregados dentro de la
    misma columna, ej. "=IFERROR(AYT3/AYT40,0)") nunca se debe congelar a
    valores -- su resultado depende de otras filas de la columna, no de un
    conteo directo contra FLOTA LP."""
    formula = str(formula) if formula else ""
    if not formula.startswith("="):
        return False
    refs = re.findall(rf"{re.escape(col_letra)}(\d+)", formula)
    return any(int(r) != fila_fecha for r in refs)


def _rangos_contiguos(filas) -> list:
    """Convierte una lista de números de fila en rangos (inicio, fin) contiguos."""
    rangos = []
    for fila in sorted(filas):
        if rangos and fila == rangos[-1][1] + 1:
            rangos[-1] = (rangos[-1][0], fila)
        else:
            rangos.append((fila, fila))
    return rangos


def _filas_a_congelar(worksheet, col_origen: str, fila_inicio: int, fila_fin: int) -> list:
    """De fila_inicio a fila_fin (columna col_origen), regresa los números de
    fila que son conteos genuinos (se deben congelar a valores) -- excluye
    las que se auto-referencian a otra fila de su propia columna."""
    formulas = worksheet.get(f"{col_origen}{fila_inicio}:{col_origen}{fila_fin}", value_render_option="FORMULA")
    filas_congelar = []
    for i in range(fila_fin - fila_inicio + 1):
        fila = fila_inicio + i
        formula = formulas[i][0] if i < len(formulas) and formulas[i] else ""
        if not _es_autoreferencia(formula, col_origen):
            filas_congelar.append(fila)
    return filas_congelar


def avanzar_columna_formulas(worksheet, col_referencia="AYT", fecha_objetivo=None):
    """
    Cada día: encuentra la columna correspondiente a 'ayer' (columna destino),
    copia las fórmulas desde la columna inmediatamente anterior (columna
    origen, que ya tiene fórmulas activas) hacia la destino, y luego convierte
    a valores fijos SOLO las filas de la columna origen que son conteos
    genuinos -- las que se auto-referencian a otra fila de su propia columna
    (agregados/porcentajes) se quedan vivas para siempre, igual que en el
    archivo original (esas filas están dispersas, no son un bloque
    contiguo -- ver _es_autoreferencia).

    fecha_objetivo: normalmente None (usa "ayer" real, para la corrida diaria).
    Se puede pasar una fecha explícita para ponerse al día si la
    automatización dejó de correr uno o más días (procesar un día a la vez,
    en orden, para que la columna origen de cada llamada ya tenga la fórmula
    recién copiada de la llamada anterior).
    """
    fecha_ayer = fecha_objetivo or (date.today() - timedelta(days=1))
    idx_destino = _encontrar_columna_por_fecha(worksheet, fecha_ayer, col_referencia=col_referencia)
    idx_origen = idx_destino - 1
    col_origen = _indice_a_col_letra(idx_origen)
    col_destino = _indice_a_col_letra(idx_destino)

    # Salvaguarda: si la columna destino ya tiene contenido, probablemente ya
    # se procesó (ej. la automatización corrió dos veces el mismo día). Copiar
    # de nuevo sobrescribiría la fórmula viva con el valor ya congelado de la
    # columna origen -- mejor no hacer nada y avisar.
    celda_destino = worksheet.get(f"{col_destino}{FILA_FORMULA_INICIO}", value_render_option="FORMULA")
    if celda_destino and celda_destino[0] and celda_destino[0][0] not in ("", None):
        log.warning(
            "UTILIZACION V3: la columna %s (fecha %s) ya tiene contenido -- "
            "no se repite el avance para evitar corromper la fórmula viva.",
            col_destino, fecha_ayer,
        )
        return

    filas_congelar = _filas_a_congelar(worksheet, col_origen, FILA_FORMULA_INICIO, FILA_FORMULA_FIN)

    sheet_id = worksheet.id
    spreadsheet = worksheet.spreadsheet

    def _rango(fila_inicio, fila_fin, col_idx):
        return {
            "sheetId": sheet_id,
            "startRowIndex": fila_inicio - 1,
            "endRowIndex": fila_fin,
            "startColumnIndex": col_idx,
            "endColumnIndex": col_idx + 1,
        }

    # 1. Copiar TODO el bloque (fila 3 + filas 4-56) a la columna nueva.
    requests_body = {
        "requests": [
            {
                "copyPaste": {
                    "source": _rango(FILA_TOTAL_ON_HIRE, FILA_FORMULA_FIN, idx_origen),
                    "destination": _rango(FILA_TOTAL_ON_HIRE, FILA_FORMULA_FIN, idx_destino),
                    "pasteType": "PASTE_FORMULA",
                }
            }
        ]
    }

    # 2. Congelar a valores SOLO las filas de conteo genuino (nunca las de
    # auto-referencia), un request por cada tramo contiguo detectado.
    for fila_ini, fila_fin in _rangos_contiguos(filas_congelar):
        requests_body["requests"].append(
            {
                "copyPaste": {
                    "source": _rango(fila_ini, fila_fin, idx_origen),
                    "destination": _rango(fila_ini, fila_fin, idx_origen),
                    "pasteType": "PASTE_VALUES",
                }
            }
        )

    spreadsheet.batch_update(requests_body)

    log.info(
        "UTILIZACION V3: fórmulas avanzadas de columna %s a %s (fecha %s), %d filas congeladas",
        col_origen, col_destino, fecha_ayer, len(filas_congelar),
    )


# =========================================================================
# "UTI. GRUPO DE AUTOS V1": avance diario de la columna de fórmulas
# =========================================================================
# Mismo mecanismo de calendario que UTILIZACION V3 (fila 2 = fechas "d-mmm"),
# y el mismo problema: NO es un simple corte "fila 3 | 4-83 | 84-115".
# Confirmado contra el sheet real: las filas 20, 36 y TODO el bloque 52-83
# también son fórmulas de agregado (ej. fila 20 "=SUM(XA21:XA35)", fila 68
# "=SUM(XA3,XA20,XA36)") mezcladas dentro de lo que se asumía era "4-83,
# congelar siempre". Igual que en UTILIZACION V3, qué filas se congelan se
# decide en tiempo real con _filas_a_congelar (ver _es_autoreferencia).

FILA_GRUPO_FLOTA_ACTIVA = 3
FILA_GRUPO_METRICAS_INICIO = 4
FILA_GRUPO_RATIOS_FIN = 115


def avanzar_columna_grupo_autos(worksheet, col_referencia="WX", fecha_objetivo=None):
    """
    Avanza un día la pestaña 'UTI. GRUPO DE AUTOS V1'. Copia toda la columna
    (fila 3 a 115) a la columna nueva, y congela a valores fijos SOLO las
    filas de la columna origen que son conteos genuinos -- las que se
    auto-referencian a otra fila de su propia columna (fila 3, y varias
    filas dispersas entre la 4 y la 115) se quedan vivas para siempre.
    """
    fecha_ayer = fecha_objetivo or (date.today() - timedelta(days=1))
    idx_destino = _encontrar_columna_por_fecha(worksheet, fecha_ayer, col_referencia=col_referencia)
    idx_origen = idx_destino - 1
    col_origen = _indice_a_col_letra(idx_origen)
    col_destino = _indice_a_col_letra(idx_destino)

    # Salvaguarda: misma razón que en avanzar_columna_formulas -- si la
    # columna destino ya tiene contenido, no repetir el avance.
    celda_destino = worksheet.get(f"{col_destino}{FILA_GRUPO_METRICAS_INICIO}", value_render_option="FORMULA")
    if celda_destino and celda_destino[0] and celda_destino[0][0] not in ("", None):
        log.warning(
            "UTI. GRUPO DE AUTOS V1: la columna %s (fecha %s) ya tiene contenido -- "
            "no se repite el avance para evitar corromper la fórmula viva.",
            col_destino, fecha_ayer,
        )
        return

    filas_congelar = _filas_a_congelar(worksheet, col_origen, FILA_GRUPO_METRICAS_INICIO, FILA_GRUPO_RATIOS_FIN)

    sheet_id = worksheet.id
    spreadsheet = worksheet.spreadsheet

    def _rango(fila_inicio, fila_fin, col_idx):
        return {
            "sheetId": sheet_id,
            "startRowIndex": fila_inicio - 1,
            "endRowIndex": fila_fin,
            "startColumnIndex": col_idx,
            "endColumnIndex": col_idx + 1,
        }

    # 1. Copiar TODO el bloque (fila 3 + filas 4-115) a la columna nueva.
    requests_body = {
        "requests": [
            {
                "copyPaste": {
                    "source": _rango(FILA_GRUPO_FLOTA_ACTIVA, FILA_GRUPO_RATIOS_FIN, idx_origen),
                    "destination": _rango(FILA_GRUPO_FLOTA_ACTIVA, FILA_GRUPO_RATIOS_FIN, idx_destino),
                    "pasteType": "PASTE_FORMULA",
                }
            }
        ]
    }

    # 2. Congelar a valores SOLO las filas de conteo genuino.
    for fila_ini, fila_fin in _rangos_contiguos(filas_congelar):
        requests_body["requests"].append(
            {
                "copyPaste": {
                    "source": _rango(fila_ini, fila_fin, idx_origen),
                    "destination": _rango(fila_ini, fila_fin, idx_origen),
                    "pasteType": "PASTE_VALUES",
                }
            }
        )

    spreadsheet.batch_update(requests_body)

    log.info(
        "UTI. GRUPO DE AUTOS V1: fórmulas avanzadas de columna %s a %s (fecha %s), %d filas congeladas",
        col_origen, col_destino, fecha_ayer, len(filas_congelar),
    )


# =========================================================================
# "UTILIZACION V3": indicador VOR Cliente (filas 50-56)
# =========================================================================
# Fuente de datos distinta a la del resto del Sheet: no viene del reporte de
# flota (reporte-flota-maxirent.php / COLUMNAS), sino de la tabla "VOR
# Cliente" del portal (dashboard-flota-lp.php), endpoint confirmado a partir
# del JS real de esa página:
#   POST {MAXINET_BASE_URL}/includes/flotaLP/historico-vor-cliente-data.php
#   body: Fecha=YYYY-MM-DD
#   respuesta: JSON estilo DataTables (procesamiento del lado del cliente,
#   sin paginar) con "data" = lista de filas:
#   [Fecha, Folio Mtto, Tipo Servicio, Placa, Grupo, Modelo, Reserva,
#    No Cliente, Cliente, Fecha Ingreso, Fecha Salida, Estatus Actual]
# Igual que el resto de la hoja: la fila que se escribe es la del día
# "ayer" (misma columna que ya dejó lista avanzar_columna_formulas).

FILA_VOR_CORRECTIVO_LOCAL = 50
FILA_VOR_PREVENTIVO_LOCAL = 51
FILA_VOR_CORRECTIVO_FORANEO = 53
FILA_VOR_PREVENTIVO_FORANEO = 54


def descargar_vor_cliente(session: requests.Session, fecha_str: str) -> list:
    """Pide al endpoint de VOR Cliente todos los registros de una fecha."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    resp = session.post(
        f"{base_url}/includes/flotaLP/historico-vor-cliente-data.php",
        data={"Fecha": fecha_str},
    )
    payload = _parse_json_bom(resp)
    return payload["data"]


def actualizar_vor_cliente(worksheet, session: requests.Session, col_referencia="AYT", fecha_objetivo=None):
    """
    Cuenta los registros de VOR Cliente del día "ayer" por Tipo Servicio y
    los escribe en la misma columna "viva" que avanzar_columna_formulas ya
    dejó lista para ese día (filas 50, 51, 53, 54). Las filas 52/55/56 son
    fórmulas de suma dentro de la misma columna -- ya se copiaron solas con
    el avance de columna, no se tocan aquí.
    """
    fecha_ayer = fecha_objetivo or (date.today() - timedelta(days=1))
    fecha_str = fecha_ayer.strftime("%Y-%m-%d")
    idx_col = _encontrar_columna_por_fecha(worksheet, fecha_ayer, col_referencia=col_referencia)
    col_letra = _indice_a_col_letra(idx_col)

    filas = descargar_vor_cliente(session, fecha_str)
    # Tipo Servicio viene con espacios de relleno inconsistentes desde
    # Maxinet (ej. "Preventivo Foráneo "), misma situación que Segmento en
    # el reporte de flota -> se limpia antes de contar.
    conteos = Counter(fila[2].strip() for fila in filas if len(fila) > 2)

    worksheet.update(
        values=[
            [conteos.get("Correctivo Local", 0)],
            [conteos.get("Preventivo Local", 0)],
        ],
        range_name=f"{col_letra}{FILA_VOR_CORRECTIVO_LOCAL}:{col_letra}{FILA_VOR_PREVENTIVO_LOCAL}",
    )
    worksheet.update(
        values=[
            [conteos.get("Correctivo Foráneo", 0)],
            [conteos.get("Preventivo Foráneo", 0)],
        ],
        range_name=f"{col_letra}{FILA_VOR_CORRECTIVO_FORANEO}:{col_letra}{FILA_VOR_PREVENTIVO_FORANEO}",
    )

    log.info(
        "VOR Cliente actualizado en columna %s (fecha %s): CorrectivoLocal=%d PreventivoLocal=%d "
        "CorrectivoForaneo=%d PreventivoForaneo=%d",
        col_letra, fecha_str,
        conteos.get("Correctivo Local", 0), conteos.get("Preventivo Local", 0),
        conteos.get("Correctivo Foráneo", 0), conteos.get("Preventivo Foráneo", 0),
    )


# =========================================================================
# "RESUMEN": columna E ("PERIODO") -- agrupa cada fecha en su quincena
# =========================================================================
# Confirmado contra el archivo original manual: cada fecha de la columna A
# se agrupa en "1-15" o "16-fin de mes" usando como valor SIEMPRE el
# calendario de 2026 (día 1 del mes, o +1 si es la segunda quincena) sin
# importar el año real de la fila -- es solo una etiqueta/categoría con
# formato de fecha (el año real se filtra aparte con la columna Z), por eso
# el mismo valor sirve para 2024, 2025 y 2026. Este proceso lo hacía a mano
# el equipo, por quincena, y por eso el archivo original mismo tiene huecos
# permanentes de sep-dic sin llenar en 2024, 2025 y 2026 -- se automatiza
# aquí para que ya no dependa de que alguien lo actualice.
EPOCH_SHEETS = date(1899, 12, 30)


def actualizar_periodo_resumen(worksheet) -> None:
    """Recalcula toda la columna E de 'RESUMEN' a partir de las fechas de
    la columna A. Es una fórmula pura de fecha (no depende de Maxinet ni del
    día anterior), así que recalcular todo cada día la mantiene siempre al
    día sin importar cuántas filas de A se hayan agregado."""
    col_a = worksheet.col_values(1, value_render_option="UNFORMATTED_VALUE")

    valores = []
    for valor in col_a[1:]:
        if not isinstance(valor, (int, float)):
            valores.append([""])
            continue
        fecha = EPOCH_SHEETS + timedelta(days=int(valor))
        ancla = date(2026, fecha.month, 1)
        serial_ancla = (ancla - EPOCH_SHEETS).days
        valores.append([serial_ancla if fecha.day <= 15 else serial_ancla + 1])

    ultima_fila = len(col_a)
    worksheet.update(values=valores, range_name=f"E2:E{ultima_fila}", value_input_option="USER_ENTERED")
    log.info("RESUMEN: columna PERIODO recalculada (%d filas)", len(valores))


def main():
    try:
        session = login_maxinet()
        df_nuevo = descargar_datos_flota(session)
        df_nuevo = leer_datos(df_nuevo)

        # IMPORTANTE: avanzar_columna_formulas() va ANTES de actualizar_sheet().
        # avanzar_columna_formulas copia la fórmula viva a la columna de mañana
        # y congela a valores fijos la columna de hoy -- usando los datos de
        # FLOTA LP tal como están AHORA (todavía los de ayer). Si actualizamos
        # el Sheet primero, FLOTA LP ya tendría los datos nuevos del día y la
        # columna que se está por congelar recalcularía contra la fecha
        # equivocada, dando 0 en vez del valor histórico real (confirmado con
        # el equipo). Este orden preserva el histórico correctamente.
        worksheet_util = conectar_sheet_secundario(os.environ["WORKSHEET_UTILIZACION"])
        avanzar_columna_formulas(worksheet_util)
        actualizar_vor_cliente(worksheet_util, session)

        worksheet_grupo_autos = conectar_sheet_secundario(os.environ["WORKSHEET_GRUPO_AUTOS"])
        avanzar_columna_grupo_autos(worksheet_grupo_autos)

        worksheet_resumen = conectar_sheet_secundario("RESUMEN")
        actualizar_periodo_resumen(worksheet_resumen)

        worksheet = conectar_sheet()
        actualizar_sheet(worksheet, df_nuevo)

        # FLOTA LP ya NO se escribe desde aquí: esa pestaña se alimenta con
        # un IMPORTRANGE en vivo desde "RESERVAS CP&LP" (decisión del
        # usuario). Escribir aquí choca con el array del IMPORTRANGE y lo
        # rompe (#REF!). actualizar_sheet_flota_lp() se deja definida por si
        # se necesita en el futuro, pero no se llama.

        log.info("Automatización completada con éxito")
    except Exception:
        log.exception("Error en la automatización diaria de Maxinet")
        sys.exit(1)


if __name__ == "__main__":
    main()
