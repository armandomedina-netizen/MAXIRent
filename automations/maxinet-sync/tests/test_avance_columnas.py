"""Avance diario de las columnas del tablero y descarga de la foto de flota cuando Maxinet no la tiene.

Origen del cambio (30-oct-2026): el corte nocturno de Maxinet no generó la foto de flota del 29; el reporte responde
sin filas, el sync fallaba con "trae [] columnas" y, de seguir así hasta el día siguiente, el avance habría copiado
una columna vacía al día nuevo dejando la viva sin cerrar."""
import json
import logging
from datetime import date

import pandas as pd
import pytest

import maxinet_sync as m
from fakes import HojaFalsa, col

D0 = (date(2026, 10, 26) - m.EPOCH_SHEETS).days          # columna B = 26-oct, C = 27, D = 28, E = 29, F = 30, G = 31


def _hoja(vivas=("D",), titulo="REPORTE DE FLOTA", filas_metricas=(4, 5, 6), con_destino=None):
    """Calendario en la fila 2 (B..I = 26-oct a 2-nov). Las columnas `vivas` llevan fórmulas (fila 3 = total, que se
    autorreferencia, y conteos); las anteriores a la primera viva llevan valores congelados; las demás quedan vacías."""
    c = {(2, 0): "FECHA"}
    for i in range(8):
        c[(2, 1 + i)] = D0 + i
    primera_viva = min((col(v) for v in vivas), default=8)
    for j in range(1, primera_viva):
        for fila in filas_metricas:
            c[(fila, j)] = 40 + fila
    for v in vivas:
        j = col(v)
        c[(3, j)] = f"=SUM({v}4:{v}6)"
        for fila in filas_metricas:
            c[(fila, j)] = f"=COUNTIFS('FLOTA LP'!$B:$B,{v}$2,'FLOTA LP'!$X:$X,{fila})"
    for letra, valor in (con_destino or {}).items():
        c[(4, col(letra))] = valor
    return HojaFalsa(c, titulo=titulo)


def _pegados(hoja):
    """[(tipo, columna_origen, columna_destino, fila_ini, fila_fin)] de las peticiones registradas."""
    out = []
    for p in hoja.spreadsheet.peticiones:
        c = p["copyPaste"]
        out.append((c["pasteType"], m._indice_a_col_letra(c["source"]["startColumnIndex"]),
                    m._indice_a_col_letra(c["destination"]["startColumnIndex"]),
                    c["source"]["startRowIndex"] + 1, c["source"]["endRowIndex"]))
    return out


# --------------------------------------------------------------- día normal
def test_dia_normal_copia_desde_la_columna_del_dia_anterior_y_la_congela():
    hoja = _hoja(vivas=("D",))
    m.avanzar_columna_formulas(hoja, fecha_objetivo=date(2026, 10, 29))
    pegados = _pegados(hoja)
    assert pegados[0][:3] == ("PASTE_FORMULA", "D", "E")
    assert all(p[1] == "D" for p in pegados) and all(p[0] == "PASTE_VALUES" for p in pegados[1:])


# --------------------------------------------------------------- día sin foto
def test_si_falto_un_dia_cierra_la_ultima_viva_y_deja_el_hueco_vacio(caplog):
    hoja = _hoja(vivas=("D",))                                 # la viva sigue en el 28; el 29 no se procesó
    with caplog.at_level(logging.WARNING):
        m.avanzar_columna_formulas(hoja, fecha_objetivo=date(2026, 10, 30))
    pegados = _pegados(hoja)
    assert pegados[0][:3] == ("PASTE_FORMULA", "D", "F")       # origen D (28-oct) -> destino F (30-oct)
    assert {p[1] for p in pegados} == {"D"}
    assert all(p[2] != "E" for p in pegados)                   # la columna del 29 no se toca
    assert "1 día(s) sin foto de flota" in caplog.text


def test_si_faltaron_varios_dias_tambien_usa_la_ultima_viva():
    hoja = _hoja(vivas=("C",))
    m.avanzar_columna_formulas(hoja, fecha_objetivo=date(2026, 11, 1))
    assert _pegados(hoja)[0][:3] == ("PASTE_FORMULA", "C", "H")


def test_sin_ninguna_columna_viva_no_escribe_nada():
    hoja = _hoja(vivas=())                                     # todas las columnas están congeladas: ninguna viva
    with pytest.raises(RuntimeError, match="ninguna de las 7 columnas anteriores"):
        m.avanzar_columna_formulas(hoja, fecha_objetivo=date(2026, 11, 2))
    assert hoja.spreadsheet.peticiones == []


