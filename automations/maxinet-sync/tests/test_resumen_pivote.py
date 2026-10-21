"""Bloques pivote de RESUMEN: se detectan por su fórmula guía y la extensión nunca pisa contenido.

El 17-oct-2026 el RESUMEN se movió 3 columnas y el sync, con letras fijas, copió la fila 1 sobre
~650 filas (copias de la guía y texto en lugar de fórmulas). Estas pruebas fijan que no se repita."""
import maxinet_sync as m
from fakes import HojaFalsa, col

GUIA = "=TRANSPOSE(UNIQUE('FLOTA POR GRUPO'!2:2))"


def _hoja(bloques, largo_fecha=670):
    """bloques: [(guia, primera, ultima, filas_con_formula)]"""
    c = {}
    for guia, ini, fin, hasta in bloques:
        g = col(guia)
        c[(1, g)] = GUIA
        for r in range(2, largo_fecha + 1):
            c[(r, g)] = 45000 + r
        for j in range(col(ini), col(fin) + 1):
            for r in range(2, hasta + 1):
                c[(r, j)] = f'=XLOOKUP({guia}{r},x,y,"")'
    return HojaFalsa(c)


def test_detecta_los_bloques_con_cualquier_nombre_de_pestana():
    hoja = _hoja([("V", "W", "AM", 662), ("AP", "AQ", "BG", 662)])
    assert m._bloques_pivote_resumen(hoja) == [("V", "W", "AM"), ("AP", "AQ", "BG")]
    assert m.GUIA_PIVOTE_RESUMEN.match("=TRANSPOSE(UNIQUE('UTI. GRUPO DE AUTOS V1'!2:2))")
    assert not m.GUIA_PIVOTE_RESUMEN.match("=TRANSPOSE('FLOTA POR GRUPO'!A84:A99)")


def test_extiende_solo_las_columnas_con_el_destino_vacio():
    hoja = _hoja([("V", "W", "AM", 662), ("AP", "AQ", "BG", 662)])
    for r in range(663, 671):  # las columnas de año ya llegan a la fila 670
        hoja.c[(r, col("W"))] = f'=IF(V{r}="","",YEAR(V{r}))'
        hoja.c[(r, col("AQ"))] = f'=IF(AP{r}="","",YEAR(AP{r}))'
    peticiones = m.extender_formulas_resumen(hoja)
    tramos = sorted(
        (p["copyPaste"]["source"]["startColumnIndex"], p["copyPaste"]["source"]["endColumnIndex"],
         p["copyPaste"]["destination"]["startRowIndex"], p["copyPaste"]["destination"]["endRowIndex"])
        for p in peticiones)
    assert tramos == [(col("X"), col("AM") + 1, 662, 670), (col("AR"), col("BG") + 1, 662, 670)]
    assert len(hoja.spreadsheet.peticiones) == 2


def test_nunca_copia_la_fila_de_encabezados():
    # sólo la guía en la fila 1 y fórmulas desde la fila 2: copia desde la fila 2 (datos)
    hoja = _hoja([("AP", "AQ", "AR", 2)])
    peticiones = m.extender_formulas_resumen(hoja)
    assert peticiones and all(p["copyPaste"]["source"]["startRowIndex"] == 1 for p in peticiones)


def test_bloque_danado_no_se_toca():
    # texto en lugar de fórmulas en Z:AM filas 2-657 (el daño real) y fórmulas buenas en 658-662
    hoja = _hoja([("V", "W", "AM", 662)])
    for j in range(col("Z"), col("AM") + 1):
        for r in range(2, 658):
            hoja.c[(r, j)] = "COMPACTOS"
    peticiones = m.extender_formulas_resumen(hoja)
    assert all(p["copyPaste"]["destination"]["startRowIndex"] >= 662 for p in peticiones)
    # sin ninguna fórmula debajo de los encabezados no se extiende nada
    for j in range(col("Z"), col("AM") + 1):
        for r in range(2, 663):
            hoja.c[(r, j)] = "COMPACTOS"
    assert m.extender_formulas_resumen(hoja) == []


def test_sin_columna_guia_no_hace_nada():
    assert m.extender_formulas_resumen(HojaFalsa({(1, 0): "x", (2, 0): "y"})) == []


def test_fila_de_origen_con_derrame_no_se_copia():
    hoja = _hoja([("AP", "AQ", "AR", 5)])
    hoja.c[(5, col("AR"))] = "=TRANSPOSE('FLOTA POR GRUPO'!A100:A115)"
    assert m.extender_formulas_resumen(hoja) == []


def test_ya_al_dia():
    assert m.extender_formulas_resumen(_hoja([("V", "W", "AB", 105)], largo_fecha=105)) == []


def test_tramos_libres_agrupa_columnas_contiguas():
    destino = [["", "dato", "", ""], ["", "", "", ""]]
    assert m._tramos_libres(destino, 4) == ([(0, 0), (2, 3)], 1)
