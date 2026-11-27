"""Unidades en proceso de venta en la Base LP: limpieza, tipos, salvaguardas y reescritura (sin red ni Sheets reales)."""
import json

import gspread
import pytest

import maxinet_unidades_venta as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte

SERIE_FECHA_COMPRA = 43350                # 2018-09-07 como número de serie de Sheets
SERIE_FECHA_ALTA = 46251                  # 2026-08-17
ESTATUS_HTML = '<span style="color:orange;">Propuesta</span>'


def _limpias(*filas):
    return m.normalizar_filas(list(filas))


def _filas(*ids):
    """Filas de la hoja (tipadas) para esos Id, como las deja una corrida."""
    return [fila_hoja(i) for i in ids]


def _hoja_con(*filas):
    return HojaFalsa([m.ENCABEZADO, *filas])


# ---------------------------------------------------------------- estructura
def test_la_tabla_tiene_45_columnas_en_el_orden_de_la_pagina_y_el_reporte_47_celdas():
    assert len(m.ENCABEZADO) == m.ANCHO_TABLA == 45 and m.ANCHO_REPORTE == 47 and len(set(m.ENCABEZADO)) == 45
    assert m.ENCABEZADO[0] == "Id" and m.ENCABEZADO[1] == "Placa" and m.ENCABEZADO[-1] == "Remanente ajustado 14%"
    assert m.ENCABEZADO[40] == "Precio caja" and m.COL_ID == 0
    assert m.ULT_COL == "AS" and m._col_a1(m.COL_ESTADO) == "AU"       # los datos acaban en AS; el sello va dos columnas después
    for grupo in (m.FECHA, m.DINERO, set(m.NUMEROS)):
        assert grupo <= set(m.ENCABEZADO)
    assert not (m.FECHA & m.DINERO) and not (m.FECHA & set(m.NUMEROS)) and not (m.DINERO & set(m.NUMEROS))


def test_las_14_columnas_de_dinero_las_5_fechas_y_las_6_medidas():
    assert len(m.DINERO) == 14 and len(m.FECHA) == 5 and len(m.NUMEROS) == 6
    assert {"Precio Compra", "Precio Actual", "TT", "Remanente ajustado 14%"} <= m.DINERO
    assert {"Fecha Compra", "Fecha Venta", "Fecha Alta", "Fecha Liberado a TP", "EntryDate"} == m.FECHA


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_espacios_html_y_none():
    assert m._texto("AQUAFIM ") == "AQUAFIM"
    assert m._texto(ESTATUS_HTML) == "Propuesta"                         # la etiqueta de color: se guarda el texto visible
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""
    assert m._texto(0) == "0" and m._texto(2091.95) == "2091.95"


def test_normalizar_deja_las_45_columnas_y_descarta_el_boton_y_la_columna_oculta():
    fila = _limpias(fila_reporte(3065))[0]
    assert len(fila) == 45 and fila[0] == "3065" and fila[1] == "PLK3065A"
    assert fila[m.ENCABEZADO.index("Estatus A")] == "Propuesta"
    assert "Detalle" not in " ".join(fila)


@pytest.mark.parametrize("n", [46, 48, 49])
def test_ancho_distinto_detiene_sin_escribir(n):
    f = fila_reporte(1)
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([f[:n] if n < 47 else f + ["x"] * (n - 47)])


def test_id_vacio_o_repetido_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="sin Id"):
        m.normalizar_filas([fila_reporte(1, Id=None)])
    with pytest.raises(RuntimeError, match="repetido"):
        m.normalizar_filas([fila_reporte(1), fila_reporte(1)])


def test_una_placa_repetida_con_ids_distintos_es_valida():
    """Una placa puede volver a venderse: la llave es el Id, no la placa."""
    filas = _limpias(fila_reporte(1, Placa="AAA111"), fila_reporte(2, Placa="AAA111"))
    assert [f[1] for f in filas] == ["AAA111", "AAA111"]


