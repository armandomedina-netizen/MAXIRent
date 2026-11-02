import datetime as dt
import json
import logging

import gspread
import pytest

import maxinet_seminuevos_lp as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte, formulas_mes_anio

SERIE_31_OCT = (dt.date(2026, 10, 31) - dt.date(1899, 12, 30)).days


@pytest.fixture(autouse=True)
def limpiar_entorno(monkeypatch):
    for v in ("DRY_RUN", "FORZAR", "WORKSHEET_SEMINUEVOS_LP"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)


def _limpias(*filas):
    return m.normalizar_filas(list(filas))


def _hoja_con(*filas_hoja, **kw):
    return HojaFalsa([m.COLUMNAS] + [list(f) for f in filas_hoja], **kw)


def _placas(n, desde=0):
    return [f"PL{desde + i:04d}B" for i in range(n)]


def _filas(*placas, **extra):
    return [fila_hoja(p, **extra) for p in placas]


# ---------------------------------------------------------------- forma del reporte
def test_el_reporte_tiene_28_columnas_en_el_orden_de_la_hoja():
    assert m.ANCHO == 28 and m.ULT_COL_DATOS == "AB"
    assert m.COLUMNAS[:6] == ["Placa", "Seminuevos", "Dias en SN", "Ult. Renta", "Dias ult. renta", "SN Maxinet"]
    assert m.COLUMNAS[-3:] == ["PUDate Ult. Renta", "Estatus ult. renta", "BOOKED_ON"]
    assert len(set(m.COLUMNAS)) == 28 and "" not in m.COLUMNAS
    assert m.FECHAS | m.ENTEROS | m.IMPORTES <= set(m.COLUMNAS)
    assert not (m.FECHAS & m.ENTEROS) and not (m.FECHAS & m.IMPORTES) and not (m.ENTEROS & m.IMPORTES)


def test_columnas_de_cada_tipo_segun_la_hoja():
    assert m.FECHAS == {"Seminuevos", "Ult. Renta", "SN Maxinet", "Venta", "ReturnDate Previa", "PUDate Ult. Renta", "BOOKED_ON"}
    assert m.ENTEROS == {"Dias en SN", "Dias ult. renta", "Dias en Exhib."}
    assert m.IMPORTES == {"Gasto SN", "Garantía", "Recup.", "Total"}


def test_mes_y_anio_estan_fuera_de_las_columnas_que_se_reemplazan():
    assert (m.COL_DERIVADAS_INI, m.COL_DERIVADAS_FIN) == (28, 30)         # AC:AD
    assert m.COL_ESTADO == 32 and m._col_a1(m.COL_ESTADO) == "AF"


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_html_entidades_y_none():
    assert m._texto('<a href="#" class="detailCostos">RB5595A</a>') == "RB5595A"
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""


def test_normalizar_limpia_las_28_celdas():
    fila = _limpias(fila_reporte("RB5595A"))[0]
    assert len(fila) == 28 and fila[0] == "RB5595A"                       # la placa sale del enlace
    assert fila[m.COLUMNAS.index("Make")] == "TOYOTA"                       # sin espacios al final
    assert fila[m.COLUMNAS.index("Estatus ult. renta")] == "CHECKED IN"
    assert fila[m.COLUMNAS.index("SN Maxinet")] == ""                       # None -> vacío


def test_ancho_distinto_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte("RB5595A")[:27]])
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte("RB5595A") + ["x"]])


@pytest.mark.parametrize("campo,valor,mensaje", [
    ("Placa", "", "Placa"),
    ("Placa", "RB 5595 A", "Placa"),
    ("Seminuevos", "05/03/2026", "Seminuevos"),
    ("Venta", "pendiente", "Venta"),
    ("Dias en SN", "3.5", "Dias en SN"),
    ("Dias en Exhib.", "tres", "Dias en Exhib."),
    ("Total", "75,542.98", "Total"),                    # con coma de millares: otra forma de la esperada
    ("Gasto SN", "abc", "Gasto SN"),
])
def test_columnas_que_no_cuadran_detienen_sin_escribir(campo, valor, mensaje):
    with pytest.raises(RuntimeError, match="no cuadran") as e:
        m.normalizar_filas([fila_reporte("RB5595A", **{campo: valor})])
    assert mensaje in str(e.value)


