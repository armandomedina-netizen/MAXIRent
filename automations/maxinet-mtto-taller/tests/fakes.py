"""Hoja y libro de mentira para probar las órdenes por ingreso a taller sin red ni credenciales."""
import re

import gspread

import maxinet_mtto_taller as m


def _col(letras: str) -> int:
    return sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(letras))) - 1


def fila_reporte(id_orden, ingreso="2026-10-05", estatus="CERRADO", placa="AAA111", **extra):
    """Fila como la entrega Maxinet: 62 celdas, con HTML en los botones y 'None' donde no hay dato."""
    f = ["None"] * m.ANCHO_REPORTE
    f[0] = f'<a class="detalleBtn" href="lp-mtto-DetailOrden.php?Id={id_orden}">Detalle</a>'
    f[1] = f'<a class="citaBtn" href="includes/mttoLP/HojaCitaVer.php?id={id_orden}">Hoja Cita</a>'
    f[2] = ""
    valores = {"Id": str(id_orden), "Tipo ticket": "CP", "Estatus": f" {estatus}", "No.Placa": placa,
               "Fecha Alta": ingreso, "Hora Alta": "09:28", "Fecha Ingreso Taller": ingreso,
               "Hora Ingreso Taller": "09:40", "Costo Total": "3665.60", "Dias Taller": "0.5",
               "Nombre Contacto": "PERSONA PRIVADA", "Tel. Contacto": "8100000000", "Cel. Contacto": "8100000001",
               "Correo": "privado@example.com", "Asesor": "ASESOR UNO"}
    valores.update(extra)
    for nombre, v in valores.items():
        f[m.COLUMNAS_REPORTE.index(nombre)] = v
    return f


def fila_hoja(id_orden, ingreso="2026-10-05", estatus="CERRADO", placa="AAA111", **extra):
    """Fila de la pestaña (59 columnas, tipada) tal como la dejaría una corrida anterior."""
    return m.a_fila_hoja(m.normalizar_filas([fila_reporte(id_orden, ingreso, estatus, placa, **extra)])[0])


class Libro:
    def __init__(self, hojas=None):
        self.hojas = list(hojas or [])
        self.peticiones = []

    def worksheets(self):
        return list(self.hojas)

    def worksheet(self, nombre):
        for h in self.hojas:
            if h.title == nombre:
                return h
        raise gspread.exceptions.WorksheetNotFound(nombre)

    def get_worksheet_by_id(self, gid):
        for h in self.hojas:
            if h.id == gid:
                return h
        raise gspread.exceptions.WorksheetNotFound(str(gid))

    def batch_update(self, cuerpo):
        self.peticiones.extend(cuerpo["requests"])


class HojaFalsa:
    """Hoja con la cuadrícula en `celdas` (lista de filas). Soporta lo que usa el script."""

    def __init__(self, filas, titulo="ORDENES", libro=None, gid=11):
        self.celdas = [list(f) for f in filas]
        self.title = titulo
        self.row_count = 1000
        self.col_count = 70
        self.id = gid
        self.spreadsheet = libro or Libro([self])
        self.escrituras = []              # (rango, valores) de cada batch_update, en orden
        self.filas_agregadas = 0
        self.alterar_antes_de_escribir = None   # función que simula a alguien editando la hoja a media corrida

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

    def batch_update(self, datos, raw=True):
        assert raw is True, "las órdenes se escriben siempre con RAW"
        if self.alterar_antes_de_escribir:
            self.alterar_antes_de_escribir()
            self.alterar_antes_de_escribir = None
        for d in datos:
            self.escrituras.append((d["range"], d["values"]))
            c1, r1, _, _ = self._rango(d["range"])
            for i, fila in enumerate(d["values"]):
                while len(self.celdas) < r1 + i:
                    self.celdas.append([])
                destino = self.celdas[r1 - 1 + i]
                while len(destino) < c1 + len(fila):
                    destino.append("")
                destino[c1:c1 + len(fila)] = list(fila)

    def add_rows(self, n):
        self.filas_agregadas += n
        self.row_count += n
