"""
Revisión diaria: login + lectura del reporte "Clientes Frecuentes Activos 35"
desde Maxinet vía requests (sin navegador) y actualización de la pestaña
"Clientes Frecuentes Activos 35" del Sheet "Base" (copia de "h encuestas").

Endpoint confirmado a partir del HTML/JS reales de Maxinet
(cp-reporte-clientes-frecuentes-activos-v2.php):
    Login:  POST {MAXINET_BASE_URL}/includes/users/AccessValidate.php
    Datos:  POST {MAXINET_BASE_URL}/json/cp-frecuentes-activos-data-v2.php
            body: Periodo=<id de la semana del selector>   (tarda ~100 s)
            respuesta: {"data": [[36 valores], ...]}: una columna de acciones
            ("Editar") al inicio, las columnas de datos y "Comentario" al final.
    Encabezados: salen de la tabla de la página (se ignoran los comentarios
    HTML, p. ej. "Facturación 2 meses", que no se muestra).
    Semana: la de fecha más reciente del selector "Semana" (Periodo).

Qué es esta pestaña: una foto COMPLETA del reporte de UNA semana, no un historial.
Cada corrida compara esa semana contra el Sheet y, si hay cualquier cambio,
REEMPLAZA el bloque de datos con la información actual de Maxinet (alta y baja de
clientes, cambios de asesor/tipo y las semanas). Si no hay cambios no escribe
nada. El log resume qué cambió.

Qué semana: siempre la MÁS RECIENTE del selector "Semana". La copia es un archivo
independiente del original (el de Nuvia, que ella pega a mano más o menos una vez al
mes): puede ir más adelantada que él y eso es correcto. La semana cargada queda anotada
en una celda bajo el enlace del encabezado ("Semana cargada: 193 (2026-10-10)") para saber
a qué corte corresponde la hoja. PERIODO=<id> fija una semana (pruebas).

Columnas: A:AH hoy (Sucursal ... Sem 24). El reporte crece por semanas: si
Maxinet agrega "Sem 25", se inserta la columna antes de "Comentario" (las
columnas manuales se recorren hacia la derecha) y se escribe su encabezado.
Si Maxinet quita o renombra columnas, la corrida se detiene SIN escribir.

Columnas que NO son de Maxinet y se respetan:
    - "Comentario": en el Sheet es manual (unas pocas filas). Como al reemplazar
      el bloque los clientes cambian de fila, los comentarios se vuelven a
      colocar por No. Cliente.
    - "TIPO": fórmula (=IF(C2="","","CLIENTE FRECUENTE")); se verifica que
      exista hasta la última fila y se copia si falta.
    - El enlace del reporte en el encabezado.

IDs: los No. Cliente que empiezan con "$" se escriben como texto (ver ADR 0007);
los numéricos sin prefijo se escriben como número, igual que en el resto del
Sheet y en el XLOOKUP de la columna NOMINA de ENTREGAS.

Salvaguarda: si el reporte trae menos de la mitad de las filas actuales, la
corrida se detiene (probable respuesta incompleta); FORZAR=1 la omite.

Variables de entorno (ver .env.example):
    MAXINET_BASE_URL, MAXINET_USER, MAXINET_PASS, GOOGLE_CREDS_PATH,
    SPREADSHEET_ID_CLIENTES_NUEVOS (mismo Sheet "Base"),
    WORKSHEET_FRECUENTES_NAME, PERIODO, DRY_RUN, FORZAR (opcionales)
"""

import os
import re
import sys
import json
import logging
import datetime as dt

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maxinet_frecuentes_activos_cp")

PAGINA = "cp-reporte-clientes-frecuentes-activos-v2.php"
ENDPOINT = "json/cp-frecuentes-activos-data-v2.php"
COLUMNAS_FIJAS = ["Sucursal", "Asesor", "Tipo", "No. Cliente", "Nombre", "Cumpleaños",
                  "Tipo Persona", "Giro", "Tipo CF", "No. Semanas Renta"]
IDX_CLIENTE = 3
IDX_NUMERICAS_DESDE = 9          # No. Semanas Renta y Sem N son números
SEM_RE = re.compile(r"^Sem (\d+)$")
FILA_ENCABEZADOS = 1
FILA_INICIO = 2
TIMEOUT_SEG = 300                # el reporte tarda ~100 s
REINTENTOS = 3
BASE_SERIAL = dt.date(1899, 12, 30)
CHUNK = 500
NOTA_RE = re.compile(r"^Semana cargada:\s*(\d+)\s*\((\d{4}-\d{2}-\d{2})\)")


