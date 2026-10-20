"""Lista ON HIRE de 'Duración rentas': fórmula matricial y funciones que no deben pisar su derrame."""
import maxinet_sync as m
from fakes import HojaFalsa


def _hoja_con_detalle(ancla_a=None, ancla_b=None):
    """Tres devoluciones (filas 15-17) y, en la fila 18, el ancla de la lista ON HIRE."""
    c = {(14, 1): "Reg No", (14, 6): "Status"}
    for i, placa in enumerate(("AAA", "BBB", "CCC")):
        fila = 15 + i
        c[(fila, 1)] = placa
        c[(fila, 6)] = "RETURNED"
        c[(fila, 4)] = f'=IF(B{fila}="","",D{fila}-C{fila})'
    if ancla_a:
        c[(18, 0)] = ancla_a
    if ancla_b:
        c[(18, 1)] = ancla_b
    # filas que derrama la fórmula matricial (valores, no fórmulas)
    c[(18, 1)] = c.get((18, 1), "DDD")
    c[(18, 6)] = "ON HIRE"
    c[(18, 4)] = 123
    c[(19, 1)] = "EEE"
    c[(19, 6)] = "ON HIRE"
    c[(19, 4)] = 99
    return HojaFalsa(c)


def test_formula_lee_tarifa_detalle_sin_pestanas_intermedias():
    formula = m.formula_on_hire_desde_tarifa_detalle("IDQUERY")
    assert formula.startswith("=ARRAYFORMULA(LET(")
    assert "IMPORTRANGE" in formula and "IDQUERY" in formula
    assert "'TARIFA DETALLE'!A2:AA" in formula
    assert "Rentas activas detalle" not in formula
    assert formula.count("ON HIRE") == 1


def test_localiza_el_bloque_matricial():
    hoja = _hoja_con_detalle(ancla_a=m.formula_on_hire_desde_tarifa_detalle("X"))
    assert m._localizar_on_hire(hoja) == (18, "matricial")


def test_localiza_el_diseno_anterior_por_fila():
    hoja = _hoja_con_detalle(ancla_b="=UNIQUE('Otra'!A4:A)")
    assert m._localizar_on_hire(hoja) == (18, "por_fila")


def test_sin_bloque_on_hire():
    hoja = HojaFalsa({(14, 1): "Reg No", (15, 1): "AAA", (15, 6): "RETURNED"})
    assert m._localizar_on_hire(hoja) == (None, None)


def test_dia_no_se_escribe_en_las_filas_derramadas():
    hoja = _hoja_con_detalle(ancla_a=m.formula_on_hire_desde_tarifa_detalle("X"))
    m.avanzar_formula_dia_duracion_rentas(hoja)
    assert hoja.escrituras == []


def test_dia_del_diseno_anterior_se_corrige_igual_que_antes():
    hoja = _hoja_con_detalle(ancla_b="=UNIQUE('Otra'!A4:A)")
    hoja.c[(18, 4)] = '=IF(B18="","",D18-C18)'
    m.avanzar_formula_dia_duracion_rentas(hoja)
    assert hoja.escrituras and "TODAY()-C18" in str(hoja.escrituras[0][1])


def test_periodo_on_hire_lo_calcula_la_formula_matricial():
    hoja = _hoja_con_detalle(ancla_a=m.formula_on_hire_desde_tarifa_detalle("X"))
    m._avanzar_periodo_on_hire(hoja, m._hoy_cdmx())
    assert hoja.escrituras == []
