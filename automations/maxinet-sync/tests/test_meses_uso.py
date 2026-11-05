"""Columna 'Meses uso' del reporte de flota (4-nov-2026): va en su propia columna de la base, fuera del bloque B:AP (sin red)."""
import pandas as pd
import pytest

import maxinet_sync as m
from tests.fakes import HojaFalsa, col


class HojaConLimpieza(HojaFalsa):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.limpiezas = []

    def batch_clear(self, rangos):
        self.limpiezas.append(rangos)


def _df(n=3):
    filas = [[f"c{c}r{i}" for c in range(len(m.COLUMNAS))] for i in range(n)]
    df = pd.DataFrame(filas, columns=m.COLUMNAS)
    df["Meses uso"] = [str(i) for i in range(n)]
    return df


def _base(encabezados):
    """Hoja con la fila 1 dada (letra -> encabezado)."""
    return HojaConLimpieza({(1, col(letra)): nombre for letra, nombre in encabezados.items()}, col_count=70)


# ---------------------------------------------------------------- estructura del reporte
def test_el_reporte_tiene_42_columnas_y_meses_uso_es_la_ultima():
    assert len(m.COLUMNAS) == 42 and m.COLUMNAS[-2:] == ["EntryDate", "Meses uso"]


def test_el_bloque_son_41_columnas_y_llena_exactamente_de_b_a_ap():
    assert len(m.COLUMNAS_BLOQUE) == 41 and m.COLUMNAS_BLOQUE[-1] == "EntryDate"
    assert "Meses uso" not in m.COLUMNAS_BLOQUE
    assert col(m.COL_INICIO) + len(m.COLUMNAS_BLOQUE) - 1 == col(m.COL_FIN)


# ---------------------------------------------------------------- el bloque no incluye la columna nueva
def test_actualizar_sheet_escribe_solo_el_bloque_b_ap():
    hoja = HojaConLimpieza(col_count=70)
    m.actualizar_sheet(hoja, _df(3))
    rango, valores = hoja.escrituras[-1]
    assert rango == "B2:AP4"
    assert all(len(f) == 41 for f in valores) and valores[0][-1] == "c40r0"
    assert hoja.limpiezas == [["B2:AP5002"]]


# ---------------------------------------------------------------- columna fuera del bloque
def test_meses_uso_se_escribe_en_la_columna_con_ese_encabezado_alineado_con_el_bloque():
    hoja = _base({"AP": "EntryDate", "AQ": "STATUS DISPONIBLE", "AS": "TIPO DE CUENTA LP", "AT": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(3))
    assert hoja.limpiezas == [["AT2:AT5002"]]
    assert hoja.escrituras == [("AT2:AT4", [[0], [1], [2]])]


def test_el_encabezado_se_reconoce_sin_importar_mayusculas_ni_espacios():
    hoja = _base({"AT": "  meses USO "})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(1))
    assert hoja.escrituras[0][0] == "AT2:AT2"


def test_si_la_columna_se_mueve_el_sync_la_sigue_por_el_encabezado():
    hoja = _base({"AU": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert hoja.escrituras[0][0] == "AU2:AU3"


def test_sin_encabezado_no_escribe_nada_y_explica_que_hacer():
    hoja = _base({"AP": "EntryDate", "AQ": "STATUS DISPONIBLE"})
    with pytest.raises(RuntimeError, match="Meses uso"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_nunca_escribe_dentro_del_bloque_b_ap():
    hoja = _base({"AP": "Meses uso"})
    with pytest.raises(RuntimeError, match="dentro de A:AP"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_no_pisa_una_columna_que_tiene_formulas():
    hoja = _base({"AT": "Meses uso"})
    hoja.c[(2, col("AT"))] = '=IF(AP2="","",1)'
    with pytest.raises(RuntimeError, match="tiene fórmulas"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_un_valor_vacio_se_escribe_vacio_y_no_como_nan():
    df = _df(2)
    df.loc[1, "Meses uso"] = None
    hoja = _base({"AT": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, df)
    assert hoja.escrituras[0][1] == [[0], [""]]


@pytest.mark.parametrize("valor,esperado", [("159", 159), (" 7 ", 7), ("12.50", 12.5), ("0", 0), ("", ""), (None, ""), ("n/d", "n/d")])
def test_las_medidas_fuera_del_bloque_se_guardan_como_numero(valor, esperado):
    resultado = m._numero_o_texto(valor)
    assert resultado == esperado and type(resultado) is type(esperado)
