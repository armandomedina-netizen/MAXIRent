"""Hoja y libro de mentira para probar los envíos a seminuevos sin red ni credenciales."""
import re

import gspread

import maxinet_seminuevos_lp as m


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def fila_reporte(placa, booked_on="2026-10-31", **extra):
    """Fila como la entrega Maxinet: 28 celdas, con la placa dentro de un enlace HTML y 'None' donde no hay dato.
    Los nombres de clientes son ficticios."""
    f = [None] * m.ANCHO
    valores = {"Placa": f'<a href="#" class="detailCostos" title="Detalle" attrPlaca="{placa}">{placa}</a>',
               "Seminuevos": "2026-10-30", "Dias en SN": "2", "Ult. Renta": "2026-10-27", "Dias ult. renta": "5",
               "Gasto SN": "0.00", "Recup.": "-3200.00", "Total": "75542.98", "Job": "NO", "BSite": "L",
               "CurrentSite": "SM", "Model": "2022 HILUX DOBLE CABINA 4X4", "Group": "DC4X4", "Status Vehicle": "ON HIRE",
               "Make": "TOYOTA ", "Booking Previa": "#222305323", "Cliente Previa": "PREVIA VENTA",
               "ReturnDate Previa": "2026-11-03", "Booking Ult. Renta": "#95707294",
               "Cliente Ult. Renta": "EMPRESA FICTICIA SA DE CV", "PUSite Ult. Renta": "L",
               "PUDate Ult. Renta": "2024-08-28", "Estatus ult. renta": "CHECKED IN  ", "BOOKED_ON": booked_on}
    valores.update(extra)
    for nombre, v in valores.items():
        f[m.COLUMNAS.index(nombre)] = v
    return f


def fila_hoja(placa, booked_on="2026-10-31", **extra):
    """Fila de la pestaña (28 columnas, tipada) tal como la dejaría una corrida anterior."""
    return m.a_fila_hoja(m.normalizar_filas([fila_reporte(placa, booked_on, **extra)])[0])


def formulas_mes_anio(fila):
    return [f'=TEXT(B{fila},"MMMM")', f"=YEAR(B{fila})"]


class Libro:
    def __init__(self, hojas=None):
        self.hojas = list(hojas or [])
        self.peticiones = []
        self.orden = []                                     # operaciones en el orden en que ocurrieron

    def worksheet(self, nombre):
        for h in self.hojas:
            if h.title == nombre:
                return h
        raise gspread.exceptions.WorksheetNotFound(nombre)

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])
        self.orden.append("batch_update")
        for p in cuerpo["requests"]:
            if "copyPaste" in p:
                self._copiar(p["copyPaste"])

    def _copiar(self, c):
        """Simula copyPaste de una fila origen repetida sobre el destino (sólo lo que usa el script)."""
        hoja = self.hojas[0]
        s, d = c["source"], c["destination"]
        assert s["endRowIndex"] - s["startRowIndex"] == 1
        if c["pasteType"] != "PASTE_NORMAL":
            return
        origen = hoja.celdas[s["startRowIndex"]]
        for r in range(d["startRowIndex"], d["endRowIndex"]):
            while len(hoja.celdas) <= r:
                hoja.celdas.append([])
            fila = hoja.celdas[r]
            while len(fila) < d["endColumnIndex"]:
                fila.append("")
            for k in range(d["startColumnIndex"], d["endColumnIndex"]):
                fila[k] = re.sub(r"\d+", str(r + 1), str(origen[k])) if str(origen[k]).startswith("=") else origen[k]


class HojaFalsa:
    """Hoja con la cuadrícula en `celdas` (lista de filas). Soporta lo que usa el script."""

    def __init__(self, filas, titulo="ENVIOS SEMINUEVOS", libro=None, con_formulas=True):
        self.celdas = []
        for i, f in enumerate(filas, 1):
            f = list(f)
            if i >= 2 and con_formulas and len(f) == m.ANCHO:
                f += formulas_mes_anio(i)
            self.celdas.append(f)
        self.title = titulo
        self.row_count = max(1200, len(self.celdas))
        self.col_count = 30
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
        vals = [str(f[col - 1]) if len(f) >= col else "" for f in self.celdas]
        while vals and vals[-1] == "":
            vals.pop()
        return vals

    def update(self, range_name=None, values=None, value_input_option=None):
        self.escrituras.append((range_name, values, value_input_option))
        self.spreadsheet.orden.append("update")
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
        self.spreadsheet.orden.append("batch_clear")
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
