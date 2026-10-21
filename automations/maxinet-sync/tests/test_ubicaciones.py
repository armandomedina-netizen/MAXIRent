"""Tabla UBICACIONES de la base: estado de Maxinet con glosario propio de respaldo."""
import pandas as pd

import maxinet_sync as m


def _flota(*filas):
    return pd.DataFrame([
        {"Placa": p, "Ultimo Msj": msj, "Odometro": km, "RT": rt, "Estado": estado}
        for p, msj, km, rt, estado in filas
    ])


MENSAJE = "2026-10-12 08:00:00"


def test_estado_de_maxinet_con_los_nombres_de_la_tabla():
    filas, conteos = m.calcular_ubicaciones([["A1", 1, 2.0, "dir", "", "Sonora"]],
                                            _flota(("A1", MENSAJE, "11.5", "1", "Coahuila")))
    assert filas[0][5] == "Coahuila De Zaragoza"
    assert filas[0][2] == 11.5 and filas[0][4] == "RT" and filas[0][3] == "dir"
    assert conteos["con_estado_maxinet"] == 1


def test_si_maxinet_no_trae_estado_se_conserva_el_del_glosario():
    filas, conteos = m.calcular_ubicaciones([["B2", 1, 2.0, "dir", "", "Sonora"]],
                                            _flota(("B2", "", "", "0", "")))
    assert filas[0][5] == "Sonora"
    assert conteos["sin_estado"] == 0


def test_placa_nueva_sin_estado_se_cuenta_para_completarla_a_mano():
    filas, conteos = m.calcular_ubicaciones([], _flota(("C3", MENSAJE, "7", "1", "")))
    assert filas[0][0] == "C3" and filas[0][5] == ""
    assert conteos["nuevas"] == 1 and conteos["sin_estado"] == 1


def test_placa_en_dos_filas_se_actualiza_en_ambas():
    existentes = [["A1", 1, 10.0, "d1", "VIRTUAL", "Nuevo León"], ["A1", 1, 9.0, "d2", "RT", "Nuevo León"]]
    filas, _ = m.calcular_ubicaciones(existentes, _flota(("A1", MENSAJE, "11.5", "1", "Coahuila")))
    assert [f[2] for f in filas] == [11.5, 11.5]
    assert [f[3] for f in filas] == ["d1", "d2"]      # la dirección nunca se toca
    assert [f[4] for f in filas] == ["VIRTUAL", "RT"]  # el GPS que ya había se respeta


def test_segunda_pasada_con_los_mismos_datos_no_cambia_nada():
    flota = _flota(("A1", MENSAJE, "11.5", "1", "Coahuila"), ("C3", MENSAJE, "7", "1", ""))
    primera, _ = m.calcular_ubicaciones([["A1", 1, 2.0, "dir", "", "Sonora"]], flota)
    segunda, conteos = m.calcular_ubicaciones(primera, flota)
    assert segunda == primera
    assert conteos["nuevas"] == 0 and conteos["actualizadas"] == 0
