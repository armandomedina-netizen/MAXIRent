"""Hoja de cálculo de mentira para probar la bitácora sin red ni credenciales (datos sintéticos)."""
import datetime as dt
import re

import maxinet_bitacora_cp as m

BASE = dt.date(1899, 12, 30)
ANCHO = len(m.ENCABEZADOS)


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def dia(texto: str) -> int:
    return (dt.date.fromisoformat(texto) - BASE).days


def fila_maxinet(promesa, hora="08:00:00", reserva="#100000001", tipo="DELIVER", **campos):
    """Fila como la entrega Maxinet: 1 columna de acción en HTML y las 37 de datos, todo texto."""
    datos = {c: "" for c in m.COLUMNAS}
    datos.update({"Tipo Serv.": tipo, "Fecha Prom.": promesa, "Hora Prom.": hora, "Fecha Real": promesa, "Hora Real": hora,
                  "Semáforo": "verde", "Estatus Serv.": "EN TIEMPO", "Tiempo Trans.": "-10 min", "Estatus": "CHECKED IN",
                  "Reserva": reserva, "Cliente": "CLIENTE PRUEBA", "Sucursal": "LT", "Costo Ent.Dom": "250.0000",
                  "Costo Rec.": "0.0000", "Dif. Dias": 3})
    datos.update(campos)
    accion = '<a href="#" class="btn-detail" attrId="#1" attrId2="#2" attrTipo="DELIVER" attrColor="verde">Comentarios</a>'
    return [accion] + [datos[c] for c in m.COLUMNAS]


def fila_hoja(promesa, **campos):
    """Fila ya escrita en la hoja (37 datos + 4 fórmulas vacías), la que dejaría una corrida anterior."""
    return m.normalizar_filas([fila_maxinet(promesa, **campos)])[0] + [""] * len(m.COLUMNAS_AUX)


class Libro:
    def __init__(self):
        self.peticiones = []

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con 41 columnas (fila 1 = encabezados) que soporta lo que usa el script."""

    def __init__(self, filas=(), encabezados=None):
        self.encabezados = list(encabezados if encabezados is not None else m.ENCABEZADOS)
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
        mm = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
        c1, r1 = _col(mm[1]), int(mm[2])
        while len(self.filas) < r1 - 2 + len(values):
            self.filas.append([""] * ANCHO)
        for i, v in enumerate(values):
            fila = self.filas[r1 - 2 + i]
            fila[c1:c1 + len(v)] = list(v)

    def batch_clear(self, rangos):
        self.limpiezas.extend(rangos)
        for rg in rangos:
            mm = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rg)
            c1, c2 = _col(mm[1]), _col(mm[3])
            for r in range(int(mm[2]), int(mm[4]) + 1):
                if 2 <= r < 2 + len(self.filas):
                    for c in range(c1, c2 + 1):
                        self.filas[r - 2][c] = ""

    def add_rows(self, n):
        self.filas_agregadas.append(n)
        self.row_count += n
