"""Hoja y libro de mentira para probar el reporte de flota última renta sin red ni credenciales."""
import re

import gspread

import maxinet_flota_ultima_renta as m


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def fila_reporte(placa, **extra):
    """Fila como la entrega Maxinet: 20 celdas, None donde no hay dato y enteros de verdad en los días. Datos ficticios."""
    valores = {
        "Placa": placa, "BSite": "L", "CurrentSite": "MA",
        "PUDate Ult. Renta Cliente": "2026-08-03", "ReturnDate Ult. Renta Cliente": "2027-07-22",
        "Dias desde Ult. Renta Cliente": None, "Dias no disponibles": None,
        "Semáforo dias no disp.": "na", "Odómetro": "10697", "Semáforo Odómetro": "verde",
        "Group": "SENTR", "Status Vehicle": "ON HIRE", "Make": "MARCA", "Model": "2026 MODELO",
        "Booking Ult. Renta Cliente": "#100000001", "Cliente Ult. Renta": "CLIENTE FICTICIO SA DE CV",
        "PUSite Ult. Renta Cliente": "L", "Estatus ult. renta Cliente": "ON HIRE     ",
        "ReturnDate Ult. Renta": "2027-07-22", "Name Ult. Renta": "CLIENTE FICTICIO SA DE CV",
    }
    valores.update(extra)
    return [valores[n] for n in m.ENCABEZADO]


def fila_hoja(placa, **extra):
    """Fila de la pestaña (20 columnas, tipada) tal como la dejaría una corrida anterior."""
    return m.a_fila_hoja(m.normalizar_filas([fila_reporte(placa, **extra)])[0])


class Libro:
    def __init__(self, hojas=None):
        self.hojas = list(hojas or [])
        self.peticiones = []
        self.creadas = []

    def worksheet(self, nombre):
        for h in self.hojas:
            if h.title == nombre:
                return h
        raise gspread.exceptions.WorksheetNotFound(nombre)

    def add_worksheet(self, title, rows, cols):
        h = HojaFalsa([], titulo=title, libro=self)
        h.row_count, h.col_count = rows, cols
        self.hojas.append(h)
        self.creadas.append(title)
        return h

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con la cuadrícula en `celdas` (lista de filas). Soporta lo que usa el script."""

    def __init__(self, filas, titulo="Reporte Flota Ultima Renta", libro=None):
        self.celdas = [list(f) for f in filas]
        self.title = titulo
        self.row_count = 1000
        self.col_count = 26
        self.id = 11
        self.spreadsheet = libro or Libro([self])
        self.escrituras = []
        self.limpiezas = []
        self.filas_agregadas = 0
        self.columnas_agregadas = 0

    def _rango(self, rango):
        mm = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d*)", rango)
        return _col(mm[1]), int(mm[2]), _col(mm[3]), int(mm[4]) if mm[4] else None

    def get(self, rango, value_render_option=None):
        c1, r1, c2, r2 = self._rango(rango)
        r2 = r2 or len(self.celdas)
        out = []
        for r in range(r1, min(r2, len(self.celdas)) + 1):
            fila = self.celdas[r - 1][c1:c2 + 1]
            while fila and fila[-1] == "":
                fila.pop()
            out.append(fila)
        while out and not out[-1]:
            out.pop()
        return out

    def col_values(self, col):
        return [str(f[col - 1]) if len(f) >= col else "" for f in self.celdas]

    def update(self, range_name=None, values=None, value_input_option=None):
        self.escrituras.append((range_name, values, value_input_option))
        c1, r1, _, _ = self._rango(range_name)
        for i, fila in enumerate(values):
            while len(self.celdas) < r1 + i:
                self.celdas.append([])
            destino = self.celdas[r1 - 1 + i]
            while len(destino) < c1 + len(fila):
                destino.append("")
            destino[c1:c1 + len(fila)] = list(fila)

    def batch_clear(self, rangos):
        self.limpiezas.extend(rangos)
        for rango in rangos:
            c1, r1, c2, r2 = self._rango(rango)
            for r in range(r1, (r2 or len(self.celdas)) + 1):
                if r <= len(self.celdas):
                    fila = self.celdas[r - 1]
                    for c in range(c1, min(c2 + 1, len(fila))):
                        fila[c] = ""

    def add_rows(self, n):
        self.filas_agregadas += n
        self.row_count += n

    def add_cols(self, n):
        self.columnas_agregadas += n
        self.col_count += n
