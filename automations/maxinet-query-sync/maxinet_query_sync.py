"""
Automatización diaria: login + descarga del reporte "Cargo de Reservas"
desde Maxinet (vía requests, sin navegador) y reemplazo total de la base
de datos en la pestaña "QUERY" de un Google Sheet.

Endpoint confirmado a partir del HTML/JS reales de Maxinet
(reporte-cargo-de-reservas.php):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
            body: email=<usuario>, password=<contraseña>
    Datos:  POST {MAXINET_BASE_URL}/includes/reportesLP/reporte-cargo_de_reservas.php
            body: Estatus=ONHIRE, Desde=Hasta=fecha de hoy -- mismos valores
            que trae el formulario por defecto al abrir la liga (y los
            mismos que usa el botón "Excel" cuando alguien descarga el
            reporte a mano hoy). Este Sheet es una copia dedicada de
            "CLIENTES ACTIVOS (QUERY)" cuya pestaña "QUERY" YA es
            exactamente ese snapshot diario de hoy (confirmado el
            2026-09-18: fila 1 encabezados, filas 2-1242 con STATUS
            "ON HIRE" y fechas de hoy) -- automatizar con estos mismos
            parámetros replica tal cual el pegado manual que ya se hacía,
            sin necesidad de traer histórico.
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
    SPREADSHEET_ID_ORIGINAL -> (opcional) ID del Sheet original de Nuvia, del
        que SOLO se LEEN las reglas (fórmulas) a espejar. Nunca se escribe.

Flujo (cada corrida, pensada para correr cada hora):
    1. Login en Maxinet.
    2. Descarga el reporte de Cargo de Reservas de hoy (Estatus=ONHIRE,
       Desde=Hasta=hoy) -- no se filtra nada más, el reporte ya viene tal
       cual, solo se limpian espacios de más en columnas de texto.
    3. Espeja desde el Sheet ORIGINAL las reglas listadas en REGLAS_ESPEJO
       (hoy QUERY!P2:T2, la fila modelo TARIFA (QUERY)!B2:AA2 y el bloque
       por ejecutivo de TABLA RESUMEN!Z10:AB30):
       si Nuvia cambia una regla ahí, la copia la recoge sola. Solo lectura
       sobre el original, nunca se escribe en él.
    4. Reemplaza POR COMPLETO el bloque A2:O... de la pestaña "QUERY" con
       los datos nuevos, sin encabezados (no se hace merge/match por fila;
       el reporte de Maxinet reemplaza al anterior tal cual). Primero escribe
       y luego limpia lo que sobre, para que el Sheet nunca quede vacío a
       media corrida. Los datos se escriben interpretados (fechas y números
       reales, no texto), igual que el pegado manual.
    5. Extiende las fórmulas auxiliares de la misma pestaña (columnas P a
       U: SIN IVA, MENSUAL, MODELO, RENTA + CDW, COMPACTOS, codigo)
       copiando la fórmula de la fila 2 hasta la última fila de datos, y
       limpia las que sobren por debajo. Antes de esto, si el reporte
       crecía más allá de donde llegaban esas fórmulas, las filas nuevas
       quedaban sin SIN IVA/RENTA y "TARIFA (QUERY)!O" (SUMIFS sobre
       QUERY!P) daba 0 para esas placas.
    6. Ajusta las filas de "TARIFA (QUERY)" (columnas B:AA) al número de
       placas del día: copia la fórmula de la fila 2 hacia abajo y limpia
       las que sobren. Es lo que Nuvia hacía a mano; sin esto, los días
       que baja la flota quedan filas con #N/A y los que sube, placas sin
       datos. Las fórmulas se escriben con repeatCell y no con copyPaste:
       copyPaste falla si alguien dejó un filtro que oculta filas (pasó el
       8-oct con un filtro por PERIODO DE RETORNO), y el filtro se respeta.
    7. Avisa en el log si alguna placa trae más de una línea RENT (ver
       PENDIENTE abajo).

PENDIENTE (confirmado el 2026-09-18, todavía SIN implementar -- falta
la regla exacta): si una misma reserva trae DOS líneas de cargo "RENT"
el mismo día para la misma placa (pasó con la reserva #202881869 /
placa PS8653B, solo cambiaba ReturnDate), el FILTER de "TARIFA (QUERY)"
que asume una sola coincidencia por placa muestra "#REF!" puntual para
esa placa. Nuvia (quien mantenía esto a mano) confirmó que es un bug
recurrente del lado de Maxinet ("sistemas" no lo ha corregido) y que
ella borra manualmente la fila duplicada -- ese paso de limpieza debe
agregarse aquí, pero aún no se sabe con qué regla exacta decide cuál de
las dos filas conservar. No adivinar esa regla; ver memoria del proyecto
para el estado de este pendiente antes de implementar un dedup.
"""

