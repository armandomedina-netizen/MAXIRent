import datetime as dt
import json

import pytest

import maxinet_mtto_ordenes as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte

SERIE_5_OCT = (dt.date(2026, 10, 5) - dt.date(1899, 12, 30)).days


@pytest.fixture(autouse=True)
def limpiar_entorno(monkeypatch):
    for v in ("FECHA_DESDE", "FECHA_HASTA", "DRY_RUN", "FORZAR", "WORKSHEET_MTTO_ORDENES"):
        monkeypatch.delenv(v, raising=False)


def _limpias(*filas):
    return m.normalizar_filas(list(filas))


def _hoja_con(*filas_hoja):
    return HojaFalsa([m.ENCABEZADO] + [list(f) for f in filas_hoja])


# ---------------------------------------------------------------- forma del reporte
def test_el_reporte_tiene_62_columnas_y_la_hoja_55_sin_botones_ni_contacto():
    assert m.ANCHO_REPORTE == 62
    assert len(m.ENCABEZADO) == 55 and m.ENCABEZADO[0] == "Id" and m.ENCABEZADO[-1] == "IdApp"
    assert "" not in m.ENCABEZADO
    assert not set(m.COLUMNAS_CONTACTO) & set(m.ENCABEZADO)
    assert m.ULT_COL == "BC"
    assert m.FECHAS | m.HORAS | m.NUMEROS <= set(m.ENCABEZADO)


# ---------------------------------------------------------------- rango de fechas
@pytest.mark.parametrize("hoy,esperado", [
    (dt.date(2026, 10, 27), ("2026-10-01", "2026-10-26")),
    (dt.date(2026, 11, 2), ("2026-11-01", "2026-11-01")),
    (dt.date(2026, 11, 1), ("2026-10-01", "2026-10-31")),     # día 1: ayer cae en el mes anterior
    (dt.date(2026, 1, 1), ("2025-12-01", "2025-12-31")),
])
def test_ventana_es_el_mes_corriente_a_ayer(hoy, esperado):
    assert m.ventana(hoy) == esperado


def test_override_de_fechas(monkeypatch):
    monkeypatch.setenv("FECHA_DESDE", "2026-10-05")
    monkeypatch.setenv("FECHA_HASTA", "2026-10-20")
    assert m.ventana(dt.date(2026, 10, 27)) == ("2026-10-05", "2026-10-20")


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_html_entidades_y_none():
    assert m._texto('<a class="x" href="y">Detalle</a>') == "Detalle"
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""


def test_normalizar_limpia_los_62_valores_y_el_estatus():
    fila = _limpias(fila_reporte(25861, estatus="TRABAJO TERMINADO"))[0]
    assert len(fila) == 62 and fila[0] == "Detalle"
    assert fila[m.COLUMNAS_REPORTE.index("Estatus")] == "TRABAJO TERMINADO"      # sin el espacio inicial
    assert fila[m.COLUMNAS_REPORTE.index("Motivo Reingreso")] == ""            # 'None' -> vacío


def test_ancho_distinto_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte(1)[:61]])
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte(1) + ["x"]])


@pytest.mark.parametrize("campo,valor", [("Id", "abc"), ("Fecha Alta", "05/10/2026"), ("No.Placa", "None")])
def test_columnas_que_no_cuadran_detienen_sin_escribir(campo, valor):
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas([fila_reporte(1, **{campo: valor})])


def test_fechas_horas_y_numeros_se_tipan():
    assert m._valor("Fecha Alta", "2026-10-05") == SERIE_5_OCT
    assert m._valor("Hora Alta", "09:28") == pytest.approx((9 * 60 + 28) / 1440)
    assert m._valor("Hora Cita", "13:05:30") == pytest.approx((13 * 3600 + 5 * 60 + 30) / 86400)
    assert m._valor("Id", "25861") == 25861 and isinstance(m._valor("Id", "25861"), int)
    assert m._valor("Costo Total", "3665.60") == 3665.6
    assert m._valor("Costo Total", "1,234.50") == 1234.5
    assert m._valor("Km.Actual", "107290") == 107290
    assert m._valor("Dias Taller", "0.5") == 0.5


@pytest.mark.parametrize("nombre,texto", [
    ("Fecha Promesa", "0026-07-15"),          # año tecleado mal en Maxinet: se conserva el texto
    ("Fecha Cierre", "2027-04-26x"),
    ("Fecha Cita", "2026-02-30"),             # fecha inexistente
    ("Hora Alta", "25:99"),
    ("Costo Total", "N/A"),
    ("Estatus", "CERRADO"),
    ("# Reserva", "#217079644"),              # los folios y las placas siempre son texto
    ("Motivo Reingreso", "=SUM(A1)"),
    ("No.Placa", "1E5"),
])
def test_lo_que_no_tiene_la_forma_esperada_queda_como_texto(nombre, texto):
    assert m._valor(nombre, texto) == texto and isinstance(m._valor(nombre, texto), str)


