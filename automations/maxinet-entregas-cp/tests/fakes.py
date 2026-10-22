"""Hoja de cálculo de mentira para probar ENTREGAS sin red ni credenciales."""
import datetime as dt
import re

BASE = dt.date(1899, 12, 30)


def serie(fecha_iso: str) -> int:
    return (dt.date.fromisoformat(fecha_iso) - BASE).days


def hora_frac(hhmmss: str) -> float:
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return (h * 3600 + m * 60 + s) / 86400


def fila_hoja(fecha, hora, cliente, reserva, estatus="ON HIRE", placa="AAA111", gas_rec=""):
    """Fila A:P como la guarda el Sheet (fecha y hora como números de serie)."""
    return [serie(fecha), hora_frac(hora), cliente, "NOMBRE", "LT", "ASESOR", 3, "", reserva, placa, "VERSA",
            "NO", "NO", estatus, "FULL", gas_rec]


def fila_mx(fecha, hora, cliente, reserva, estatus="ON HIRE", placa="AAA111", gas_rec=None):
    """Fila como la entrega Maxinet (18 columnas: 16 + JOB Entrega y JOB Recepción)."""
    return [fecha, hora, cliente, "NOMBRE", "LT", "ASESOR", 3, None, reserva, placa, "VERSA",
            "NO", "NO", estatus + "   ", "FULL", gas_rec, "SI", "NO"]


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


class Libro:
    def __init__(self):
        self.peticiones = []

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con filas A:P (fila 1 = encabezados) que soporta lo que usa el script."""

    def __init__(self, filas):
        self.filas = [list(f) for f in filas]               # filas[0] es la fila 2 de la hoja
        self.row_count = 1000
        self.id = 7
        self.spreadsheet = Libro()
        self.escrituras = []
        self.limpiezas = []
        self.filas_agregadas = []

    def col_values(self, col):
        out = ["Fecha"] + [str(f[col - 1]) for f in self.filas]
        return out

    def get(self, rango, value_render_option=None):
        m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rango)
        c1, r1, c2, r2 = _col(m[1]), int(m[2]), _col(m[3]), int(m[4])
        out = []
        for r in range(r1, r2 + 1):
            if 2 <= r < 2 + len(self.filas):
                f = self.filas[r - 2]
                out.append([f[c] if c < len(f) else "" for c in range(c1, c2 + 1)])
        return out

    def update(self, range_name=None, values=None, value_input_option=None):
        self.escrituras.append((range_name, values, value_input_option))
        m = re.fullmatch(r"A(\d+):P(\d+)", range_name)
        r1 = int(m[1])
        while len(self.filas) < r1 - 2 + len(values):
            self.filas.append([""] * 16)
        for i, v in enumerate(values):
            self.filas[r1 - 2 + i] = list(v)

    def batch_clear(self, rangos):
        self.limpiezas.extend(rangos)
        for rg in rangos:
            m = re.fullmatch(r"A(\d+):P(\d+)", rg)
            for r in range(int(m[1]), int(m[2]) + 1):
                if 2 <= r < 2 + len(self.filas):
                    self.filas[r - 2] = [""] * 16

    def add_rows(self, n):
        self.filas_agregadas.append(n)
        self.row_count += n
