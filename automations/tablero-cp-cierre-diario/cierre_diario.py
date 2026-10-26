"""
Cierre diario de las columnas por día del Tablero CP copia.

Las pestañas "UNIDADES CP", "UTILIZACION TODOS LOS GRUPO" y "UTILIZACION POR GRUPO" llevan una
columna por día. Sólo una columna, la "viva", tiene fórmulas COUNTIFS sobre "FLOTA CP", que filtran
por la fecha de los datos de esa hoja ('FLOTA CP'!$E:$E igual a la fecha del encabezado, fila 2).
Cuando "FLOTA CP" avanza al día siguiente, la columna viva del día anterior deja de coincidir y se
vuelve cero. En el archivo original Nuvia cierra eso a mano: congela la columna del día anterior
(constantes en las filas COUNTIFS y en los subtotales que ella decide; las sumas de totales y los
porcentajes IFERROR se quedan como fórmula) y pasa las fórmulas a la columna del día nuevo.

Este script hace ese cierre. No depende de la hora a la que corre:

1. Lee la fecha de los datos de "FLOTA CP" (la fecha que traen la mayoría de sus filas).
2. En cada pestaña toma la columna de esa fecha (fila 2) y revisa los días previos:
   - Si la columna del día ya tiene las fórmulas vivas, no cambia nada.
   - Si no, copia las fórmulas (y el formato) de la columna viva anterior a la del día y congela la
     anterior con los valores de su "foto de cierre". Las filas que se congelan son las que están
     como constante en la columna cerrada inmediata anterior, el mismo criterio de Nuvia.
3. Guarda una foto de los valores de la columna viva del día en la pestaña oculta "_CIERRE_DIARIO".
   Cada corrida la actualiza, de modo que la última foto del día es la final. Es lo que se usa al
   congelar: nunca se congelan los valores que da la fórmula después del cambio de fecha, que son
   ceros.

Seguridad: no escribe nada si "FLOTA CP" no tiene al menos MIN_FILAS_FLOTA filas con la fecha del
día (los datos aún no cargan), no guarda una foto con valores no numéricos o en cero y no congela
una columna que no tenga foto (avisa y termina con código 1). Idempotente: se puede correr varias
veces al día. No escribe datos personales en el log; sólo fechas, nombres de pestañas y conteos.

Variables de entorno: GOOGLE_CREDS_PATH, SPREADSHEET_ID_TABLERO_CP; opcionales DRY_RUN (calcula y
muestra el plan sin escribir), FECHA_DATOS=AAAA-MM-DD (simula otra fecha de datos; sólo con
DRY_RUN, o con FORZAR=1 para un caso excepcional).
"""
import os
import sys
import json
import time
import logging
import datetime as dt
from collections import Counter

import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tablero_cp_cierre_diario")

HOJA_FLOTA = "FLOTA CP"
HOJA_FOTOS = "_CIERRE_DIARIO"
PESTANAS = ("UNIDADES CP", "UTILIZACION TODOS LOS GRUPO", "UTILIZACION POR GRUPO")
FILA_FECHAS = 2
PRIMERA_FILA = 3
FILAS_MAX = 400            # las tablas diarias terminan mucho antes; se lee hasta aquí
VENTANA_DIAS = 8           # días hacia atrás que se revisan
MIN_FILAS_FLOTA = 1000     # filas de FLOTA CP con la fecha del día para dar los datos por cargados
DIAS_FOTOS = 14
BASE_SERIE = dt.date(1899, 12, 30)


def reintentar(fn, *args, **kwargs):
    """Llama a Sheets y reintenta con espera creciente ante 429 (cuota por minuto compartida) o fallos 5xx."""
    for n in range(7):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            codigo = getattr(e.response, "status_code", 0)
            if codigo in (429, 500, 502, 503) and n < 6:
                espera = 15 * (n + 1)
                log.warning("Sheets respondió %s; se reintenta en %d s", codigo, espera)
                time.sleep(espera)
                continue
            raise


