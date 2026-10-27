import datetime as dt

import pytest

import guardia as g

AYER = dt.date(2026, 10, 25)

# Muestras reales de las corridas en seco del 26-oct-2026
NUEVOS_FALTAN_7 = """2026-10-26 12:08:46,826 INFO Datos descargados de Maxinet: 296 filas (Desde=2026-10-01, Hasta=2026-10-26)
2026-10-26 12:08:48,529 INFO Filas omitidas por ClientNo/BookingNo ya existente en el Sheet: 289
2026-10-26 12:08:48,767 INFO DRY_RUN: se agregarían 7 filas en B3206:Q3212 (no se escribió nada)
2026-10-26 12:08:49,146 INFO Validación OK: sin ClientNo ni BookingNo repetidos en el Sheet
2026-10-26 12:08:49,146 INFO Automatización completada con éxito (0 filas nuevas)"""
NUEVOS_AL_DIA = """2026-10-26 14:26:01,351 INFO Filas omitidas por ClientNo/BookingNo ya existente en el Sheet: 249
2026-10-26 14:26:01,352 INFO No hay filas nuevas que agregar.
2026-10-26 14:26:02,176 INFO Automatización completada con éxito (0 filas nuevas)"""
ENCUESTAS_FALTAN_2 = """2026-10-26 14:26:14,547 INFO DRY_RUN: se agregarían 2 encuestas en C1112:Z1113 (no se escribió nada). Primera: 2026-10-22 | Última: 2026-10-22
2026-10-26 14:26:14,548 INFO Automatización completada con éxito (0 encuestas nuevas)"""
ENTREGAS = """2026-10-26 14:26:36,071 INFO Bloque desde 2026-10-01: filas 1825 -> 1825 | altas 0, bajas 0, estatus cambiados 52 | ON HIRE 256 -> 237
2026-10-26 14:26:36,072 INFO DRY_RUN: se reescribirían A21938:P23762 (1825 filas) (no se escribió nada).
2026-10-26 14:26:36,587 INFO Automatización completada con éxito (bloque de 1825 entregas desde 2026-10-01)"""
ENTREGAS_CON_ALTAS = ENTREGAS.replace("altas 0, bajas 0", "altas 3, bajas 1")
ENTREGAS_DOS_BLOQUES = ENTREGAS + "\n2026-10-02 INFO Bloque desde 2026-09-01: filas 10 -> 12 | altas 2, bajas 0, estatus cambiados 1 | ON HIRE 1 -> 2"
FRECUENTES_AL_DIA = """2026-10-22 14:25:53,977 INFO Sin cambios: la pestaña ya refleja la semana 193 (2026-10-10) de Maxinet (769 clientes).
2026-10-22 14:25:54,643 INFO Revisión completada con éxito (semana 193, 2026-10-10)"""
FRECUENTES_CAMBIA = """2026-10-26 INFO Semana 194 descargada de Maxinet: 766 clientes
2026-10-26 INFO DRY_RUN: se reemplazarían 769 filas por 766 (no se escribió nada).
2026-10-26 INFO Revisión completada con éxito (semana 194, 2026-10-17)"""
CIERRE_AL_DIA = """2026-10-26 INFO Fecha de los datos de FLOTA CP: 2026-10-25 (1702 filas)
2026-10-26 INFO UNIDADES CP: datos del 2026-10-25 -> columna YN (ya viva) | crear columna viva: no | columnas a congelar: ninguna | filas de la foto: 32
2026-10-26 INFO Cierre diario completado con éxito"""
CIERRE_PENDIENTE = """2026-10-26 INFO Fecha de los datos de FLOTA CP: 2026-10-25 (1702 filas)
2026-10-26 INFO UNIDADES CP: datos del 2026-10-25 -> columna YN (nueva) | crear columna viva: sí | columnas a congelar: ['2026-10-22'] | filas de la foto: 32
2026-10-26 INFO Cierre diario completado con éxito"""
CIERRE_CON_ERROR = """2026-10-26 INFO Fecha de los datos de FLOTA CP: 2026-10-25 (1702 filas)
2026-10-26 ERROR UNIDADES CP: no hay foto de cierre del 2026-10-22; esa columna no se congela
2026-10-26 ERROR Cierre diario con pendientes: 1 de 3 pestañas con aviso"""


# ---------------------------------------------------------------- lectores de salida
def test_pendientes_filas():
    assert g.pendientes_filas(NUEVOS_FALTAN_7) == 7
    assert g.pendientes_filas(NUEVOS_AL_DIA) == 0
    assert g.pendientes_filas(ENCUESTAS_FALTAN_2) == 2
    assert g.pendientes_filas("2026 INFO Login en Maxinet exitoso\nTraceback ...") is None          # no terminó: no se asume que esté al día


def test_pendientes_entregas_cuenta_altas_y_bajas_pero_no_estatus():
    assert g.pendientes_entregas(ENTREGAS) == 0
    assert g.pendientes_entregas(ENTREGAS_CON_ALTAS) == 4
    assert g.pendientes_entregas(ENTREGAS_DOS_BLOQUES) == 2
    assert g.pendientes_entregas("INFO Automatización completada con éxito (x)") is None           # sin línea del bloque