def test_columnas_recorridas_detienen_sin_escribir():
    filas = [fila_reporte(i, **{"Fecha Compra": "Carga"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)
    filas = [fila_reporte(i, **{"Precio Compra": "CARGA"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)
    filas = [fila_reporte(i, **{"Año": "MARCA"}) for i in range(20)]
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas(filas)


def test_un_dato_raro_aislado_no_detiene_la_corrida_y_queda_como_texto():
    filas = [fila_reporte(i) for i in range(30)]
    filas[3] = fila_reporte(3, **{"Fecha Compra": "0000-00-00"})
    limpias = m.normalizar_filas(filas)
    k = m.ENCABEZADO.index("Fecha Compra")
    assert m.a_fila_hoja(limpias[3])[k] == "0000-00-00"
    assert m.a_fila_hoja(limpias[4])[k] == SERIE_FECHA_COMPRA


@pytest.mark.parametrize("texto,esperado", [
    ("$ 208,000.00", 208000), ("$ 1.00", 1), ("$ 0.00", 0), ("$ 1,820,001.16", 1820001.16),
    ("-$ 1,200.50", -1200.5), ("$ -1,200.50", -1200.5), ("-19424.91", -19424.91), ("179310.34", 179310.34), ("0", 0),
])
def test_los_precios_con_signo_de_pesos_o_sin_el_se_convierten_a_numero(texto, esperado):
    v = m._valor("Precio Compra", texto)
    assert v == esperado and not isinstance(v, str)


@pytest.mark.parametrize("texto", ["N/D", "$ ", "1.2.3", "$ 12 mil", "=SUM(A1)"])
def test_un_precio_sin_la_forma_esperada_queda_como_texto(texto):
    assert m._valor("Precio Compra", texto) == texto


def test_los_precios_enteros_se_guardan_enteros_y_los_decimales_como_decimal():
    assert type(m._valor("Precio Compra", "$ 208,000.00")) is int
    assert type(m._valor("Total MOI", "442551.72")) is float


def test_fechas_y_medidas_se_tipan():
    assert m._valor("Fecha Compra", "2018-09-07") == SERIE_FECHA_COMPRA
    assert m._valor("Id", "3065") == 3065 and type(m._valor("Id", "3065")) is int
    assert m._valor("Año", "2018") == 2018
    assert m._valor("Km Prohire", "116269.00") == 116269 and type(m._valor("Km Prohire", "116269.00")) is int
    assert m._valor("% Utilización", "38.30") == 38.3
    assert m._valor("Meses Uso", "95") == 95
    cero = m._valor("% Utilización", "0.00")
    assert cero == 0 and not isinstance(cero, str)                                   # el cero es un dato, no un vacío


@pytest.mark.parametrize("nombre,texto", [
    ("Fecha Compra", "0000-00-00"),                     # fecha vacía de MySQL
    ("Fecha Alta", "2026-02-30"),                       # fecha inexistente
    ("EntryDate", "1999-01-01"),                        # año fuera de rango
    ("Km Prohire", "116,269.00"),
    ("# Cliente", "#4799998"),                          # el número de cliente es texto
    ("Placa", "@LG41116"),                              # empieza con @: siempre texto
    ("Placa", "123456"),                                # una placa sólo con dígitos tampoco es número
    ("Grupo", "3.5RE"),
    ("No. Serie", "1234567890"),
    ("Cliente", "=SUM(A1)"),
    ("RFC", "XAXX010101000"),
])
def test_lo_que_no_es_fecha_precio_ni_medida_queda_como_texto(nombre, texto):
    v = m._valor(nombre, texto)
    assert v == texto and isinstance(v, str)


def test_vacio_sigue_vacio():
    assert all(m._valor(n, "") == "" for n in ("Precio Compra", "Fecha Venta", "Km Visual", "Cliente"))


def test_fila_de_la_hoja_tiene_45_columnas_tipadas():
    fila = fila_hoja(3065)
    k = m.ENCABEZADO.index
    assert len(fila) == 45 and fila[k("Id")] == 3065 and fila[k("Placa")] == "PLK3065A"
    assert fila[k("Estatus A")] == "Propuesta" and fila[k("Estatus B")] == ""
    assert fila[k("Precio Compra")] == 208000 and fila[k("Costo Adecuaciones")] == 1
    assert fila[k("Precio Final Venta")] == "" and fila[k("Fecha Venta")] == ""
    assert fila[k("Fecha Compra")] == SERIE_FECHA_COMPRA and fila[k("Fecha Alta")] == SERIE_FECHA_ALTA
    assert fila[k("Meses Uso")] == 95 and fila[k("Total MOI")] == 179310.34 and fila[k("Precio caja")] == 0
    assert fila[k("Remanente ajustado 14%")] == -19424.91 and fila[k("# Cliente")] == ""


# ---------------------------------------------------------------- consulta a Maxinet
class _Resp:
    def __init__(self, cuerpo):
        self.content = ("﻿" + cuerpo).encode("utf-8")


class _Sesion:
    def __init__(self, cuerpo):
        self.cuerpo, self.pedidos = cuerpo, []

    def post(self, url, data=None, timeout=None):
        self.pedidos.append((url, data))
        cuerpo = self.cuerpo[data["Estatus"]] if isinstance(self.cuerpo, dict) and data["Estatus"] in self.cuerpo else self.cuerpo
        return _Resp(cuerpo)


def test_consultar_pide_el_endpoint_del_reporte_con_el_estatus(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor/maxinetv2/")
    s = _Sesion(json.dumps({"data": [fila_reporte(1)]}))
    assert len(m.consultar(s, "1")) == 1
    assert s.pedidos == [("http://servidor/maxinetv2/json/unidades-venta-all.php", {"Estatus": "1", "Desde": "", "Hasta": ""})]


def test_por_omision_se_pide_solo_el_estatus_abierto(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    monkeypatch.delenv("ESTATUS_UNIDADES_VENTA", raising=False)
    s = _Sesion(json.dumps({"data": [fila_reporte(1), fila_reporte(2)]}))
    assert len(m.consultar_todos(s)) == 2
    assert [d["Estatus"] for _, d in s.pedidos] == ["1"]


def test_varios_estatus_se_juntan_sin_repetir_id(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    monkeypatch.setenv("ESTATUS_UNIDADES_VENTA", " 1, 10 ")
    s = _Sesion({"1": json.dumps({"data": [fila_reporte(1), fila_reporte(2)]}),
                 "10": json.dumps({"data": [fila_reporte(2), fila_reporte(3)]})})
    filas = m.consultar_todos(s)
    assert [f[2] for f in filas] == ["1", "2", "3"] and [d["Estatus"] for _, d in s.pedidos] == ["1", "10"]


@pytest.mark.parametrize("valor", ["abierto", "1;10", "1,x"])
def test_un_estatus_invalido_falla_antes_de_consultar(monkeypatch, valor):
    monkeypatch.setenv("ESTATUS_UNIDADES_VENTA", valor)
    with pytest.raises(RuntimeError, match="inválido"):
        m.estatus_a_consultar()


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_Sesion(json.dumps({"data": ""})), "1") == []
    assert m.consultar(_Sesion(json.dumps({"data": []})), "1") == []


def test_consultar_con_respuesta_inesperada_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_Sesion(json.dumps({"data": {"a": 1}})), "1")
    with pytest.raises(RuntimeError, match="ya no trae 'data'"):
        m.consultar(_Sesion(json.dumps({"dataReservas": [fila_reporte(1)]})), "1")
    with pytest.raises(RuntimeError, match="ya no trae 'data'"):
        m.consultar(_Sesion(json.dumps([])), "1")


# ---------------------------------------------------------------- reescritura de la hoja
def test_en_la_hoja_ya_armada_escribe_los_datos_sin_tocar_el_encabezado():
    hoja = _hoja_con()
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3))
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A2:AS4" and modo == "RAW" and len(valores) == 3 and valores[0][0] == 1
    assert all(not e[0].startswith("A1:") for e in hoja.escrituras)                 # la fila 1 es de quien armó la hoja
    assert (r["antes"], r["despues"], r["altas"], r["bajas"]) == (0, 3, 3, 0)


def test_una_hoja_con_el_encabezado_vacio_lo_recibe():
    hoja = HojaFalsa([])
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    assert hoja.escrituras[0][:2] == ("A1:AS1", [m.ENCABEZADO])


def test_conserva_el_orden_en_que_maxinet_entrega_las_filas():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(30, 10, 20))
    assert [hoja.celdas[i][0] for i in (1, 2, 3)] == [30, 10, 20]


def test_deja_la_fecha_de_actualizacion_fuera_de_los_datos():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    rango, valores, _ = hoja.escrituras[-1]
    assert rango == "AU1:AU2" and valores[0] == ["ACTUALIZADO (hora CDMX)"]


def test_aplica_formatos_de_fecha_moneda_y_numero_sin_tocar_el_encabezado_ni_congelar():
    hoja = _hoja_con()
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones if "repeatCell" in p]
    tipos = [p["cell"]["userEnteredFormat"]["numberFormat"]["type"] for p in pedidos]
    assert tipos.count("DATE") == 5 and tipos.count("CURRENCY") == 14 and tipos.count("NUMBER") == 6
    assert all(p["range"]["startRowIndex"] == 1 for p in pedidos)                   # de la fila 2 en adelante
    assert not any("updateSheetProperties" in p for p in hoja.spreadsheet.peticiones)
    patron = {p["range"]["startColumnIndex"]: p["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] for p in pedidos}
    assert patron[m.ENCABEZADO.index("Precio Compra")] == "$#,##0.00"
    assert patron[m.ENCABEZADO.index("Remanente ajustado 14%")] == "$#,##0.00"
    assert patron[m.ENCABEZADO.index("Km Prohire")] == "#,##0"
    assert patron[m.ENCABEZADO.index("% Utilización")] == "0.00"
    assert patron[m.ENCABEZADO.index("Fecha Venta")] == "yyyy-mm-dd"
    assert len(patron) == 25                                                         # 5 + 14 + 6, cada columna una vez


def test_cuenta_altas_bajas_y_cambios_y_limpia_lo_que_sobra():
    hoja = _hoja_con(*_filas(1, 2, 3, 4), fila_hoja(5, Grupo="VIEJO"))
    nuevas = [fila_hoja(1), fila_hoja(2, **{"Precio Final Venta": "$ 205,000.00"}), fila_hoja(5, Grupo="NUEVO"), fila_hoja(6)]
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas)
    assert (r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"]) == (5, 4, 1, 2, 2)
    assert hoja.limpiezas == ["A6:AS6"]                       # la hoja tenía 5 unidades y ahora hay 4
    assert [f[0] for f in hoja.celdas[1:5]] == [1, 2, 5, 6]


def test_los_decimales_que_devuelve_sheets_no_cuentan_como_cambios():
    """Sheets devuelve 3065 donde se escribió 3065.0: la comparación con lo que ya había no debe verlo como cambio."""
    nuevas = _filas(1, 2)
    hoja = _hoja_con(*[[int(x) if isinstance(x, float) and x == int(x) else x for x in f] for f in nuevas])
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas)
    assert r["cambios"] == 0 and r["altas"] == 0 and r["bajas"] == 0


def test_un_precio_que_cambia_si_cuenta_como_cambio():
    hoja = _hoja_con(fila_hoja(1))
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, [fila_hoja(1, **{"Precio Actual": "$ 425,600.00"})])
    assert r["cambios"] == 1


def test_una_fila_vieja_incompleta_no_rompe_la_lectura():
    hoja = HojaFalsa([m.ENCABEZADO, [7, "X"], [1, "PLK1A"]])
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    assert r["antes"] == 2


def test_no_limpia_si_la_hoja_no_queda_mas_corta():
    hoja = _hoja_con(*_filas(1, 2))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3))
    assert hoja.limpiezas == []


