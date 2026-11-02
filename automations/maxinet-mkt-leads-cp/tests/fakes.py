"""Hoja de cálculo de mentira para probar MKT sin red ni credenciales (datos sintéticos)."""
import datetime as dt
import re

import maxinet_mkt_leads_cp as m

BASE = dt.date(1899, 12, 30)


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def serie(texto: str) -> float:
    return m._serie(texto, "x")


def fila_maxinet(registro, lid, **campos):
    """Fila como la entrega Maxinet: 2 columnas de acción en HTML y las 40 de datos, todo texto."""
    datos = {c: "" for c in m.COLUMNAS}
    datos.update({"Atendido": "SI", "Contactado": "SI", "Nombre": "NOMBRE PRUEBA", "Fecha Registro": registro,
                  "Fecha Asignado": registro, "Fecha Atendido": registro, "No.Intento": "1",
                  "Fecha Ult.Intento": registro, "Teléfono": "8110000000"})
    datos.update(campos)
    accion = f'<a href="#" title="Detalle" class="muestraDtail" attrId="{lid}" >Detalle</a>'
    return [accion, ""] + [datos[c] for c in m.COLUMNAS]


def fila_hoja(registro, **campos):
    """Fila ya escrita en la hoja (40 valores tipados), la que dejaría una corrida anterior."""
    return m.normalizar_filas([fila_maxinet(registro, 1, **campos)])[0]


class Libro:
    def __init__(self):
        self.peticiones = []

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con 40 columnas (fila 1 = encabezados) que soporta lo que usa el script."""

    def __init__(self, filas=(), encabezados=None):
        self.encabezados = list(encabezados if encabezados is not None else m.COLUMNAS)
        self.filas = [list(f) for f in filas]               # filas[0] es la fila 2 de la hoja
        self.row_count = 1000
        self.id = 7
        self.spreadsheet = Libro()
        self.escrituras = []
        self.limpiezas = []
        self.filas_agregadas = []

    def get(self, rango, value_render_option=None):
        mm = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rango)
        c1, r1, c2, r2 = _col(mm[1]), int(mm[2]), _col(mm[3]), int(mm[4])
        out = []
        for r in range(r1, r2 + 1):
            if r == 1:
                fila = self.encabezados
            elif 2 <= r < 2 + len(self.filas):
                fila = self.filas[r - 2]
            else:
                continue
            out.append([fila[c] if c < len(fila) else "" for c in range(c1, c2 + 1)])
        return out

    def update(self, range_name=None, values=None, value_input_option=None):
        self.escrituras.append((range_name, values, value_input_option))
        mm = re.fullmatch(r"A(\d+):AN(\d+)", range_name)
        r1 = int(mm[1])
        while len(self.filas) < r1 - 2 + len(values):
            self.filas.append([""] * len(m.COLUMNAS))
        for i, v in enumerate(values):
            self.filas[r1 - 2 + i] = list(v)

    def batch_clear(self, rangos):
        self.limpiezas.extend(rangos)
        for rg in rangos:
            mm = re.fullmatch(r"A(\d+):AN(\d+)", rg)
            for r in range(int(mm[1]), int(mm[2]) + 1):
                if 2 <= r < 2 + len(self.filas):
                    self.filas[r - 2] = [""] * len(m.COLUMNAS)

    def add_rows(self, n):
        self.filas_agregadas.append(n)
        self.row_count += n