import os
import sys
import json
import logging
from datetime import date

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
    hoy = date.today().strftime("%Y-%m-%d")

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

# Columnas con fórmulas auxiliares por fila (P a U) que viven en la misma
# pestaña. La fila FILA_INICIO_DATOS es el modelo que se copia hacia abajo.
COL_FORMULAS_INICIO = "P"
COL_FORMULAS_FIN = "U"

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


def _repetir_formulas_modelo(worksheet, fila_modelo: int, fila_final: int, col_ini: int, formulas: list):
    """
    Escribe cada fórmula de la fila modelo en su columna, desde la fila
    modelo hasta fila_final, con un repeatCell por columna: la API recorre
    las referencias relativas fila por fila (igual que arrastrar) y, a
    diferencia de copyPaste, funciona aunque un filtro oculte filas.
    col_ini es el índice (base 0) de la columna de la primera fórmula.
    """
    worksheet.spreadsheet.batch_update({"requests": [{
        "repeatCell": {
            "range": {"sheetId": worksheet.id, "startRowIndex": fila_modelo - 1, "endRowIndex": fila_final,
                      "startColumnIndex": col_ini + j, "endColumnIndex": col_ini + j + 1},
            "cell": {"userEnteredValue": {"formulaValue": formula}},
            "fields": "userEnteredValue",
        }
    } for j, formula in enumerate(formulas)]})


def _extender_formulas(worksheet, fila_final: int):
    """
    Copia las fórmulas de la fila modelo (FILA_INICIO_DATOS, columnas P:U)
    hacia abajo hasta fila_final -- las referencias relativas se recorren
    solas, igual que arrastrar la fila en Sheets -- y limpia P:U por debajo
    de fila_final.
    """
    rango_modelo = f"{COL_FORMULAS_INICIO}{FILA_INICIO_DATOS}:{COL_FORMULAS_FIN}{FILA_INICIO_DATOS}"
    col_ini = gspread.utils.a1_to_rowcol(f"{COL_FORMULAS_INICIO}1")[1] - 1
    col_fin = gspread.utils.a1_to_rowcol(f"{COL_FORMULAS_FIN}1")[1]  # exclusivo
    n_cols = col_fin - col_ini

    modelo = worksheet.get(rango_modelo, value_render_option="FORMULA")
    fila_modelo = modelo[0] if modelo else []
    if len(fila_modelo) < n_cols or not all(str(c).startswith("=") for c in fila_modelo):
        # Sin fórmulas modelo no se puede copiar nada: mejor avisar fuerte
        # que dejar filas nuevas sin SIN IVA/RENTA en silencio.
        raise RuntimeError(
            f"No se extendieron las fórmulas: {rango_modelo} ya no contiene "
            f"{n_cols} fórmulas (encontré: {fila_modelo!r})."
        )

    if fila_final > FILA_INICIO_DATOS:
        _repetir_formulas_modelo(worksheet, FILA_INICIO_DATOS, fila_final, col_ini, fila_modelo[:n_cols])

    sobrante = f"{COL_FORMULAS_INICIO}{fila_final + 1}:{COL_FORMULAS_FIN}{fila_final + MAX_FILAS_BUFFER}"
    worksheet.batch_clear([sobrante])
    log.info("Fórmulas %s:%s extendidas hasta la fila %d (sobrantes limpiadas)",
             COL_FORMULAS_INICIO, COL_FORMULAS_FIN, fila_final)


# Reglas que se espejan del Sheet ORIGINAL (hoja, rango): solo lectura sobre
# el original. Se copian las celdas con contenido que difieran; las vacías
# (por ejemplo las que son resultado de un UNIQUE) se ignoran.
REGLAS_ESPEJO = [
    ("QUERY", "P2:T2"),
    # Fila modelo de TARIFA (QUERY); ajustar_filas_tarifa la extiende a todas
    # las placas (p. ej. la regla de PROX RETORNOS de la columna X).
    ("TARIFA (QUERY)", "B2:AA2"),
    ("TABLA RESUMEN", "Z10:AB30"),
]