def test_placa_repetida_detiene_sin_escribir_aunque_cambie_la_capitalizacion():
    with pytest.raises(RuntimeError, match="repetida"):
        m.normalizar_filas([fila_reporte("RB5595A"), fila_reporte("rb5595a")])


def test_los_valores_se_tipan_como_en_la_hoja():
    assert m._valor("Seminuevos", "2026-10-31") == SERIE_31_OCT and isinstance(m._valor("Seminuevos", "2026-10-31"), int)
    assert m._valor("Dias en SN", "227") == 227 and m._valor("Dias ult. renta", "-224") == -224
    assert m._valor("Total", "75542.98") == 75542.98 and m._valor("Gasto SN", "0") == 0.0
    assert m._valor("Recup.", "-3200.00") == -3200.0
    assert m._valor("Venta", "") == "" and m._valor("Garantía", "") == "" and m._valor("Dias en Exhib.", "") == ""


@pytest.mark.parametrize("nombre,texto", [
    ("Seminuevos", "0000-00-00"),          # fecha vacía de MySQL
    ("Venta", "2026-02-30"),               # fecha inexistente
    ("Ult. Renta", "1999-01-01"),          # año fuera de rango
    ("Placa", "123456"),                   # una placa sólo de números sigue siendo texto
    ("Booking Previa", "#222305323"),
    ("Job", "NO"),
    ("Model", "=SUM(A1)"),
])
def test_lo_que_no_es_fecha_numero_o_importe_queda_como_texto(nombre, texto):
    assert m._valor(nombre, texto) == texto and isinstance(m._valor(nombre, texto), str)


def test_fila_de_la_hoja_tiene_28_columnas_tipadas():
    fila = fila_hoja("RB5595A")
    assert len(fila) == 28 and fila[0] == "RB5595A"
    assert fila[m.COLUMNAS.index("BOOKED_ON")] == SERIE_31_OCT
    assert fila[m.COLUMNAS.index("Recup.")] == -3200.0 and fila[m.COLUMNAS.index("Total")] == 75542.98
    assert fila[m.COLUMNAS.index("Garantía")] == ""


# ---------------------------------------------------------------- orden
def test_ordena_por_booked_on_descendente_con_las_filas_sin_fecha_al_final_y_es_estable():
    filas = [fila_hoja("AAAA1", "2026-10-01"), fila_hoja("BBBB2", ""), fila_hoja("CCCC3", "2026-10-31"),
             fila_hoja("DDDD4", "2026-10-01"), fila_hoja("EEEE5", ""), fila_hoja("FFFF6", "2026-10-15")]
    orden = [f[0] for f in m.ordenar_como_maxinet(filas)]
    assert orden == ["CCCC3", "FFFF6", "AAAA1", "DDDD4", "BBBB2", "EEEE5"]


# ---------------------------------------------------------------- consulta a Maxinet
class _Resp:
    def __init__(self, cuerpo):
        self.content = ("﻿" + cuerpo).encode("utf-8")


class _Sesion:
    def __init__(self, cuerpo):
        self.cuerpo, self.pedidos = cuerpo, []

    def post(self, url, data=None, timeout=None):
        self.pedidos.append((url, data, timeout))
        return _Resp(self.cuerpo)


def test_consultar_pide_todas_al_endpoint_del_reporte(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor/maxinetv2/")
    s = _Sesion(json.dumps({"data": [fila_reporte("RB5595A")]}))
    assert len(m.consultar(s)) == 1
    url, datos, espera = s.pedidos[0]
    assert url == "http://servidor/maxinetv2/includes/flota/reporte-dias-sn.php"
    assert datos == {"Estatus": "2"}                                       # TODAS: una fila por placa, con el historial
    assert espera >= 240                                                  # la consulta tarda ~90 s en Maxinet


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_Sesion(json.dumps({"data": ""}))) == []