def test_amplia_la_hoja_si_las_filas_no_caben():
    hoja = _hoja_con(*_filas(1))
    hoja.row_count = 2
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3, 4))
    assert hoja.filas_agregadas > 0 and hoja.row_count >= 5


def test_agrega_columnas_si_la_hoja_no_llega_a_la_del_sello():
    hoja = _hoja_con(*_filas(1))
    hoja.col_count = 26
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    assert hoja.col_count >= m.COL_ESTADO and hoja.escrituras[-1][0] == "AU1:AU2"


def test_salvaguarda_si_maxinet_trae_menos_del_80_por_ciento():
    hoja = _hoja_con(*_filas(*range(1, 41)))
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(*range(1, 31)))
    assert hoja.escrituras == []


def test_forzar_omite_la_salvaguarda(monkeypatch):
    monkeypatch.setenv("FORZAR", "1")
    hoja = _hoja_con(*_filas(*range(1, 41)))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(*range(1, 31)))
    assert hoja.escrituras


def test_una_hoja_chica_no_activa_la_salvaguarda():
    hoja = _hoja_con(*_filas(*range(1, 11)))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2))
    assert hoja.escrituras


def test_encabezado_distinto_detiene_sin_escribir():
    hoja = HojaFalsa([["Otra", "cosa"] + m.ENCABEZADO[2:], *_filas(1)])
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    assert hoja.escrituras == []