def espejar_reglas(libro_destino):
    """
    Lee de la copia y del ORIGINAL (solo get, jamás update en el original) los
    rangos de REGLAS_ESPEJO con fórmulas sin evaluar y escribe en la copia las
    celdas que difieran. Así la copia hereda las reglas de Nuvia (ej. el
    SUB -> SUV de COMPACTOS) sin hardcodear fórmulas en el repo público.
    """
    id_original = os.environ.get("SPREADSHEET_ID_ORIGINAL")
    if not id_original:
        log.info("SPREADSHEET_ID_ORIGINAL no definido -- no se espejan reglas del original")
        return
    libro_origen = _cliente_gspread().open_by_key(id_original)

    for hoja, rango in REGLAS_ESPEJO:
        orig = libro_origen.worksheet(hoja).get(rango, value_render_option="FORMULA")
        dest_ws = libro_destino.worksheet(hoja)
        dest = dest_ws.get(rango, value_render_option="FORMULA")
        fila0, col0 = gspread.utils.a1_to_rowcol(rango.split(":")[0])

        cambios = []
        for i, fila in enumerate(orig):
            for j, valor in enumerate(fila):
                if valor in ("", None):
                    continue
                actual = dest[i][j] if i < len(dest) and j < len(dest[i]) else ""
                if actual != valor:
                    cambios.append({"range": gspread.utils.rowcol_to_a1(fila0 + i, col0 + j), "values": [[valor]]})
        if cambios and os.environ.get("ESPEJO_SOLO_LOG") == "1":
            log.info("[SOLO LOG] Cambiaría en '%s' %s: %s", hoja, rango,
                     json.dumps(cambios, ensure_ascii=False))
        elif cambios:
            celdas = ", ".join(c["range"] for c in cambios)  # gspread modifica 'range' al enviar
            try:
                dest_ws.batch_update(cambios, raw=False)
            except gspread.exceptions.APIError as exc:
                if "protected" not in str(exc).lower():
                    raise
                # Hoja/rango protegido en la copia: no es un fallo de la
                # automatización. Se avisa con la acción a tomar y se sigue.
                log.warning(
                    "No se pudo espejar '%s' %s (%s): la hoja/rango está PROTEGIDO en la copia. "
                    "Agregar maxinet-sync@unique-moon-508216-f7.iam.gserviceaccount.com como editor "
                    "en Datos > Hojas y rangos protegidos.", hoja, rango, celdas)
                continue
            log.info("Regla espejada del original en '%s' %s: %d celda(s) actualizada(s) (%s)",
                     hoja, rango, len(cambios), celdas)
        else:
            log.info("Regla de '%s' %s ya coincide con el original", hoja, rango)


# "TARIFA (QUERY)": la columna A es un FILTER que se derrama (una fila por cada
# línea RENT de QUERY) y las columnas B:AA son fórmulas por fila que deben
# existir exactamente para esas placas.
HOJA_TARIFA = "TARIFA (QUERY)"
COL_TARIFA_INICIO = "B"
COL_TARIFA_FIN = "AA"
FILA_TARIFA_MODELO = 2


def _asegurar_filas(worksheet, fila_necesaria: int):
    if fila_necesaria > worksheet.row_count:
        worksheet.add_rows(fila_necesaria - worksheet.row_count)


def ajustar_filas_tarifa(libro, df_nuevo: pd.DataFrame):
    """
    Deja las fórmulas por fila de TARIFA (QUERY)!B:AA justo para las placas de
    hoy (= líneas RENT del reporte, que es lo que derrama A2): copia la fila 2
    hacia abajo y limpia las filas que sobren.
    """
    ws = libro.worksheet(HOJA_TARIFA)
    n_placas = int((df_nuevo["CONCEPTO_CARGO"].str.strip().str.upper() == "RENT").sum())
    fila_final = FILA_TARIFA_MODELO + n_placas - 1
    if n_placas == 0:
        log.warning("Ninguna línea RENT hoy -- no se ajustan las filas de %s", HOJA_TARIFA)
        return

    col_ini = gspread.utils.a1_to_rowcol(f"{COL_TARIFA_INICIO}1")[1] - 1
    col_fin = gspread.utils.a1_to_rowcol(f"{COL_TARIFA_FIN}1")[1]  # exclusivo
    rango_modelo = f"{COL_TARIFA_INICIO}{FILA_TARIFA_MODELO}:{COL_TARIFA_FIN}{FILA_TARIFA_MODELO}"
    modelo = ws.get(rango_modelo, value_render_option="FORMULA")
    fila_modelo = modelo[0] if modelo else []
    if len(fila_modelo) < (col_fin - col_ini) or not all(str(c).startswith("=") for c in fila_modelo):
        raise RuntimeError(f"{HOJA_TARIFA}!{rango_modelo} ya no contiene fórmulas en todas las columnas: {fila_modelo!r}")

    _asegurar_filas(ws, fila_final)
    if fila_final > FILA_TARIFA_MODELO:
        _repetir_formulas_modelo(ws, FILA_TARIFA_MODELO, fila_final, col_ini, fila_modelo[:col_fin - col_ini])
    ws.batch_clear([f"{COL_TARIFA_INICIO}{fila_final + 1}:{COL_TARIFA_FIN}{fila_final + MAX_FILAS_BUFFER}"])
    log.info("%s: fórmulas %s:%s ajustadas a %d placas (filas %d-%d)",
             HOJA_TARIFA, COL_TARIFA_INICIO, COL_TARIFA_FIN, n_placas, FILA_TARIFA_MODELO, fila_final)


