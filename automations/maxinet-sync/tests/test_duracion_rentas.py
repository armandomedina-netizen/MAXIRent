"""Duración de rentas en dos pestañas ('Duracion de rentas' = ACTIVAS y 'Duración retornos'): filas por etiqueta,
lista ON HIRE matricial intacta, congelado del mes que cierra y devoluciones nuevas."""
import logging
from datetime import date

import pytest

import maxinet_sync as m
from fakes import HojaFalsa, col

ETIQ_ACTIVAS = "TIEMPO DE VIDA (ACTIVAS)"
ETIQ_RETORNOS = "TIEMPO DE VIDA (RETORNOS)"
ENCABEZADOS = ["UNIFICADO", "Reg No", "PU Date", "Return Date", "DIA", "MES", "Status", "Name", "EJECUTIVO",
               "GRUPO", "MODELO", "PERIODO", "TARIFA DIARIA (SIN IVA)", "MENSUAL"]
VIVA_OCT = '=AVERAGEIFS($F8:$F,$L8:$L,K$5,$G8:$G,"on hire")'


class HojaDoble(HojaFalsa):
    """Fórmulas en `c` y, para UNFORMATTED_VALUE, los valores calculados que se pasen en `valores`."""

    def __init__(self, formulas, valores=None, **kw):
        super().__init__(formulas, **kw)
        self.valores = valores or {}

    def get(self, rango, value_render_option=None):
        if value_render_option == "UNFORMATTED_VALUE" and self.valores:
            original = self.c
            self.c = {**original, **self.valores}
            try:
                return super().get(rango, value_render_option)
            finally:
                self.c = original
        return super().get(rango, value_render_option)


def _meses(fila, primer_serial):
    return {(fila, 1 + i): primer_serial + 30 * i for i in range(12)}


def _activas(mes_vivo="K", meses_vivos=("K",), con_2026=True, on_hire=((10, "ON HIRE"), (20, "ON HIRE"), (30, "ON HIRE"))):
    """Réplica del diseño real: 2025 en filas 2-3, 2026 en 5-6, encabezados en la fila 8 y la matricial en A9."""
    c = {(1, 0): "MENU PRINCIPAL", (2, 0): 2025, (3, 0): ETIQ_ACTIVAS, (8, 0): "UNIFICADO", (8, 1): "Reg No"}
    c.update(_meses(2, 45658))
    c.update({(3, 1 + i): 7.0 for i in range(12)})
    if con_2026:
        c.update({(5, 0): 2026, (6, 0): ETIQ_ACTIVAS})
        c.update(_meses(5, 46023))
        for i in range(12):
            letra = chr(66 + i)
            if letra in meses_vivos:
                c[(6, 1 + i)] = VIVA_OCT.replace("K$5", f"{letra}$5")
            elif letra < mes_vivo:
                c[(6, 1 + i)] = 6.5
    c[(9, 0)] = m.formula_on_hire_desde_tarifa_detalle("IDQUERY")
    for i, (mes, status) in enumerate(on_hire):
        c[(9 + i, 1)] = f"PL{i}"
        c[(9 + i, col("F"))] = mes
        c[(9 + i, col("G"))] = status
    return HojaDoble(c, titulo="Duracion de rentas")


def _retornos(retornos=((300, "AAA"), (305, "BBB"), (315, "CCC")), mes_vivo="K"):
    """Réplica del diseño real: 2024-2026 en filas 2-9, encabezados en la fila 11 y el detalle desde la 12."""
    c = {(1, 0): "MENU PRINCIPAL", (11, 0): "UNIFICADO", (11, 1): "Reg No"}
    for fila_meses, anio in ((2, 2024), (5, 2025), (8, 2026)):
        c[(fila_meses, 0)] = anio
        c[(fila_meses + 1, 0)] = ETIQ_RETORNOS
        c.update(_meses(fila_meses, 45292))
        for i in range(12):
            letra = chr(66 + i)
            if anio < 2026 or letra <= mes_vivo:
                c[(fila_meses + 1, 1 + i)] = (
                    f'=IFERROR(AVERAGEIFS($F$11:$F,$L$11:$L,{letra}{fila_meses},$G$11:$G,"RETURNED"),0)')
    for i, (retorno, placa) in enumerate(retornos):
        f = 12 + i
        c.update({(f, 0): f"UNIF {placa}", (f, 1): placa, (f, 2): retorno - 100, (f, 3): retorno,
                  (f, 4): f"=D{f}-C{f}", (f, 5): f"=E{f}/30", (f, 6): "RETURNED", (f, 7): f"CLIENTE {placa}",
                  (f, 8): "EJ", (f, 9): "G", (f, 10): "M", (f, 11): 46296, (f, 12): 1000, (f, 13): f"=M{f}*MIN(E{f},30)"})
    return HojaFalsa(c, titulo="Duración retornos")