def test_pendientes_frecuentes():
    assert g.pendientes_frecuentes(FRECUENTES_AL_DIA) == 0
    assert g.pendientes_frecuentes(FRECUENTES_CAMBIA) == 1
    assert g.pendientes_frecuentes("Sin cambios") is None


def test_leer_cierre():
    assert g.leer_cierre(CIERRE_AL_DIA) == {"fecha": AYER, "pendientes": 0}
    assert g.leer_cierre(CIERRE_PENDIENTE)["pendientes"] == 2          # columna por crear y columna por congelar
    assert g.leer_cierre(CIERRE_CON_ERROR)["pendientes"] == 2          # dos líneas ERROR
    assert g.leer_cierre("nada") == {}


# ---------------------------------------------------------------- revisar una automatización
class Ejecutor:
    """Devuelve las salidas en orden, una por llamada, y registra qué se ejecutó."""

    def __init__(self, *salidas):
        self.salidas, self.llamadas = list(salidas), []

    def __call__(self, rev):
        self.llamadas.append(rev.nombre)
        salida = self.salidas.pop(0)
        return salida if isinstance(salida, tuple) else (0, salida)


class Relanzador:
    def __init__(self, conclusion="success"):
        self.conclusion, self.llamadas = conclusion, []

    def __call__(self, workflow):
        self.llamadas.append(workflow)
        return self.conclusion


NUEVOS = g.REVISIONES[0]


def test_al_dia_no_relanza_nada():
    rel = Relanzador()
    r = g.revisar(NUEVOS, Ejecutor(NUEVOS_AL_DIA), rel)
    assert r.estado == "ok" and rel.llamadas == []


def test_si_falta_relanza_espera_y_comprueba_otra_vez():
    ej, rel = Ejecutor(NUEVOS_FALTAN_7, NUEVOS_AL_DIA), Relanzador("success")
    r = g.revisar(NUEVOS, ej, rel)
    assert r.estado == "recuperado" and rel.llamadas == ["maxinet-clientes-nuevos-cp.yml"] and len(ej.llamadas) == 2
    assert "7" in r.detalle


def test_si_tras_relanzar_aun_falta_queda_pendiente():
    r = g.revisar(NUEVOS, Ejecutor(NUEVOS_FALTAN_7, NUEVOS_FALTAN_7), Relanzador("success"))
    assert r.estado == "pendiente" and "aún falta" in r.detalle


@pytest.mark.parametrize("conclusion", ["failure", "timeout", "no disponible", "no se pudo lanzar (HTTP 403)"])
def test_si_el_relanzado_no_termina_bien_queda_pendiente_sin_volver_a_ejecutar(conclusion):
    ej = Ejecutor(NUEVOS_FALTAN_7)
    r = g.revisar(NUEVOS, ej, Relanzador(conclusion))
    assert r.estado == "pendiente" and conclusion in r.detalle and len(ej.llamadas) == 1


def test_una_salida_que_no_se_entiende_no_se_da_por_buena():
    assert g.revisar(NUEVOS, Ejecutor((1, "Traceback")), Relanzador()).estado == "no verificado"
    assert g.revisar(NUEVOS, Ejecutor((0, "salida rara sin el mensaje final")), Relanzador()).estado == "no verificado"


def test_cada_automatizacion_tiene_su_lector_y_su_workflow():
    nombres = [r.nombre for r in g.REVISIONES]
    assert nombres == ["Clientes Nuevos", "Clientes Potenciales", "Encuestas", "Entregas", "Frecuentes Activos"]
    assert all(r.workflow.endswith(".yml") and (g.RAIZ / r.directorio / r.script).exists() for r in g.REVISIONES + (g.CIERRE,))


# ---------------------------------------------------------------- el Tablero
def test_tablero_al_dia():
    out = g.revisar_tablero(AYER, Ejecutor(CIERRE_AL_DIA), Relanzador())
    assert [r.estado for r in out] == ["ok", "ok"]


def test_tablero_sin_los_datos_del_dia_no_se_relanza_el_cierre():
    rel = Relanzador()
    out = g.revisar_tablero(dt.date(2026, 10, 26), Ejecutor(CIERRE_AL_DIA), rel)
    assert out[0].estado == "sin datos" and "2026-10-25" in out[0].detalle and rel.llamadas == []


def test_tablero_con_cierre_pendiente_se_relanza_y_se_recupera():
    rel = Relanzador("success")
    out = g.revisar_tablero(AYER, Ejecutor(CIERRE_PENDIENTE, CIERRE_AL_DIA), rel)
    assert [r.estado for r in out] == ["ok", "recuperado"] and rel.llamadas == ["tablero-cp-cierre-diario.yml"]


def test_tablero_con_cierre_que_sigue_pendiente():
    out = g.revisar_tablero(AYER, Ejecutor(CIERRE_PENDIENTE, CIERRE_PENDIENTE), Relanzador("success"))
    assert out[-1].estado == "pendiente"