def test_consultar_con_data_inesperado_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_Sesion(json.dumps({"data": {"a": 1}})))


# ---------------------------------------------------------------- resumen y salvaguarda
def test_resumen_cuenta_altas_bajas_y_cambios_y_no_confunde_0_con_0_0():
    viejas = [fila_hoja("AAAA1"), fila_hoja("BBBB2"), fila_hoja("CCCC3")]
    viejas[0][m.COLUMNAS.index("Gasto SN")] = 0                             # la hoja devuelve 0 entero; el reporte trae 0.0
    nuevas = [fila_hoja("AAAA1"), fila_hoja("CCCC3", **{"Status Vehicle": "OFF_FLEET"}), fila_hoja("DDDD4")]
    r = m._resumen_y_salvaguarda(viejas, nuevas)
    assert (r["antes"], r["despues"], r["altas"], r["bajas"], r["cambios"], r["activas"]) == (3, 3, 1, 1, 1, 2)


def test_salvaguarda_detiene_si_trae_menos_del_80_por_ciento():
    viejas = _filas(*_placas(100))
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m._resumen_y_salvaguarda(viejas, viejas[:79])
    assert m._resumen_y_salvaguarda(viejas, viejas[:80])["despues"] == 80


def test_salvaguarda_no_aplica_a_hojas_chicas_y_forzar_la_omite(monkeypatch):
    chicas = _filas(*_placas(29))
    assert m._resumen_y_salvaguarda(chicas, chicas[:1])["despues"] == 1
    grandes = _filas(*_placas(100))
    monkeypatch.setenv("FORZAR", "1")
    assert m._resumen_y_salvaguarda(grandes, grandes[:10])["despues"] == 10


# ---------------------------------------------------------------- refrescar
def test_dry_run_no_escribe_nada(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2"))
    antes = [list(f) for f in hoja.celdas]
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas("AAAA1", "BBBB2", "CCCC3"))
    assert hoja.escrituras == [] and hoja.limpiezas == [] and hoja.spreadsheet.peticiones == []
    assert hoja.filas_agregadas == 0 and hoja.columnas_agregadas == 0 and hoja.celdas == antes


def test_reemplaza_los_datos_sin_tocar_el_encabezado_ni_mes_y_anio():
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2", "CCCC3"))
    nuevas = _filas("DDDD4", "AAAA1", "EEEE5")
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, nuevas)
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A2:AB4" and modo == "RAW" and valores == nuevas        # A2: el encabezado de la hoja no se reescribe
    assert [f[0] for f in hoja.celdas[1:4]] == ["DDDD4", "AAAA1", "EEEE5"]
    assert hoja.celdas[0][:28] == m.COLUMNAS                               # encabezado intacto
    assert [f[28:30] for f in hoja.celdas[1:4]] == [formulas_mes_anio(i) for i in (2, 3, 4)]   # MES y AÑO intactos
    assert all(not e[0].startswith(("AC", "AD")) for e in hoja.escrituras if not e[0].startswith("AF"))


