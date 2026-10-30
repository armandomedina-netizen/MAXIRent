import datetime as dt
import json

import gspread
import pytest

import maxinet_expedientes_lp as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte

SERIE_5_MAR = (dt.date(2026, 3, 5) - dt.date(1899, 12, 30)).days


@pytest.fixture(autouse=True)
def limpiar_entorno(monkeypatch):
    for v in ("DRY_RUN", "FORZAR", "WORKSHEET_EXPEDIENTES_LP"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)


def _limpias(*filas):
    return m.normalizar_filas(list(filas))


def _hoja_con(*filas_hoja):
    return HojaFalsa([m.ENCABEZADO] + [list(f) for f in filas_hoja])


def _filas(*folios, **extra):
    return [fila_hoja(i, **extra) for i in folios]


# ---------------------------------------------------------------- forma de la tabla
def test_la_tabla_tiene_32_celdas_y_la_hoja_31_columnas_en_el_orden_pedido():
    assert m.ANCHO_REPORTE == 32 and len(m.ENCABEZADO) == 31
    assert m.ENCABEZADO[0] == "Folio" and m.ENCABEZADO[-1] == "Teléfono(Contacto)"
    assert "" not in m.ENCABEZADO
    assert m.ENCABEZADO[:6] == ["Folio", "Ejecutivo", "Fecha Registro", "Nombre", "Razón Social", "Validación CXC"]
    assert m.ENCABEZADO[26:] == ["Nombre(Compras)", "Email(Compras)", "Teléfono(Compras)", "Email(Contacto)", "Teléfono(Contacto)"]
    assert m.ULT_COL == "AE"
    assert m.FECHA | m.FECHA_HORA | m.NUMEROS <= set(m.ENCABEZADO)


def test_fecha_facturacion_no_se_trata_como_fecha():
    assert "Fecha Facturación" not in (m.FECHA | m.FECHA_HORA)         # en Maxinet trae un número de día
    assert m._valor("Fecha Facturación", "22") == "22"


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_html_entidades_y_none():
    assert m._texto('<a href="x" >Ver Expediente</a>') == "Ver Expediente"
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""


def test_normalizar_limpia_las_32_celdas():
    fila = _limpias(fila_reporte(6013))[0]
    assert len(fila) == 32 and fila[0] == "Ver Expediente"
    assert fila[m.COLUMNAS_REPORTE.index("Teléfono(Contacto)")] == "81 0000 0000"       # sin espacios sobrantes
    assert fila[m.COLUMNAS_REPORTE.index("Giro")] == "SERVICIOS"
    assert fila[m.COLUMNAS_REPORTE.index("Plazo")] == ""                              # 'None' -> vacío


def test_ancho_distinto_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte(1)[:31]])
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte(1) + ["x"]])


@pytest.mark.parametrize("campo,valor", [("Folio", "abc"), ("Fecha Registro", "05/03/2026"), ("Fecha Registro", "None")])
def test_columnas_que_no_cuadran_detienen_sin_escribir(campo, valor):
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas([fila_reporte(1, **{campo: valor})])


def test_folio_repetido_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="repetido"):
        m.normalizar_filas([fila_reporte(7), fila_reporte(7)])


def test_folio_y_fechas_se_tipan():
    assert m._valor("Folio", "6013") == 6013 and isinstance(m._valor("Folio", "6013"), int)
    assert m._valor("Fecha Registro", "2026-03-05") == SERIE_5_MAR
    con_hora = m._valor("Fecha Validación CXC", "2026-03-05 12:00:00")
    assert con_hora == pytest.approx(SERIE_5_MAR + 0.5)
    assert m._valor("Fecha de la presentación", "2026-03-05 06:30") == pytest.approx(SERIE_5_MAR + 0.25 + 0.0)


