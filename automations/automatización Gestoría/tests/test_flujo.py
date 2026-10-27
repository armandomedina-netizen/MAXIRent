import pandas as pd

import gestoria_lp_cp_sync as g
import hojas_apoyo as h
from tests.fakes import HojaFalsa, LibroFalso


class HojaDatos(HojaFalsa):
    def __init__(self, libro_ref, filas):
        super().__init__("GESTORIA CP - LP", {"A2:AI": filas})
        self.spreadsheet = libro_ref


def df_maxinet(*filas):
    base = {c: None for c in g.COLUMNAS_SHEET}
    return pd.DataFrame([{**base, **f} for f in filas])


def test_el_sync_ya_no_busca_la_pestana_2026():
    assert not hasattr(g, "mantener_formulas_historico") and not hasattr(g, "conectar_hoja_historico")


def test_actualizar_apoyo_escribe_sello_alertas_y_nombres():
    fuentes, alertas = HojaFalsa(h.PESTANA_FUENTES), HojaFalsa(h.PESTANA_ALERTAS)
    revisar = HojaFalsa(h.PESTANA_REVISAR)
    indice = HojaFalsa(h.PESTANA_INDICE, {"A2:A": [["TALLER TALLER"]]})
    libro = LibroFalso(fuentes, alertas, revisar, indice)
    hoja = HojaDatos(libro, [["1", "ABIERTO"], ["2", "CERRADO"]])
    df = df_maxinet({"id": 1700, "estatus": "ABIERTO", "nombreTipo": "SINIESTRO", "FromSite": "", "ClientName": "REPOSICION",
                     "fecha_evento": "2026-10-10", "created_at": "2026-10-10 09:00:00", "registrationNo": "A", "bookingNo": "#R"})
    g.actualizar_apoyo(hoja, df, nuevos=3, cerrados=1, fechas=0, refrescados=2)
    sello = {r: v[0][0] for r, v in fuentes.escrituras}
    assert sello["B4"] == 1 and sello["B5"] == 2 and sello["B7"] == 1 and sello["B8"] == 1
    assert sello["B6"] == "3 nuevos, 1 cerrados, 0 fechas de cierre, 2 campos refrescados"
    assert alertas.escrituras and alertas.escrituras[0][1][0][3] == "Sucursal"
    assert revisar.escrituras[0][1][0][0] == "REPOSICION"


def test_actualizar_apoyo_en_dry_run_no_escribe_nada():
    hojas = [HojaFalsa(n) for n in (h.PESTANA_FUENTES, h.PESTANA_ALERTAS, h.PESTANA_REVISAR)] + [HojaFalsa(h.PESTANA_INDICE)]
    libro = LibroFalso(*hojas)
    g.actualizar_apoyo(HojaDatos(libro, []), df_maxinet({"id": 1, "ClientName": "X"}), 0, 0, 0, 0, dry_run=True)
    assert all(not x.escrituras and not x.limpiezas for x in hojas)