def test_la_nota_que_hay_hoy_en_la_pestana_detiene_sin_escribir_hasta_retirarla():
    """La pestaña nació con una nota en A1 y la URL en A2: no es un encabezado y la corrida no lo pisa por su cuenta."""
    hoja = HojaFalsa([["Armando Medina APOYAME A VACIAR ESTA INF"], ["http://servidor/Unidades-Venta.php"]])
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1))
    assert hoja.escrituras == []


def test_sin_unidades_no_escribe_nada():
    hoja = _hoja_con(*_filas(1, 2))
    with pytest.raises(RuntimeError, match="no trajo ninguna unidad"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, [])
    assert hoja.escrituras == []


def test_dry_run_no_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    hoja = _hoja_con(*_filas(1))
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2))
    assert hoja.escrituras == [] and hoja.spreadsheet.peticiones == [] and r["altas"] == 1


# ---------------------------------------------------------------- la pestaña, validación, nombre y reintentos
def test_la_pestana_existente_se_obtiene_y_la_que_falta_detiene_sin_crearla():
    hoja = HojaFalsa([m.ENCABEZADO])
    libro = Libro([hoja])
    assert m.obtener_hoja(libro, "Unidades en Proceso de Venta") is hoja
    with pytest.raises(RuntimeError, match="no la crea"):
        m.obtener_hoja(libro, "Otra")
    assert libro.creadas == [] and len(libro.hojas) == 1


def test_validar_sin_repetidos_detecta_ids_repetidos():
    m.validar_sin_repetidos(_hoja_con(*_filas(1, 2, 3)))
    with pytest.raises(RuntimeError, match="Id repetido"):
        m.validar_sin_repetidos(_hoja_con(*_filas(1, 2, 2)))


def test_nombre_de_la_hoja_tolera_comillas_y_espacios(monkeypatch):
    monkeypatch.delenv("WORKSHEET_UNIDADES_VENTA", raising=False)
    assert m.nombre_hoja() == "Unidades en Proceso de Venta"
    monkeypatch.setenv("WORKSHEET_UNIDADES_VENTA", ' "Otra Hoja" ')
    assert m.nombre_hoja() == "Otra Hoja"
    monkeypatch.setenv("WORKSHEET_UNIDADES_VENTA", "")                      # un secret sin definir llega vacío desde Actions
    assert m.nombre_hoja() == "Unidades en Proceso de Venta"


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