# ---------------------------------------------------------------- Maxinet
def _parse_json_bom(resp: requests.Response):
    texto = resp.content.decode("utf-8-sig")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        log.error("Respuesta de Maxinet no es JSON válido. Primeros 500 caracteres: %r", texto[:500])
        raise


def _nueva_sesion() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=REINTENTOS, connect=REINTENTOS, read=REINTENTOS, status=REINTENTOS,
                  backoff_factor=2, status_forcelist=(502, 503, 504), allowed_methods=None)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def login_maxinet() -> requests.Session:
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = _nueva_sesion()
    resp = session.post(
        f"{base_url}/includes/users/AccessValidate.php",
        data={"email": os.environ["MAXINET_USER"], "password": os.environ["MAXINET_PASS"]},
        timeout=TIMEOUT_SEG,
    )
    data = _parse_json_bom(resp)
    if data.get("respuesta") == "error":
        raise RuntimeError(f"Login falló en Maxinet: {data.get('valor')}")
    log.info("Login en Maxinet exitoso")
    return session


def leer_pagina(html: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(encabezados de la tabla, [(id, fecha)] de las semanas del selector)."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)        # "Facturación 2 meses" va comentada
    thead = html[html.find("<thead"):html.find("</thead>")]
    encabezados = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<th[^>]*>(.*?)</th>", thead, flags=re.S)]
    select = html[html.find('name="Periodo"'):]
    select = select[:select.find("</select>")]
    semanas = re.findall(r'<option value="(\d+)"[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</option>', select)
    return encabezados, semanas


def columnas_de_datos(encabezados: list[str]) -> list[str]:
    """Nombres de las columnas de datos (sin la de acciones ni 'Comentario'), validados."""
    if len(encabezados) < len(COLUMNAS_FIJAS) + 3 or encabezados[0] != "" or encabezados[-1] != "Comentario":
        raise RuntimeError(f"La tabla de Maxinet cambió de estructura: encabezados {encabezados[:3]}...{encabezados[-2:]}. "
                           f"No se escribió nada en el Sheet.")
    datos = encabezados[1:-1]
    if datos[:len(COLUMNAS_FIJAS)] != COLUMNAS_FIJAS:
        raise RuntimeError(f"Las primeras columnas de Maxinet cambiaron: {datos[:len(COLUMNAS_FIJAS)]}. No se escribió nada en el Sheet.")
    numeros = [int(SEM_RE.match(c).group(1)) if SEM_RE.match(c) else None for c in datos[len(COLUMNAS_FIJAS):]]
    if None in numeros or numeros != list(range(1, len(numeros) + 1)) or not numeros:
        raise RuntimeError(f"Las columnas de semanas de Maxinet no son 'Sem 1..N' contiguas: {datos[len(COLUMNAS_FIJAS):]}. "
                           f"No se escribió nada en el Sheet.")
    return datos


def semana_mas_reciente(semanas: list[tuple[str, str]]) -> tuple[str, str]:
    if not semanas:
        raise RuntimeError("No se encontró el selector de semanas en la página de Maxinet.")
    return max(semanas, key=lambda s: s[1])


def normalizar_filas(filas: list[list], n_datos: int) -> list[list]:
    """Quita la columna de acciones y 'Comentario'; texto sin espacios, nulos como ""
    y números como int en No. Semanas Renta y Sem N."""
    if not filas:
        return []
    anchos = {len(f) for f in filas}
    if anchos != {n_datos + 2}:
        raise RuntimeError(f"Maxinet devolvió filas de {sorted(anchos)} columnas y se esperan {n_datos + 2} "
                           f"(acciones + {n_datos} de datos + Comentario). No se escribió nada en el Sheet.")
    out = []
    for f in filas:
        fila = []
        for j, v in enumerate(f[1:1 + n_datos]):
            v = "" if v is None else (v.strip() if isinstance(v, str) else v)
            if j >= IDX_NUMERICAS_DESDE and isinstance(v, str) and re.fullmatch(r"-?\d+", v):
                v = int(v)
            fila.append(v)
        if not str(fila[IDX_CLIENTE]) or "<" in str(fila[IDX_CLIENTE]):
            raise RuntimeError(f"Las columnas de Maxinet no cuadran (No. Cliente={str(fila[IDX_CLIENTE])[:40]!r}). "
                               f"No se escribió nada en el Sheet.")
        out.append(fila)
    return out


def info_maxinet():
    """Encabezados de datos y semanas disponibles, según la página de Maxinet."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    html = session.get(f"{base_url}/{PAGINA}", timeout=TIMEOUT_SEG).content.decode("utf-8", "replace")
    encabezados, semanas = leer_pagina(html)
    return columnas_de_datos(encabezados), semanas


def descargar_semana(periodo: str, n_datos: int) -> list[list]:
    """Filas normalizadas de una semana (sesión propia: se puede llamar en paralelo)."""
    base_url = os.environ["MAXINET_BASE_URL"].rstrip("/")
    session = login_maxinet()
    resp = session.post(f"{base_url}/{ENDPOINT}", data={"Periodo": periodo}, timeout=TIMEOUT_SEG)
    filas = normalizar_filas(_parse_json_bom(resp)["data"], n_datos)
    vistos, unicas = set(), []
    for f in filas:
        k = _norm_id(f[IDX_CLIENTE])
        if k in vistos:
            log.warning("No. Cliente repetido en el reporte de Maxinet (semana %s), se conserva el primero: %s", periodo, f[IDX_CLIENTE])
            continue
        vistos.add(k)
        unicas.append(f)
    log.info("Semana %s descargada de Maxinet: %d clientes", periodo, len(unicas))
    return unicas


# ------------------------------------------------------------------ Sheet
def _norm_id(v) -> str:
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return re.sub(r"[#$,.\s]", "", str(v)).lower()


def _celda(v):
    """'=', '+', '@' y '$' al inicio se fuerzan a texto (fórmula/moneda dañarían el ID)."""
    if isinstance(v, str) and v.startswith(("=", "+", "@", "$")):
        return "'" + v
    return v


def _valor_hoja(v, j):
    """Valor de una celda leída con UNFORMATTED_VALUE, en la misma forma que Maxinet."""
    if v is None:
        return ""
    if j == 5 and isinstance(v, (int, float)) and v:                       # Cumpleaños: serial -> ISO
        return (BASE_SERIAL + dt.timedelta(days=int(v))).isoformat()
    if isinstance(v, float) and v == int(v):
        v = int(v)
    if j == IDX_CLIENTE:                       # Sheets guarda "634" como número; Maxinet lo da como texto
        return str(v).strip()
    if isinstance(v, str):
        v = v.strip()
        if j >= IDX_NUMERICAS_DESDE and re.fullmatch(r"-?\d+", v):
            v = int(v)
    return v


def _cliente():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds)


def _nombre_pestana(var: str) -> str:
    return (os.environ.get(var) or "").strip().strip("\"'").strip() or "Clientes Frecuentes Activos 35"


def resolver_pestana(libro, referencia: str):
    """La pestaña del libro por gid (si la referencia es un número) o por nombre. Nuvia renombra pestañas;
    el gid no cambia. Los logs son públicos: si falta, el error sólo dice cuántas pestañas tiene el libro."""
    referencia = str(referencia).strip()
    try:
        return libro.get_worksheet_by_id(int(referencia)) if referencia.isdigit() else libro.worksheet(referencia)
    except gspread.exceptions.WorksheetNotFound:
        raise gspread.exceptions.WorksheetNotFound(
            f"{referencia} (el libro tiene {len(libro.worksheets())} pestañas; si la renombraron, usa su gid en el secret)") from None


def conectar_sheet():
    libro = _cliente().open_by_key(os.environ["SPREADSHEET_ID_CLIENTES_NUEVOS"])
    return resolver_pestana(libro, _nombre_pestana("WORKSHEET_FRECUENTES_NAME"))


# Registro de la semana cargada: una celda de texto bajo el enlace del encabezado (columna "http...").
def _celda_estado(ws):
    enc = ws.row_values(FILA_ENCABEZADOS)
    for i, h in enumerate(enc, start=1):
        if str(h).strip().lower().startswith("http"):
            return f"{_col(i)}{FILA_INICIO}"
    return None


def leer_estado(ws):
    celda = _celda_estado(ws)
    if not celda:
        return None
    v = ws.get(celda)
    m = NOTA_RE.match(str(v[0][0])) if v and v[0] else None
    return (m.group(1), m.group(2)) if m else None


def guardar_estado(ws, periodo: str, etiqueta: str):
    celda = _celda_estado(ws)
    if celda and not os.environ.get("DRY_RUN") and leer_estado(ws) != (periodo, etiqueta):
        ws.update(range_name=celda, values=[[f"Semana cargada: {periodo} ({etiqueta})"]], value_input_option="RAW")


def _col(n: int) -> str:
    return gspread.utils.rowcol_to_a1(1, n).rstrip("1")


def estructura_hoja(ws) -> dict:
    """Posiciones (1-indexadas) de las columnas de datos, 'Comentario' y 'TIPO' según el encabezado."""
    enc = [h.strip() for h in ws.row_values(FILA_ENCABEZADOS)]
    if enc[:len(COLUMNAS_FIJAS)] != COLUMNAS_FIJAS or "Comentario" not in enc:
        raise RuntimeError(f"La estructura de la pestaña cambió: encabezados {enc[:4]}... No se escribió nada.")
    c_com = enc.index("Comentario") + 1
    datos = enc[:c_com - 1]
    sems = datos[len(COLUMNAS_FIJAS):]
    if sems != [f"Sem {i}" for i in range(1, len(sems) + 1)]:
        raise RuntimeError(f"Las columnas de semanas de la pestaña no son 'Sem 1..N' contiguas: {sems}. No se escribió nada.")
    c_tipo = enc.index("TIPO") + 1 if "TIPO" in enc else None
    return {"datos": datos, "n_datos": len(datos), "c_comentario": c_com, "c_tipo": c_tipo}


def adaptar_columnas(ws, est: dict, datos_mx: list[str]) -> dict:
    """Si Maxinet tiene más 'Sem N' que la pestaña, inserta columnas antes de 'Comentario'."""
    if datos_mx[:est["n_datos"]] != est["datos"]:
        raise RuntimeError("Las columnas de Maxinet no coinciden con las de la pestaña "
                           f"(pestaña termina en {est['datos'][-1]}, Maxinet tiene {datos_mx[:est['n_datos']][-1:]}). "
                           "No se escribió nada.")
    extra = datos_mx[est["n_datos"]:]
    if not extra:
        return est
    log.warning("Maxinet agregó columnas de semanas: %s. Se insertan antes de 'Comentario'.", extra)
    if os.environ.get("DRY_RUN"):
        return {**est, "n_datos": len(datos_mx), "datos": datos_mx, "c_comentario": est["c_comentario"] + len(extra),
                "c_tipo": est["c_tipo"] + len(extra) if est["c_tipo"] else None}
    ini = est["c_comentario"] - 1                                  # índice 0-based donde va la nueva columna
    ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": ini, "endIndex": ini + len(extra)},
        "inheritFromBefore": True}}]})
    ws.update(range_name=f"{_col(est['c_comentario'])}{FILA_ENCABEZADOS}:{_col(est['c_comentario'] + len(extra) - 1)}{FILA_ENCABEZADOS}",
              values=[extra], value_input_option="RAW")
    return {**est, "n_datos": len(datos_mx), "datos": datos_mx, "c_comentario": est["c_comentario"] + len(extra),
            "c_tipo": est["c_tipo"] + len(extra) if est["c_tipo"] else None}


def leer_hoja(ws, est: dict):
    """(filas de datos normalizadas, comentarios por No. Cliente, última fila)"""
    ultima = max((i for i, v in enumerate(ws.col_values(IDX_CLIENTE + 1), start=1) if i >= FILA_INICIO and str(v).strip()),
                 default=FILA_INICIO - 1)
    if ultima < FILA_INICIO:
        return [], {}, FILA_INICIO - 1
    fin = max(est["c_comentario"], est["n_datos"])
    filas = []
    for r in range(FILA_INICIO, ultima + 1, 2000):
        filas += ws.get(f"A{r}:{_col(fin)}{min(r + 1999, ultima)}", value_render_option="UNFORMATTED_VALUE")
    datos, coment = [], {}
    for f in filas:
        f = list(f) + [""] * (fin - len(f))
        fila = [_valor_hoja(v, j) for j, v in enumerate(f[:est["n_datos"]])]
        datos.append(fila)
        c = f[est["c_comentario"] - 1] if est["c_comentario"] - 1 < len(f) else ""
        if str(c).strip():
            coment[_norm_id(fila[IDX_CLIENTE])] = c
    return datos, coment, ultima


def resumir_cambios(actual: list[list], nuevo: list[list]) -> dict:
    a = {_norm_id(r[IDX_CLIENTE]): r for r in actual}
    n = {_norm_id(r[IDX_CLIENTE]): r for r in nuevo}
    altas, bajas = sorted(set(n) - set(a)), sorted(set(a) - set(n))
    filas_cambiadas, celdas = 0, {}
    for k in set(a) & set(n):
        dif = [j for j in range(min(len(a[k]), len(n[k]))) if a[k][j] != n[k][j]]
        if dif:
            filas_cambiadas += 1
            for j in dif:
                celdas[j] = celdas.get(j, 0) + 1
    mismo_orden = [_norm_id(r[IDX_CLIENTE]) for r in actual if _norm_id(r[IDX_CLIENTE]) in n] == \
                  [_norm_id(r[IDX_CLIENTE]) for r in nuevo if _norm_id(r[IDX_CLIENTE]) in a]
    exacto = actual == nuevo
    return {"altas": altas, "bajas": bajas, "filas_cambiadas": filas_cambiadas, "celdas_por_columna": celdas,
            "mismo_orden": mismo_orden, "sin_cambios": exacto}


def escribir(ws, est: dict, nuevo: list[list], comentarios: dict, ultima_vieja: int):
    n = len(nuevo)
    ultima_nueva = FILA_INICIO + n - 1
    if ultima_nueva > ws.row_count:
        ws.add_rows(ultima_nueva - ws.row_count + 50)
    c_fin = _col(est["n_datos"])
    for i in range(0, n, CHUNK):
        bloque = [[_celda(v) for v in fila] for fila in nuevo[i:i + CHUNK]]
        ws.update(range_name=f"A{FILA_INICIO + i}:{c_fin}{FILA_INICIO + i + len(bloque) - 1}", values=bloque,
                  value_input_option="USER_ENTERED")
    if ultima_vieja > ultima_nueva:
        ws.batch_clear([f"A{ultima_nueva + 1}:{c_fin}{ultima_vieja}"])
    # Comentarios manuales: se vuelven a colocar por No. Cliente (y se limpian los sobrantes)
    c_com = _col(est["c_comentario"])
    limite = max(ultima_nueva, ultima_vieja)
    col = [[comentarios.get(_norm_id(f[IDX_CLIENTE]), "")] for f in nuevo] + [[""]] * (limite - ultima_nueva)
    if col:
        ws.update(range_name=f"{c_com}{FILA_INICIO}:{c_com}{limite}", values=col, value_input_option="RAW")
    perdidos = len(set(comentarios) - {_norm_id(f[IDX_CLIENTE]) for f in nuevo})
    if perdidos:
        log.warning("Comentarios manuales de clientes que ya no están en el reporte: %d (se retiran con ellos).", perdidos)
    asegurar_formato(ws, est, ultima_vieja, ultima_nueva)
    log.info("Pestaña actualizada: %d clientes en A%d:%s%d", n, FILA_INICIO, c_fin, ultima_nueva)


def asegurar_formato(ws, est, ultima_vieja, ultima_nueva):
    """Si hay filas nuevas más allá de las anteriores: copia el formato de A:datos desde la fila 2."""
    if ultima_nueva <= ultima_vieja:
        return
    sid = ws.id
    ws.spreadsheet.batch_update({"requests": [{"copyPaste": {
        "source": {"sheetId": sid, "startRowIndex": FILA_INICIO - 1, "endRowIndex": FILA_INICIO,
                   "startColumnIndex": 0, "endColumnIndex": est["n_datos"]},
        "destination": {"sheetId": sid, "startRowIndex": ultima_vieja, "endRowIndex": ultima_nueva,
                        "startColumnIndex": 0, "endColumnIndex": est["n_datos"]},
        "pasteType": "PASTE_FORMAT"}}]})


def completar_tipo(ws, est, ultima):
    """La columna TIPO es una fórmula: debe existir en TODAS las filas con datos (en el archivo de
    Nuvia terminaba antes de la última fila y tenía un hueco). Copia la de la fila 2 donde falte."""
    if not est["c_tipo"] or ultima < FILA_INICIO:
        return
    letra = _col(est["c_tipo"])
    actuales = ws.get(f"{letra}{FILA_INICIO}:{letra}{ultima}", value_render_option="FORMULA")
    faltan = [FILA_INICIO + i for i in range(ultima - FILA_INICIO + 1)
              if i >= len(actuales) or not actuales[i] or not str(actuales[i][0]).startswith("=")]
    if not faltan:
        return
    grupos, ini, prev = [], faltan[0], faltan[0]
    for r in faltan[1:]:
        if r != prev + 1:
            grupos.append((ini, prev)); ini = r
        prev = r
    grupos.append((ini, prev))
    c = est["c_tipo"]
    pedidos = [{"copyPaste": {
        "source": {"sheetId": ws.id, "startRowIndex": FILA_INICIO - 1, "endRowIndex": FILA_INICIO, "startColumnIndex": c - 1, "endColumnIndex": c},
        "destination": {"sheetId": ws.id, "startRowIndex": a - 1, "endRowIndex": b, "startColumnIndex": c - 1, "endColumnIndex": c},
        "pasteType": "PASTE_FORMULA"}} for a, b in grupos]
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: faltan %d fórmulas en la columna TIPO (no se escribió nada).", len(faltan))
        return
    ws.spreadsheet.batch_update({"requests": pedidos})
    log.info("Columna TIPO: se completó la fórmula en %d filas que no la tenían.", len(faltan))


def validar_sin_repetidos(ws):
    vistos, dups = set(), set()
    for v in ws.col_values(IDX_CLIENTE + 1)[FILA_INICIO - 1:]:
        k = _norm_id(v)
        if k:
            (dups if k in vistos else vistos).add(k)
    if dups:
        raise RuntimeError(f"No. Cliente repetido en el Sheet ({len(dups)}): {sorted(dups)[:10]}")
    log.info("Validación OK: sin No. Cliente repetidos en el Sheet")


def sincronizar(ws, datos_mx: list[str], filas_mx: list[list], periodo: str, etiqueta: str) -> bool:
    est = adaptar_columnas(ws, estructura_hoja(ws), datos_mx)
    actual, comentarios, ultima = leer_hoja(ws, est)
    r = resumir_cambios(actual, filas_mx)
    if r["sin_cambios"]:
        log.info("Sin cambios: la pestaña ya refleja la semana %s (%s) de Maxinet (%d clientes).", periodo, etiqueta, len(actual))
        completar_tipo(ws, est, ultima)
        guardar_estado(ws, periodo, etiqueta)
        return False
    nombres = est["datos"]
    por_col = {nombres[j]: c for j, c in sorted(r["celdas_por_columna"].items(), key=lambda kv: -kv[1])}
    log.info("Cambios detectados: %d altas, %d bajas, %d clientes con datos distintos, mismo orden: %s",
             len(r["altas"]), len(r["bajas"]), r["filas_cambiadas"], r["mismo_orden"])
    log.info("Celdas distintas por columna (top): %s", dict(list(por_col.items())[:8]))
    if actual and len(filas_mx) < len(actual) / 2 and not os.environ.get("FORZAR"):
        raise RuntimeError(f"El reporte trae {len(filas_mx)} clientes y la pestaña tiene {len(actual)}: menos de la mitad. "
                           f"Probable respuesta incompleta; no se escribió nada (FORZAR=1 para omitir esta revisión).")
    if os.environ.get("DRY_RUN"):
        log.info("DRY_RUN: se reemplazarían %d filas por %d (no se escribió nada).", len(actual), len(filas_mx))
        return False
    escribir(ws, est, filas_mx, comentarios, ultima)
    completar_tipo(ws, est, FILA_INICIO + len(filas_mx) - 1)
    guardar_estado(ws, periodo, etiqueta)
    return True


def elegir_semana():
    """(datos, filas, periodo, etiqueta): la semana más reciente del selector, o la fija PERIODO=<id> (pruebas)."""
    datos, semanas = info_maxinet()
    etiquetas = dict(semanas)
    periodo = os.environ.get("PERIODO")
    if periodo:
        etiqueta = etiquetas.get(periodo, "?")
        log.info("Semana fija: Periodo=%s (%s)", periodo, etiqueta)
    else:
        periodo, etiqueta = semana_mas_reciente(semanas)
        log.info("Semana más reciente: Periodo=%s (%s)", periodo, etiqueta)
    return datos, descargar_semana(periodo, len(datos)), periodo, etiqueta


def main():
    try:
        ws = conectar_sheet()
        datos, filas, periodo, etiqueta = elegir_semana()
        cambio = sincronizar(ws, datos, filas, periodo, etiqueta)
        if cambio:
            validar_sin_repetidos(ws)
        log.info("Revisión completada con éxito (semana %s, %s)", periodo, etiqueta)
    except Exception:
        log.exception("Error en la revisión de Clientes Frecuentes Activos 35")
        sys.exit(1)


if __name__ == "__main__":
    main()