@pytest.mark.parametrize("nombre,texto", [
    ("Fecha Validación CXC", "0000-00-00 00:00:00"),    # fecha vacía de MySQL
    ("Fecha Validación Mtto", "2026-02-30 10:00:00"),    # fecha inexistente
    ("Fecha Registro", "1999-01-01"),                    # año fuera de rango
    ("Fecha Validación Gcia", "pendiente"),
    ("Folio", "12A"),
    ("No. Cliente Prohire", "#33860235"),                # los folios y los teléfonos siempre son texto
    ("Plazo", "0"),
    ("Plazo Renta", "CLIENTE SIN UNIDADES // Venta no cerrada"),
    ("Fecha Facturación", "7"),
    ("Teléfono(Compras)", "442 832 9960"),
    ("Giro", "=SUM(A1)"),
])
def test_lo_que_no_tiene_la_forma_esperada_o_no_es_fecha_queda_como_texto(nombre, texto):
    assert m._valor(nombre, texto) == texto and isinstance(m._valor(nombre, texto), str)


def test_vacio_sigue_vacio():
    assert all(m._valor(n, "") == "" for n in ("Folio", "Fecha Registro", "Fecha Validación CXC", "Giro"))


def test_fila_de_la_hoja_tiene_31_columnas_y_conserva_el_contacto():
    fila = fila_hoja(6013)
    assert len(fila) == 31 and fila[0] == 6013 and fila[2] == SERIE_5_MAR
    assert "contacto@example.com" in fila and "81 0000 0000" in fila


# ---------------------------------------------------------------- consulta a Maxinet
class _Resp:
    def __init__(self, cuerpo):
        self.content = ("﻿" + cuerpo).encode("utf-8")


class _Sesion:
    def __init__(self, cuerpo):
        self.cuerpo, self.pedidos = cuerpo, []

    def post(self, url, data=None, timeout=None):
        self.pedidos.append((url, data))
        return _Resp(self.cuerpo)


def test_consultar_manda_los_valores_por_defecto_de_la_pagina(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor/maxinetv2/")
    s = _Sesion(json.dumps({"data": [fila_reporte(1)]}))
    assert len(m.consultar(s)) == 1
    url, datos = s.pedidos[0]
    assert url == "http://servidor/maxinetv2/includes/prospeccion/expedientesData.php"
    assert datos == {"Criterio": "ESTATUS", "Estatus": "1", "Desde": "", "Hasta": "", "valueCriterio": ""}


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_Sesion('{"data":""}')) == []


def test_consultar_con_data_inesperado_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_Sesion('{"data":{"a":1}}'))


# ---------------------------------------------------------------- reescritura de la hoja
def test_primera_corrida_crea_la_pestana_y_la_escribe_tipada():
    libro = Libro([])
    r = m.refrescar(None, libro, "EXPEDIENTES LP", _filas(10, 20, 30))
    hoja = libro.worksheet("EXPEDIENTES LP")
    assert libro.creadas == ["EXPEDIENTES LP"]
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A1:AE4" and modo == "RAW" and valores[0] == m.ENCABEZADO and len(valores) == 4
    assert hoja.celdas[1][0] == 10 and hoja.celdas[1][2] == SERIE_5_MAR
    assert (r["antes"], r["despues"], r["altas"], r["bajas"]) == (0, 3, 3, 0)


def test_conserva_el_orden_en_que_maxinet_entrega_las_filas():
    libro = Libro([])
    m.refrescar(None, libro, "EXPEDIENTES LP", _filas(6013, 8871, 2364))
    hoja = libro.worksheet("EXPEDIENTES LP")
    assert [hoja.celdas[i][0] for i in (1, 2, 3)] == [6013, 8871, 2364]


def test_deja_la_fecha_de_actualizacion_fuera_de_los_datos():
    libro = Libro([])
    m.refrescar(None, libro, "EXPEDIENTES LP", _filas(1))
    rango, valores, _ = libro.worksheet("EXPEDIENTES LP").escrituras[1]
    assert rango == "AG1:AG2" and valores[0] == ["ACTUALIZADO (hora CDMX)"]