# --- diseño: filas por etiqueta -------------------------------------------------------------

def test_formula_lee_tarifa_detalle_sin_pestanas_intermedias():
    formula = m.formula_on_hire_desde_tarifa_detalle("IDQUERY")
    assert formula.startswith("=ARRAYFORMULA(LET(")
    assert "IMPORTRANGE" in formula and "IDQUERY" in formula
    assert "'TARIFA DETALLE'!A2:AA" in formula
    assert "Rentas activas detalle" not in formula
    assert formula.count("ON HIRE") == 1


def test_encabezado_del_detalle_se_busca_por_sus_titulos():
    assert m._fila_encabezado_detalle(_activas()) == 8
    assert m._fila_encabezado_detalle(_retornos()) == 11
    with pytest.raises(LookupError):
        m._fila_encabezado_detalle(HojaFalsa({(1, 0): "otra cosa"}))


def test_bloques_de_anio_por_etiqueta():
    assert m._bloques_por_anio(_activas(), m.ETIQUETA_ACTIVAS) == {2025: (2, 3), 2026: (5, 6)}
    assert m._bloques_por_anio(_retornos(), m.ETIQUETA_RETORNOS) == {2024: (2, 3), 2025: (5, 6), 2026: (8, 9)}
    # sin el año en A o sin la etiqueta debajo no es un bloque
    assert m._bloques_por_anio(HojaFalsa({(2, 0): "Total", (3, 0): ETIQ_ACTIVAS}), m.ETIQUETA_ACTIVAS) == {}


def test_nombres_por_defecto_son_los_de_las_dos_pestanas():
    assert m.PESTANA_DURACION_ACTIVAS == "Duracion de rentas"
    assert m.PESTANA_DURACION_RETORNOS == "Duración retornos"


# --- lista ON HIRE: el sync no la toca ------------------------------------------------------

def test_lista_on_hire_matricial_se_verifica_sin_escribir():
    hoja = _activas()
    assert m.verificar_lista_on_hire(hoja) == 3
    assert hoja.escrituras == []


def test_lista_on_hire_sin_formula_avisa(caplog):
    hoja = _activas()
    del hoja.c[(9, 0)]
    with caplog.at_level(logging.WARNING):
        assert m.verificar_lista_on_hire(hoja) == 0
    assert "no hay fórmula matricial" in caplog.text
    assert hoja.escrituras == []


def test_lista_on_hire_con_error_avisa(caplog):
    hoja = _activas()
    hoja.valores = {(9, 0): "#REF!"}
    with caplog.at_level(logging.WARNING):
        assert m.verificar_lista_on_hire(hoja) == 0
    assert "da error (#REF!)" in caplog.text


# --- ACTIVAS: congelar el mes que cierra -----------------------------------------------------

def test_mes_en_curso_con_formula_viva_no_escribe_nada():
    hoja = _activas()
    m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 10, 22))
    assert hoja.escrituras == []


def test_cambio_de_mes_congela_octubre_con_el_promedio_de_la_lista_y_crea_noviembre():
    hoja = _activas()
    m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 11, 1))
    assert hoja.escrituras == [
        ("K6", [[20.0]]),   # promedio de MES (10, 20, 30) de las tres rentas ON HIRE
        ("L6", [['=AVERAGEIFS($F8:$F,$L8:$L,L$5,$G8:$G,"on hire")']]),
    ]


