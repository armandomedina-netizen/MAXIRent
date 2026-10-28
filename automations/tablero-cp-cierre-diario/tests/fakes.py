"""Libro y hojas de mentira para probar el cierre diario sin red ni credenciales."""
import re

import gspread


def _idx(letras: str) -> int:
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n


def _a1(rango: str):
    m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rango)
    return _idx(m[1]), int(m[2]), _idx(m[3]), int(m[4])


class HojaFalsa:
    """formulas[f][c] y valores[f][c] (índices desde 0)."""

    def __init__(self, formulas, valores, nombre="HOJA", row_count=1000, id=1):
        self.formulas, self.valores, self.title, self.row_count, self.id = formulas, valores, nombre, row_count, id

    def get(self, rango, value_render_option="FORMATTED_VALUE"):
        c1, r1, c2, r2 = _a1(rango)
        fuente = self.formulas if value_render_option == "FORMULA" else self.valores
        out = []
        for r in range(r1, r2 + 1):
            fila = fuente[r - 1] if r - 1 < len(fuente) else []
            out.append([fila[c - 1] if c - 1 < len(fila) else "" for c in range(c1, c2 + 1)])
        while out and not any(x != "" for x in out[-1]):          # la API recorta filas vacías al final
            out.pop()
        return out


class LibroFalso:
    def __init__(self, hojas):
        self.hojas = {h.title: h for h in hojas}
        self.peticiones = []

    def worksheet(self, nombre):
        if nombre not in self.hojas:
            raise gspread.WorksheetNotFound(nombre)
        return self.hojas[nombre]

    def get_worksheet_by_id(self, gid):
        for h in self.hojas.values():
            if h.id == gid:
                return h
        raise gspread.WorksheetNotFound(str(gid))

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class FotosFalsas:
    """Misma interfaz que cierre_diario.Fotos, en memoria."""

    def __init__(self, existentes=None, gids=None):
        self.datos = dict(existentes or {})          # (fecha, pestaña) -> {fila: valor}
        self.gids = dict(gids or {})                 # nombre de siempre -> identificador
        self.guardadas = []

    def leer_todas(self, pestana):
        return {f: v for (f, p), v in self.datos.items() if p == pestana}

    def gid_de(self, logico):
        return self.gids.get(logico)

    def guardar_gid(self, logico, gid):
        self.gids[logico] = gid

    def guardar(self, fecha, pestana, valores, hoy):
        self.datos[(fecha, pestana)] = dict(valores)
        self.guardadas.append((fecha, pestana, dict(valores)))



class HojaOculta:
    """Pestaña oculta del cierre: filas de texto, con lo mínimo que usa cierre_diario.Fotos."""

    def __init__(self, filas, id=900):
        self.filas, self.id, self.title = [list(f) for f in filas], id, "_CIERRE_DIARIO"
        self.limpiadas = []

    def get_all_values(self):
        return [list(f) for f in self.filas]

    def update(self, range_name=None, values=None, value_input_option=None):
        m = re.fullmatch(r"A(\d+):C(\d+)", range_name)
        n = int(m[1])
        while len(self.filas) < n:
            self.filas.append(["", "", ""])
        self.filas[n - 1] = list(values[0])

    def batch_clear(self, rangos):
        self.limpiadas.extend(rangos)
