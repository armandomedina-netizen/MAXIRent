"""Avance diario de las columnas del tablero cuando falta la foto de flota de un día.

Origen del cambio (30-oct-2026): el corte nocturno de Maxinet no generó la foto del 29. Si ese día no se llega a
procesar, el avance del día siguiente habría copiado una columna vacía y dejado la viva sin cerrar. (La descarga
vacía y la espera ya se prueban en test_foto_flota.py.)"""
import logging
from datetime import date

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
