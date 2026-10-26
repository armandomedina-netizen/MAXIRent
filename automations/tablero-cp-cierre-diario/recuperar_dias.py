"""
Reconstrucción de un día pasado para las columnas por día del Tablero CP.

Si el cierre diario no corre uno o más días (una caída, un fin de semana sin el PR en producción),
las columnas de esos días quedan vacías y "FLOTA CP" sólo conserva la foto del día más reciente.
Maxinet, en cambio, devuelve el reporte de flota de cualquier fecha (mismo endpoint que usa el sync,
con Desde = Hasta = la fecha), así que el día se reconstruye con el mismo proceso de cada día:

1. Se descarga el reporte de flota de la fecha (41 columnas crudas, E:AS de "FLOTA CP").
2. Se arman las columnas de "FLOTA CP" de ese día: las crudas vienen del reporte; las derivadas por
   fila (TODO LO DISPONIBLE, PRESTAMOS, BSITE CP, DISPONIBLES DE PRESTAMOS) se calculan con las mismas
   reglas de las fórmulas de la hoja; las que no cambian entre días (GRUPO, STATUS DISPONIBLE,
   UNIDADES, 3 grupos) se toman de la hoja de hoy por placa, y la tabla lateral AX:BA (autos con
   antigüedad) se toma tal cual de hoy.
3. Se evalúan las fórmulas de conteo (COUNTIFS y SUM) de la columna viva más reciente con esos datos.

Es una aproximación con una comprobación incorporada: antes de usarla, el cierre reconstruye con este
mismo código la columna ya congelada (su foto de cierre) y exige que coincida exactamente; si algo
difiere, no rellena nada y avisa. No usa ningún archivo de Nuvia.
"""
import os
import re
import json
import logging
import datetime as dt

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("tablero_cp_cierre_diario")

ANCHO_REPORTE = 41            # Fecha ... EntryDate; el reporte trae antes una columna de acciones
PRIMERA_CRUDA = 5             # columna E de FLOTA CP
ESTATICAS = ("D", "AT", "AU", "AW")           # por placa, no cambian entre días
LATERAL = ("AX", "AY", "AZ", "BA")            # tabla lateral de antigüedad: se toma tal cual de hoy
BSITE_CP = {"LT", "PE", "TO", "FU", "AR", "LF"}
SEDES_PRESTAMO = {"LF", "LT", "FU", "SO", "TO"}
TIMEOUT = 300
REINTENTOS = 5


class FormulaNoSoportada(Exception):
    pass


