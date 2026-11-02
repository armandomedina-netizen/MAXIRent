import logging

import pytest

import maxinet_encuestas_cp as m
from tests.fakes import HojaFalsa

MP = {"ini": 3, "fin": 26, "orden": m.COLUMNAS, "enc": ["PERIODO", "RECLASIFICACION"] + m.COLUMNAS}


def reparar(ws, filas):
    col_fecha = ws.col_values(3)
    return m.reparar_filas_recientes(ws, MP, col_fecha, filas)


def peticiones(ws):
    return [p["copyPaste"] for lote in ws.spreadsheet.lotes for p in lote]


# ---------------------------------------------------------------- caso real del 2-nov: datos escritos, sin fórmulas ni formato
def test_completa_formulas_y_formato_de_las_filas_que_quedaron_a_medias():
    ws = HojaFalsa(filas=30, sin_formulas={28, 29, 30})
    assert reparar(ws, 30) == 3
    assert ws.formulas(1) >= {28, 29, 30} and ws.formulas(2) >= {28, 29, 30}
    assert {28, 29, 30} <= ws.con_formato
    formato = [c for c in peticiones(ws) if c["pasteType"] == "PASTE_FORMAT"]
    assert len(formato) == 1
    assert formato[0]["source"]["startRowIndex"] == 26                       # fila 27, la última completa
    assert (formato[0]["destination"]["startRowIndex"], formato[0]["destination"]["endRowIndex"]) == (27, 30)


def test_segunda_corrida_ya_no_encuentra_nada_que_reparar():
    ws = HojaFalsa(filas=30, sin_formulas={28, 29, 30})
    reparar(ws, 30)
    lotes = len(ws.spreadsheet.lotes)
    assert reparar(ws, 30) == 0
    assert len(ws.spreadsheet.lotes) == lotes


def test_sin_filas_incompletas_solo_lee():
    ws = HojaFalsa(filas=30)
    assert reparar(ws, 30) == 0
    assert ws.spreadsheet.lotes == []


def test_dos_tramos_separados_se_reparan_con_la_fila_completa_mas_reciente_como_modelo():
    ws = HojaFalsa(filas=40, sin_formulas={10, 11, 30})
    assert reparar(ws, 40) == 3
    formato = [c for c in peticiones(ws) if c["pasteType"] == "PASTE_FORMAT"]
    assert sorted((c["destination"]["startRowIndex"], c["destination"]["endRowIndex"]) for c in formato) == [(9, 11), (29, 30)]
    assert {c["source"]["startRowIndex"] for c in formato} == {39}           # fila 40, la más reciente completa


def test_no_toca_filas_en_blanco_ni_filas_fuera_de_la_ventana():
    ws = HojaFalsa(filas=200, sin_formulas={5, 100}, en_blanco={151})
    assert reparar(ws, 200) == 0                                             # 5 y 100 quedan fuera de la ventana (filas 141 a 200)
    ws2 = HojaFalsa(filas=200, sin_formulas={180, 181}, en_blanco={181})
    assert reparar(ws2, 200) == 1                                            # la 181 no tiene fecha: se ignora
    assert 181 not in ws2.formulas(1) and 180 in ws2.formulas(1)


def test_sin_fila_completa_de_modelo_avisa_y_no_escribe(caplog):
    ws = HojaFalsa(filas=10, sin_formulas=set(range(2, 11)))
    with caplog.at_level(logging.WARNING):
        assert reparar(ws, 10) == 0
    assert ws.spreadsheet.lotes == []
    assert "no se reparó nada" in caplog.text


def test_dry_run_no_escribe(monkeypatch, caplog):
    monkeypatch.setenv("DRY_RUN", "1")
    ws = HojaFalsa(filas=30, sin_formulas={29, 30})
    with caplog.at_level(logging.INFO):
        assert reparar(ws, 30) == 0
    assert ws.spreadsheet.lotes == [] and "DRY_RUN" in caplog.text


def test_hoja_sin_datos_no_hace_nada():
    ws = HojaFalsa(filas=1)
    assert m.reparar_filas_recientes(ws, MP, ws.col_values(3), 1) == 0


# ---------------------------------------------------------------- integrada: sin encuestas nuevas, igual repara
def test_agregar_encuestas_sin_nuevas_repara_las_filas_a_medias(monkeypatch):
    ws = HojaFalsa(filas=30, sin_formulas={29, 30})
    monkeypatch.setattr(m, "mapear_columnas", lambda hoja: MP)
    assert m.agregar_encuestas(ws, [], "2026-10-01") == 0
    assert {29, 30} <= ws.formulas(1)


# ---------------------------------------------------------------- el aviso de fórmulas copiadas sólo sale si Sheets aceptó
def test_no_dice_que_copio_formulas_si_google_rechazo_la_copia(caplog):
    ws = HojaFalsa(filas=30, sin_formulas={30})
    ws.spreadsheet.fallar = RuntimeError("rechazada")
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        m.asegurar_formulas_y_formato(ws, MP, 30, 30, 29)
    assert "se copió" not in caplog.text


def test_dice_cuantas_formulas_copio_cuando_google_acepto(caplog):
    ws = HojaFalsa(filas=30, sin_formulas={30})
    with caplog.at_level(logging.INFO):
        m.asegurar_formulas_y_formato(ws, MP, 30, 30, 29)
    assert "Fórmula PERIODO: se copió a 1 filas" in caplog.text


def test_la_tolerancia_a_filtros_queda_instalada_al_importar_el_modulo():
    from gspread.http_client import HTTPClient
    assert getattr(HTTPClient.batch_update, "_tolera_filtros", False)
