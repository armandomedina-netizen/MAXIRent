"""Reporte de flota última renta en el Tablero LP: limpieza, tipos, salvaguardas y reescritura (sin red ni Sheets reales)."""
import json

import gspread
import pytest

import maxinet_flota_ultima_renta as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte

SERIE_3_AGO = 46237                       # 2026-08-03 como número de serie de Sheets


def _limpias(*filas):
    return m.normalizar_filas(list(filas))


def _filas(*placas):
    """Filas de la hoja (tipadas) para esas placas, como las deja una corrida."""
    return [fila_hoja(p) for p in placas]


def _hoja_con(*filas):
    return HojaFalsa([m.ENCABEZADO, *filas])


# ---------------------------------------------------------------- estructura
def test_la_tabla_tiene_20_columnas_en_el_orden_de_la_pagina():
    assert len(m.ENCABEZADO) == m.ANCHO_REPORTE == 20
    assert m.ENCABEZADO[0] == "Placa" and m.ENCABEZADO[-1] == "Name Ult. Renta"
    assert m.ENCABEZADO[7] == "Semáforo dias no disp." and m.ENCABEZADO[9] == "Semáforo Odómetro"
    assert m.ULT_COL == "T" and m._col_a1(m.COL_ESTADO) == "V"           # los datos acaban en T; el sello va dos columnas después
    assert m.FECHA | m.ENTEROS <= set(m.ENCABEZADO) and not (m.FECHA & m.ENTEROS)


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_espacios_de_relleno_html_y_none():
    assert m._texto("ON HIRE     ") == "ON HIRE"
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""
    assert m._texto(0) == "0" and m._texto(134) == "134"                  # un 0 de días no es vacío


def test_normalizar_limpia_las_20_celdas():
    fila = _limpias(fila_reporte("TST001"))[0]
    assert len(fila) == 20
    assert fila[m.ENCABEZADO.index("Estatus ult. renta Cliente")] == "ON HIRE"
    assert fila[m.ENCABEZADO.index("Dias no disponibles")] == ""         # None -> vacío


@pytest.mark.parametrize("n", [19, 21])
def test_ancho_distinto_detiene_sin_escribir(n):
    f = fila_reporte("TST001")
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([f[:n] if n < 20 else f + ["x"]])


def test_placa_vacia_o_repetida_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="sin Placa"):
        m.normalizar_filas([fila_reporte(None)])
    with pytest.raises(RuntimeError, match="repetida"):
        m.normalizar_filas([fila_reporte("TST001"), fila_reporte("TST001")])


