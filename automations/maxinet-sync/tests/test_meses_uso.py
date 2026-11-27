"""Columnas del reporte de flota fuera del bloque B:AP: 'Meses uso' (4-nov-2026) y las siete de precio y depreciación (26-nov-2026); cada una va en su propia columna de la base (sin red)."""
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
    for k, nombre in enumerate(NUEVAS):
        df[nombre] = [f"{1000 * (k + 1) + i}.50" for i in range(n)]
    return df


NUEVAS = ["Precio Compra", "MOI (sin iva)", "Precio caja", "Total MOI", "Dep. Mensual", "Dep. Acumulada", "Remanente ajustado 14%"]
LETRAS_NUEVAS = ["BO", "BP", "BQ", "BR", "BS", "BT", "BU"]


def _base(encabezados, con_nuevas=True):
    """Hoja con la fila 1 dada (letra -> encabezado). Por omisión también trae las siete columnas nuevas en BO:BU."""
    if con_nuevas:
        encabezados = {**dict(zip(LETRAS_NUEVAS, NUEVAS)), **encabezados}
    return HojaConLimpieza({(1, col(letra)): nombre for letra, nombre in encabezados.items()}, col_count=75)


# ---------------------------------------------------------------- estructura del reporte
def test_el_reporte_tiene_49_columnas_y_las_siete_nuevas_son_las_ultimas():
    assert len(m.COLUMNAS) == 49 and m.COLUMNAS[40:42] == ["EntryDate", "Meses uso"] and m.COLUMNAS[-7:] == NUEVAS


def test_todas_las_columnas_fuera_del_bloque_existen_en_el_reporte():
    assert m.COLUMNAS_FUERA_DE_BLOQUE == ("Meses uso", *NUEVAS) and set(m.COLUMNAS_FUERA_DE_BLOQUE) <= set(m.COLUMNAS)


def test_el_bloque_son_41_columnas_y_llena_exactamente_de_b_a_ap():
    assert len(m.COLUMNAS_BLOQUE) == 41 and m.COLUMNAS_BLOQUE[-1] == "EntryDate"
    assert "Meses uso" not in m.COLUMNAS_BLOQUE and not set(NUEVAS) & set(m.COLUMNAS_BLOQUE)
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
def _escrito(hoja, rango):
    return dict(hoja.escrituras).get(rango)


def test_meses_uso_se_escribe_en_la_columna_con_ese_encabezado_alineado_con_el_bloque():
    hoja = _base({"AP": "EntryDate", "AQ": "STATUS DISPONIBLE", "AS": "TIPO DE CUENTA LP", "AT": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(3))
    assert ["AT2:AT5002"] in hoja.limpiezas
    assert _escrito(hoja, "AT2:AT4") == [[0], [1], [2]]


def test_el_encabezado_se_reconoce_sin_importar_mayusculas_ni_espacios():
    hoja = _base({"AT": "  meses USO "})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(1))
    assert _escrito(hoja, "AT2:AT2") == [[0]]