def test_si_el_destino_ya_tiene_contenido_no_repite_ni_falla(caplog):
    hoja = _hoja(vivas=("E",), con_destino=None)               # ya se avanzó al 29: la viva es E
    with caplog.at_level(logging.WARNING):
        m.avanzar_columna_formulas(hoja, fecha_objetivo=date(2026, 10, 29))
    assert hoja.spreadsheet.peticiones == [] and "ya tiene contenido" in caplog.text


# --------------------------------------------------------------- flota por grupo (misma regla)
def test_flota_por_grupo_tambien_salta_el_dia_sin_foto():
    hoja = _hoja(vivas=("D",), titulo="FLOTA POR GRUPO")
    m.avanzar_columna_grupo_autos(hoja, fecha_objetivo=date(2026, 10, 30))
    assert _pegados(hoja)[0][:3] == ("PASTE_FORMULA", "D", "F")


def test_flota_por_grupo_sin_columna_viva_no_escribe_nada():
    hoja = _hoja(vivas=(), titulo="FLOTA POR GRUPO")
    with pytest.raises(RuntimeError, match="no se avanzó nada"):
        m.avanzar_columna_grupo_autos(hoja, fecha_objetivo=date(2026, 11, 2))
    assert hoja.spreadsheet.peticiones == []


# --------------------------------------------------------------- descarga de la foto de flota
class _Resp:
    def __init__(self, cuerpo):
        self.content = ("﻿" + json.dumps(cuerpo)).encode("utf-8")


def _con_respuesta(monkeypatch, *respuestas):
    cola = list(respuestas)
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    monkeypatch.setattr(m, "_post_con_reintentos", lambda *a, **k: _Resp(cola.pop(0) if len(cola) > 1 else cola[0]))


def _fila_valida():
    return ["<a>boton</a>"] + [f"v{i}" for i in range(len(m.COLUMNAS))]


def test_reporte_sin_filas_es_flota_no_disponible_con_mensaje_claro(monkeypatch):
    _con_respuesta(monkeypatch, {"data": []})
    with pytest.raises(m.FlotaNoDisponible, match="no tiene la foto de flota del"):
        m.descargar_datos_flota(object())


def test_ancho_distinto_sigue_siendo_el_error_de_estructura(monkeypatch):
    _con_respuesta(monkeypatch, {"data": [["x", "a", "b"]]})
    with pytest.raises(RuntimeError, match="cambió la estructura") as e:
        m.descargar_datos_flota(object())
    assert not isinstance(e.value, m.FlotaNoDisponible)


def test_con_filas_validas_arma_el_dataframe(monkeypatch):
    _con_respuesta(monkeypatch, {"data": [_fila_valida(), _fila_valida()]})
    df = m.descargar_datos_flota(object())
    assert isinstance(df, pd.DataFrame) and len(df) == 2 and list(df.columns) == m.COLUMNAS


# --------------------------------------------------------------- espera a que Maxinet publique
def test_sin_espera_configurada_falla_de_inmediato(monkeypatch):
    monkeypatch.delenv("ESPERA_FLOTA_MIN", raising=False)
    dormido = []
    monkeypatch.setattr(m.time, "sleep", dormido.append)
    _con_respuesta(monkeypatch, {"data": []})
    with pytest.raises(m.FlotaNoDisponible):
        m.descargar_datos_flota_con_espera(object())
    assert dormido == []


def test_espera_y_toma_la_foto_en_cuanto_aparece(monkeypatch):
    monkeypatch.setenv("ESPERA_FLOTA_MIN", "25")
    dormido = []
    monkeypatch.setattr(m.time, "sleep", dormido.append)
    _con_respuesta(monkeypatch, {"data": []}, {"data": []}, {"data": [_fila_valida()]})
    df = m.descargar_datos_flota_con_espera(object())
    assert len(df) == 1 and dormido == [m.INTERVALO_ESPERA_FLOTA_SEG] * 2


def test_si_nunca_aparece_agota_la_espera_y_falla(monkeypatch):
    monkeypatch.setenv("ESPERA_FLOTA_MIN", "5")
    reloj = iter(range(0, 10_000, 100))
    monkeypatch.setattr(m.time, "monotonic", lambda: next(reloj))
    dormido = []
    monkeypatch.setattr(m.time, "sleep", dormido.append)
    _con_respuesta(monkeypatch, {"data": []})
    with pytest.raises(m.FlotaNoDisponible):
        m.descargar_datos_flota_con_espera(object())
    assert 1 <= len(dormido) <= 3
