"""Las siete automatizaciones de CP reintentan ante el 429 de cuota de Google Sheets (sin red)."""
import importlib.util
from pathlib import Path

import gspread
import pytest
from gspread.http_client import HTTPClient

RAIZ = Path(__file__).resolve().parents[2]
AUTOMATIZACIONES = (
    ("maxinet-clientes-nuevos-cp", "maxinet_clientes_nuevos_cp"),
    ("maxinet-clientes-potenciales-cp", "maxinet_clientes_potenciales_cp"),
    ("maxinet-encuestas-cp", "maxinet_encuestas_cp"),
    ("maxinet-entregas-cp", "maxinet_entregas_cp"),
    ("maxinet-frecuentes-activos-cp", "maxinet_frecuentes_activos_cp"),
    ("maxinet-mkt-leads-cp", "maxinet_mkt_leads_cp"),
    ("maxinet-bitacora-cp", "maxinet_bitacora_cp"),
)


class _Resp:
    def __init__(self, codigo):
        self.status_code = codigo
        self.text = '{"error": {"code": %d, "message": "x", "status": "X"}}' % codigo

    def json(self):
        return {"error": {"code": self.status_code, "message": "x", "status": "X"}}


def _error(codigo):
    return gspread.exceptions.APIError(_Resp(codigo))


@pytest.fixture(params=AUTOMATIZACIONES, ids=[a[1] for a in AUTOMATIZACIONES])
def modulo(request, monkeypatch):
    carpeta, nombre = request.param
    spec = importlib.util.spec_from_file_location(f"{nombre}__429", RAIZ / carpeta / f"{nombre}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    dormidos = []
    monkeypatch.setattr(m.time, "sleep", lambda s: dormidos.append(s))
    m.dormidos = dormidos
    return m


def _cliente(*resultados):
    """Clase con el contrato de HTTPClient.request; cada llamada consume el siguiente resultado (error o valor)."""
    cola = list(resultados)
    llamadas = []

    class Falso:
        def request(self, method, *a, **k):
            llamadas.append(method)
            r = cola.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    Falso.llamadas = llamadas
    return Falso


def test_al_importar_el_modulo_ya_reintenta_el_cliente_real_de_gspread(modulo):
    assert getattr(HTTPClient.request, "_reintenta_429", False) is True


def test_reintenta_el_429_con_espera_creciente_y_devuelve_el_resultado(modulo):
    cliente = _cliente(_error(429), _error(429), "ok")
    modulo._instalar_reintentos_gspread(cliente)
    assert cliente().request("post", "url") == "ok"
    assert modulo.dormidos == [20, 40] and len(cliente.llamadas) == 3


def test_si_el_429_no_cede_se_rinde_tras_seis_intentos(modulo):
    cliente = _cliente(*[_error(429)] * 6)
    modulo._instalar_reintentos_gspread(cliente)
    with pytest.raises(gspread.exceptions.APIError):
        cliente().request("get", "url")
    assert modulo.dormidos == [20, 40, 60, 80, 100] and len(cliente.llamadas) == 6


def test_otros_errores_no_se_reintentan(modulo):
    cliente = _cliente(_error(403), "no debe llegar")
    modulo._instalar_reintentos_gspread(cliente)
    with pytest.raises(gspread.exceptions.APIError):
        cliente().request("get", "url")
    assert modulo.dormidos == [] and len(cliente.llamadas) == 1


def test_un_5xx_se_reintenta_en_lecturas_pero_no_en_escrituras(modulo):
    lectura = _cliente(_error(503), "ok")
    modulo._instalar_reintentos_gspread(lectura)
    assert lectura().request("get", "url") == "ok" and len(lectura.llamadas) == 2
    escritura = _cliente(_error(503), "duplicaría la escritura")
    modulo._instalar_reintentos_gspread(escritura)
    with pytest.raises(gspread.exceptions.APIError):
        escritura().request("post", "url")
    assert len(escritura.llamadas) == 1


def test_instalarlo_dos_veces_no_anida_los_reintentos(modulo):
    cliente = _cliente(*[_error(429)] * 6)
    modulo._instalar_reintentos_gspread(cliente)
    modulo._instalar_reintentos_gspread(cliente)
    with pytest.raises(gspread.exceptions.APIError):
        cliente().request("get", "url")
    assert len(cliente.llamadas) == 6                       # no 36