def test_si_la_columna_se_mueve_el_sync_la_sigue_por_el_encabezado():
    hoja = _base({"AU": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert _escrito(hoja, "AU2:AU3") == [[0], [1]]


def test_sin_encabezado_no_escribe_esa_columna_y_explica_que_hacer():
    hoja = _base({"AP": "EntryDate", "AQ": "STATUS DISPONIBLE"}, con_nuevas=False)
    with pytest.raises(RuntimeError, match="Meses uso"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_nunca_escribe_dentro_del_bloque_b_ap():
    hoja = _base({"AP": "Meses uso"})
    with pytest.raises(RuntimeError, match="dentro de A:AP"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert _escrito(hoja, "AP2:AP3") is None and not any(r.startswith("AP") for rangos in hoja.limpiezas for r in rangos)


def test_no_pisa_una_columna_que_tiene_formulas():
    hoja = _base({"AT": "Meses uso"})
    hoja.c[(2, col("AT"))] = '=IF(AP2="","",1)'
    with pytest.raises(RuntimeError, match="tiene fórmulas"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert _escrito(hoja, "AT2:AT3") is None and ["AT2:AT5002"] not in hoja.limpiezas


def test_un_valor_vacio_se_escribe_vacio_y_no_como_nan():
    df = _df(2)
    df.loc[1, "Meses uso"] = None
    hoja = _base({"AT": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, df)
    assert _escrito(hoja, "AT2:AT3") == [[0], [""]]


@pytest.mark.parametrize("valor,esperado", [("159", 159), (" 7 ", 7), ("12.50", 12.5), ("0", 0), ("", ""), (None, ""), ("n/d", "n/d")])
def test_las_medidas_fuera_del_bloque_se_guardan_como_numero(valor, esperado):
    resultado = m._numero_o_texto(valor)
    assert resultado == esperado and type(resultado) is type(esperado)


# ---------------------------------------------------------------- las siete columnas de precio y depreciación (26-nov-2026)
def test_las_siete_columnas_nuevas_se_escriben_cada_una_en_su_encabezado_como_numero():
    hoja = _base({"AT": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    for k, letra in enumerate(LETRAS_NUEVAS):
        assert _escrito(hoja, f"{letra}2:{letra}3") == [[1000.5 * 0 + (1000 * (k + 1)) + 0.5], [(1000 * (k + 1)) + 1.5]]
        assert [f"{letra}2:{letra}5002"] in hoja.limpiezas
    assert len(hoja.escrituras) == 8                                            # Meses uso + las siete


def test_los_valores_del_reporte_que_vienen_como_texto_o_como_numero_quedan_como_numero():
    df = _df(3)
    df["Precio Compra"] = ["513360.00", "0.00", None]            # Maxinet manda este campo como texto
    df["Total MOI"] = [442551.72, 0, "-259028.59"]               # y otros como número (o negativos como texto)
    hoja = _base({"AT": "Meses uso"})
    m.actualizar_columnas_fuera_del_bloque(hoja, df)
    assert _escrito(hoja, "BO2:BO4") == [[513360], [0], [""]] and type(_escrito(hoja, "BO2:BO4")[0][0]) is int
    assert _escrito(hoja, "BR2:BR4") == [[442551.72], [0], [-259028.59]]


def test_sin_los_encabezados_nuevos_meses_uso_si_se_escribe_y_el_aviso_nombra_las_siete():
    hoja = _base({"AT": "Meses uso"}, con_nuevas=False)
    with pytest.raises(RuntimeError) as e:
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    assert _escrito(hoja, "AT2:AT3") == [[0], [1]]               # lo que sí tiene encabezado se escribe
    assert len(hoja.escrituras) == 1
    texto = str(e.value)
    assert all(f"'{n}'" in texto for n in NUEVAS) and "'Meses uso'" not in texto


def test_un_encabezado_con_formulas_o_dentro_del_bloque_no_impide_escribir_los_demas():
    hoja = _base({"AT": "Meses uso", "BO": "Precio Compra"})
    hoja.c[(2, col("BP"))] = '=A2*2'                              # BP 'MOI (sin iva)' ya tiene fórmulas
    with pytest.raises(RuntimeError, match="tiene fórmulas"):
        m.actualizar_columnas_fuera_del_bloque(hoja, _df(2))
    escritos = {rango for rango, _ in hoja.escrituras}
    assert "BP2:BP3" not in escritos and {"AT2:AT3", "BO2:BO3", "BQ2:BQ3", "BU2:BU3"} <= escritos


def test_las_columnas_nuevas_no_entran_al_bloque_ni_cambian_su_rango():
    hoja = HojaConLimpieza(col_count=75)
    m.actualizar_sheet(hoja, _df(2))
    rango, valores = hoja.escrituras[-1]
    assert rango == "B2:AP3" and all(len(f) == 41 for f in valores)
