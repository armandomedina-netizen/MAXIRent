"""Hoja de cálculo de mentira para probar 2das y 3ras rentas sin red ni credenciales (datos sintéticos)."""
import re

import maxinet_rentas_2_3_cp as m


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def fila_maxinet(cliente, evento, f2="", f3="", **campos):
    """Fila como la entrega Maxinet: 18 valores, todo texto."""
    datos = {c: "" for c in m.COLUMNAS}
    datos.update({"No. Cliente": cliente, "Cliente": "CLIENTE PRUEBA", "No.Rentas": str(evento),
                  "No.Evento": str(evento), "Fecha 1ra renta": "2025-03-15", "Suc. 1ra renta": "LF",
                  "Asesor 1ra renta": "ASESOR UNO", "Fecha 2da renta": f2, "Suc. 2da renta": "LF",
                  "Asesor 2da renta": "ASESOR DOS", "Fecha 3ra renta": f3,
                  "ContactTelNo": "8110000000", "Email": "prueba@example.com"})
    if f3:
        datos.update({"Suc. 3ra renta": "LF", "Asesor 3ra renta": "ASESOR TRES"})
    datos.update(campos)
    return [datos[c] for c in m.COLUMNAS]


def fila_hoja(cliente, evento, f2="", f3="", **campos):
    """Fila ya escrita en la hoja (18 valores tipados), la que dejaría una corrida anterior."""
    return m.normalizar_filas([fila_maxinet(cliente, evento, f2, f3, **campos)])[0]


class Libro:
    def __init__(self):
        self.peticiones = []

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con 18 columnas (fila 1 = encabezados) que soporta lo que usa el script."""

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
            elif r - 2 < len(self.filas):
                fila = self.filas[r - 2]
            else:
                fila = []
            sub = list(fila[c1:c2 + 1])
            while sub and sub[-1] == "":
                sub.pop()
            out.append(sub)
        while out and not out[-1]:
            out.pop()
        return out

    def update(self, range_name, values, value_input_option=None):
        mm = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
        assert value_input_option == "RAW"
        self.escrituras.append((range_name, [list(v) for v in values]))
        r1 = int(mm[2])
        for k, v in enumerate(values):
            i = r1 - 2 + k
            while len(self.filas) <= i:
                self.filas.append([""] * len(m.COLUMNAS))
            self.filas[i] = list(v)

    def batch_clear(self, rangos):
        self.limpiezas.extend(rangos)
        for rg in rangos:
            mm = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rg)
            for r in range(int(mm[2]), int(mm[4]) + 1):
                if r - 2 < len(self.filas):
                    self.filas[r - 2] = [""] * len(m.COLUMNAS)

    def add_rows(self, n):
        self.filas_agregadas.append(n)
        self.row_count += n
