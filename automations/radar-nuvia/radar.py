"""
Radar de cambios de Nuvia en nuestros libros.

Nuvia está ajustando el Tablero CP y la Base CP copia (renombra pestañas, quita el menú, cambia
columnas...) y nuestras automatizaciones dependen de esa estructura. El radar vigila la estructura, no
los datos, y avisa cuando ella termina para adaptar las reglas con calma:

1. Toma una huella de cada pestaña: nombre, identificador, oculta, número de columnas, congelados, gráficas,
   protecciones, combinadas, formatos condicionales, filtro, encabezados (filas 1 a 3) y los patrones de las
   fórmulas de las primeras 60 filas (con las referencias de celda generalizadas, para que los datos que
   crecen o la columna viva que avanza cada día no cuenten como cambio). No cuenta las filas de datos.
2. La compara con la línea base, por identificador de pestaña: así distingue un renombre de una pestaña
   nueva y otra eliminada.
3. Estados: "sin cambios"; "en curso" (hay cambios y la huella cambió desde la corrida anterior: Nuvia sigue
   ajustando); "estable" (hay cambios y llevan SILENCIO_MIN minutos sin moverse: hay que revisarlos y adaptar).
   La guardia de actualización convierte "estable" en un pendiente que se avisa por correo.
4. La línea base sólo se actualiza con ACEPTAR_BASE=1, después de adaptar las automatizaciones.

El detalle (qué pestaña, qué cambió, qué encabezados) queda en la pestaña oculta "_RADAR" del Tablero, que es
privada; el registro público sólo trae nombres de pestañas y conteos. No toca datos ni estructura de los libros.

Variables de entorno: GOOGLE_CREDS_PATH, SPREADSHEET_ID_TABLERO_CP, SPREADSHEET_ID_CLIENTES_NUEVOS;
opcionales ACEPTAR_BASE=1 y SILENCIO_MIN (por defecto 60).
"""
import os
import re
import sys
import json
import time
import hashlib
import logging
import datetime as dt

import gspread
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radar_nuvia")

HOJA_RADAR = "_RADAR"
PROPIAS = (HOJA_RADAR, "_CIERRE_DIARIO")
LIBROS = {"Tablero CP": "SPREADSHEET_ID_TABLERO_CP", "Base CP": "SPREADSHEET_ID_CLIENTES_NUEVOS"}
FILAS_CABECERA = 3
FILAS_MUESTRA = 60
COLS_MUESTRA = 78                       # hasta la columna BZ
SILENCIO_MIN = 60
REF_CELDA = re.compile(r"\$?[A-Z]{1,3}\$?\d+")
# Qué automatización o qué parte del Tablero depende de cada pestaña (para el detalle privado)
IMPACTO = {
    "UNIDADES CP": "cierre diario (columnas por día)", "UTILIZACION TODOS LOS GRUPO": "cierre diario (columnas por día)",
    "UTILIZACION POR GRUPO": "cierre diario (columnas por día)", "FLOTA CP": "cierre diario y reconstrucción de días (columnas A:BA)",
    "DETALLE": "fórmulas que leen las columnas por día", "GRAFICAS": "importa DETALLE",
    "ENTREGAS": "maxinet-entregas-cp (A:P datos, Q:X fórmulas)", "Reporte Generales Clientes Nuevo": "maxinet-clientes-nuevos-cp (B:Q)",
    "Reporte Clientes Potenciales CP": "maxinet-clientes-potenciales-cp (columnas por encabezado)",
    "ENCUESTAS": "maxinet-encuestas-cp (C:Z por encabezado, A:B fórmulas)", "Clientes Frecuentes Activos 35": "maxinet-frecuentes-activos-cp",
}