def test_formula_nueva_es_igual_a_la_que_ya_usa_el_tablero():
    hoja = _activas()
    m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 11, 1))
    assert hoja.escrituras[1][1][0][0] == VIVA_OCT.replace("K$5", "L$5")


def test_las_rentas_que_no_estan_on_hire_no_cuentan_en_el_promedio():
    hoja = _activas(on_hire=((10, "ON HIRE"), (50, "RETURNED"), (30, "ON HIRE")))
    m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 11, 1))
    assert hoja.escrituras[0] == ("K6", [[20.0]])


def test_sin_rentas_on_hire_no_se_congela_en_cero(caplog):
    hoja = _activas(on_hire=())
    with caplog.at_level(logging.WARNING):
        m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 11, 1))
    assert all(rango != "K6" for rango, _ in hoja.escrituras)
    assert "no se congela" in caplog.text


def test_mes_mas_viejo_con_formula_no_se_inventa(caplog):
    hoja = _activas(meses_vivos=("J", "K"))
    with caplog.at_level(logging.WARNING):
        m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 11, 1))
    rangos = [rango for rango, _ in hoja.escrituras]
    assert "J6" not in rangos and "K6" in rangos
    assert "resolverlo a mano" in caplog.text


def test_cambio_de_anio_congela_diciembre_y_avisa_si_falta_el_bloque_nuevo(caplog):
    hoja = _activas(mes_vivo="M", meses_vivos=("M",))
    with caplog.at_level(logging.WARNING):
        m.avanzar_activas_duracion_rentas(hoja, hoy=date(2027, 1, 1))
    assert hoja.escrituras == [("M6", [[20.0]])]
    assert "no hay bloque del año 2027" in caplog.text


def test_si_el_equipo_ya_creo_el_mes_nuevo_solo_se_congela_el_anterior():
    hoja = _activas(meses_vivos=("K", "L"))
    m.avanzar_activas_duracion_rentas(hoja, hoy=date(2026, 11, 1))
    assert hoja.escrituras == [("K6", [[20.0]])]


# --- RETORNOS: fórmula del mes en curso -----------------------------------------------------

def test_retornos_crea_la_formula_del_mes_nuevo():
    hoja = _retornos()
    m.completar_retornos_mes_duracion_rentas(hoja, hoy=date(2026, 11, 2))
    assert hoja.escrituras == [
        ("L9", [['=IFERROR(AVERAGEIFS($F$11:$F,$L$11:$L,L8,$G$11:$G,"RETURNED"),0)']])]


def test_retornos_no_toca_un_mes_que_ya_tiene_formula():
    hoja = _retornos()
    m.completar_retornos_mes_duracion_rentas(hoja, hoy=date(2026, 10, 22))
    assert hoja.escrituras == []


def test_retornos_avisa_si_no_hay_bloque_del_anio(caplog):
    hoja = _retornos()
    with caplog.at_level(logging.WARNING):
        m.completar_retornos_mes_duracion_rentas(hoja, hoy=date(2027, 1, 4))
    assert hoja.escrituras == [] and "no hay bloque del año 2027" in caplog.text


# --- RETORNOS: devoluciones nuevas -----------------------------------------------------------

def _maxinet(placa, pu, retorno, estatus="RETURNED", efecto="SI APLICA", cliente="CLI"):
    fila = [""] * 15
    fila[m.IDX_RER_CLIENTE], fila[m.IDX_RER_ESTATUS], fila[m.IDX_RER_PU] = cliente, estatus, pu
    fila[m.IDX_RER_RETORNO], fila[m.IDX_RER_EFECTO], fila[m.IDX_RER_PLACA] = retorno, efecto, placa
    fila[m.IDX_RER_GRUPO], fila[m.IDX_RER_MODELO] = "G1", "MOD"
    return fila


def _serial(texto):
    return m._a_serial(texto)


@pytest.fixture
def hoja_retornos():
    base = _serial("2026-10-15")
    return _retornos(retornos=((base, "AAA"), (base + 3, "BBB"), (base + 5, "CCC")))