def test_si_la_tabla_crece_extiende_mes_y_anio_y_copia_el_formato_de_la_fila_2():
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2", "CCCC3"))
    nuevas = _filas("AAAA1", "BBBB2", "CCCC3", "DDDD4", "EEEE5")
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, nuevas)
    formato, formulas = hoja.spreadsheet.peticiones
    assert formato["copyPaste"]["pasteType"] == "PASTE_FORMAT"
    assert formato["copyPaste"]["source"] == {"sheetId": 11, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 30}
    assert (formato["copyPaste"]["destination"]["startRowIndex"], formato["copyPaste"]["destination"]["endRowIndex"]) == (2, 6)
    assert formulas["copyPaste"]["pasteType"] == "PASTE_NORMAL"
    # la fórmula se toma de la última fila que la tiene (la 4) y se extiende a las filas 5 y 6
    assert formulas["copyPaste"]["source"]["startRowIndex"] == 3 and formulas["copyPaste"]["source"]["endRowIndex"] == 4
    assert (formulas["copyPaste"]["source"]["startColumnIndex"], formulas["copyPaste"]["source"]["endColumnIndex"]) == (28, 30)
    assert (formulas["copyPaste"]["destination"]["startRowIndex"], formulas["copyPaste"]["destination"]["endRowIndex"]) == (4, 6)
    assert [f[28:30] for f in hoja.celdas[4:6]] == [formulas_mes_anio(5), formulas_mes_anio(6)]


def test_si_la_tabla_se_acorta_limpia_datos_y_mes_y_anio_de_las_filas_que_sobran():
    hoja = _hoja_con(*_filas(*_placas(6)))
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas(*_placas(4)))
    assert hoja.limpiezas == ["A6:AB7", "AC6:AD7"]
    assert all(f[0] == "" for f in hoja.celdas[5:7]) and all(f[28:30] == ["", ""] for f in hoja.celdas[5:7])
    assert [f[0] for f in hoja.celdas[1:5]] == _placas(4)
    assert not any("PASTE_NORMAL" in json.dumps(p) for p in hoja.spreadsheet.peticiones)   # no hay fórmulas que extender


def test_escribe_primero_y_limpia_despues():
    hoja = _hoja_con(*_filas(*_placas(6)))
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas(*_placas(4)))
    orden = hoja.spreadsheet.orden
    assert orden.index("update") < orden.index("batch_clear")


def test_agrega_filas_si_la_tabla_no_cabe_y_columnas_hasta_la_de_estado():
    hoja = _hoja_con(*_filas(*_placas(5)))
    hoja.row_count = 6
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas(*_placas(10)))
    assert hoja.row_count >= 11 and hoja.filas_agregadas > 0
    assert hoja.col_count >= 32 and hoja.columnas_agregadas == 2


def test_la_hora_de_actualizacion_va_en_af_con_una_columna_libre_de_por_medio():
    hoja = _hoja_con(*_filas("AAAA1"))
    m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas("AAAA1", "BBBB2"))
    rango, valores, modo = hoja.escrituras[-1]
    assert rango == "AF1:AF2" and modo == "RAW"
    assert valores[0] == ["ACTUALIZADO (hora CDMX)"] and len(valores[1][0]) == 16


def test_sin_formulas_de_mes_y_anio_avisa_y_no_inventa_ninguna(caplog):
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2"), con_formulas=False)
    with caplog.at_level(logging.WARNING):
        m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas("AAAA1", "BBBB2", "CCCC3"))
    assert "no tienen fórmulas" in caplog.text
    assert not any("PASTE_NORMAL" in json.dumps(p) for p in hoja.spreadsheet.peticiones)


def test_hoja_inexistente_detiene_sin_crearla():
    with pytest.raises(RuntimeError, match="No existe la pestaña"):
        m.refrescar(None, Libro(), "ENVIOS SEMINUEVOS", _filas("AAAA1"))


def test_encabezado_distinto_detiene_sin_escribir():
    hoja = _hoja_con(*_filas("AAAA1"))
    hoja.celdas[0][3], hoja.celdas[0][4] = hoja.celdas[0][4], hoja.celdas[0][3]      # alguien movió columnas
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas("AAAA1"))
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_sin_filas_detiene_sin_escribir():
    hoja = _hoja_con(*_filas("AAAA1"))
    with pytest.raises(RuntimeError, match="no trajo ninguna"):
        m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, [])
    assert hoja.escrituras == []


def test_respuesta_incompleta_detiene_sin_escribir():
    hoja = _hoja_con(*_filas(*_placas(100)))
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas(*_placas(50)))
    assert hoja.escrituras == [] and hoja.limpiezas == [] and hoja.spreadsheet.peticiones == []


