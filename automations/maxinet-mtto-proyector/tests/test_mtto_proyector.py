"""Proyector de mantenimiento en la Base LP: limpieza, tipos, salvaguardas y reescritura (sin red ni Sheets reales)."""
import json

import gspread
import pytest

import maxinet_mtto_proyector as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte

SERIE_FECHA_RENTA = 44377                 # 2021-06-30 como número de serie de Sheets
SERIE_ULT_MTTO = 45964                    # 2025-11-03
SERIE_PROX_MTTO = 46054                   # 2026-02-01
SERIE_SIG_MTTO = 46362                    # 2026-12-06

ESTATUS_HTML = '<a class="text-primary" href="lp-mtto-DetailOrden.php?Id=31013" target="_Blank">CITA APROBADA</a>'


def _limpias(*filas):
    return m.normalizar_filas(list(filas))


def _filas(*placas):
    """Filas de la hoja (tipadas) para esas placas, como las deja una corrida."""
    return [fila_hoja(p) for p in placas]


def _hoja_con(*filas):
    return HojaFalsa([m.ENCABEZADO, *filas])


# ---------------------------------------------------------------- estructura
def test_la_tabla_tiene_15_columnas_en_el_orden_de_la_pagina_y_el_reporte_una_celda_mas():
    assert len(m.ENCABEZADO) == m.ANCHO_TABLA == 15 and m.ANCHO_REPORTE == 16
    assert m.ENCABEZADO[0] == "FECHA RENTA" and m.ENCABEZADO[2] == "PLACA" and m.ENCABEZADO[-1] == "Fecha Prox. Mtto"
    assert m.ENCABEZADO[12] == "Fecha Sig. Mtto" and m.COL_PLACA == 2
    assert m.ULT_COL == "O" and m._col_a1(m.COL_ESTADO) == "Q"          # los datos acaban en O; el sello va dos columnas después
    assert m.FECHA <= set(m.ENCABEZADO) and m.FECHA_O_TEXTO <= set(m.ENCABEZADO) and set(m.NUMEROS) <= set(m.ENCABEZADO)
    assert not (m.FECHA & m.FECHA_O_TEXTO) and not ((m.FECHA | m.FECHA_O_TEXTO) & set(m.NUMEROS))


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_espacios_de_relleno_html_y_none():
    assert m._texto("AQUAFIM ") == "AQUAFIM"
    assert m._texto(ESTATUS_HTML) == "CITA APROBADA"                     # el enlace a la orden: se guarda el texto visible
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""
    assert m._texto(0) == "0" and m._texto(2) == "2"


def test_normalizar_deja_las_15_celdas_de_la_tabla_y_descarta_el_codigo_de_color():
    fila = _limpias(fila_reporte("TST001", ESTATUS=ESTATUS_HTML))[0]
    assert len(fila) == 15
    assert fila[m.ENCABEZADO.index("ESTATUS")] == "CITA APROBADA"
    assert fila[m.ENCABEZADO.index("CLIENTE")] == "CLIENTE FICTICIO SA DE CV"      # sin el espacio de relleno
    assert "2" not in fila[-1:] and fila[-1] == "2026-02-01"


def test_placa_con_espacios_se_limpia():
    assert _limpias(fila_reporte("  PM8759A "))[0][m.COL_PLACA] == "PM8759A"


@pytest.mark.parametrize("n", [15, 17])
def test_ancho_distinto_detiene_sin_escribir(n):
    f = fila_reporte("TST001")
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([f[:n] if n < 16 else f + ["x"]])


def test_placa_vacia_o_repetida_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="sin Placa"):
        m.normalizar_filas([fila_reporte(None)])
    with pytest.raises(RuntimeError, match="repetida"):
        m.normalizar_filas([fila_reporte("TST001"), fila_reporte("TST001")])


