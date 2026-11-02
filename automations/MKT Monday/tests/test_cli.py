import logging
from datetime import date

import pytest

from mkt_sync import cli
from mkt_sync.config import Config
from mkt_sync.hoja import ORIGEN_SERIE

CFG = Config(tablero_id=1, columna_estado="e", etiqueta_califica="Califica", columna_tipo="t", tipos_incluidos=("A",))
LEADS = [
    {"id": "1", "created_at": "2026-10-15T15:00:00Z", "column_values": [{"id": "e", "text": "Califica"}]},
    {"id": "2", "created_at": "2026-10-16T15:00:00Z", "column_values": [{"id": "e", "text": "Otro"}]},
    {"id": "3", "created_at": "2026-11-02T15:00:00Z", "column_values": [{"id": "e", "text": "Califica"}]},
]


def serie(anio, mes):
    """Número de serie de Sheets del primer día del mes."""
    return (date(anio, mes, 1) - ORIGEN_SERIE).days


class ClienteFalso:
    """Cliente de monday simulado: entrega siempre los mismos leads."""

    def __init__(self, token, version):
        pass

    def validar(self, cfg):
        return [1]

    def leer_leads(self, cfg, ids_tipo):
        return LEADS


class HojaFalsa:
    """Pestaña simulada con los periodos en F4:F y los valores previos de G/H por celda."""

    def __init__(self, periodos, celdas=None):
        self.periodos, self.celdas, self.escrituras = periodos, celdas or {}, {}

    def get(self, rango, value_render_option=None):
        if rango.startswith("F4:F"):
            return [[p] for p in self.periodos]
        valor = self.celdas.get(rango)
        return [[valor]] if valor is not None else []

    def update(self, values, range_name, value_input_option=None):
        self.escrituras[range_name] = values[0][0]


class LibroFalso:
    def __init__(self, hoja):
        self.hoja = hoja

    def worksheet(self, nombre):
        return self.hoja


@pytest.fixture
def preparar(monkeypatch):
    """Variables de entorno, configuración y clientes simulados; devuelve una función que fija los
    periodos que toca actualizar y la hoja que se usa."""
    monkeypatch.setenv("MONDAY_TOKEN", "t")
    monkeypatch.setenv("GOOGLE_CREDS_PATH", "x")
    monkeypatch.setenv("SPREADSHEET_ID_MKT", "id")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(cli, "cargar_config", lambda: CFG)
    monkeypatch.setattr(cli, "ClienteMonday", ClienteFalso)

    def fijar(periodos, hoja):
        monkeypatch.setattr(cli, "abrir_libro", lambda ruta, id_libro: LibroFalso(hoja))
        monkeypatch.setattr(cli, "periodos_a_actualizar", lambda ahora: periodos)
    return fijar


def test_actualiza_el_mes_anterior_y_el_mes_en_curso(preparar):
    hoja = HojaFalsa([serie(2026, 10), serie(2026, 11)], {"G4": 1, "H4": 0})
    preparar([(2026, 10), (2026, 11)], hoja)
    assert cli.main([]) == 0
    assert hoja.escrituras == {"G4": 2, "H4": 1, "G5": 1, "H5": 1}


def test_si_falta_la_fila_de_un_periodo_el_otro_se_escribe_igual(preparar, caplog):
    hoja = HojaFalsa([serie(2026, 10)], {"G4": 1, "H4": 0})
    preparar([(2026, 10), (2026, 12)], hoja)
    with caplog.at_level(logging.INFO):
        assert cli.main([]) == 1
    assert hoja.escrituras == {"G4": 2, "H4": 1}
    assert "2026-12" in caplog.text and "agrega la fila" in caplog.text


def test_con_mes_solo_se_actualiza_ese_periodo(preparar, monkeypatch):
    hoja = HojaFalsa([serie(2026, 10), serie(2026, 11)], {"G4": 1, "H4": 0})
    preparar([(2026, 11)], hoja)
    assert cli.main(["--mes", "2026-10"]) == 0
    assert hoja.escrituras == {"G4": 2, "H4": 1}


def test_mes_invalido_termina_con_error_sin_escribir(preparar):
    hoja = HojaFalsa([serie(2026, 10)])
    preparar([(2026, 10)], hoja)
    assert cli.main(["--mes", "octubre"]) == 1
    assert hoja.escrituras == {}


def test_simular_no_escribe(preparar):
    hoja = HojaFalsa([serie(2026, 10)], {"G4": 1, "H4": 0})
    preparar([(2026, 10)], hoja)
    assert cli.main(["--simular"]) == 0
    assert hoja.escrituras == {}


def test_en_actions_el_registro_no_trae_cifras(preparar, monkeypatch, caplog):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    hoja = HojaFalsa([serie(2026, 10)], {"G4": 1, "H4": 0})
    preparar([(2026, 10)], hoja)
    with caplog.at_level(logging.INFO):
        assert cli.main([]) == 0
    assert "2026-10" in caplog.text and "recibidos" not in caplog.text and "->" not in caplog.text
