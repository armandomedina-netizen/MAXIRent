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
import sys
import json
import logging
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

    # Regla del equipo: Segmento "OTROS" con un cliente real asignado (no
    # "TRASLADO") debe reclasificarse a EN RENTA CLIENTE LP o CP, según si
    # ese cliente aparece en "Rentas activas detalle" (columna T = LP).
    cliente = df["Cliente Actual"].fillna("").str.strip()
    mask_otros_con_cliente = (
        (df["Segmento"] == "OTROS")
        & (cliente != "")
        & (cliente.str.upper() != "TRASLADO")
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


def avanzar_columna_formulas(worksheet, col_referencia="AYT", fecha_objetivo=None):
    """
    Cada día: encuentra la columna correspondiente a 'ayer' (columna destino),
    copia las fórmulas desde la columna inmediatamente anterior (columna
    origen, que ya tiene fórmulas activas) hacia la destino, y luego convierte
    la columna origen a valores fijos para no acumular peso en el archivo.

    fecha_objetivo: normalmente None (usa "ayer" real, para la corrida diaria).
    Se puede pasar una fecha explícita para ponerse al día si la
    automatización dejó de correr uno o más días (procesar un día a la vez,
    en orden, para que la columna origen de cada llamada ya tenga la fórmula
    recién copiada de la llamada anterior).
    """
    fecha_ayer = fecha_objetivo or (date.today() - timedelta(days=1))
    idx_destino = _encontrar_columna_por_fecha(worksheet, fecha_ayer, col_referencia=col_referencia)
    idx_origen = idx_destino - 1

    # Salvaguarda: si la columna destino ya tiene contenido, probablemente ya
    # se procesó (ej. la automatización corrió dos veces el mismo día). Copiar
    # de nuevo sobrescribiría la fórmula viva con el valor ya congelado de la
    # columna origen -- mejor no hacer nada y avisar.
    col_destino = _indice_a_col_letra(idx_destino)
    celda_destino = worksheet.get(f"{col_destino}{FILA_FORMULA_INICIO}", value_render_option="FORMULA")
    if celda_destino and celda_destino[0] and celda_destino[0][0] not in ("", None):
        log.warning(
            "UTILIZACION V3: la columna %s (fecha %s) ya tiene contenido -- "
            "no se repite el avance para evitar corromper la fórmula viva.",
            col_destino, fecha_ayer,
        )
        return

    sheet_id = worksheet.id
    spreadsheet = worksheet.spreadsheet

    fila_inicio_0idx = FILA_FORMULA_INICIO - 1  # la API usa índices base 0
    fila_fin_0idx = FILA_FORMULA_FIN  # endRowIndex es exclusivo, así que no se resta 1

    requests_body = {
        "requests": [
            # 1. Copiar fórmulas de la columna origen a la columna destino
            #    (las referencias relativas se recorren automáticamente,
            #    igual que copiar/pegar una celda a la de al lado)
            {
                "copyPaste": {
                    "source": {
                        "sheetId": sheet_id,
                        "startRowIndex": fila_inicio_0idx,
                        "endRowIndex": fila_fin_0idx,
                        "startColumnIndex": idx_origen,
                        "endColumnIndex": idx_origen + 1,
                    },
                    "destination": {
                        "sheetId": sheet_id,
                        "startRowIndex": fila_inicio_0idx,
                        "endRowIndex": fila_fin_0idx,
                        "startColumnIndex": idx_destino,
                        "endColumnIndex": idx_destino + 1,
                    },
                    "pasteType": "PASTE_FORMULA",
                }
            },
            # 2. Convertir la columna origen (ya copiada) a valores fijos,
            #    para no seguir cargando con fórmulas viejas
            {
                "copyPaste": {
                    "source": {
                        "sheetId": sheet_id,
                        "startRowIndex": fila_inicio_0idx,
                        "endRowIndex": fila_fin_0idx,
                        "startColumnIndex": idx_origen,
                        "endColumnIndex": idx_origen + 1,
                    },
                    "destination": {
                        "sheetId": sheet_id,
                        "startRowIndex": fila_inicio_0idx,
                        "endRowIndex": fila_fin_0idx,
                        "startColumnIndex": idx_origen,
                        "endColumnIndex": idx_origen + 1,
                    },
                    "pasteType": "PASTE_VALUES",
                }
            },
        ]
    }

    spreadsheet.batch_update(requests_body)

    log.info(
        "UTILIZACION V3: fórmulas avanzadas de columna %s a %s (fecha %s)",
        _indice_a_col_letra(idx_origen), _indice_a_col_letra(idx_destino), fecha_ayer,
    )


def main():
    try:
        session = login_maxinet()
        df_nuevo = descargar_datos_flota(session)
        df_nuevo = leer_datos(df_nuevo)

        worksheet = conectar_sheet()
        actualizar_sheet(worksheet, df_nuevo)

        # FLOTA LP ya NO se escribe desde aquí: esa pestaña se alimenta con
        # un IMPORTRANGE en vivo desde "RESERVAS CP&LP" (decisión del
        # usuario). Escribir aquí choca con el array del IMPORTRANGE y lo
        # rompe (#REF!). actualizar_sheet_flota_lp() se deja definida por si
        # se necesita en el futuro, pero no se llama.

        worksheet_util = conectar_sheet_secundario(os.environ["WORKSHEET_UTILIZACION"])
        avanzar_columna_formulas(worksheet_util)

        log.info("Automatización completada con éxito")
    except Exception:
        log.exception("Error en la automatización diaria de Maxinet")
        sys.exit(1)


if __name__ == "__main__":
    main()