# ---------------------------------------------------------------- huella de una pestaña
def corto(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def patron(formula: str) -> str:
    """La fórmula con las referencias de celda generalizadas: el mismo cálculo en otra celda es el mismo patrón."""
    return REF_CELDA.sub("REF", formula)


def huella_hoja(meta: dict, matriz: list) -> dict:
    """meta: lo que devuelve la API para la pestaña; matriz: sus primeras filas con las fórmulas como texto."""
    p = meta["properties"]
    g = p.get("gridProperties", {})
    cabecera = [[str(x) for x in fila[:COLS_MUESTRA]] for fila in matriz[:FILAS_CABECERA]]
    primera = [x[:24] for x in (cabecera[0] if cabecera else [])]
    patrones = sorted({patron(str(x)) for fila in matriz[:FILAS_MUESTRA] for x in fila if str(x).startswith("=")})
    return {
        "t": p["title"], "h": bool(p.get("hidden")), "c": g.get("columnCount", 0),
        "fz": [g.get("frozenRowCount", 0), g.get("frozenColumnCount", 0)],
        "gr": sorted((c.get("spec", {}).get("title") or "(sin título)") for c in meta.get("charts", [])),
        "pr": len(meta.get("protectedRanges", [])), "mg": len(meta.get("merges", [])),
        "cf": len(meta.get("conditionalFormats", [])), "fl": bool(meta.get("basicFilter")),
        "ca": corto(cabecera), "v1": primera, "fm": corto(patrones), "nfm": len(patrones),
    }


def _rango(titulo: str) -> str:
    return "'" + titulo.replace("'", "''") + f"'!A1:{_letras(COLS_MUESTRA)}{FILAS_MUESTRA}"


def _letras(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def tomar_instantanea(libro) -> dict:
    """{identificador de pestaña: huella} de las pestañas del libro, sin las ocultas propias del radar y del cierre."""
    campos = ("sheets(properties(sheetId,title,hidden,gridProperties),charts(spec(title)),"
              "protectedRanges(protectedRangeId),merges,conditionalFormats,basicFilter)")
    metas = [m for m in con_reintentos(libro.fetch_sheet_metadata, {"fields": campos})["sheets"]
             if m["properties"]["title"] not in PROPIAS]
    rangos = [_rango(m["properties"]["title"]) for m in metas]
    respuesta = con_reintentos(libro.values_batch_get, rangos, params={"valueRenderOption": "FORMULA"})
    out = {}
    for m, vr in zip(metas, respuesta["valueRanges"]):
        out[str(m["properties"]["sheetId"])] = huella_hoja(m, vr.get("values", []))
    return out


# ---------------------------------------------------------------- comparación con la línea base
def comparar(base: dict, actual: dict) -> list:
    """Lista de (identificador, nombre, tipo, detalle), ordenada; vacía si la estructura es la misma."""
    cambios = []
    for i in sorted(set(base) | set(actual), key=lambda k: (actual.get(k) or base.get(k))["t"]):
        b, a = base.get(i), actual.get(i)
        if b is None:
            cambios.append((i, a["t"], "pestaña nueva", f"{a['c']} columnas"))
            continue
        if a is None:
            cambios.append((i, b["t"], "pestaña eliminada", ""))
            continue
        if b["t"] != a["t"]:
            cambios.append((i, a["t"], "renombrada", f"antes '{b['t']}'"))
        if b["h"] != a["h"]:
            cambios.append((i, a["t"], "oculta" if a["h"] else "visible", ""))
        if b["c"] != a["c"]:
            cambios.append((i, a["t"], "columnas", f"{b['c']} -> {a['c']}"))
        if b["fz"] != a["fz"]:
            cambios.append((i, a["t"], "filas o columnas congeladas", f"{b['fz']} -> {a['fz']}"))
        if b["ca"] != a["ca"]:
            difs = [f"{_letras(k + 1)}1: '{x}' -> '{y}'" for k, (x, y) in enumerate(zip(b["v1"] + [""] * 80, a["v1"] + [""] * 80))
                    if x != y and k < max(len(b["v1"]), len(a["v1"]))][:5]
            cambios.append((i, a["t"], "encabezados", "; ".join(difs) or "filas 2 y 3"))
        if b["fm"] != a["fm"]:
            cambios.append((i, a["t"], "fórmulas", f"{b['nfm']} -> {a['nfm']} patrones distintos"))
        if b["gr"] != a["gr"]:
            cambios.append((i, a["t"], "gráficas", f"{len(b['gr'])} -> {len(a['gr'])}"))
        for clave, nombre in (("pr", "protecciones"), ("mg", "celdas combinadas"), ("cf", "formatos condicionales")):
            if b[clave] != a[clave]:
                cambios.append((i, a["t"], nombre, f"{b[clave]} -> {a[clave]}"))
        if b["fl"] != a["fl"]:
            cambios.append((i, a["t"], "filtro", "activado" if a["fl"] else "quitado"))
    return cambios


def evaluar(estado: dict, base: dict, actual: dict, ahora: dt.datetime, silencio_min: int = SILENCIO_MIN):
    """(nuevo estado, cambios). estado: {"estado", "hash", "desde"} de la corrida anterior o {}."""
    cambios = comparar(base, actual)
    if not cambios:
        return {"estado": "sin cambios", "hash": "", "desde": ""}, cambios
    h = corto(actual)
    if estado.get("hash") != h:                                      # la estructura volvió a cambiar: Nuvia sigue ajustando
        return {"estado": "en curso", "hash": h, "desde": ahora.isoformat()}, cambios
    desde = dt.datetime.fromisoformat(estado["desde"])
    calma = (ahora - desde).total_seconds() / 60 >= silencio_min
    return {"estado": "estable" if calma else "en curso", "hash": h, "desde": estado["desde"]}, cambios


# ---------------------------------------------------------------- almacenamiento en la pestaña oculta
def con_reintentos(fn, *args, **kwargs):
    """Llama a Sheets y reintenta con espera creciente ante 429 (la cuota por minuto se comparte) o 5xx."""
    for n in range(6):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if getattr(e.response, "status_code", 0) in (429, 500, 502, 503) and n < 5:
                time.sleep(20 * (n + 1))
                continue
            raise


class Almacen:
    """
    Pestaña oculta "_RADAR" del Tablero. Filas de cuatro columnas:
    BASE | libro | identificador | huella (JSON) · ESTADO | libro | JSON del estado · INFORME | libro | línea de texto.
    La línea base sólo cambia con aceptar(); cada corrida reescribe el estado y el informe sin borrar antes.
    """

    def __init__(self, libro_tablero):
        self.libro, self._ws, self.filas = libro_tablero, None, None

    def _hoja(self):
        if self._ws is None:
            try:
                self._ws = con_reintentos(self.libro.worksheet, HOJA_RADAR)
            except gspread.WorksheetNotFound:
                self._ws = con_reintentos(self.libro.add_worksheet, title=HOJA_RADAR, rows=400, cols=4)
                con_reintentos(self.libro.batch_update, {"requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": self._ws.id, "hidden": True}, "fields": "hidden"}}]})
                log.info("Se creó la pestaña oculta %s", HOJA_RADAR)
        return self._ws

    def cargar(self):
        self.filas = [list(f) + [""] * (4 - len(f)) for f in con_reintentos(self._hoja().get_all_values)]

    def base(self, libro: str) -> dict:
        return {f[2]: json.loads(f[3]) for f in self.filas if f[0] == "BASE" and f[1] == libro and f[3]}

    def estado(self, libro: str) -> dict:
        for f in self.filas:
            if f[0] == "ESTADO" and f[1] == libro and f[2]:
                return json.loads(f[2])
        return {}

    def guardar(self, bases: dict, estados: dict, informes: dict):
        """bases: {libro: {id: huella}} (None conserva la actual); estados y informes por libro."""
        nuevas = []
        for libro in LIBROS:
            b = bases.get(libro)
            if b is None:
                b = self.base(libro)
            nuevas += [["BASE", libro, i, json.dumps(h, ensure_ascii=False)] for i, h in sorted(b.items())]
        nuevas += [["ESTADO", libro, json.dumps(e, ensure_ascii=False), ""] for libro, e in estados.items()]
        nuevas += [["INFORME", libro, linea, ""] for libro, lineas in informes.items() for linea in lineas]
        ws = self._hoja()
        if len(nuevas) > ws.row_count:
            con_reintentos(ws.add_rows, len(nuevas) - ws.row_count + 100)
        con_reintentos(ws.update, range_name=f"A1:D{len(nuevas)}", values=nuevas, value_input_option="RAW")
        sobran = len(self.filas or []) - len(nuevas)
        if sobran > 0:
            con_reintentos(ws.batch_clear, [f"A{len(nuevas) + 1}:D{len(self.filas)}"])
        self.filas = nuevas


