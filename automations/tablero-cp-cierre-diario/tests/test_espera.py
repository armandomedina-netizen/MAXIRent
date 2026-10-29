"""Espera matutina a que FLOTA CP cargue el día de ayer (sin red ni hojas reales)."""
import datetime as dt
import logging

import pytest

import cierre_diario as c

AYER = dt.date(2026, 10, 28)
ANTEAYER = dt.date(2026, 10, 27)


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.delenv("ESPERAR_DATOS_MIN", raising=False)


def _a(hh, mm):
    return dt.datetime(2026, 10, 29, hh, mm, tzinfo=dt.timezone(dt.timedelta(hours=-6)))


# ---------------------------------------------------------------- cuánto espera
@pytest.mark.parametrize("hh,mm,esperado", [(7, 54, 0), (7, 55, c.ESPERA_MANANA_MIN), (8, 0, c.ESPERA_MANANA_MIN),
                                           (9, 30, c.ESPERA_MANANA_MIN), (9, 31, 0), (15, 0, 0), (2, 42, 0)])
def test_sólo_espera_por_la_mañana(hh, mm, esperado):
    assert c.minutos_de_espera(_a(hh, mm), dry_run=False, simulada=False) == esperado


def test_con_dry_run_o_fecha_simulada_no_espera():
    assert c.minutos_de_espera(_a(8, 10), dry_run=True, simulada=False) == 0
    assert c.minutos_de_espera(_a(8, 10), dry_run=False, simulada=True) == 0


def test_la_variable_de_entorno_manda(monkeypatch):
    monkeypatch.setenv("ESPERAR_DATOS_MIN", "5")
    assert c.minutos_de_espera(_a(15, 0), dry_run=False, simulada=False) == 5
    assert c.minutos_de_espera(_a(8, 10), dry_run=True, simulada=False) == 5
    monkeypatch.setenv("ESPERAR_DATOS_MIN", "0")
    assert c.minutos_de_espera(_a(8, 10), dry_run=False, simulada=False) == 0


def test_una_variable_invalida_se_ignora_y_avisa(monkeypatch, caplog):
    monkeypatch.setenv("ESPERAR_DATOS_MIN", "mucho")
    with caplog.at_level(logging.WARNING):
        assert c.minutos_de_espera(_a(8, 10), dry_run=False, simulada=False) == c.ESPERA_MANANA_MIN
    assert "ESPERAR_DATOS_MIN" in caplog.text


# ---------------------------------------------------------------- el sondeo
class Reloj:
    """Reloj y sueño falsos: dormir adelanta el reloj, así que las pruebas no esperan de verdad."""

    def __init__(self):
        self.t, self.dormidos = 0.0, []

    def reloj(self):
        return self.t

    def dormir(self, seg):
        self.dormidos.append(seg)
        self.t += seg


def _lector(*lecturas):
    cola = list(lecturas)
    llamadas = []

    def leer():
        llamadas.append(1)
        return cola.pop(0) if len(cola) > 1 else cola[0]
    leer.llamadas = llamadas
    return leer


def test_si_ya_trae_ayer_no_espera():
    r = Reloj()
    leer = _lector((AYER, 1701))
    assert c.esperar_datos_nuevos(leer, AYER, 25, r.reloj, r.dormir) == (AYER, 1701)
    assert r.dormidos == [] and len(leer.llamadas) == 1


def test_espera_hasta_que_cambia_la_fecha_y_cierra_en_cuanto_cambia(caplog):
    r = Reloj()
    leer = _lector((ANTEAYER, 1703), (ANTEAYER, 1703), (AYER, 300), (AYER, 1701))      # 300 filas: carga a medias
    with caplog.at_level(logging.INFO):
        assert c.esperar_datos_nuevos(leer, AYER, 25, r.reloj, r.dormir) == (AYER, 1701)
    assert len(leer.llamadas) == 4 and r.dormidos == [c.SONDEO_ESPERA_SEG] * 3
    assert "se espera hasta 25 min" in caplog.text and "ya trae los datos del 2026-10-28" in caplog.text


