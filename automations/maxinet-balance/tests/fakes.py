"""Hojas y libro simulados en memoria: sólo lo que usa maxinet_balance al cargar ONHIRE y RETORNOS."""
import re

import gspread
from gspread.utils import a1_to_rowcol, rowcol_to_a1


def _rango(texto: str, filas_totales: int):
    inicio, _, fin = texto.partition(":")
    r0, c0 = a1_to_rowcol(inicio)
    fin = fin or inicio
    m = re.fullmatch(r"([A-Z]+)(\d*)", fin)
    c1 = a1_to_rowcol(m.group(1) + "1")[1]
    r1 = int(m.group(2)) if m.group(2) else filas_totales
    return r0, c0, r1, c1


class HojaFalsa:
    def __init__(self, titulo, filas=1000, columnas=26):
        self.title, self.id = titulo, abs(hash(titulo)) % 10**6
        self.row_count, self.col_count = filas, columnas
        self.celdas = {}                    # (fila, col) -> valor o fórmula
        self.escrituras = []                # rangos escritos, para comprobar qué se tocó

    # lectura
    def get(self, rango, value_render_option=None):
        r0, c0, r1, c1 = _rango(rango, self.row_count)
        filas = [[self.celdas.get((r, c), "") for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]
        while filas and not any(x != "" for x in filas[-1]):
            filas.pop()
        return [[x for x in f] for f in filas] if filas else []

    def row_values(self, n):
        fila = [self.celdas.get((n, c), "") for c in range(1, self.col_count + 1)]
        while fila and fila[-1] == "":
            fila.pop()
        return fila

    def col_values(self, n):
        valores = [self.celdas.get((r, n), "") for r in range(1, self.row_count + 1)]
        while valores and valores[-1] == "":
            valores.pop()
        return valores

    # escritura
    def update(self, values=None, range_name="A1", value_input_option=None, raw=None):
        r0, c0 = a1_to_rowcol(range_name.split(":")[0])
        for i, fila in enumerate(values):
            for j, v in enumerate(fila):
                self.celdas[(r0 + i, c0 + j)] = v
        self.escrituras.append(range_name)

    def batch_update(self, data, value_input_option=None, **kw):
        for d in data:
            self.update(values=d["values"], range_name=d["range"])

    def batch_clear(self, rangos):
        for rng in rangos:
            r0, c0, r1, c1 = _rango(rng, self.row_count)
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    self.celdas.pop((r, c), None)
        self.escrituras.append("clear:" + ",".join(rangos))

    def clear(self):
        self.celdas.clear()

    def add_rows(self, n): self.row_count += n
    def add_cols(self, n): self.col_count += n

    # ayudas de las pruebas
    def celda(self, a1):
        return self.celdas.get(a1_to_rowcol(a1), "")

    def poner(self, a1, valor):
        self.celdas[a1_to_rowcol(a1)] = valor


class LibroFalso:
    def __init__(self):
        self.hojas = {}

    def worksheet(self, titulo):
        if titulo not in self.hojas:
            raise gspread.WorksheetNotFound(titulo)
        return self.hojas[titulo]

    def add_worksheet(self, title, rows, cols):
        self.hojas[title] = HojaFalsa(title, rows, cols)
        return self.hojas[title]

    def batch_update(self, cuerpo):
        return {}

    def fetch_sheet_metadata(self, params=None):
        return {"sheets": []}