def test_una_hoja_vacia_se_llena_sin_error():
    hoja = HojaFalsa([m.COLUMNAS])
    r = m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas("AAAA1", "BBBB2"))
    assert r["antes"] == 0 and r["despues"] == 2 and hoja.escrituras[0][0] == "A2:AB3"


def test_los_logs_solo_llevan_conteos(caplog):
    hoja = _hoja_con(*_filas("AAAA1"))
    with caplog.at_level(logging.INFO):
        m.refrescar(hoja, hoja.spreadsheet, m.HOJA_POR_DEFECTO, _filas("AAAA1", "BBBB2"))
    assert "EMPRESA FICTICIA" not in caplog.text and "BBBB2" not in caplog.text


def test_nombre_de_hoja_por_defecto_y_por_secret(monkeypatch):
    assert m.nombre_hoja() == "ENVIOS SEMINUEVOS"
    monkeypatch.setenv("WORKSHEET_SEMINUEVOS_LP", ' "OTRA HOJA" ')
    assert m.nombre_hoja() == "OTRA HOJA"


# ---------------------------------------------------------------- validación posterior
def test_validar_acepta_la_hoja_correcta():
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2"))
    m.validar(hoja)


def test_validar_detecta_placas_repetidas():
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2", "aaaa1"))
    with pytest.raises(RuntimeError, match="Placa repetida"):
        m.validar(hoja)


def test_validar_detecta_mes_y_anio_sin_formula_en_la_ultima_fila():
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2", "CCCC3"))
    hoja.celdas[3][28:30] = ["", ""]
    with pytest.raises(RuntimeError, match="MES y AÑO"):
        m.validar(hoja)


# ---------------------------------------------------------------- flujo completo
def _armar_main(monkeypatch, hoja, filas_reporte):
    monkeypatch.setattr(m, "login_maxinet", lambda: object())
    monkeypatch.setattr(m, "consultar", lambda s: filas_reporte)
    monkeypatch.setattr(m, "conectar_libro", lambda: hoja.spreadsheet)


def test_main_de_punta_a_punta_deja_la_hoja_ordenada_y_con_formulas(monkeypatch):
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2"))
    _armar_main(monkeypatch, hoja, [fila_reporte("AAAA1", "2026-09-01"), fila_reporte("CCCC3", "2026-10-30"),
                                    fila_reporte("DDDD4", "")])
    m.main()
    assert [f[0] for f in hoja.celdas[1:4]] == ["CCCC3", "AAAA1", "DDDD4"]      # BOOKED_ON desc, sin fecha al final
    assert hoja.celdas[3][28:30] == formulas_mes_anio(4)
    assert hoja.celdas[0][m.COL_ESTADO - 1] == "ACTUALIZADO (hora CDMX)"


def test_main_termina_con_error_y_sin_tocar_la_hoja_si_el_reporte_no_cuadra(monkeypatch):
    hoja = _hoja_con(*_filas("AAAA1", "BBBB2"))
    antes = [list(f) for f in hoja.celdas]
    _armar_main(monkeypatch, hoja, [fila_reporte("AAAA1"), fila_reporte("AAAA1")])
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 1 and hoja.celdas == antes and hoja.escrituras == []


def test_main_en_dry_run_no_valida_ni_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    hoja = _hoja_con(*_filas("AAAA1"))
    _armar_main(monkeypatch, hoja, [fila_reporte("AAAA1"), fila_reporte("BBBB2")])
    m.main()
    assert hoja.escrituras == [] and hoja.spreadsheet.peticiones == []


# ---------------------------------------------------------------- tolerancia a filtros
def test_se_instala_la_tolerancia_a_filtros_activos_de_google_sheets():
    from gspread.http_client import HTTPClient
    assert getattr(HTTPClient.batch_update, "_tolera_filtros", False)