def test_aplica_formatos_de_fecha_y_congela_el_encabezado():
    libro = Libro([])
    m.refrescar(None, libro, "EXPEDIENTES LP", _filas(1))
    tipos = [p["repeatCell"]["cell"]["userEnteredFormat"].get("numberFormat", {}).get("type")
             for p in libro.peticiones if "repeatCell" in p]
    assert tipos.count("DATE") == len(m.FECHA) and tipos.count("DATE_TIME") == len(m.FECHA_HORA)
    assert any("updateSheetProperties" in p for p in libro.peticiones)


def test_cuenta_altas_bajas_y_cambios_y_limpia_lo_que_sobra():
    hoja = _hoja_con(*_filas(1, 2, 3, 4), fila_hoja(5, Giro="ENERGIA"))
    nuevas = [fila_hoja(1), fila_hoja(2, **{"Validación CXC": "RECHAZADO"}), fila_hoja(5, Giro="SERVICIOS"), fila_hoja(6)]
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas)
    assert (r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"]) == (5, 4, 1, 2, 2)
    assert hoja.limpiezas == ["A6:AE6"]                      # la hoja tenía 5 expedientes y ahora hay 4
    assert [f[0] for f in hoja.celdas[1:5]] == [1, 2, 5, 6]


def test_no_limpia_si_la_hoja_no_queda_mas_corta():
    hoja = _hoja_con(*_filas(1, 2))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3))
    assert hoja.limpiezas == []


def test_amplia_la_hoja_si_las_filas_no_caben():
    hoja = _hoja_con(*_filas(1))
    hoja.row_count = 2
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3, 4))
    assert hoja.filas_agregadas > 0 and hoja.row_count >= 5


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


def test_sin_expedientes_no_escribe_nada():
    hoja = _hoja_con(*_filas(1, 2))
    with pytest.raises(RuntimeError, match="no trajo ningún expediente"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, [])
    assert hoja.escrituras == []


def test_dry_run_no_crea_ni_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    libro = Libro([])
    r = m.refrescar(None, libro, "EXPEDIENTES LP", _filas(1, 2))
    assert libro.hojas == [] and libro.peticiones == [] and r["altas"] == 2
    hoja = _hoja_con(*_filas(1))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2))
    assert hoja.escrituras == []


# ---------------------------------------------------------------- validación, nombre y reintentos
def test_validar_sin_repetidos_detecta_folios_repetidos():
    m.validar_sin_repetidos(_hoja_con(*_filas(1, 2, 3)))
    with pytest.raises(RuntimeError, match="Folio repetido"):
        m.validar_sin_repetidos(_hoja_con(*_filas(1, 2, 2)))


def test_nombre_de_la_hoja_tolera_comillas_y_espacios(monkeypatch):
    assert m.nombre_hoja() == "EXPEDIENTES LP"
    monkeypatch.setenv("WORKSHEET_EXPEDIENTES_LP", ' "EXPEDIENTES X" ')
    assert m.nombre_hoja() == "EXPEDIENTES X"


class _RespError:
    def __init__(self, codigo):
        self.status_code = codigo
        self.text = "x"

    def json(self):
        return {"error": {"code": self.status_code, "message": "cuota", "status": "X"}}


def _error(codigo):
    return gspread.exceptions.APIError(_RespError(codigo))


def test_reintenta_ante_429_y_termina():
    llamadas = []

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise _error(429)
        return "ok"
    assert m._con_reintento(fn) == "ok" and len(llamadas) == 3


def test_no_reintenta_errores_que_no_son_de_cuota():
    llamadas = []

    def fn():
        llamadas.append(1)
        raise _error(403)
    with pytest.raises(gspread.exceptions.APIError):
        m._con_reintento(fn)
    assert len(llamadas) == 1


def test_si_la_cuota_no_cede_falla_al_agotar_los_intentos():
    with pytest.raises(gspread.exceptions.APIError):
        m._con_reintento(lambda: (_ for _ in ()).throw(_error(429)), intentos=3)
