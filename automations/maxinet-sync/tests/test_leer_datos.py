"""leer_datos: recorta los textos sin tocar los valores que no son texto (sin red)."""
import pandas as pd

import maxinet_sync as m


def _df(**cambios):
    fila = {c: "" for c in m.COLUMNAS}
    fila.update({"Placa": "ABC123", "Segmento": "DISPONIBLE", "BSite": "L", "CurrentSite": "L"})
    filas = [{**fila, **{k: v[i] for k, v in cambios.items()}} for i in range(len(next(iter(cambios.values()))))]
    return pd.DataFrame(filas, columns=m.COLUMNAS)


def test_el_cero_numerico_de_una_columna_mixta_se_conserva():
    """'Precio caja' trae 0 (número) en la mayoría de las filas y montos como texto en otras."""
    df = m.leer_datos(_df(**{"Precio caja": [0, "350000.00", 0, " 120000.50 "]}))
    assert df["Precio caja"].tolist() == [0, "350000.00", 0, "120000.50"]


def test_los_textos_se_recortan_y_los_vacios_siguen_vacios():
    df = m.leer_datos(_df(**{"Estatus Vehiculo": ["  DISPONIBLE   ", None, "TALLER  "]}))
    assert df["Estatus Vehiculo"].tolist()[0] == "DISPONIBLE" and df["Estatus Vehiculo"].tolist()[2] == "TALLER"
    assert df["Estatus Vehiculo"].isna().tolist() == [False, True, False]


def test_las_columnas_numericas_no_cambian():
    df = m.leer_datos(_df(**{"MOI (sin iva)": [179310.34, 0, 5]}))
    assert df["MOI (sin iva)"].tolist() == [179310.34, 0, 5]


def test_la_regla_de_las_placas_de_servicio_sigue_vigente():
    df = m.leer_datos(_df(Placa=["&SER01 ", "ABC123"], Segmento=["OTROS", "DISPONIBLE"], BSite=["L", "L"], CurrentSite=["L", "L"]))
    assert df.loc[0, ["Placa", "Segmento", "BSite", "CurrentSite"]].tolist() == ["&SER01", "SERVICIOS", "SE", "SE"]
    assert df.loc[1, "Segmento"] == "DISPONIBLE"