def test_vacio_sigue_vacio():
    assert all(m._valor(n, "") == "" for n in ("Id", "Fecha Alta", "Hora Alta", "Costo Total", "Estatus"))


def test_fila_de_la_hoja_tiene_55_columnas_sin_datos_de_contacto():
    fila = fila_hoja(25861, "2026-10-05", "EN TALLER", "TEX769B")
    assert len(fila) == 55
    assert fila[m.COL_ID] == 25861 and fila[m.COL_FECHA_ALTA] == SERIE_5_OCT
    assert fila[m.COL_ESTATUS] == "EN TALLER" and fila[m.COL_PLACA] == "TEX769B"
    plano = json.dumps(fila, ensure_ascii=False)
    assert "PERSONA PRIVADA" not in plano and "8100000000" not in plano and "privado@example.com" not in plano


# ---------------------------------------------------------------- unión sin repetidos
def test_unir_no_repite_ordenes_y_ordena_por_id():
    ventana_ = _limpias(fila_reporte(30), fila_reporte(10, estatus="EN TALLER"))
    abiertas = _limpias(fila_reporte(10, estatus="EN TALLER"), fila_reporte(5, "2026-05-02", "EN REVISIÓN"))
    filas = m.unir(ventana_, abiertas)
    assert [f[m.COL_ID] for f in filas] == [5, 10, 30]
    assert all(len(f) == 55 for f in filas)


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


def test_consultar_manda_el_estatus_siempre_y_devuelve_las_filas(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor/maxinetv2/")
    s = _Sesion(json.dumps({"data": [fila_reporte(1)]}))
    assert len(m.consultar(s, "ALTA", "1", "2026-10-01", "2026-10-26")) == 1
    url, datos = s.pedidos[0]
    assert url == "http://servidor/maxinetv2/json/lp-mtto-ordenes.php"
    assert datos == {"Criterio": "ALTA", "Estatus": "1", "Desde": "2026-10-01", "Hasta": "2026-10-26", "valueCriterio": ""}


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_Sesion('{"data":""}'), "ALTA") == []


def test_consultar_con_data_inesperado_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_Sesion('{"data":{"a":1}}'), "ALTA")


# ---------------------------------------------------------------- reescritura de la hoja
def _filas(*ids, alta="2026-10-05", estatus="CERRADO"):
    return [fila_hoja(i, alta, estatus) for i in ids]


def test_primera_corrida_crea_la_pestana_y_la_escribe_tipada():
    libro = Libro([])
    r = m.refrescar(None, libro, "ORDENES MTTO", _filas(1, 2, 3), "2026-10-01", "2026-10-26")
    hoja = libro.worksheet("ORDENES MTTO")
    assert libro.creadas == ["ORDENES MTTO"]
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A1:BC4" and modo == "RAW" and valores[0] == m.ENCABEZADO and len(valores) == 4
    assert hoja.celdas[1][m.COL_ID] == 1 and hoja.celdas[1][m.COL_FECHA_ALTA] == SERIE_5_OCT
    assert (r["antes"], r["despues"], r["altas"], r["bajas"]) == (0, 3, 3, 0)


def test_deja_la_fecha_de_actualizacion_fuera_de_los_datos():
    libro = Libro([])
    m.refrescar(None, libro, "ORDENES MTTO", _filas(1), "2026-10-01", "2026-10-26")
    rango, valores, _ = libro.worksheet("ORDENES MTTO").escrituras[1]
    assert rango == "BE1:BE4" and valores[0] == ["ACTUALIZADO (hora CDMX)"] and "2026-10-01 a 2026-10-26" in valores[3][0]


def test_aplica_formatos_de_fecha_hora_y_costo_y_congela_el_encabezado():
    libro = Libro([])
    m.refrescar(None, libro, "ORDENES MTTO", _filas(1), "2026-10-01", "2026-10-26")
    tipos = [p["repeatCell"]["cell"]["userEnteredFormat"].get("numberFormat", {}).get("type")
             for p in libro.peticiones if "repeatCell" in p]
    assert tipos.count("DATE") == len(m.FECHAS) and tipos.count("TIME") == len(m.HORAS) and tipos.count("NUMBER") == 3
    assert any("updateSheetProperties" in p for p in libro.peticiones)


