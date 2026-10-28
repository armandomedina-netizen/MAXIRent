from datetime import date

import pytest

from mkt_sync.config import Config
from mkt_sync.errores import ErrorHoja
from mkt_sync.hoja import ORIGEN_SERIE, actualizar_mes, buscar_fila, parsear_periodo

CFG = Config(tablero_id=1, columna_estado="e", etiqueta_califica="c", columna_tipo="t", tipos_incluidos=("A",))


def serie(anio, mes):
    """Número de serie de Sheets del primer día del mes."""
    return (date(anio, mes, 1) - ORIGEN_SERIE).days


class HojaFalsa:
    """Pestaña simulada con la columna de periodos en F4:F y las celdas G/H de cada fila."""

    def __init__(self, periodos, celdas=None):
        self.periodos = periodos
        self.celdas = celdas or {}
        self.escrituras = []

    def get(self, rango, value_render_option=None):
        if rango.startswith("F4:F"):
            return [[p] if p is not None else [] for p in self.periodos]
        valor = self.celdas.get(rango)
        return [[valor]] if valor is not None else []

    def update(self, values, range_name, value_input_option=None):
        self.escrituras.append((range_name, values[0][0], value_input_option))


def test_la_serie_de_sheets_del_1_de_octubre_de_2026():
    assert serie(2026, 10) == 46296


def test_parsear_periodo_de_fecha_y_de_texto():
    assert parsear_periodo(46296) == (2026, 10)
    assert parsear_periodo(46296.0) == (2026, 10)
    assert parsear_periodo("oct 2026") == (2026, 10)
    assert parsear_periodo("Octubre 2026") == (2026, 10)
    assert parsear_periodo("sept. 2025") == (2025, 9)


@pytest.mark.parametrize("valor", [None, "", "total", "oct", "oct 26", "xyz 2026", True, 1e30])
def test_parsear_periodo_ignora_lo_que_no_es_periodo(valor):
    assert parsear_periodo(valor) is None


def test_buscar_fila_cuenta_desde_la_primera_fila_y_salta_vacios():
    periodos = [serie(2026, 8), None, serie(2026, 9), serie(2026, 10)]
    assert buscar_fila(periodos, 4, 2026, 10) == 7
    assert buscar_fila(periodos, 4, 2026, 8) == 4


def test_buscar_fila_falla_si_falta_o_esta_duplicada():
    with pytest.raises(ErrorHoja, match="agrega la fila"):
        buscar_fila([serie(2026, 9)], 4, 2026, 10)
    with pytest.raises(ErrorHoja, match="2 filas"):
        buscar_fila([serie(2026, 10), "oct 2026"], 4, 2026, 10)


def test_actualiza_solo_las_celdas_que_cambian():
    hoja = HojaFalsa([serie(2026, 9), serie(2026, 10)], {"G5": 123, "H5": 29})
    r = actualizar_mes(hoja, CFG, 2026, 10, 125, 29)
    assert (r.fila, r.antes, r.despues, r.escrito) == (5, (123, 29), (125, 29), True)
    assert hoja.escrituras == [("G5", 125, "RAW")]


def test_sin_cambios_no_escribe():
    hoja = HojaFalsa([serie(2026, 10)], {"G4": 125, "H4": 29})
    r = actualizar_mes(hoja, CFG, 2026, 10, 125, 29)
    assert not r.escrito and hoja.escrituras == []


def test_simular_no_escribe():
    hoja = HojaFalsa([serie(2026, 10)], {"G4": 1, "H4": 1})
    r = actualizar_mes(hoja, CFG, 2026, 10, 125, 29, simular=True)
    assert not r.escrito and hoja.escrituras == []


def test_celdas_vacias_se_llenan():
    hoja = HojaFalsa([serie(2026, 11)])
    r = actualizar_mes(hoja, CFG, 2026, 11, 3, 1)
    assert r.antes == (None, None) and hoja.escrituras == [("G4", 3, "RAW"), ("H4", 1, "RAW")]


def test_no_sobrescribe_formulas():
    hoja = HojaFalsa([serie(2026, 10)], {"G4": "=SUM(A1:A3)", "H4": 29})
    with pytest.raises(ErrorHoja, match="fórmula"):
        actualizar_mes(hoja, CFG, 2026, 10, 125, 29)
    assert hoja.escrituras == []


def test_un_cero_no_pisa_un_total_existente_salvo_que_se_fuerce():
    hoja = HojaFalsa([serie(2026, 10)], {"G4": 123, "H4": 29})
    with pytest.raises(ErrorHoja, match="0 leads"):
        actualizar_mes(hoja, CFG, 2026, 10, 0, 0)
    assert hoja.escrituras == []
    actualizar_mes(hoja, CFG, 2026, 10, 0, 0, forzar=True)
    assert [e[:2] for e in hoja.escrituras] == [("G4", 0), ("H4", 0)]


def test_cero_sobre_celda_vacia_es_valido():
    hoja = HojaFalsa([serie(2026, 11)])
    actualizar_mes(hoja, CFG, 2026, 11, 0, 0)
    assert [e[:2] for e in hoja.escrituras] == [("G4", 0), ("H4", 0)]
