"""Hojas de cálculo de mentira para probar el sync sin red ni credenciales."""
import re


def col(letras: str) -> int:
    """Índice 0-based de una columna ('A' -> 0, 'AA' -> 26)."""
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


class Libro:
    """Libro falso: guarda las peticiones de batch_update y las hojas por título."""

    def __init__(self, hojas=None):
        self.peticiones = []
        self.hojas = hojas or []

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])

    def worksheet(self, nombre):
        import gspread
        for hoja in self.hojas:
            if hoja.title == nombre:
                return hoja
        raise gspread.exceptions.WorksheetNotFound(nombre)

    def get_worksheet_by_id(self, gid):
        import gspread
        for hoja in self.hojas:
            if hoja.id == gid:
                return hoja
        raise gspread.exceptions.WorksheetNotFound(str(gid))

    def worksheets(self):
        return list(self.hojas)


class HojaFalsa:
    """Hoja falsa con celdas {(fila, columna_0based): valor_o_formula}.

    Soporta get('A1:B9'), get('A1:B') (hasta la última fila con datos),
    get('A1'), row_values, col_values y update (que sólo registra)."""

    def __init__(self, celdas=None, col_count=68, titulo="HOJA", gid=1):
        self.c = celdas or {}
        self.col_count = col_count
        self.row_count = 1000
        self.title = titulo
        self.id = gid
        self.spreadsheet = Libro([self])
        self.escrituras = []

    def _fila(self, r, c1=0, c2=None):
        maximo = max([k[1] for k in self.c if k[0] == r] + [-1])
        c2 = maximo if c2 is None else c2
        fila = [self.c.get((r, c), "") for c in range(c1, c2 + 1)]
        while fila and fila[-1] == "":
            fila.pop()
        return fila

    def row_values(self, r, value_render_option=None):
        return self._fila(r)

    def col_values(self, c1, value_render_option=None):
        ultima = max([k[0] for k in self.c if k[1] == c1 - 1] + [0])
        return [self.c.get((r, c1 - 1), "") for r in range(1, ultima + 1)]

    def get(self, rango, value_render_option=None):
        a = re.match(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d*))?$", rango)
        c1, r1, c2, r2 = a.groups()
        c2 = c2 or c1
        if col(c2) >= self.col_count:
            raise RuntimeError(f"Range ({rango}) exceeds grid limits")
        ultima = int(r2) if r2 else max([k[0] for k in self.c] + [int(r1)])
        filas = [self._fila(r, col(c1), col(c2)) for r in range(int(r1), ultima + 1)]
        while filas and not filas[-1]:
            filas.pop()
        return filas

    def update(self, values=None, range_name=None, value_input_option=None):
        self.escrituras.append((range_name, values))