def avisar_duplicados_rent(df: pd.DataFrame):
    """Solo avisa (no borra): placas con más de una línea RENT el mismo día."""
    rent = df[df["CONCEPTO_CARGO"].str.strip().str.upper() == "RENT"]
    dup = rent[rent.duplicated("CURRENT_REG_NO", keep=False)]
    if len(dup):
        # Solo el conteo: el repo es público y los logs de Actions los puede ver
        # cualquiera con cuenta de GitHub, así que no se imprimen placas ni
        # números de reserva. Para ubicarlas: filtrar RENT repetidos en QUERY!C.
        log.warning("%d placa(s) traen más de una línea RENT -- romperán el FILTER de TARIFA (QUERY); "
                    "falta definir la regla para cuál conservar",
                    dup["CURRENT_REG_NO"].nunique())


def actualizar_query(worksheet, df_nuevo: pd.DataFrame):
    """
    Reemplaza POR COMPLETO el bloque de datos A2:O... con el reporte
    descargado: no se hace merge/match por fila, el reporte de Maxinet
    reemplaza al anterior tal cual (decisión del usuario). Como corre cada
    hora, primero ESCRIBE los datos nuevos encima y después limpia solo lo
    que sobre por debajo -- así el Sheet nunca queda vacío ni con errores a
    media corrida. Después extiende las fórmulas auxiliares P:U.
    """
    n_filas = len(df_nuevo)

    if n_filas == 0:
        log.warning("El reporte de Maxinet vino vacío -- no se toca QUERY para no borrar los datos buenos.")
        return

    # 1. Escribir los datos nuevos con tipos reales. raw=False = USER_ENTERED:
    #    con el modo "raw" que usa gspread por default, las fechas y los
    #    precios quedaban guardados como texto ('2019-06-25', '962.4'),
    #    distinto al Sheet original donde son fecha y número.
    fila_final = FILA_INICIO_DATOS + n_filas - 1
    _asegurar_filas(worksheet, fila_final)
    rango_datos = f"{COL_INICIO}{FILA_INICIO_DATOS}:{COL_FIN}{fila_final}"
    worksheet.update(values=_valores_para_hoja(df_nuevo), range_name=rango_datos, raw=False)
    log.info("QUERY actualizado: %d filas escritas en %s", n_filas, rango_datos)

    # 2. Limpiar solo lo que sobre debajo (si hoy hay menos filas que ayer)
    worksheet.batch_clear([f"{COL_INICIO}{fila_final + 1}:{COL_FIN}{fila_final + MAX_FILAS_BUFFER}"])

    # 3. Fórmulas auxiliares P:U hasta la última fila de datos
    _extender_formulas(worksheet, fila_final)


def main():
    try:
        df_nuevo = descargar_cargo_de_reservas()
        avisar_duplicados_rent(df_nuevo)

        libro = conectar_libro_destino()
        worksheet = conectar_sheet_query(libro)

        # Pasos secundarios: si fallan se registra, se sigue con los datos y la
        # corrida termina en error al final para que se note (correo de GitHub).
        fallos = []
        try:
            espejar_reglas(libro)
        except Exception:
            log.exception("No se pudieron espejar las reglas del original")
            fallos.append("espejar_reglas")

        actualizar_query(worksheet, df_nuevo)

        try:
            ajustar_filas_tarifa(libro, df_nuevo)
        except Exception:
            log.exception("No se pudieron ajustar las filas de TARIFA (QUERY)")
            fallos.append("ajustar_filas_tarifa")

        if fallos:
            log.error("Datos actualizados, pero fallaron pasos secundarios: %s", ", ".join(fallos))
            sys.exit(1)
        log.info("Automatización completada con éxito")
    except Exception:
        log.exception("Error en la automatización diaria de Cargo de Reservas")
        sys.exit(1)


if __name__ == "__main__":
    main()
