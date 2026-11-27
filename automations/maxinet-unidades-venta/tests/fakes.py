"""Hoja y libro de mentira para probar la carga de unidades en proceso de venta sin red ni credenciales."""
import re

import gspread

import maxinet_unidades_venta as m


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def fila_reporte(ident, **extra):
    """Fila como la entrega Maxinet: botón, columna oculta vacía y 45 columnas de la tabla. Datos ficticios."""
    valores = {
        "Id": str(ident), "Placa": f"PLK{ident}A", "Grupo": "GRUPO1", "Motivo envío": "Fin de vida útil",
        "Estatus A": '<span style="color:orange;">Propuesta</span>', "Estatus B": None,
        "Precio Compra": "$ 208,000.00", "Precio Venta Propuesto": "$ 247,000.00", "P.EBC Compra": "$ 194,000.00",
        "P.EBC Venta": "$ 223,300.00", "Costo Adecuaciones": "$ 1.00", "Precio Final Venta": "", "TT": "",
        "Precio Actual": "", "Asesor": None, "Categoría": "Carga", "No. Serie": "9BD265559J9111585",
        "Fecha Compra": "2018-09-07", "Fecha Venta": None, "Marca": "MARCA", "Modelo": "2018 MODELO FICTICIO",
        "Modelo Oficial": "2018 MODELO FICTICIO", "Año": "2018", "Km Prohire": "116269.00", "Km Visual": "116270.00",
        "Transmisión": None, "% Utilización": None, "# Cliente": None, "Cliente": None,
        "Nombre para facturación": None, "RFC": None, "Fecha Alta": "2026-08-17", "Fecha Liberado a TP": None,
        "Author": "usuario.ficticio", "Modelo Equivalente": None, "Bsite": "L", "CurrentSite": "BA",
        "EntryDate": "2018-09-10", "Meses Uso": "95", "MOI (sin iva)": 179310.34, "Precio caja": 0,
        "Total MOI": 179310.34, "Dep. Mensual": 2091.95, "Dep. Acumulada": 198735.25,
        "Remanente ajustado 14%": -19424.91,
    }
    valores.update(extra)
    return ['<a href="detail-Unidad-Propuesta.php?id=1" class="btn-detail">Detalle</a> &nbsp;', ""] + [valores[n] for n in m.ENCABEZADO]


def fila_hoja(ident, **extra):
    """Fila de la pestaña (45 columnas, tipada) tal como la dejaría una corrida anterior."""
    return m.a_fila_hoja(m.normalizar_filas([fila_reporte(ident, **extra)])[0])


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

    def add_worksheet(self, title, rows, cols):          # la automatización NO debe llamarlo; se registra para probarlo
        self.creadas.append(title)
        raise AssertionError("la automatización no debe crear pestañas")

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con la cuadrícula en `celdas` (lista de filas). Soporta lo que usa el script."""

    def __init__(self, filas, titulo="Unidades en Proceso de Venta", libro=None):
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
