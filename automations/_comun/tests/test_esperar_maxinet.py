"""Acción `esperar-maxinet` (ADR 0034): la sonda se prueba contra servidores HTTP reales en local, sin tocar Maxinet."""
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / ".github" / "actions" / "esperar-maxinet" / "esperar.sh"


class _Servidor:
    """Servidor HTTP local que contesta siempre con `codigo` y recuerda las rutas que le pidieron."""

    def __init__(self, codigo=200, puerto=0):
        self.pedidos = []
        pedidos = self.pedidos

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self):
                pedidos.append(self.path)
                self.send_response(codigo)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
        self.puerto = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def cerrar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _correr(base_url, espera_max=3, sondeo=1, **extra):
    env = {**os.environ, "BASE_URL": base_url, "ESPERA_MAX_SEG": str(espera_max), "SONDEO_SEG": str(sondeo), **extra}
    t = time.monotonic()
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t


@pytest.fixture
def servidores():
    abiertos = []

    def crear(codigo=200, puerto=0):
        s = _Servidor(codigo, puerto)
        abiertos.append(s)
        return s
    yield crear
    for s in abiertos:
        s.cerrar()


def test_si_maxinet_responde_sigue_de_inmediato(servidores):
    s = servidores(200)
    rc, salida, seg = _correr(f"http://127.0.0.1:{s.puerto}/maxinetv2")
    assert rc == 0 and "Maxinet responde (HTTP 200)" in salida and seg < 5


@pytest.mark.parametrize("codigo", [302, 403, 404])
def test_cualquier_respuesta_menor_a_500_cuenta_como_arriba(servidores, codigo):
    s = servidores(codigo)
    rc, salida, _ = _correr(f"http://127.0.0.1:{s.puerto}")
    assert rc == 0 and f"HTTP {codigo}" in salida


def test_un_error_5xx_cuenta_como_caido_y_agota_la_espera(servidores):
    s = servidores(503)
    rc, salida, seg = _correr(f"http://127.0.0.1:{s.puerto}", espera_max=2)
    assert rc == 1 and "::error::Maxinet no respondió" in salida and "HTTP 503" in salida
    assert 1 <= seg < 15                                                     # el script mide en segundos enteros: ±1 s


def test_la_conexion_rechazada_agota_la_espera_y_falla():
    rc, salida, seg = _correr(f"http://127.0.0.1:{_puerto_libre()}", espera_max=2)
    assert rc == 1 and "curl 7" in salida and "::error::Maxinet no respondió" in salida
    assert 1 <= seg < 15


def test_si_maxinet_vuelve_durante_la_espera_el_workflow_sigue(servidores):
    puerto = _puerto_libre()
    threading.Timer(2.5, lambda: servidores(200, puerto)).start()            # el servidor "revive" a los 2.5 s
    rc, salida, seg = _correr(f"http://127.0.0.1:{puerto}", espera_max=20)
    assert rc == 0 and "curl 7" in salida and "::warning::Maxinet volvió a responder" in salida
    assert 2 <= seg < 15


def test_una_barra_final_no_duplica_la_ruta(servidores):
    s = servidores(200)
    _correr(f"http://127.0.0.1:{s.puerto}/maxinetv2/")
    assert s.pedidos == ["/maxinetv2/"]


def test_la_url_nunca_se_imprime(servidores):
    s = servidores(200)
    _, ok, _ = _correr(f"http://127.0.0.1:{s.puerto}/ruta-secreta-xyz")
    _, mal, _ = _correr(f"http://127.0.0.1:{_puerto_libre()}/ruta-secreta-xyz", espera_max=1)
    assert "ruta-secreta-xyz" not in ok and "ruta-secreta-xyz" not in mal and "127.0.0.1" not in ok + mal


def test_sin_url_falla_con_un_mensaje_claro():
    rc, salida, _ = _correr("")
    assert rc == 1 and "Falta la URL de Maxinet" in salida


def test_la_espera_se_expresa_en_minutos_si_no_hay_override():
    env = {k: v for k, v in os.environ.items() if k not in ("ESPERA_MAX_SEG",)}
    env.update(BASE_URL=f"http://127.0.0.1:{_puerto_libre()}", MINUTOS="0", SONDEO_SEG="1")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "máximo 0 min" in r.stdout


def test_los_avisos_se_espacian_para_no_llenar_el_log(servidores):
    rc, salida, _ = _correr(f"http://127.0.0.1:{_puerto_libre()}", espera_max=5, AVISO_CADA="100")
    assert rc == 1 and salida.count("Maxinet no responde") == 1            # sólo el primero; el resto se calla