# ---------------------------------------------------------------- ejecución
def conectar(clave_env: str):
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return con_reintentos(gspread.authorize(creds).open_by_key, os.environ[clave_env])


def informe(libro: str, estado: dict, cambios: list, base: dict) -> list:
    lineas = [f"{libro}: {estado['estado']}" + (f" (desde {estado['desde'][:16]})" if estado.get("desde") else "")]
    for i, nombre, tipo, detalle in cambios:
        impacto = IMPACTO.get(base.get(i, {}).get("t", "")) or IMPACTO.get(nombre)
        lineas.append(f"- {nombre} [{i}]: {tipo}" + (f" ({detalle})" if detalle else "") + (f" · afecta: {impacto}" if impacto else ""))
    return lineas


def main() -> int:
    ahora = dt.datetime.now(dt.timezone.utc)
    aceptar = bool(os.environ.get("ACEPTAR_BASE"))
    silencio = int(os.environ.get("SILENCIO_MIN") or SILENCIO_MIN)
    libros = {nombre: conectar(clave) for nombre, clave in LIBROS.items()}
    almacen = Almacen(libros["Tablero CP"])
    almacen.cargar()
    bases, estados, informes, resumen = {}, {}, {}, []
    for nombre, libro in libros.items():
        actual = tomar_instantanea(libro)
        base = almacen.base(nombre)
        if aceptar or not base:
            bases[nombre] = actual
            estados[nombre] = {"estado": "sin cambios", "hash": "", "desde": "", "revisado": ahora.isoformat()}
            informes[nombre] = [f"{nombre}: línea base {'actualizada' if base else 'creada'} con {len(actual)} pestañas"]
            log.info("%s: línea base %s (%d pestañas)", nombre, "actualizada" if base else "creada", len(actual))
            continue
        estado, cambios = evaluar(almacen.estado(nombre), base, actual, ahora, silencio)
        estado["revisado"] = ahora.isoformat()
        estados[nombre], informes[nombre] = estado, informe(nombre, estado, cambios, base)
        resumen.append((nombre, estado["estado"], cambios))
    almacen.guardar(bases, estados, informes)
    for nombre, est, cambios in resumen:
        log.info("%s: %s, %d cambio(s) respecto de la línea base", nombre, est, len(cambios))
        for i, tab, tipo, _ in cambios:
            log.info("   %s: %s", tab, tipo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