# ---------------------------------------------------------------- utilidades
def letras(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def indice(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def texto(v) -> str:
    """Texto comparable como lo hace COUNTIFS: sin distinguir mayúsculas y con enteros sin '.0'."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().lower()


def partir_argumentos(s: str) -> list:
    """Parte por comas de primer nivel (fuera de comillas y de paréntesis)."""
    out, nivel, comillas, ini = [], 0, False, 0
    for i, ch in enumerate(s):
        if ch == '"':
            comillas = not comillas
        elif not comillas and ch == "(":
            nivel += 1
        elif not comillas and ch == ")":
            nivel -= 1
        elif not comillas and nivel == 0 and ch == ",":
            out.append(s[ini:i].strip())
            ini = i + 1
    out.append(s[ini:].strip())
    return out


# ---------------------------------------------------------------- Maxinet
def _sesion() -> requests.Session:
    s = requests.Session()
    reintento = Retry(total=REINTENTOS, connect=REINTENTOS, read=REINTENTOS, status=REINTENTOS, backoff_factor=2,
                      status_forcelist=(502, 503, 504), allowed_methods=None)
    s.mount("http://", HTTPAdapter(max_retries=reintento))
    s.mount("https://", HTTPAdapter(max_retries=reintento))
    return s


def descargar_flota(fecha: dt.date) -> list:
    """Filas crudas (41 valores) del reporte de flota de Maxinet para la fecha."""
    base = os.environ["MAXINET_BASE_URL"].rstrip("/")
    s = _sesion()
    r = s.post(f"{base}/includes/users/AccessValidate.php",
               data={"email": os.environ["MAXINET_USER"], "password": os.environ["MAXINET_PASS"]}, timeout=TIMEOUT)
    if json.loads(r.content.decode("utf-8-sig")).get("respuesta") == "error":
        raise RuntimeError("Login falló en Maxinet")
    r = s.post(f"{base}/includes/gpsrt/reporte-flota-maxirent.php",
               data={"Desde": fecha.isoformat(), "Hasta": fecha.isoformat()}, timeout=TIMEOUT)
    filas = [f[1:] for f in json.loads(r.content.decode("utf-8-sig"))["data"]]
    anchos = {len(f) for f in filas}
    if anchos != {ANCHO_REPORTE}:
        raise RuntimeError(f"El reporte de flota trae {sorted(anchos)} columnas y se esperaban {ANCHO_REPORTE}")
    fechas = {str(f[0])[:10] for f in filas}
    if fechas != {fecha.isoformat()}:
        raise RuntimeError(f"El reporte pedido para {fecha} trae las fechas {sorted(fechas)[:3]}")
    log.info("Reporte de flota del %s descargado de Maxinet: %d filas", fecha, len(filas))
    return filas


# ---------------------------------------------------------------- columnas de FLOTA CP de un día
def armar_columnas(filas: list, hoy: dict) -> dict:
    """
    filas: filas crudas del reporte (41 valores). hoy: {letra: [valores]} de FLOTA CP de hoy, filas desde la 2.
    Devuelve {letra: [valores]} con las columnas de FLOTA CP de ese día (una lista por columna).
    """
    cols = {letras(PRIMERA_CRUDA + i): [("" if f[i] is None else f[i]) for f in filas] for i in range(ANCHO_REPORTE)}
    h, i_, j = cols["H"], cols["I"], cols["J"]
    cols["B"] = ["PRESTAMO" if texto(x).upper() in SEDES_PRESTAMO else "NA" for x in i_]
    cols["A"] = ["OK" if b == "PRESTAMO" or texto(x).upper() == "TO" else "NG" for b, x in zip(cols["B"], h)]
    cols["C"] = ["TO" if texto(x).upper() in BSITE_CP else "NA" for x in h]
    cols["AV"] = ["OK" if texto(x) in ("disponible", "otros") else "NA" for x in j]
    pos = {texto(p): n for n, p in enumerate(hoy.get("G", []))}
    for letra in ESTATICAS:
        origen = hoy.get(letra, [])
        cols[letra] = [(origen[pos[texto(p)]] if texto(p) in pos and pos[texto(p)] < len(origen) else "")
                       for p in cols["G"]]
    for letra in LATERAL:
        cols[letra] = list(hoy.get(letra, []))
    return cols


# ---------------------------------------------------------------- evaluación de las fórmulas de conteo
class Evaluador:
    """Evalúa COUNTIFS y SUM de la columna viva de una pestaña con las columnas de FLOTA CP de otro día."""

    def __init__(self, formulas: dict, letra_col: str, etiquetas: dict, fecha: dt.date, flota: dict):
        self.formulas, self.letra, self.etiquetas, self.fecha, self.flota = formulas, letra_col, etiquetas, fecha, flota
        self.memo = {}

    def valor(self, fila: int) -> float:
        if fila not in self.memo:
            f = self.formulas.get(fila, "")
            if not isinstance(f, str) or not f.startswith("="):
                raise FormulaNoSoportada(f"fila {fila}: no es una fórmula")
            if f.startswith("=COUNTIFS(") and f.endswith(")"):
                self.memo[fila] = self._countifs(f[len("=COUNTIFS("):-1], fila)
            elif f.startswith("=SUM(") and f.endswith(")"):
                self.memo[fila] = self._sum(f[len("=SUM("):-1])
            else:
                raise FormulaNoSoportada(f"fila {fila}: sólo se evalúan COUNTIFS y SUM")
        return self.memo[fila]

    def _criterio(self, c: str, fila: int):
        if c.startswith('"') and c.endswith('"') and len(c) >= 2:
            lit = c[1:-1]
            if lit[:1] in "<>=" or any(ch in lit for ch in "*?~"):
                raise FormulaNoSoportada(f"criterio con operador o comodín: {lit}")
            return ("texto", texto(lit))
        if re.fullmatch(rf"{self.letra}\$2", c):
            return ("fecha", self.fecha.isoformat())
        m = re.fullmatch(r"\$A\$?(\d+)", c)
        if m:
            etq = self.etiquetas.get(int(m[1]), "")
            if texto(etq) == "" or any(ch in str(etq) for ch in "*?~<>="):
                raise FormulaNoSoportada(f"etiqueta no soportada como criterio: {etq!r}")
            return ("texto", texto(etq))
        raise FormulaNoSoportada(f"criterio no soportado: {c}")

    def _countifs(self, args: str, fila: int) -> int:
        partes = partir_argumentos(args)
        if len(partes) % 2:
            raise FormulaNoSoportada("COUNTIFS con argumentos impares")
        condiciones = []
        for k in range(0, len(partes), 2):
            m = re.fullmatch(r"'FLOTA CP'!\$([A-Z]+):\$([A-Z]+)", partes[k])
            if not m or m[1] != m[2]:
                raise FormulaNoSoportada(f"rango no soportado: {partes[k]}")
            tipo, valor = self._criterio(partes[k + 1], fila)
            datos = self.flota.get(m[1])
            if datos is None:
                raise FormulaNoSoportada(f"FLOTA CP no tiene la columna {m[1]}")
            condiciones.append((tipo, valor, datos))
        n = max(len(d) for _, _, d in condiciones)
        total = 0
        for r in range(n):
            ok = True
            for tipo, valor, datos in condiciones:
                v = datos[r] if r < len(datos) else ""
                if (str(v)[:10] != valor) if tipo == "fecha" else (texto(v) != valor):
                    ok = False
                    break
            total += ok
        return total

    def _sum(self, args: str) -> float:
        total = 0
        for a in partir_argumentos(args):
            m = re.fullmatch(rf"{self.letra}(\d+):{self.letra}(\d+)", a)
            if m:
                filas = range(int(m[1]), int(m[2]) + 1)
            else:
                m = re.fullmatch(rf"{self.letra}(\d+)", a)
                if not m:
                    raise FormulaNoSoportada(f"argumento de SUM no soportado: {a}")
                filas = [int(m[1])]
            for r in filas:
                f = self.formulas.get(r, "")
                if isinstance(f, str) and f.startswith("="):
                    total += self.valor(r)
                elif isinstance(f, (int, float)) and not isinstance(f, bool):
                    total += f
        return total


def evaluar(formulas: dict, letra_col: str, etiquetas: dict, fecha: dt.date, flota: dict, filas: list) -> dict:
    ev = Evaluador(formulas, letra_col, etiquetas, fecha, flota)
    return {r: ev.valor(r) for r in filas}


class Recuperador:
    """Reconstruye las columnas de FLOTA CP de días pasados (con caché) y evalúa fórmulas con ellas."""

    def __init__(self, cargar_hoy, descargar=descargar_flota):
        self._cargar_hoy, self._descargar = cargar_hoy, descargar
        self._hoy, self._dias = None, {}

    def flota(self, fecha: dt.date) -> dict:
        if fecha not in self._dias:
            if self._hoy is None:
                self._hoy = self._cargar_hoy()
            self._dias[fecha] = armar_columnas(self._descargar(fecha), self._hoy)
        return self._dias[fecha]

    def evaluar(self, formulas: dict, letra_col: str, etiquetas: dict, fecha: dt.date, filas: list) -> dict:
        return evaluar(formulas, letra_col, etiquetas, fecha, self.flota(fecha), filas)