def test_columnas_recorridas_detienen_sin_escribir():
    filas = [fila_reporte(f"TST{i:03d}", **{"PUDate Ult. Renta Cliente": "ON HIRE"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)
    filas = [fila_reporte(f"TST{i:03d}", **{"Odómetro": "verde"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)


def test_un_dato_raro_aislado_no_detiene_la_corrida_y_queda_como_texto():
    filas = [fila_reporte(f"TST{i:03d}") for i in range(30)]
    filas[3] = fila_reporte("TST003", **{"PUDate Ult. Renta Cliente": "0000-00-00"})
    limpias = m.normalizar_filas(filas)
    assert m.a_fila_hoja(limpias[3])[3] == "0000-00-00"
    assert m.a_fila_hoja(limpias[4])[3] == SERIE_3_AGO


def test_fechas_dias_y_odometro_se_tipan():
    assert m._valor("PUDate Ult. Renta Cliente", "2026-08-03") == SERIE_3_AGO
    assert m._valor("Odómetro", "10697") == 10697 and isinstance(m._valor("Odómetro", "10697"), int)
    d0 = m._valor("Dias no disponibles", "0")
    assert d0 == 0 and isinstance(d0, int)                               # el cero es un dato, no un vacío
    assert m._valor("Dias desde Ult. Renta Cliente", "134") == 134


@pytest.mark.parametrize("nombre,texto", [
    ("PUDate Ult. Renta Cliente", "0000-00-00"),         # fecha vacía de MySQL
    ("ReturnDate Ult. Renta", "2026-02-30"),             # fecha inexistente
    ("ReturnDate Ult. Renta Cliente", "1999-01-01"),     # año fuera de rango
    ("Odómetro", "10,697"),
    ("Placa", "@LG41116"),                               # empieza con @: siempre texto
    ("Booking Ult. Renta Cliente", "#100000001"),
    ("Semáforo Odómetro", "rojo"),
    ("Cliente Ult. Renta", "=SUM(A1)"),
])
def test_lo_que_no_tiene_la_forma_esperada_o_no_es_fecha_o_numero_queda_como_texto(nombre, texto):
    assert m._valor(nombre, texto) == texto and isinstance(m._valor(nombre, texto), str)


def test_vacio_sigue_vacio():
    assert all(m._valor(n, "") == "" for n in ("Odómetro", "PUDate Ult. Renta Cliente", "Dias no disponibles", "Model"))


def test_fila_de_la_hoja_tiene_20_columnas_tipadas():
    fila = fila_hoja("@LG41116", **{"Dias no disponibles": 0, "Dias desde Ult. Renta Cliente": 12})
    assert len(fila) == 20 and fila[0] == "@LG41116" and fila[3] == SERIE_3_AGO
    assert fila[5] == 12 and fila[6] == 0 and fila[8] == 10697 and fila[17] == "ON HIRE"


# ---------------------------------------------------------------- consulta a Maxinet
class _Resp:
    def __init__(self, cuerpo):
        self.content = ("﻿" + cuerpo).encode("utf-8")


class _Sesion:
    def __init__(self, cuerpo):
        self.cuerpo, self.pedidos = cuerpo, []

    def get(self, url, timeout=None):
        self.pedidos.append(url)
        return _Resp(self.cuerpo)


def test_consultar_pide_el_endpoint_sin_parametros(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor/maxinetv2/")
    s = _Sesion(json.dumps({"data": [fila_reporte("TST001")]}))
    assert len(m.consultar(s)) == 1
    assert s.pedidos == ["http://servidor/maxinetv2/includes/flota/reporte-flota-ultima-renta.php"]


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_Sesion(json.dumps({"data": ""}))) == []


def test_consultar_con_data_inesperado_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_Sesion(json.dumps({"data": {"a": 1}})))


# ---------------------------------------------------------------- reescritura de la hoja
def test_en_la_hoja_ya_armada_escribe_los_datos_sin_tocar_el_encabezado():
    hoja = _hoja_con()
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1", "A2", "A3"))
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A2:T4" and modo == "RAW" and len(valores) == 3 and valores[0][0] == "A1"
    assert all(not e[0].startswith("A1:") for e in hoja.escrituras)                 # la fila 1 es de quien armó la hoja
    assert hoja.spreadsheet.creadas == [] and (r["antes"], r["despues"], r["altas"], r["bajas"]) == (0, 3, 3, 0)


def test_primera_corrida_sin_la_pestana_la_crea_con_el_encabezado():
    libro = Libro([])
    m.refrescar(None, libro, "Reporte Flota Ultima Renta", _filas("A1", "A2"))
    hoja = libro.worksheet("Reporte Flota Ultima Renta")
    assert libro.creadas == ["Reporte Flota Ultima Renta"]
    assert hoja.escrituras[0][:2] == ("A1:T1", [m.ENCABEZADO]) and hoja.escrituras[1][0] == "A2:T3"
    assert hoja.celdas[1][0] == "A1" and hoja.celdas[1][3] == SERIE_3_AGO


def test_una_hoja_con_el_encabezado_vacio_lo_recibe():
    hoja = HojaFalsa([])
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert hoja.escrituras[0][:2] == ("A1:T1", [m.ENCABEZADO])


def test_conserva_el_orden_en_que_maxinet_entrega_las_filas():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("Z9", "A1", "M5"))
    assert [hoja.celdas[i][0] for i in (1, 2, 3)] == ["Z9", "A1", "M5"]


def test_deja_la_fecha_de_actualizacion_fuera_de_los_datos():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    rango, valores, _ = hoja.escrituras[-1]
    assert rango == "V1:V2" and valores[0] == ["ACTUALIZADO (hora CDMX)"]


def test_aplica_formatos_de_fecha_y_entero_sin_tocar_el_encabezado_ni_congelar():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones if "repeatCell" in p]
    tipos = [p["cell"]["userEnteredFormat"]["numberFormat"]["type"] for p in pedidos]
    assert tipos.count("DATE") == 3 and tipos.count("NUMBER") == 3
    assert all(p["range"]["startRowIndex"] == 1 for p in pedidos)                   # de la fila 2 en adelante
    assert not any("updateSheetProperties" in p for p in hoja.spreadsheet.peticiones)
    odometro = next(p for p in pedidos if p["range"]["startColumnIndex"] == m.ENCABEZADO.index("Odómetro"))
    assert odometro["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] == "#,##0"


def test_cuenta_altas_bajas_y_cambios_y_limpia_lo_que_sobra():
    hoja = _hoja_con(*_filas("A1", "A2", "A3", "A4"), fila_hoja("A5", Make="VIEJA"))
    nuevas = [fila_hoja("A1"), fila_hoja("A2", **{"Status Vehicle": "AVAILABLE"}), fila_hoja("A5", Make="NUEVA"), fila_hoja("A6")]
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas)
    assert (r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"]) == (5, 4, 1, 2, 2)
    assert hoja.limpiezas == ["A6:T6"]                       # la hoja tenía 5 placas y ahora hay 4
    assert [f[0] for f in hoja.celdas[1:5]] == ["A1", "A2", "A5", "A6"]


def test_no_limpia_si_la_hoja_no_queda_mas_corta():
    hoja = _hoja_con(*_filas("A1", "A2"))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1", "A2", "A3"))
    assert hoja.limpiezas == []


def test_amplia_la_hoja_si_las_filas_no_caben():
    hoja = _hoja_con(*_filas("A1"))
    hoja.row_count = 2
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1", "A2", "A3", "A4"))
    assert hoja.filas_agregadas > 0 and hoja.row_count >= 5


def test_agrega_columnas_si_la_hoja_no_llega_a_la_del_sello():
    hoja = _hoja_con(*_filas("A1"))
    hoja.col_count = 20
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert hoja.col_count >= m.COL_ESTADO and hoja.escrituras[-1][0] == "V1:V2"


def test_salvaguarda_si_maxinet_trae_menos_del_80_por_ciento():
    hoja = _hoja_con(*_filas(*[f"P{i}" for i in range(40)]))
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(*[f"P{i}" for i in range(30)]))
    assert hoja.escrituras == []


def test_forzar_omite_la_salvaguarda(monkeypatch):
    monkeypatch.setenv("FORZAR", "1")
    hoja = _hoja_con(*_filas(*[f"P{i}" for i in range(40)]))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(*[f"P{i}" for i in range(30)]))
    assert hoja.escrituras