def test_tablero_con_salida_ilegible():
    assert g.revisar_tablero(AYER, Ejecutor((1, "Traceback")), Relanzador())[0].estado == "no verificado"


# ---------------------------------------------------------------- errores en pestañas
def test_errores_en_el_tablero():
    assert g.revisar_errores(lambda: {}).estado == "ok"
    r = g.revisar_errores(lambda: {"MKT": 2, "GRAFICAS": 1})
    assert r.estado == "pendiente" and "MKT: 2" in r.detalle and "GRAFICAS: 1" in r.detalle


def test_si_no_se_puede_leer_el_tablero_no_se_da_por_bueno():
    def falla():
        raise RuntimeError("cuota")
    assert g.revisar_errores(falla).estado == "no verificado"


# ---------------------------------------------------------------- resumen y código de salida
def test_resumen_y_codigo_de_salida(monkeypatch, capsys):
    ok = g.Resultado("A", "ok")
    mal = g.Resultado("B", "pendiente", "faltaban 3")
    monkeypatch.setattr(g, "revisar", lambda rev, *a, **k: ok)
    monkeypatch.setattr(g, "revisar_tablero", lambda ayer, *a, **k: [ok])
    monkeypatch.setattr(g, "revisar_errores", lambda *a, **k: ok)
    monkeypatch.setattr(g, "revisar_radar", lambda *a, **k: ok)
    assert g.main() == 0
    monkeypatch.setattr(g, "revisar_errores", lambda *a, **k: mal)
    assert g.main() == 1
    assert "PENDIENTE" in g.resumen([ok, mal]) and "faltaban 3" in g.resumen([ok, mal])


def test_sin_token_no_se_relanza(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert g.relanzar_workflow("x.yml") == "no disponible"
    monkeypatch.setenv("GITHUB_TOKEN", "t"); monkeypatch.setenv("GITHUB_REPOSITORY", "o/r"); monkeypatch.setenv("SIN_RELANZAR", "1")
    assert g.relanzar_workflow("x.yml") == "no disponible"


# ---------------------------------------------------------------- reintentos ante 429
class _Resp:
    def __init__(self, codigo):
        self.status_code = codigo
        self.text = '{"error": {"code": %d, "message": "cuota", "status": "RESOURCE_EXHAUSTED"}}' % codigo

    def json(self):
        return {"error": {"code": self.status_code, "message": "cuota", "status": "RESOURCE_EXHAUSTED"}}


def test_con_reintentos_espera_y_reintenta_ante_429(monkeypatch):
    import gspread
    esperas, llamadas = [], []
    monkeypatch.setattr(g.time, "sleep", lambda s: esperas.append(s))

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise gspread.exceptions.APIError(_Resp(429))
        return "ok"
    assert g.con_reintentos(fn) == "ok" and esperas == [20, 40]


def test_con_reintentos_no_oculta_otros_errores(monkeypatch):
    import gspread
    monkeypatch.setattr(g.time, "sleep", lambda s: None)

    def fn():
        raise gspread.exceptions.APIError(_Resp(403))
    with pytest.raises(gspread.exceptions.APIError):
        g.con_reintentos(fn)


# ---------------------------------------------------------------- radar de cambios de Nuvia
AHORA = dt.datetime(2026, 10, 27, 17, 0, tzinfo=dt.timezone.utc)
RECIENTE = (AHORA - dt.timedelta(hours=1)).isoformat()


def test_radar_sin_cambios_o_en_curso_no_es_pendiente():
    ok = g.revisar_radar(lambda: {"Tablero CP": {"estado": "sin cambios", "revisado": RECIENTE}, "Base CP": {"estado": "sin cambios", "revisado": RECIENTE}}, AHORA)
    assert ok.estado == "ok" and "sin cambios" in ok.detalle
    en_curso = g.revisar_radar(lambda: {"Tablero CP": {"estado": "en curso", "revisado": RECIENTE}}, AHORA)
    assert en_curso.estado == "ok" and "sigue ajustando" in en_curso.detalle


def test_radar_con_cambios_estables_es_pendiente_y_dice_que_hacer():
    r = g.revisar_radar(lambda: {"Tablero CP": {"estado": "estable", "revisado": RECIENTE}}, AHORA)
    assert r.estado == "pendiente" and "Tablero CP" in r.detalle and "_RADAR" in r.detalle and "línea base" in r.detalle


def test_radar_que_no_corre_o_sin_linea_base_no_se_da_por_bueno():
    viejo = (AHORA - dt.timedelta(hours=7)).isoformat()
    assert g.revisar_radar(lambda: {"Tablero CP": {"estado": "sin cambios", "revisado": viejo}}, AHORA).estado == "no verificado"
    assert g.revisar_radar(lambda: {"Tablero CP": {"estado": "sin cambios"}}, AHORA).estado == "no verificado"
    assert g.revisar_radar(lambda: {}, AHORA).estado == "no verificado"

    def falla():
        raise RuntimeError("x")
    assert g.revisar_radar(falla, AHORA).estado == "no verificado"