def test_columnas_recorridas_detienen_sin_escribir():
    filas = [fila_reporte(f"TST{i:03d}", **{"FECHA RENTA": "GRUPO1"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)
    filas = [fila_reporte(f"TST{i:03d}", **{"Odometro ult.Mtto": "SIN DATO"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)
    filas = [fila_reporte(f"TST{i:03d}", **{"Fecha Prox. Mtto": "VENCIDO"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)
    filas = [fila_reporte(f"TST{i:03d}", codigo="2026-02-01") for i in range(20)]
    with pytest.raises(RuntimeError, match="código de color"):
        m.normalizar_filas(filas)


def test_un_dato_raro_aislado_no_detiene_la_corrida_y_queda_como_texto():
    filas = [fila_reporte(f"TST{i:03d}") for i in range(30)]
    filas[3] = fila_reporte("TST003", **{"Fecha Ult.Mtto": "0000-00-00"})
    limpias = m.normalizar_filas(filas)
    assert m.a_fila_hoja(limpias[3])[13] == "0000-00-00"
    assert m.a_fila_hoja(limpias[4])[13] == SERIE_ULT_MTTO


def test_unidad_sin_mantenimiento_previo_trae_las_fechas_vacias():
    f = fila_reporte("TST001", **{"Fecha Ult.Mtto": None, "Fecha Prox. Mtto": ""}, codigo=3)
    fila = fila_hoja("TST001", **{"Fecha Ult.Mtto": None, "Fecha Prox. Mtto": ""}, codigo=3)
    assert m.normalizar_filas([f])[0][13:] == ["", ""]
    assert fila[13] == "" and fila[14] == ""


def test_fechas_y_numeros_se_tipan():
    assert m._valor("FECHA RENTA", "2021-06-30") == SERIE_FECHA_RENTA
    v = m._valor("Odometro ult.Mtto", "55194.00")
    assert v == 55194 and isinstance(v, float)
    k = m._valor("Km. de Regla", "10000")
    assert k == 10000 and isinstance(k, int)
    assert m._valor("% Vencimiento", "21.90") == 21.9
    assert m._valor("Km Recorridos desde Ult. Mtto", "-12.50") == -12.5          # una lectura menor a la anterior
    cero = m._valor("% Vencimiento", "0.00")
    assert cero == 0 and isinstance(cero, float)                                  # el cero es un dato, no un vacío


def test_fecha_sig_mtto_mezcla_fechas_y_semaforos():
    assert m._valor("Fecha Sig. Mtto", "2026-12-06") == SERIE_SIG_MTTO
    for texto in ("MAYOR A 1 MES", "VENCIDO", "KMS EN 0"):
        assert m._valor("Fecha Sig. Mtto", texto) == texto


@pytest.mark.parametrize("nombre,texto", [
    ("FECHA RENTA", "0000-00-00"),                      # fecha vacía de MySQL
    ("Fecha Prox. Mtto", "2026-02-30"),                 # fecha inexistente
    ("Fecha Ult.Mtto", "1999-01-01"),                   # año fuera de rango
    ("Odometro ult.Mtto", "55,194.00"),
    ("Km. de Regla", "10000 km"),
    ("PLACA", "@LG41116"),                              # empieza con @: siempre texto
    ("PLACA", "123456"),                                # una placa sólo con dígitos tampoco es número
    ("GRUPO", "3.5RE"),
    ("ESTATUS", "POR CITAR"),
    ("CLIENTE", "=SUM(A1)"),
])
def test_lo_que_no_tiene_la_forma_esperada_o_no_es_fecha_o_numero_queda_como_texto(nombre, texto):
    assert m._valor(nombre, texto) == texto and isinstance(m._valor(nombre, texto), str)


def test_vacio_sigue_vacio():
    assert all(m._valor(n, "") == "" for n in ("Odometro ult.Mtto", "FECHA RENTA", "Fecha Sig. Mtto", "CLIENTE"))


def test_fila_de_la_hoja_tiene_15_columnas_tipadas():
    fila = fila_hoja("@LG41116", ESTATUS=ESTATUS_HTML, **{"Fecha Sig. Mtto": "2026-12-06"})
    assert len(fila) == 15 and fila[0] == SERIE_FECHA_RENTA and fila[2] == "@LG41116" and fila[3] == "CITA APROBADA"
    assert fila[7] == 55194 and fila[8] == 10000 and fila[9] == 65194 and fila[10] == 2190.16 and fila[11] == 21.9
    assert fila[12] == SERIE_SIG_MTTO and fila[13] == SERIE_ULT_MTTO and fila[14] == SERIE_PROX_MTTO


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
    s = _Sesion(json.dumps({"dataReservas": [fila_reporte("TST001")]}))
    assert len(m.consultar(s)) == 1
    assert s.pedidos == ["http://servidor/maxinetv2/includes/mttoLP/lp-mtto-proyeccionmtto-data.php"]


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_Sesion(json.dumps({"dataReservas": ""}))) == []
    assert m.consultar(_Sesion(json.dumps({"dataReservas": []}))) == []


def test_consultar_con_respuesta_inesperada_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_Sesion(json.dumps({"dataReservas": {"a": 1}})))
    with pytest.raises(RuntimeError, match="ya no trae 'dataReservas'"):
        m.consultar(_Sesion(json.dumps({"data": [fila_reporte("TST001")]})))
    with pytest.raises(RuntimeError, match="ya no trae 'dataReservas'"):
        m.consultar(_Sesion(json.dumps([])))


# ---------------------------------------------------------------- reescritura de la hoja
def test_en_la_hoja_ya_armada_escribe_los_datos_sin_tocar_el_encabezado():
    hoja = _hoja_con()
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1", "A2", "A3"))
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A2:O4" and modo == "RAW" and len(valores) == 3 and valores[0][2] == "A1"
    assert all(not e[0].startswith("A1:") for e in hoja.escrituras)                 # la fila 1 es de quien armó la hoja
    assert (r["antes"], r["despues"], r["altas"], r["bajas"]) == (0, 3, 3, 0)


def test_una_hoja_con_el_encabezado_vacio_lo_recibe():
    hoja = HojaFalsa([])
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert hoja.escrituras[0][:2] == ("A1:O1", [m.ENCABEZADO])


def test_conserva_el_orden_en_que_maxinet_entrega_las_filas():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("Z9", "A1", "M5"))
    assert [hoja.celdas[i][2] for i in (1, 2, 3)] == ["Z9", "A1", "M5"]


def test_deja_la_fecha_de_actualizacion_fuera_de_los_datos():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    rango, valores, _ = hoja.escrituras[-1]
    assert rango == "Q1:Q2" and valores[0] == ["ACTUALIZADO (hora CDMX)"]


def test_aplica_formatos_de_fecha_y_numero_sin_tocar_el_encabezado_ni_congelar():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones if "repeatCell" in p]
    tipos = [p["cell"]["userEnteredFormat"]["numberFormat"]["type"] for p in pedidos]
    assert tipos.count("DATE") == 4 and tipos.count("NUMBER") == 5
    assert all(p["range"]["startRowIndex"] == 1 for p in pedidos)                   # de la fila 2 en adelante
    assert not any("updateSheetProperties" in p for p in hoja.spreadsheet.peticiones)
    patron = {p["range"]["startColumnIndex"]: p["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] for p in pedidos}
    assert patron[m.ENCABEZADO.index("Odometro ult.Mtto")] == "#,##0.00"
    assert patron[m.ENCABEZADO.index("Km. de Regla")] == "#,##0"                    # como la página: sin decimales
    assert patron[m.ENCABEZADO.index("% Vencimiento")] == "0.00"
    assert patron[m.ENCABEZADO.index("Fecha Sig. Mtto")] == "yyyy-mm-dd"            # la columna mixta: las fechas se ven como fecha


def test_cuenta_altas_bajas_y_cambios_y_limpia_lo_que_sobra():
    hoja = _hoja_con(*_filas("A1", "A2", "A3", "A4"), fila_hoja("A5", GRUPO="VIEJO"))
    nuevas = [fila_hoja("A1"), fila_hoja("A2", **{"Fecha Sig. Mtto": "VENCIDO"}), fila_hoja("A5", GRUPO="NUEVO"), fila_hoja("A6")]
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas)
    assert (r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"]) == (5, 4, 1, 2, 2)
    assert hoja.limpiezas == ["A6:O6"]                       # la hoja tenía 5 placas y ahora hay 4
    assert [f[2] for f in hoja.celdas[1:5]] == ["A1", "A2", "A5", "A6"]


def test_los_decimales_que_devuelve_sheets_no_cuentan_como_cambios():
    """Sheets devuelve 55194 donde se escribió 55194.0: la comparación con lo que ya había no debe verlo como cambio."""
    nuevas = _filas("A1", "A2")
    hoja = _hoja_con(*[[int(x) if isinstance(x, float) and x == int(x) else x for x in f] for f in nuevas])
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas)
    assert r["cambios"] == 0 and r["altas"] == 0 and r["bajas"] == 0


def test_un_numero_que_cambia_si_cuenta_como_cambio():
    hoja = _hoja_con(fila_hoja("A1"))
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, [fila_hoja("A1", **{"% Vencimiento": "22.40"})])
    assert r["cambios"] == 1


def test_una_fila_vieja_incompleta_no_rompe_la_lectura():
    hoja = HojaFalsa([m.ENCABEZADO, ["2021-06-30", "G"], [44377, "G", "A1"]])
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert r["antes"] == 1


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
    hoja.col_count = 15
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert hoja.col_count >= m.COL_ESTADO and hoja.escrituras[-1][0] == "Q1:Q2"


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


def test_el_encabezado_de_la_automatizacion_de_flota_ultima_renta_detiene_sin_escribir():
    """La pestaña (DATA) nació con los 20 encabezados de otro reporte: mientras no se cambien, la corrida no escribe."""
    viejo = ["Placa", "BSite", "CurrentSite", "PUDate Ult. Renta Cliente", "ReturnDate Ult. Renta Cliente",
             "Dias desde Ult. Renta Cliente", "Dias no disponibles", "Semáforo dias no disp.", "Odómetro",
             "Semáforo Odómetro", "Group", "Status Vehicle", "Make", "Model", "Booking Ult. Renta Cliente",
             "Cliente Ult. Renta", "PUSite Ult. Renta Cliente", "Estatus ult. renta Cliente",
             "ReturnDate Ult. Renta", "Name Ult. Renta"]
    hoja = HojaFalsa([viejo])
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1"))
    assert hoja.escrituras == [] and hoja.celdas[0] == viejo


def test_sin_placas_no_escribe_nada():
    hoja = _hoja_con(*_filas("A1", "A2"))
    with pytest.raises(RuntimeError, match="no trajo ninguna placa"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, [])
    assert hoja.escrituras == []


def test_dry_run_no_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    hoja = _hoja_con(*_filas("A1"))
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas("A1", "A2"))
    assert hoja.escrituras == [] and hoja.spreadsheet.peticiones == [] and r["altas"] == 1


# ---------------------------------------------------------------- la pestaña, validación, nombre y reintentos
def test_la_pestana_existente_se_obtiene_y_la_que_falta_detiene_sin_crearla():
    hoja = HojaFalsa([m.ENCABEZADO])
    libro = Libro([hoja])
    assert m.obtener_hoja(libro, "Proyección de Mantenimientos(DATA)") is hoja
    with pytest.raises(RuntimeError, match="no la crea"):
        m.obtener_hoja(libro, "Otra")
    assert libro.creadas == [] and len(libro.hojas) == 1


def test_validar_sin_repetidos_detecta_placas_repetidas():
    m.validar_sin_repetidos(_hoja_con(*_filas("A1", "A2", "A3")))
    with pytest.raises(RuntimeError, match="Placa repetida"):
        m.validar_sin_repetidos(_hoja_con(*_filas("A1", "A2", "A2")))


def test_nombre_de_la_hoja_tolera_comillas_y_espacios(monkeypatch):
    monkeypatch.delenv("WORKSHEET_MTTO_PROYECTOR", raising=False)
    assert m.nombre_hoja() == "Proyección de Mantenimientos(DATA)"
    monkeypatch.setenv("WORKSHEET_MTTO_PROYECTOR", ' "Otra Hoja" ')
    assert m.nombre_hoja() == "Otra Hoja"
    monkeypatch.setenv("WORKSHEET_MTTO_PROYECTOR", "")                      # un secret sin definir llega vacío desde Actions
    assert m.nombre_hoja() == "Proyección de Mantenimientos(DATA)"


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