def test_una_hoja_chica_no_activa_la_salvaguarda():
    hoja = _hoja_con(*_filas(*[f"P{i}" for i in range(10)]))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("P0", "P1"))
    assert hoja.escrituras


def test_encabezado_distinto_detiene_sin_escribir():
    hoja = HojaFalsa([["Otra", "cosa"] + m.ENCABEZADO[2:], *_filas("A1")])
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert hoja.escrituras == []


def test_sin_placas_no_escribe_nada():
    hoja = _hoja_con(*_filas("A1", "A2"))
    with pytest.raises(RuntimeError, match="no trajo ninguna placa"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, [])
    assert hoja.escrituras == []


def test_dry_run_no_crea_ni_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    libro = Libro([])
    r = m.refrescar(None, libro, "Reporte Flota Ultima Renta", _filas("A1", "A2"))
    assert libro.hojas == [] and libro.peticiones == [] and r["altas"] == 2
    hoja = _hoja_con(*_filas("A1"))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1", "A2"))
    assert hoja.escrituras == [] and hoja.spreadsheet.peticiones == []


# ---------------------------------------------------------------- validación, nombre y reintentos
def test_validar_sin_repetidos_detecta_placas_repetidas():
    m.validar_sin_repetidos(_hoja_con(*_filas("A1", "A2", "A3")))
    with pytest.raises(RuntimeError, match="Placa repetida"):
        m.validar_sin_repetidos(_hoja_con(*_filas("A1", "A2", "A2")))


def test_nombre_de_la_hoja_tolera_comillas_y_espacios(monkeypatch):
    monkeypatch.delenv("WORKSHEET_FLOTA_ULTIMA_RENTA", raising=False)
    assert m.nombre_hoja() == "Reporte Flota Ultima Renta"
    monkeypatch.setenv("WORKSHEET_FLOTA_ULTIMA_RENTA", ' "Otra Hoja" ')
    assert m.nombre_hoja() == "Otra Hoja"


class _RespError:
    def __init__(self, codigo):
        self.status_code = codigo
        self.text = "x"

    def json(self):
        return {"error": {"code": self.status_code, "message": "cuota", "status": "X"}}


def _error(codigo):
    return gspread.exceptions.APIError(_RespError(codigo))


@pytest.fixture
def sin_esperas(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda s: None)


def test_reintenta_ante_429_y_termina(sin_esperas):
    llamadas = []

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise _error(429)
        return "ok"
    assert m._con_reintento(fn) == "ok" and len(llamadas) == 3


def test_no_reintenta_errores_que_no_son_de_cuota(sin_esperas):
    llamadas = []

    def fn():
        llamadas.append(1)
        raise _error(403)
    with pytest.raises(gspread.exceptions.APIError):
        m._con_reintento(fn)
    assert len(llamadas) == 1


def test_si_la_cuota_no_cede_falla_al_agotar_los_intentos(sin_esperas):
    llamadas = []

    def fn():
        llamadas.append(1)
        raise _error(429)
    with pytest.raises(gspread.exceptions.APIError):
        m._con_reintento(fn, intentos=3)
    assert len(llamadas) == 3
