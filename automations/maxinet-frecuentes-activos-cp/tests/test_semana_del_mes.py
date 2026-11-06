"""Modo "semana N del mes" de Clientes Frecuentes: elección del tercer sábado y congelamiento (sin red)."""
import pytest

import maxinet_frecuentes_activos_cp as m

# Fragmento real del selector (id, etiqueta), con los cortes irregulares de fin de mes
SELECTOR = [("195", "2026-10-24"), ("194", "2026-10-17"), ("193", "2026-10-10"), ("192", "2026-10-03"),
            ("191", "2026-09-26"), ("190", "2026-09-19"), ("189", "2026-09-12"), ("188", "2026-09-05"),
            ("187", "2026-09-04"), ("186", "2026-08-31"), ("185", "2026-08-29"), ("184", "2026-08-22"),
            ("183", "2026-08-15"), ("182", "2026-08-08"), ("177", "2026-08-01")]


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for v in ("SEMANA_DEL_MES", "WORKSHEET_FRECUENTES_NAME", "PERIODO", "FORZAR", "DRY_RUN"):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------- qué semana es la 3
def test_la_semana_3_es_la_del_tercer_sabado_de_su_mes_mas_reciente():
    assert m.semana_n_del_mes(SELECTOR, 3) == ("194", "2026-10-17")           # 3, 10 y 17 de octubre


def test_antes_de_que_se_publique_la_del_mes_en_curso_se_queda_la_anterior():
    sin_octubre = [s for s in SELECTOR if not s[1].startswith("2026-10-1") and s[1] != "2026-10-24"]
    assert m.semana_n_del_mes(sin_octubre, 3) == ("190", "2026-09-19")


def test_otras_semanas_del_mes_y_ninguna_cuando_no_hay():
    assert m.semana_n_del_mes(SELECTOR, 1) == ("192", "2026-10-03")
    assert m.semana_n_del_mes(SELECTOR, 2) == ("193", "2026-10-10")
    assert m.semana_n_del_mes(SELECTOR, 4) == ("195", "2026-10-24")
    assert m.semana_n_del_mes([("186", "2026-08-31"), ("187", "2026-09-04")], 3) is None     # no son sábados


def test_los_cortes_irregulares_no_cuentan_aunque_caigan_en_la_semana_3():
    assert m.semana_n_del_mes([("1", "2026-01-07"), ("2", "2026-01-16"), ("3", "2026-01-17")], 3) == ("3", "2026-01-17")
    assert m.semana_n_del_mes([("1", "2026-01-16")], 3) is None                                 # viernes


@pytest.mark.parametrize("fecha,n", [("2026-11-21", 3), ("2026-12-19", 3), ("2026-02-21", 3), ("2026-05-16", 3), ("2026-05-02", 1), ("2026-05-30", 5)])
def test_el_enesimo_sabado_de_cada_mes(fecha, n):
    assert m.semana_n_del_mes([("9", fecha)], n) == ("9", fecha)


@pytest.mark.parametrize("fecha,n", [("2026-11-14", 3), ("2026-11-28", 3), ("2026-12-12", 3), ("2026-12-26", 3)])
def test_el_sabado_de_otra_semana_no_es_la_n(fecha, n):
    assert m.semana_n_del_mes([("9", fecha)], n) is None


# ---------------------------------------------------------------- configuración
def test_semana_del_mes_se_lee_y_valida(monkeypatch):
    assert m.semana_del_mes() is None
    monkeypatch.setenv("SEMANA_DEL_MES", " 3 ")
    assert m.semana_del_mes() == 3
    for malo in ("0", "6", "tres", "-1"):
        monkeypatch.setenv("SEMANA_DEL_MES", malo)
        with pytest.raises(RuntimeError, match="SEMANA_DEL_MES"):
            m.semana_del_mes()


def test_el_nombre_por_defecto_nunca_cae_en_la_pestana_de_la_semana_mas_reciente(monkeypatch):
    assert m._nombre_pestana("WORKSHEET_FRECUENTES_NAME") == "Clientes Frecuentes Activos 35"
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    assert m._nombre_pestana("WORKSHEET_FRECUENTES_NAME") == "Clientes frecuentes Semana 3"
    monkeypatch.setenv("WORKSHEET_FRECUENTES_NAME", ' "473185" ')
    assert m._nombre_pestana("WORKSHEET_FRECUENTES_NAME") == "473185"


# ---------------------------------------------------------------- congelamiento
class Hoja:
    pass


@pytest.fixture
def maxinet(monkeypatch):
    descargas = []
    monkeypatch.setattr(m, "info_maxinet", lambda: (["Sucursal"], SELECTOR))
    monkeypatch.setattr(m, "descargar_semana", lambda periodo, n: descargas.append(periodo) or [["LT"]])
    return descargas


def test_si_la_semana_ya_esta_cargada_no_descarga_nada_y_queda_congelada(monkeypatch, maxinet):
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setattr(m, "leer_estado", lambda ws: ("194", "2026-10-17"))
    assert m.elegir_semana(Hoja()) is None and maxinet == []


def test_si_la_hoja_trae_otra_semana_descarga_la_tercera(monkeypatch, maxinet):
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setattr(m, "leer_estado", lambda ws: ("195", "2026-10-24"))             # la clonada trae la más reciente
    assert m.elegir_semana(Hoja()) == (["Sucursal"], [["LT"]], "194", "2026-10-17") and maxinet == ["194"]


def test_una_hoja_sin_registro_de_semana_tambien_se_carga(monkeypatch, maxinet):
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setattr(m, "leer_estado", lambda ws: None)
    assert m.elegir_semana(Hoja())[2] == "194"


def test_forzar_refresca_aunque_ya_este_cargada(monkeypatch, maxinet):
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setenv("FORZAR", "1")
    monkeypatch.setattr(m, "leer_estado", lambda ws: ("194", "2026-10-17"))
    assert m.elegir_semana(Hoja())[2] == "194" and maxinet == ["194"]


def test_periodo_fijo_manda_sobre_la_regla(monkeypatch, maxinet):
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setenv("PERIODO", "193")
    assert m.elegir_semana(Hoja())[2:] == ("193", "2026-10-10") and maxinet == ["193"]


def test_sin_semana_del_mes_el_modo_normal_sigue_igual(monkeypatch, maxinet):
    monkeypatch.setattr(m, "leer_estado", lambda ws: ("195", "2026-10-24"))
    assert m.elegir_semana(Hoja())[2:] == ("195", "2026-10-24") and maxinet == ["195"]       # sin congelar


def test_si_el_selector_no_tiene_la_semana_falla_con_mensaje_claro(monkeypatch):
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setattr(m, "info_maxinet", lambda: (["Sucursal"], [("186", "2026-08-31")]))
    with pytest.raises(RuntimeError, match="ninguna semana 3 del mes"):
        m.elegir_semana(Hoja())


def test_main_registra_que_esta_congelada_y_no_escribe(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("SEMANA_DEL_MES", "3")
    monkeypatch.setattr(m, "conectar_sheet", lambda: Hoja())
    monkeypatch.setattr(m, "elegir_semana", lambda ws: None)
    monkeypatch.setattr(m, "leer_estado", lambda ws: ("194", "2026-10-17"))
    monkeypatch.setattr(m, "sincronizar", lambda *a, **k: pytest.fail("no debe escribir"))
    with caplog.at_level(logging.INFO):
        m.main()
    assert "congelada" in caplog.text and "completada con éxito (semana 194, 2026-10-17)" in caplog.text