def test_cuenta_altas_bajas_y_estatus_cambiados_y_limpia_lo_que_sobra():
    hoja = _hoja_con(*_filas(1, 2, 3, 4), fila_hoja(5, estatus="EN TALLER"))
    nuevas = [fila_hoja(1), fila_hoja(2, estatus="CANCELADO"), fila_hoja(5, estatus="CERRADO"), fila_hoja(6)]
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas, "2026-10-01", "2026-10-26")
    assert (r["antes"], r["despues"], r["altas"], r["bajas"], r["estatus"]) == (5, 4, 1, 2, 2)
    assert hoja.limpiezas == ["A6:BC6"]                       # la hoja tenía 5 órdenes y ahora hay 4
    assert [f[m.COL_ID] for f in hoja.celdas[1:5]] == [1, 2, 5, 6]


def test_no_limpia_si_la_hoja_no_queda_mas_corta():
    hoja = _hoja_con(*_filas(1, 2))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3), "2026-10-01", "2026-10-26")
    assert hoja.limpiezas == []


def test_amplia_la_hoja_si_las_filas_no_caben():
    hoja = _hoja_con(*_filas(1))
    hoja.row_count = 2
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2, 3, 4), "2026-10-01", "2026-10-26")
    assert hoja.filas_agregadas > 0 and hoja.row_count >= 5


def test_salvaguarda_si_maxinet_trae_menos_del_80_por_ciento_del_rango():
    hoja = _hoja_con(*_filas(*range(1, 41)))                  # 40 órdenes de octubre en la hoja
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(*range(1, 31)), "2026-10-01", "2026-10-26")
    assert hoja.escrituras == []


def test_forzar_omite_la_salvaguarda(monkeypatch):
    monkeypatch.setenv("FORZAR", "1")
    hoja = _hoja_con(*_filas(*range(1, 41)))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(*range(1, 31)), "2026-10-01", "2026-10-26")
    assert hoja.escrituras


def test_salvaguarda_de_ordenes_abiertas():
    hoja = _hoja_con(*_filas(*range(1, 41), alta="2026-05-05", estatus="EN TALLER"))
    nuevas = _filas(*range(1, 21), alta="2026-05-05", estatus="EN TALLER") + _filas(*range(100, 140))
    with pytest.raises(RuntimeError, match="abiertas"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas, "2026-10-01", "2026-10-26")


def test_el_cambio_de_mes_no_dispara_la_salvaguarda():
    # octubre completo en la hoja (100 cerradas); el 2-nov el rango es sólo el 1-nov y la hoja se reduce a propósito
    hoja = _hoja_con(*_filas(*range(1, 101), alta="2026-10-15"))
    nuevas = _filas(*range(200, 210), alta="2026-11-01") + _filas(300, 301, alta="2026-09-02", estatus="EN TALLER")
    r = m.refrescar(hoja, hoja.spreadsheet, hoja.title, nuevas, "2026-11-01", "2026-11-01")
    assert r["despues"] == 12 and hoja.escrituras


def test_encabezado_distinto_detiene_sin_escribir():
    hoja = HojaFalsa([["Otra", "cosa"] + m.ENCABEZADO[2:], *_filas(1)])
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1), "2026-10-01", "2026-10-26")
    assert hoja.escrituras == []


def test_sin_ordenes_no_escribe_nada():
    hoja = _hoja_con(*_filas(1, 2))
    with pytest.raises(RuntimeError, match="no trajo ninguna orden"):
        m.refrescar(hoja, hoja.spreadsheet, hoja.title, [], "2026-10-01", "2026-10-26")
    assert hoja.escrituras == []


def test_dry_run_no_crea_ni_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    libro = Libro([])
    r = m.refrescar(None, libro, "ORDENES MTTO", _filas(1, 2), "2026-10-01", "2026-10-26")
    assert libro.hojas == [] and libro.peticiones == [] and r["altas"] == 2
    hoja = _hoja_con(*_filas(1))
    m.refrescar(hoja, hoja.spreadsheet, hoja.title, _filas(1, 2), "2026-10-01", "2026-10-26")
    assert hoja.escrituras == []


# ---------------------------------------------------------------- validación y nombre de la hoja
def test_validar_sin_repetidos_detecta_ids_repetidos():
    m.validar_sin_repetidos(_hoja_con(*_filas(1, 2, 3)))
    with pytest.raises(RuntimeError, match="Id repetido"):
        m.validar_sin_repetidos(_hoja_con(*_filas(1, 2, 2)))


def test_nombre_de_la_hoja_tolera_comillas_y_espacios(monkeypatch):
    assert m.nombre_hoja() == "ORDENES MTTO"
    monkeypatch.setenv("WORKSHEET_MTTO_ORDENES", ' "ORDENES X" ')
    assert m.nombre_hoja() == "ORDENES X"
