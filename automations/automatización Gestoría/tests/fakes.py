"""Libro y hojas de mentira para probar las pestañas de apoyo sin red ni credenciales."""
import gspread


class HojaFalsa:
    def __init__(self, titulo, rangos=None, row_count=1000):
        self.title = titulo
        self.rangos = rangos or {}          # {"A2:F": [[...]], ...}
        self.row_count = row_count
        self.escrituras = []                # (rango, valores)
        self.limpiezas = []
        self.filas_agregadas = 0

    def get(self, rango, **kw):
        return self.rangos.get(rango, [])

    def batch_update(self, cambios, value_input_option=None):
        for c in cambios:
            self.escrituras.append((c["range"], c["values"]))

    def update(self, values=None, range_name=None, value_input_option=None):
        self.escrituras.append((range_name, values))

    def batch_clear(self, rangos):
        self.limpiezas.extend(rangos)

    def add_rows(self, n):
        self.filas_agregadas += n
        self.row_count += n


class LibroFalso:
    def __init__(self, *hojas):
        self.hojas = {h.title: h for h in hojas}

    def worksheet(self, nombre):
        if nombre not in self.hojas:
            raise gspread.WorksheetNotFound(nombre)
        return self.hojas[nombre]
