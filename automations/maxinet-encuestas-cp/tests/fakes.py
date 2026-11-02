"""Hoja de Encuestas simulada: datos en C:Z (fila 1 = encabezados), PERIODO y RECLASIFICACION en A y B."""
import re

import maxinet_encuestas_cp as m

ENCABEZADOS = ["PERIODO", "RECLASIFICACION"] + m.COLUMNAS


def _letra_a_col(letras: str) -> int:
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - 64)
    return n


class LibroFalso:
    def __init__(self, hoja):
        self.hoja = hoja
        self.lotes = []                          # cada batch_update recibido (lista de peticiones)
        self.fallar = None                       # excepción que levantará el próximo batch_update

    def batch_update(self, body):
        if self.fallar:
            e, self.fallar = self.fallar, None
            raise e
        pedidos = list(body["requests"])
        self.lotes.append(pedidos)
        for p in pedidos:                        # aplica el efecto de las copias sobre la hoja simulada
            cp = p["copyPaste"]
            o, d = cp["source"], cp["destination"]
            for fila in range(d["startRowIndex"] + 1, d["endRowIndex"] + 1):
                for col in range(d["startColumnIndex"] + 1, d["endColumnIndex"] + 1):
                    if cp["pasteType"] == "PASTE_FORMULA":
                        self.hoja.celdas[(fila, col)] = f"=FORMULA_DE_{col}_FILA_{fila}"
                    else:
                        self.hoja.con_formato.add(fila)


class HojaFalsa:
    """`filas`: número de filas con datos (fila 1 = encabezados). Las filas de `sin_formulas` no tienen PERIODO ni
    RECLASIFICACION ni formato; `en_blanco` son filas sin fecha."""

    id = 7
    row_count = 5000

    def __init__(self, filas, sin_formulas=(), en_blanco=()):
        self.celdas = {}
        self.con_formato = set()
        self.spreadsheet = LibroFalso(self)
        for j, h in enumerate(ENCABEZADOS, start=1):
            self.celdas[(1, j)] = h
        for fila in range(2, filas + 1):
            if fila in en_blanco:
                continue
            self.celdas[(fila, 3)] = "2026-11-01"                                    # Fecha resp.
            self.celdas[(fila, 5)] = f"R{fila}"                                      # Reserva
            if fila not in sin_formulas:
                self.celdas[(fila, 1)] = f"=PERIODO_FILA_{fila}"
                self.celdas[(fila, 2)] = f"=RECLASIF_FILA_{fila}"
                self.con_formato.add(fila)

    def row_values(self, fila):
        ultimo = max((c for (f, c) in self.celdas if f == fila), default=0)
        return [str(self.celdas.get((fila, c), "")) for c in range(1, ultimo + 1)]

    def col_values(self, col):
        ultimo = max((f for (f, c), v in self.celdas.items() if c == col and v != ""), default=0)
        return [str(self.celdas.get((f, col), "")) for f in range(1, ultimo + 1)]

    def get(self, rango, value_render_option=None):
        a, b = rango.split(":")
        ma, mb = re.fullmatch(r"([A-Z]+)(\d+)", a), re.fullmatch(r"([A-Z]+)(\d+)", b)
        c1, f1, c2, f2 = _letra_a_col(ma.group(1)), int(ma.group(2)), _letra_a_col(mb.group(1)), int(mb.group(2))
        filas = []
        for f in range(f1, f2 + 1):
            fila = [self.celdas.get((f, c), "") for c in range(c1, c2 + 1)]
            while fila and fila[-1] == "":
                fila.pop()
            filas.append(fila)
        while filas and not filas[-1]:
            filas.pop()
        return filas

    def formulas(self, col):
        return {f for (f, c), v in self.celdas.items() if c == col and str(v).startswith("=")}