# ---------------------------------------------------------------- utilidades puras
def letras(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def a_serie(d: dt.date) -> int:
    return (d - BASE_SERIE).days


def de_serie(n) -> dt.date:
    return BASE_SERIE + dt.timedelta(days=int(n))


def parsear_fecha(v):
    """Fecha de una celda de FLOTA CP: texto ISO (2026-10-22) o número de serie de Sheets."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return de_serie(v) if v > 40000 else None
    try:
        return dt.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def es_formula(x) -> bool:
    return isinstance(x, str) and x.startswith("=")


def es_constante(x) -> bool:
    return x not in ("", None) and not es_formula(x)


def fecha_de_datos(valores_e: list) -> tuple:
    """(fecha, filas con esa fecha) de la columna E de FLOTA CP."""
    cuenta = Counter(parsear_fecha(f[0]) for f in valores_e if f)
    cuenta.pop(None, None)
    if not cuenta:
        return None, 0
    return cuenta.most_common(1)[0]


def clasificar(celdas: list) -> str:
    """viva: tiene fórmulas COUNTIFS; congelada: tiene constantes; vacia: ninguna (filas desde la 3)."""
    datos = celdas[PRIMERA_FILA - 1:]
    if any(isinstance(x, str) and x.startswith("=COUNTIFS(") for x in datos):
        return "viva"
    if any(es_constante(x) for x in datos):
        return "congelada"
    return "vacia"


# ---------------------------------------------------------------- plan
def planear(columnas: dict, fechas: dict, fecha_datos: dt.date, fotos: dict) -> dict:
    """
    columnas: {indice de columna (1 = A): [contenido de cada fila, fila 1 primero]} con fórmulas.
    fechas:   {indice de columna: fecha del encabezado} (sólo columnas con fecha <= fecha_datos).
    fotos:    {fecha: {fila: valor}} de los cierres guardados.
    """
    plan = {"errores": [], "avisos": [], "col_dia": None, "base": None, "fuente": None, "congelar": [],
            "crear_viva": False, "filas_patron": []}
    col_dia = next((i for i, f in fechas.items() if f == fecha_datos), None)
    if col_dia is None:
        plan["errores"].append(f"la fecha {fecha_datos} no está en la fila {FILA_FECHAS} de la pestaña")
        return plan
    plan["col_dia"] = col_dia
    clases = {i: clasificar(columnas[i]) for i in columnas if fechas[i] <= fecha_datos}
    if clases[col_dia] == "congelada":
        plan["errores"].append("la columna del día de los datos está congelada; no se toca")
        return plan
    vivas = sorted(i for i, c in clases.items() if c == "viva")
    primera = min(vivas + [col_dia])
    cerradas = [i for i, c in clases.items() if c == "congelada" and i < primera]
    if not cerradas:
        plan["errores"].append("no hay una columna cerrada anterior que sirva de modelo")
        return plan
    base = max(cerradas)
    fuente = col_dia if clases[col_dia] == "viva" else (max(vivas) if vivas else None)
    if fuente is None:
        plan["errores"].append("no hay una columna viva de la cual copiar las fórmulas")
        return plan
    plan["base"], plan["fuente"] = base, fuente
    plan["crear_viva"] = clases[col_dia] != "viva"
    n = len(columnas[base])

    def patron(origen):
        return [r for r in range(PRIMERA_FILA, n + 1)
                if es_constante(columnas[base][r - 1]) and es_formula(columnas[origen][r - 1])]

    plan["filas_patron"] = patron(fuente)
    if not plan["filas_patron"]:
        plan["errores"].append("no hay filas por congelar según la columna cerrada anterior")
        return plan
    for c in (v for v in vivas if fechas[v] < fecha_datos):
        filas = patron(c)
        foto = fotos.get(fechas[c])
        if not foto:
            plan["errores"].append(f"no hay foto de cierre del {fechas[c]}; esa columna no se congela")
            continue
        faltan = [r for r in filas if str(r) not in {str(k) for k in foto}]
        if faltan:
            plan["errores"].append(f"la foto del {fechas[c]} no trae {len(faltan)} filas por congelar")
            continue
        plan["congelar"].append((c, {r: foto.get(r, foto.get(str(r))) for r in filas}))
    return plan


# ---------------------------------------------------------------- solicitudes de Sheets
def _rango(sid, c1, c2, r1, r2):
    """Rango en índices de la API: columnas y filas desde 1, ambos extremos incluidos."""
    return {"sheetId": sid, "startColumnIndex": c1 - 1, "endColumnIndex": c2,
            "startRowIndex": r1 - 1, "endRowIndex": r2}


def solicitudes(sid: int, plan: dict, filas_formato: int, ultima_formula: int) -> list:
    """Orden: primero se copian las fórmulas del día (aún vivas), luego se congela y se da formato."""
    reqs = []
    if plan["crear_viva"]:
        f, d = plan["fuente"], plan["col_dia"]
        reqs.append({"copyPaste": {"source": _rango(sid, f, f, PRIMERA_FILA, ultima_formula),
                                   "destination": _rango(sid, d, d, PRIMERA_FILA, ultima_formula),
                                   "pasteType": "PASTE_FORMULA", "pasteOrientation": "NORMAL"}})
        reqs.append({"copyPaste": {"source": _rango(sid, f, f, 1, filas_formato),
                                   "destination": _rango(sid, d, d, 1, filas_formato),
                                   "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
    for c, valores in plan["congelar"]:
        filas = sorted(valores)
        i = 0
        while i < len(filas):                    # una solicitud por tramo de filas seguidas
            j = i
            while j + 1 < len(filas) and filas[j + 1] == filas[j] + 1:
                j += 1
            reqs.append({"updateCells": {
                "rows": [{"values": [{"userEnteredValue": {"numberValue": valores[r]}}]} for r in filas[i:j + 1]],
                "fields": "userEnteredValue",
                "start": {"sheetId": sid, "rowIndex": filas[i] - 1, "columnIndex": c - 1}}})
            i = j + 1
        b = plan["base"]
        reqs.append({"copyPaste": {"source": _rango(sid, b, b, 1, filas_formato),
                                   "destination": _rango(sid, c, c, 1, filas_formato),
                                   "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
    return reqs


# ---------------------------------------------------------------- fotos de cierre (pestaña oculta)
class Fotos:
    """Fotos de los valores de la columna viva, una fila por (fecha, pestaña): [fecha, pestaña, JSON fila->valor]."""

    def __init__(self, libro, escribir: bool):
        self.libro, self.escribir, self._ws = libro, escribir, None

    def _hoja(self, crear=False):
        if self._ws is None:
            try:
                self._ws = reintentar(self.libro.worksheet, HOJA_FOTOS)
            except gspread.WorksheetNotFound:
                if not (crear and self.escribir):
                    return None
                self._ws = reintentar(self.libro.add_worksheet, title=HOJA_FOTOS, rows=200, cols=3)
                reintentar(self._ws.update, range_name="A1:C1", values=[["fecha", "pestaña", "valores_por_fila"]],
                           value_input_option="RAW")
                reintentar(self.libro.batch_update, {"requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": self._ws.id, "hidden": True}, "fields": "hidden"}}]})
                log.info("Se creó la pestaña oculta %s", HOJA_FOTOS)
        return self._ws

    def leer_todas(self, pestana: str) -> dict:
        ws = self._hoja()
        if ws is None:
            return {}
        out = {}
        for fila in reintentar(ws.get_all_values)[1:]:
            if len(fila) >= 3 and fila[1] == pestana and fila[2]:
                try:
                    out[dt.date.fromisoformat(fila[0])] = {int(k): v for k, v in json.loads(fila[2]).items()}
                except (ValueError, TypeError):
                    log.warning("Foto ilegible en %s; se ignora", HOJA_FOTOS)
        return out

    def guardar(self, fecha: dt.date, pestana: str, valores: dict, hoy: dt.date):
        ws = self._hoja(crear=True)
        if ws is None:
            return
        filas = reintentar(ws.get_all_values)
        destino = next((i + 1 for i, f in enumerate(filas) if i > 0 and len(f) >= 2 and f[0] == fecha.isoformat()
                        and f[1] == pestana), len(filas) + 1)
        reintentar(ws.update, range_name=f"A{destino}:C{destino}",
                   values=[[fecha.isoformat(), pestana, json.dumps({str(k): v for k, v in sorted(valores.items())})]],
                   value_input_option="RAW")
        viejas = [i + 1 for i, f in enumerate(filas) if i > 0 and f and f[0] and
                  dt.date.fromisoformat(f[0]) < hoy - dt.timedelta(days=DIAS_FOTOS)]
        if viejas:
            reintentar(ws.batch_clear, [f"A{i}:C{i}" for i in viejas])


# ---------------------------------------------------------------- lectura y ejecución por pestaña
def _leer_estado(ws, fecha_datos):
    fila2 = reintentar(ws.get, f"A{FILA_FECHAS}:ZZ{FILA_FECHAS}", value_render_option="UNFORMATTED_VALUE")
    fila2 = fila2[0] if fila2 else []
    series = {i + 1: v for i, v in enumerate(fila2) if isinstance(v, (int, float)) and not isinstance(v, bool)}
    serie_dia = a_serie(fecha_datos)
    ventana = sorted(i for i, v in series.items() if serie_dia - VENTANA_DIAS <= v <= serie_dia)
    if not ventana:
        return {}, {}, 0
    c1, c2 = ventana[0], ventana[-1]
    filas = min(ws.row_count, FILAS_MAX)
    mat = reintentar(ws.get, f"{letras(c1)}1:{letras(c2)}{filas}", value_render_option="FORMULA")
    mat = list(mat) + [[] for _ in range(filas - len(mat))]
    columnas = {i: [(f[i - c1] if i - c1 < len(f) else "") for f in mat] for i in ventana}
    fechas = {i: de_serie(series[i]) for i in ventana}
    ultima = max((r + 1 for r in range(filas) for i in ventana if es_formula(columnas[i][r])), default=0)
    return columnas, fechas, ultima


def cerrar_pestana(libro, nombre: str, fecha_datos: dt.date, fotos: Fotos, hoy: dt.date, dry_run: bool) -> bool:
    """True si la pestaña quedó en orden; False si hay algo que revisar."""
    ws = reintentar(libro.worksheet, nombre)
    columnas, fechas, ultima = _leer_estado(ws, fecha_datos)
    if not columnas:
        log.error("%s: no hay columnas con fecha cercana a %s en la fila %d", nombre, fecha_datos, FILA_FECHAS)
        return False
    plan = planear(columnas, fechas, fecha_datos, fotos.leer_todas(nombre))
    for e in plan["errores"]:
        log.error("%s: %s", nombre, e)
    if plan["col_dia"] is None or plan["fuente"] is None or not plan["filas_patron"]:
        return False
    filas_formato = max(ultima, max(plan["filas_patron"]))
    letra = letras(plan["col_dia"])
    log.info("%s: datos del %s -> columna %s (%s) | crear columna viva: %s | columnas a congelar: %s | filas de la foto: %d",
             nombre, fecha_datos, letra, "ya viva" if not plan["crear_viva"] else "nueva",
             "sí" if plan["crear_viva"] else "no", [fechas[c].isoformat() for c, _ in plan["congelar"]] or "ninguna",
             len(plan["filas_patron"]))
    reqs = solicitudes(ws.id, plan, filas_formato, ultima)
    if reqs and not dry_run:
        reintentar(libro.batch_update, {"requests": reqs})
        log.info("%s: %d solicitudes aplicadas", nombre, len(reqs))
    elif reqs:
        log.info("%s: DRY_RUN: se aplicarían %d solicitudes (no se escribió nada)", nombre, len(reqs))
    # foto del día, después de crear la columna viva (se recalcula sola)
    if dry_run and plan["crear_viva"]:
        return not plan["errores"]
    filas = reintentar(ws.get, f"{letra}{PRIMERA_FILA}:{letra}{filas_formato}", value_render_option="UNFORMATTED_VALUE")
    valores = {r: (filas[r - PRIMERA_FILA][0] if r - PRIMERA_FILA < len(filas) and filas[r - PRIMERA_FILA] else None)
               for r in plan["filas_patron"]}
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in valores.values()) or not any(valores.values()):
        log.warning("%s: la columna %s no trae valores numéricos o están en cero; no se guarda la foto", nombre, letra)
        return not plan["errores"]
    if dry_run:
        log.info("%s: DRY_RUN: se guardaría la foto del %s (%d filas)", nombre, fecha_datos, len(valores))
    else:
        fotos.guardar(fecha_datos, nombre, valores, hoy)
        log.info("%s: foto del %s guardada (%d filas)", nombre, fecha_datos, len(valores))
    return not plan["errores"]


def conectar_libro():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return reintentar(gspread.authorize(creds).open_by_key, os.environ["SPREADSHEET_ID_TABLERO_CP"])


def main() -> int:
    dry_run = bool(os.environ.get("DRY_RUN"))
    libro = conectar_libro()
    simulada = (os.environ.get("FECHA_DATOS") or "").strip()
    if simulada:
        if not (dry_run or os.environ.get("FORZAR")):
            log.error("FECHA_DATOS sólo se admite con DRY_RUN=1 (o FORZAR=1)")
            return 1
        fecha, filas = dt.date.fromisoformat(simulada), None
        log.warning("Fecha de datos simulada: %s", fecha)
    else:
        valores = reintentar(reintentar(libro.worksheet, HOJA_FLOTA).get, "E2:E6000", value_render_option="UNFORMATTED_VALUE")
        fecha, filas = fecha_de_datos(valores)
        if fecha is None or filas < MIN_FILAS_FLOTA:
            log.error("FLOTA CP no trae datos completos de un día (%s filas con la fecha más común, mínimo %d); no se hace nada",
                      filas, MIN_FILAS_FLOTA)
            return 1
        log.info("Fecha de los datos de %s: %s (%d filas)", HOJA_FLOTA, fecha, filas)
    hoy = dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date()
    fotos = Fotos(libro, escribir=not dry_run)
    resultados = []
    for nombre in PESTANAS:
        try:
            resultados.append(cerrar_pestana(libro, nombre, fecha, fotos, hoy, dry_run))
        except Exception:                                    # una pestaña con error no detiene a las demás
            log.exception("%s: error inesperado", nombre)
            resultados.append(False)
    if not all(resultados):
        log.error("Cierre diario con pendientes: %d de %d pestañas con aviso", resultados.count(False), len(resultados))
        return 1
    log.info("Cierre diario completado con éxito")
    return 0


if __name__ == "__main__":
    sys.exit(main())
