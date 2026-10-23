"""Tablero CP: avance diario de 'UNIDADES CP' (copiar fórmulas de conteo al día nuevo y congelar el anterior)."""
import logging
from datetime import date

import pytest

import maxinet_sync as m
from fakes import HojaFalsa, col

SERIAL_20 = (date(2026, 10, 20) - m.EPOCH_SHEETS).days
COL_20, COL_21 = col("E"), col("F")   # en la prueba: E = 20-oct, F = 21-oct


def _unidades(origen_con_formulas=(4, 5, 6, 8), destino=None, etiquetas=True):
    """Réplica reducida del diseño real: A = etiquetas, fila 2 = fechas, fila 3 = TOTAL ON HIRE (SUM en todas las
    columnas), filas de conteo entre TOTAL ON HIRE e INVENTARIO COMERCIAL."""
    c = {(2, 0): "FECHA"}
    if etiquetas:
        c.update({(1, 0): "MENU PRINCIPAL", (3, 0): "TOTAL ON HIRE", (4, 0): "ON HIRE BASE SITE CP",
                  (5, 0): "PRESTADAS DE LP A CP", (6, 0): "SUBARRENDADA", (7, 0): "DISPONIBLES PARA RENTA",
                  (8, 0): "LA FE", (10, 0): "INVENTARIO COMERCIAL"})
    for i, j in enumerate(range(col("B"), col("H") + 1)):
        c[(2, j)] = SERIAL_20 - 3 + i                     # B = 17-oct ... E = 20-oct, F = 21-oct, G = 22-oct
        c[(3, j)] = f"=SUM({chr(65 + j)}4:{chr(65 + j)}6)"
        c[(11, j)] = f"=SUM({chr(65 + j)}3,{chr(65 + j)}8)"
    for fila in origen_con_formulas:                      # E (20-oct) es la columna viva
        c[(fila, COL_20)] = f'=COUNTIFS(\'FLOTA CP\'!$E:$E,E$2,\'FLOTA CP\'!$X:$X,{fila})'
    for fila, valor in (destino or {}).items():
        c[(fila, COL_21)] = valor
    return HojaFalsa(c, titulo="UNIDADES CP")


def _requests(hoja):
    return [p["copyPaste"] for p in hoja.spreadsheet.peticiones]


def test_avanza_copiando_formulas_al_dia_nuevo_y_congelando_el_anterior():
    hoja = _unidades()
    m.avanzar_columna_unidades_cp(hoja, fecha_objetivo=date(2026, 10, 21))
    pegados = [(r["pasteType"], r["source"]["startRowIndex"] + 1, r["source"]["endRowIndex"],
                r["source"]["startColumnIndex"], r["destination"]["startColumnIndex"]) for r in _requests(hoja)]
    assert pegados == [
        ("PASTE_FORMULA", 4, 6, COL_20, COL_21), ("PASTE_FORMULA", 8, 8, COL_20, COL_21),
        ("PASTE_VALUES", 4, 6, COL_20, COL_20), ("PASTE_VALUES", 8, 8, COL_20, COL_20),
    ]


def test_no_toca_la_fila_total_ni_los_indicadores_del_final():
    hoja = _unidades()
    m.avanzar_columna_unidades_cp(hoja, fecha_objetivo=date(2026, 10, 21))
    filas = {fila for r in _requests(hoja)
             for fila in range(r["source"]["startRowIndex"] + 1, r["source"]["endRowIndex"] + 1)}
    assert filas <= {4, 5, 6, 8} and 3 not in filas and 11 not in filas


def test_si_el_destino_ya_tiene_contenido_no_repite_el_avance(caplog):
    hoja = _unidades(destino={4: 346})
    with caplog.at_level(logging.WARNING):
        m.avanzar_columna_unidades_cp(hoja, fecha_objetivo=date(2026, 10, 21))
    assert hoja.spreadsheet.peticiones == [] and "ya tiene contenido" in caplog.text


def test_si_el_origen_no_tiene_formulas_vivas_no_avanza(caplog):
    hoja = _unidades(origen_con_formulas=())
    with caplog.at_level(logging.WARNING):
        m.avanzar_columna_unidades_cp(hoja, fecha_objetivo=date(2026, 10, 21))
    assert hoja.spreadsheet.peticiones == [] and "no tiene fórmulas vivas" in caplog.text


def test_fecha_que_no_esta_en_el_calendario_falla_con_mensaje_claro():
    with pytest.raises(LookupError, match="no está en la fila 2"):
        m.avanzar_columna_unidades_cp(_unidades(), fecha_objetivo=date(2030, 1, 1))


def test_primera_columna_no_tiene_origen():
    with pytest.raises(LookupError, match="primera columna"):
        m.avanzar_columna_unidades_cp(_unidades(), fecha_objetivo=date(2026, 10, 17))


def test_sin_las_etiquetas_esperadas_no_adivina():
    with pytest.raises(LookupError, match="TOTAL ON HIRE"):
        m.avanzar_columna_unidades_cp(_unidades(etiquetas=False), fecha_objetivo=date(2026, 10, 21))


def test_filas_de_conteo_se_buscan_por_etiqueta():
    assert m._filas_conteo_unidades_cp(_unidades()) == (4, 9)


def test_sin_secret_del_tablero_cp_avisa_con_claridad(monkeypatch):
    monkeypatch.delenv("SPREADSHEET_ID_TABLERO_CP", raising=False)
    with pytest.raises(RuntimeError, match="SPREADSHEET_ID_TABLERO_CP"):
        m.conectar_sheet_tablero_cp("UNIDADES CP")
    assert m.PESTANA_UNIDADES_CP == "UNIDADES CP"
