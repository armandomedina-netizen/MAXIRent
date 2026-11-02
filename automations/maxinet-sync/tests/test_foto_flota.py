"""Foto de flota de Maxinet: vacía no es cambio de estructura, y el sync espera a que se publique (sin red)."""
import json

import pytest

import maxinet_sync as m


class _Resp:
    def __init__(self, filas):
        self.content = b"\xef\xbb\xbf" + json.dumps({"data": filas}).encode()


def _fila_maxinet(n=41):
    return ["<a>comentarios</a>"] + [f"v{i}" for i in range(n)]


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://maxinet.prueba")
    monkeypatch.delenv("ESPERAR_FOTO_MIN", raising=False)


def _servir(monkeypatch, *respuestas):
    """Cada llamada a Maxinet devuelve la siguiente respuesta (la última se repite)."""
    cola = list(respuestas)
    llamadas = []

    def post(session, url, data, intentos=3):
        llamadas.append(data)
        return _Resp(cola.pop(0) if len(cola) > 1 else cola[0])
    monkeypatch.setattr(m, "_post_con_reintentos", post)
    return llamadas


# ---------------------------------------------------------------- vacía vs estructura distinta
def test_una_foto_sin_filas_es_foto_vacia_y_no_un_cambio_de_estructura(monkeypatch):
    _servir(monkeypatch, [])
    with pytest.raises(m.FotoFlotaVacia) as e:
        m.descargar_datos_flota(object())
    assert "0 filas" in str(e.value) and "no es un cambio de estructura" in str(e.value)
    assert isinstance(e.value, RuntimeError)


def test_un_ancho_distinto_sigue_siendo_cambio_de_estructura(monkeypatch):
    _servir(monkeypatch, [_fila_maxinet(42)])
    with pytest.raises(RuntimeError, match="cambió la estructura") as e:
        m.descargar_datos_flota(object())
    assert not isinstance(e.value, m.FotoFlotaVacia)


def test_una_foto_completa_se_descarga(monkeypatch):
    llamadas = _servir(monkeypatch, [_fila_maxinet(), _fila_maxinet()])
    df = m.descargar_datos_flota(object())
    assert len(df) == 2 and list(df.columns) == m.COLUMNAS
    assert llamadas[0]["Desde"] == llamadas[0]["Hasta"]


# ---------------------------------------------------------------- espera
class Reloj:
    def __init__(self):
        self.t, self.dormidos = 0.0, []

    def reloj(self):
        return self.t

    def dormir(self, seg):
        self.dormidos.append(seg)
        self.t += seg


def test_sin_espera_falla_a_la_primera_si_la_foto_esta_vacia(monkeypatch):
    llamadas = _servir(monkeypatch, [])
    r = Reloj()
    with pytest.raises(m.FotoFlotaVacia):
        m.descargar_datos_flota_esperando(object(), 0, r.reloj, r.dormir)
    assert len(llamadas) == 1 and r.dormidos == []


def test_espera_hasta_que_maxinet_publica_y_vuelve_a_iniciar_sesion(monkeypatch):
    _servir(monkeypatch, [], [], [_fila_maxinet()])
    sesiones = []
    monkeypatch.setattr(m, "login_maxinet", lambda: sesiones.append(1) or f"sesion{len(sesiones)}")
    r = Reloj()
    df, sesion = m.descargar_datos_flota_esperando("sesion0", 120, r.reloj, r.dormir)
    assert len(df) == 1 and r.dormidos == [m.SONDEO_FOTO_SEG] * 2
    assert sesion == "sesion2" and len(sesiones) == 2           # una sesión nueva en cada reintento


def test_al_agotar_el_tiempo_falla_con_foto_vacia_y_no_escribe_nada(monkeypatch):
    llamadas = _servir(monkeypatch, [])
    monkeypatch.setattr(m, "login_maxinet", lambda: "sesion")
    r = Reloj()
    with pytest.raises(m.FotoFlotaVacia):
        m.descargar_datos_flota_esperando("s", 10, r.reloj, r.dormir)
    assert sum(r.dormidos) == 600 and len(llamadas) == 6        # 0, 2, 4, 6, 8 y 10 min


def test_un_cambio_de_estructura_no_espera(monkeypatch):
    llamadas = _servir(monkeypatch, [_fila_maxinet(42)])
    r = Reloj()
    with pytest.raises(RuntimeError, match="cambió la estructura"):
        m.descargar_datos_flota_esperando(object(), 120, r.reloj, r.dormir)
    assert len(llamadas) == 1 and r.dormidos == []


# ---------------------------------------------------------------- main
def test_main_pasa_los_minutos_de_espera_y_no_escribe_si_la_foto_sigue_vacia(monkeypatch):
    monkeypatch.setenv("ESPERAR_FOTO_MIN", "120")
    visto = {}

    def esperando(session, espera):
        visto["espera"] = espera
        raise m.FotoFlotaVacia("vacía")
    monkeypatch.setattr(m, "login_maxinet", lambda: "s")
    monkeypatch.setattr(m, "descargar_datos_flota_esperando", esperando)
    monkeypatch.setattr(m, "conectar_sheet_secundario", lambda *a, **k: pytest.fail("no debe escribir nada"))
    monkeypatch.setattr(m, "conectar_sheet", lambda *a, **k: pytest.fail("no debe escribir nada"))
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 1 and visto["espera"] == 120