def test_al_agotar_el_tiempo_devuelve_lo_ultimo_que_leyo():
    r = Reloj()
    leer = _lector((ANTEAYER, 1703))
    assert c.esperar_datos_nuevos(leer, AYER, 2, r.reloj, r.dormir) == (ANTEAYER, 1703)
    assert sum(r.dormidos) == 120 and len(leer.llamadas) == 5        # 0, 30, 60, 90, 120 s


def test_datos_incompletos_tambien_hacen_esperar():
    r = Reloj()
    leer = _lector((None, 0), (AYER, 12), (AYER, 1701))
    assert c.esperar_datos_nuevos(leer, AYER, 25, r.reloj, r.dormir) == (AYER, 1701)
    assert len(r.dormidos) == 2


def test_sin_espera_lee_una_sola_vez_aunque_este_viejo():
    r = Reloj()
    leer = _lector((ANTEAYER, 1703))
    assert c.esperar_datos_nuevos(leer, AYER, 0, r.reloj, r.dormir) == (ANTEAYER, 1703)
    assert r.dormidos == [] and len(leer.llamadas) == 1


def test_una_fecha_mas_reciente_que_ayer_tambien_sirve():
    r = Reloj()
    assert c.esperar_datos_nuevos(_lector((AYER + dt.timedelta(days=1), 1701)), AYER, 25, r.reloj, r.dormir)[0] > AYER


# ---------------------------------------------------------------- main
class HojaFlota:
    def get(self, rango, value_render_option=None):
        return []


@pytest.fixture
def entorno_main(monkeypatch):
    """main() con el libro, las fotos y el cierre por pestaña sustituidos; registra qué se cerró y cuánto se esperó."""
    registro = {"cerradas": [], "espera": None}
    monkeypatch.setattr(c, "conectar_libro", lambda: object())
    monkeypatch.setattr(c, "Fotos", lambda libro, escribir: object())
    monkeypatch.setattr(c, "resolver_pestana", lambda libro, fotos, logico: HojaFlota())
    monkeypatch.setattr(c, "crear_recuperador", lambda libro, fotos: None)
    monkeypatch.setattr(c, "cerrar_pestana", lambda libro, nombre, fecha, fotos, hoy, dry_run, recuperador: registro["cerradas"].append((nombre, fecha)) or True)

    def fingir(hora, lectura):
        class RelojDt(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 29, hora[0], hora[1], tzinfo=tz)
        monkeypatch.setattr(c.dt, "datetime", RelojDt)

        def esperar(leer, ayer, max_min, *a, **k):
            registro["espera"] = (ayer, max_min)
            return lectura
        monkeypatch.setattr(c, "esperar_datos_nuevos", esperar)
    registro["fingir"] = fingir
    return registro


def test_main_por_la_manana_con_datos_nuevos_cierra_las_tres_pestanas(entorno_main):
    entorno_main["fingir"]((8, 2), (AYER, 1701))
    assert c.main() == 0
    assert entorno_main["espera"] == (AYER, c.ESPERA_MANANA_MIN)
    assert [n for n, f in entorno_main["cerradas"]] == list(c.PESTANAS) and all(f == AYER for n, f in entorno_main["cerradas"])


def test_main_si_tras_esperar_sigue_viejo_termina_con_1_y_no_cierra_nada(entorno_main, caplog):
    entorno_main["fingir"]((8, 2), (ANTEAYER, 1703))
    with caplog.at_level(logging.ERROR):
        assert c.main() == 1
    assert entorno_main["cerradas"] == [] and "sigue con los datos del 2026-10-27 después de esperar 25 min" in caplog.text


def test_main_fuera_de_la_manana_no_espera_y_cierra_con_la_fecha_que_haya(entorno_main):
    entorno_main["fingir"]((15, 0), (ANTEAYER, 1703))
    assert c.main() == 0
    assert entorno_main["espera"] == (AYER, 0) and all(f == ANTEAYER for n, f in entorno_main["cerradas"])


def test_main_con_dry_run_no_espera(entorno_main, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    entorno_main["fingir"]((8, 2), (ANTEAYER, 1703))
    assert c.main() == 0 and entorno_main["espera"] == (AYER, 0)


def test_main_con_datos_incompletos_sigue_siendo_error(entorno_main):
    entorno_main["fingir"]((15, 0), (AYER, 12))
    assert c.main() == 1 and entorno_main["cerradas"] == []