def _con_maxinet(monkeypatch, retornos):
    monkeypatch.setattr(m, "descargar_entregas_retornos", lambda s, d, h, tipo: retornos if tipo == "RETORNOS" else [])


def test_devolucion_nueva_se_agrega_al_final_con_ejecutivo_y_tarifa_del_historial(monkeypatch, hoja_retornos):
    pu = _serial("2026-09-01")
    historial = {("NEW1", pu): ["NEW1", pu, "UNIF NEW", "CLI", "EJECUTIVO X", 1500.0, 46318]}
    _con_maxinet(monkeypatch, [_maxinet("NEW1", "2026-09-01", "2026-10-21")])
    nuevas = m.actualizar_detalle_retornos(hoja_retornos, None, historial, hoy=date(2026, 10, 22))
    assert len(nuevas) == 1
    peticion = hoja_retornos.spreadsheet.peticiones[0]["insertDimension"]["range"]
    assert (peticion["startIndex"], peticion["endIndex"]) == (14, 15)   # fila 15, justo debajo de la última (14)
    rango, valores = hoja_retornos.escrituras[0]
    assert rango == "A15:N15"
    fila = valores[0]
    assert fila[:4] == ["UNIF NEW", "NEW1", pu, _serial("2026-10-21")]
    assert fila[4:6] == ["=D15-C15", "=E15/30"] and fila[13] == "=M15*MIN(E15,30)"
    assert fila[6:13] == ["RETURNED", "CLI", "EJECUTIVO X", "G1", "MOD", _serial("2026-10-01"), 1500.0]


def test_devolucion_ya_cargada_o_no_devuelta_no_se_agrega(monkeypatch, hoja_retornos):
    base = _serial("2026-10-15")
    ya = _maxinet("CCC", "2026-06-01", "2026-10-20")          # misma placa y retorno que la fila 14
    ya[m.IDX_RER_RETORNO] = "2026-10-20"
    activa = _maxinet("DDD", "2026-10-01", "2026-10-21", estatus="ON HIRE")
    sin_efecto = _maxinet("EEE", "2026-09-01", "2026-10-21", efecto="NO APLICA")
    _con_maxinet(monkeypatch, [ya, activa, sin_efecto])
    assert m.actualizar_detalle_retornos(hoja_retornos, None, {}, hoy=date(2026, 10, 22)) == []
    assert hoja_retornos.escrituras == [] and hoja_retornos.spreadsheet.peticiones == []


def test_devolucion_tardia_se_inserta_en_su_lugar_por_fecha(monkeypatch, hoja_retornos):
    # retorno del 18-oct: entre BBB (18-oct) y CCC (20-oct) -> después de BBB, fila 14
    _con_maxinet(monkeypatch, [_maxinet("LATE", "2026-09-10", "2026-10-19")])
    m.actualizar_detalle_retornos(hoja_retornos, None, {}, hoy=date(2026, 10, 22))
    peticion = hoja_retornos.spreadsheet.peticiones[0]["insertDimension"]["range"]
    assert (peticion["startIndex"], peticion["endIndex"]) == (13, 14)
    assert hoja_retornos.escrituras[0][0] == "A14:N14"


def test_devolucion_sin_historial_se_agrega_incompleta_y_avisa(monkeypatch, hoja_retornos, caplog):
    _con_maxinet(monkeypatch, [_maxinet("NEW2", "2026-09-01", "2026-10-21")])
    with caplog.at_level(logging.WARNING):
        m.actualizar_detalle_retornos(hoja_retornos, None, {}, hoy=date(2026, 10, 22))
    assert "sin ejecutivo o tarifa" in caplog.text
    assert hoja_retornos.escrituras[0][1][0][8] == ""


def test_aplicar_false_solo_calcula(monkeypatch, hoja_retornos):
    _con_maxinet(monkeypatch, [_maxinet("NEW3", "2026-09-01", "2026-10-21")])
    assert len(m.actualizar_detalle_retornos(hoja_retornos, None, {}, hoy=date(2026, 10, 22), aplicar=False)) == 1
    assert hoja_retornos.escrituras == [] and hoja_retornos.spreadsheet.peticiones == []
