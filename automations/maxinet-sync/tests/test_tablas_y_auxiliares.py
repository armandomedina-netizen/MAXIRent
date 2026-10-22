"""TABLAS con extensión segura, pasos auxiliares tolerantes y pestañas por nombre, alias o gid."""
import gspread
import pytest

import maxinet_sync as m
from fakes import HojaFalsa, Libro, col


# --- TABLAS: extender fórmulas hacia abajo sin pisar nada -------------------------------------

def test_bloque_normal_se_extiende_hasta_la_ultima_fila():
    c = {(r, j): "=AVERAGEIFS(x)" for r in range(3, 6) for j in range(col("B"), col("E") + 1)}
    peticiones = m._extender_bloques_formulas(HojaFalsa(c), 7, None, [("B", "E")], 8)
    assert len(peticiones) == 1
    destino = peticiones[0]["copyPaste"]["destination"]
    assert (destino["startRowIndex"], destino["endRowIndex"]) == (5, 8)


def test_fila_con_derrame_no_se_copia():
    # el 20-oct TABLAS!BK2 era =UNIQUE(...): copiarlo habría bloqueado su derrame
    hoja = HojaFalsa({(2, col("BK")): "=UNIQUE(RESUMEN!BK:BK)"})
    assert m._extender_bloques_formulas(hoja, 7, None, [("BJ", "BK")], 37) == []


@pytest.mark.parametrize("formula", [
    '=IMPORTRANGE("https://docs.google.com/spreadsheets/d/ID/edit","DETALLE!GP:GR")',
    '=QUERY(RESUMEN!A:G,"select A,B",1)',
    "=FLATTEN(RESUMEN!A1:C3)",
    '=SPLIT(RESUMEN!A2,",")',
    "=SEQUENCE(10,1)",
])
def test_importrange_y_otras_formulas_que_se_derraman_no_se_copian(formula):
    # el 22-oct TABLAS!BR2 era un IMPORTRANGE de 3 columnas y el sync lo copió hasta la fila 37
    hoja = HojaFalsa({(2, col("BR")): formula}, col_count=73)
    assert m._extender_bloques_formulas(hoja, 7, None, [("BR", "BR")], 37) == []


def test_formula_por_fila_con_referencia_normal_sigue_extendiendose():
    hoja = HojaFalsa({(r, col("BR")): "=IFERROR(AVERAGEIFS(RESUMEN!$G:$G,RESUMEN!$E:$E,$BQ3),\"\")"
                      for r in range(2, 4)}, col_count=73)
    assert len(m._extender_bloques_formulas(hoja, 7, None, [("BR", "BR")], 8)) == 1


def test_bloque_fuera_de_la_hoja_se_omite():
    assert m._extender_bloques_formulas(HojaFalsa({}), 7, None, [("BR", "BR")], 37) == []


def test_columna_con_contenido_en_el_destino_se_omite():
    c = {(r, j): "=f" for r in range(3, 6) for j in range(col("B"), col("E") + 1)}
    c[(7, col("C"))] = "dato"
    peticiones = m._extender_bloques_formulas(HojaFalsa(c), 7, None, [("B", "E")], 8)
    tramos = sorted((p["copyPaste"]["source"]["startColumnIndex"], p["copyPaste"]["source"]["endColumnIndex"])
                    for p in peticiones)
    assert tramos == [(col("B"), col("C")), (col("D"), col("E") + 1)]


# --- pasos auxiliares ---------------------------------------------------------------------------

def test_un_paso_auxiliar_que_falla_se_avisa_y_no_detiene(capsys):
    llamados = []

    def falla():
        raise RuntimeError("boom")

    m._paso_auxiliar("PRUEBA", falla)
    m._paso_auxiliar("OK", lambda: llamados.append(1))
    assert llamados == [1]
    assert "::warning title=Maxinet Sync::PRUEBA no se pudo completar" in capsys.readouterr().out


# --- pestañas por nombre, alias o gid -----------------------------------------------------------

def _libro(*titulos):
    return Libro([HojaFalsa(titulo=t, gid=1000 + i) for i, t in enumerate(titulos)])


def test_resuelve_por_nombre_por_alias_y_por_gid():
    libro = _libro("FLOTA LP", "REPORTE DE FLOTA", "FLOTA POR GRUPO")
    assert m._resolver_pestana(libro, "REPORTE DE FLOTA").title == "REPORTE DE FLOTA"
    assert m._resolver_pestana(libro, "UTILIZACION V3").title == "REPORTE DE FLOTA"          # nombre de antes
    assert m._resolver_pestana(libro, "UTI. GRUPO DE AUTOS V1").title == "FLOTA POR GRUPO"
    assert m._resolver_pestana(libro, "1001").title == "REPORTE DE FLOTA"                       # gid


def test_pestana_inexistente_no_vuelca_el_inventario_en_los_logs():
    libro = _libro("FLOTA LP", "OTRA")
    with pytest.raises(gspread.exceptions.WorksheetNotFound) as error:
        m._resolver_pestana(libro, "REPORTE DE FLOTA")
    mensaje = str(error.value)
    assert "el libro tiene 2 pestañas" in mensaje
    assert "OTRA" not in mensaje  # el repositorio y sus logs son públicos


def test_nombres_por_defecto_y_listas_sin_pestanas_que_ya_no_existen():
    assert m.PESTANA_UTILIZACION == "REPORTE DE FLOTA"
    assert m.PESTANA_GRUPO_AUTOS == "FLOTA POR GRUPO"
    assert m.BLOQUES_FORMULAS_TABLERO == {}
    assert "GRAFICOS UTILIZACION" not in m.GRAFICOS_CRECIENTES["tablero"]
    m.mantener_formulas_tablero()  # sin bloques: no hace nada ni falla


def test_pestana_con_otro_acento_o_mayusculas_se_encuentra(caplog):
    from fakes import Libro
    libro = Libro([HojaFalsa(titulo="Duración retornos", gid=5)])
    with caplog.at_level("WARNING"):
        assert m._resolver_pestana(libro, "Duracion  RETORNOS").id == 5
    assert "se usa 'Duración retornos'" in caplog.text
    with pytest.raises(gspread.exceptions.WorksheetNotFound):
        m._resolver_pestana(libro, "Otra pestaña")
