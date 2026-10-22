import pytest

import maxinet_entregas_cp as m
from tests.fakes import HojaFalsa, fila_hoja, fila_mx


@pytest.fixture(autouse=True)
def limpiar_entorno(monkeypatch):
    for v in ("FECHA_DESDE", "FECHA_HASTA", "DRY_RUN", "FORZAR"):
        monkeypatch.delenv(v, raising=False)
    # Las fórmulas y el formato de las filas nuevas se prueban aparte
    monkeypatch.setattr(m, "asegurar_formulas_y_formato", lambda *a, **k: None)


# ---------------------------------------------------------------- bloques de fechas
@pytest.mark.parametrize("hasta,esperado", [
    ("2026-10-21", [("2026-10-01", "2026-10-21")]),
    ("2026-10-31", [("2026-10-01", "2026-10-31")]),           # hoy es día 1: ayer cae en el mes anterior
    ("2026-11-01", [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-01")]),
    ("2026-11-03", [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-03")]),
    ("2026-11-04", [("2026-11-01", "2026-11-04")]),
    ("2026-01-02", [("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-02")]),
])
def test_bloques_a_refrescar(monkeypatch, hasta, esperado):
    monkeypatch.setenv("FECHA_HASTA", hasta)
    assert m.bloques_a_refrescar() == esperado


def test_override_de_fechas_es_un_solo_bloque(monkeypatch):
    monkeypatch.setenv("FECHA_DESDE", "2026-10-05")
    monkeypatch.setenv("FECHA_HASTA", "2026-10-21")
    assert m.bloques_a_refrescar() == [("2026-10-05", "2026-10-21")]


# ---------------------------------------------------------------- forma del reporte
def test_normalizar_acepta_16_y_18_columnas_y_limpia_texto():
    f = fila_mx("2026-10-01", "08:00:00", "#1", "#R1")
    assert len(m.normalizar_filas([f])[0]) == 16
    assert len(m.normalizar_filas([f[:16]])[0]) == 16
    assert m.normalizar_filas([f])[0][13] == "ON HIRE"                     # sin espacios sobrantes
    assert m.normalizar_filas([f])[0][15] == ""                           # None -> ""


@pytest.mark.parametrize("fila", [
    fila_mx("2026-10-01", "08:00:00", "#1", "#R1") + ["x"],               # 19 columnas
    ["<a>Editar</a>"] + fila_mx("2026-10-01", "08:00:00", "#1", "#R1"),   # columna extra al inicio
    fila_mx("2026-10-01", "08:00:00", "#1", ""),                          # reserva vacía
])
def test_normalizar_detiene_si_el_formato_cambia(fila):
    with pytest.raises(RuntimeError):
        m.normalizar_filas([fila])


# ---------------------------------------------------------------- refresco del bloque
def hoja_con(cerrado, octubre):
    return HojaFalsa([fila_hoja(*f) for f in cerrado] + [fila_hoja(*f) for f in octubre])


def test_refresca_estatus_inserta_rezagadas_y_no_toca_meses_cerrados():
    hoja = hoja_con(
        cerrado=[("2026-09-29", "09:00:00", "#C0", "#R0")],
        octubre=[("2026-10-01", "08:00:00", "#C1", "#R1"), ("2026-10-02", "09:00:00", "#C2", "#R2"),
                 ("2026-10-03", "10:00:00", "#C3", "#R3")])
    mx = m.normalizar_filas([
        fila_mx("2026-10-03", "10:00:00", "#C3", "#R3", estatus="RETURNED", gas_rec="FULL"),    # cambió el estatus
        fila_mx("2026-10-01", "08:00:00", "#C1", "#R1", estatus="CHECKED IN", gas_rec="FULL"),  # cambió el estatus
        fila_mx("2026-10-01", "12:00:00", "#C9", "#R9"),                                        # rezagada: entra en su lugar
        # #R2 ya no está en Maxinet
    ])
    r = m.refrescar_bloque(hoja, mx, "2026-10-01")
    rango, valores, modo = hoja.escrituras[0]
    assert rango == "A3:P5" and modo == "USER_ENTERED"                    # empieza en el primer día del bloque
    assert [(v[0], v[8]) for v in valores] == [("2026-10-01", "#R1"), ("2026-10-01", "#R9"), ("2026-10-03", "#R3")]
    assert [v[13] for v in valores] == ["CHECKED IN", "ON HIRE", "RETURNED"]
    assert hoja.limpiezas == []                                           # 3 filas antes, 3 después: no sobra nada
    assert hoja.filas[0][8] == "#R0" and hoja.filas[0][13] == "ON HIRE"   # el mes cerrado no se tocó
    assert (r["altas"], r["bajas"], r["estatus"], r["antes"], r["despues"]) == (1, 1, 2, 3, 3)


def test_si_el_bloque_se_encoge_limpia_las_filas_sobrantes():
    hoja = hoja_con(cerrado=[], octubre=[("2026-10-01", "08:00:00", "#C1", "#R1"), ("2026-10-02", "09:00:00", "#C2", "#R2"),
                                         ("2026-10-03", "10:00:00", "#C3", "#R3")])
    r = m.refrescar_bloque(hoja, m.normalizar_filas([fila_mx("2026-10-01", "08:00:00", "#C1", "#R1"),
                                                      fila_mx("2026-10-03", "10:00:00", "#C3", "#R3")]), "2026-10-01")
    assert hoja.escrituras[0][0] == "A2:P3" and hoja.limpiezas == ["A4:P4"]
    assert [f[8] for f in hoja.filas] == ["#R1", "#R3", ""] and r["bajas"] == 1


def test_si_el_bloque_crece_agrega_filas_y_prepara_las_nuevas(monkeypatch):
    llamadas = []
    monkeypatch.setattr(m, "asegurar_formulas_y_formato", lambda *a: llamadas.append(a))
    hoja = hoja_con(cerrado=[], octubre=[("2026-10-01", "08:00:00", "#C1", "#R1")])
    hoja.row_count = 2
    mx = m.normalizar_filas([fila_mx("2026-10-01", "08:00:00", "#C1", "#R1"), fila_mx("2026-10-02", "08:00:00", "#C2", "#R2")])
    m.refrescar_bloque(hoja, mx, "2026-10-01")
    assert hoja.escrituras[0][0] == "A2:P3" and hoja.filas_agregadas
    assert llamadas == [(hoja, 3, 3, 2)]                                  # fila 3 nueva, modelo = fila 2


def test_una_respuesta_incompleta_no_vacia_el_mes():
    octubre = [("2026-10-01", "08:%02d:00" % i, "#C%d" % i, "#R%d" % i) for i in range(40)]
    hoja = hoja_con(cerrado=[], octubre=octubre)
    mx = m.normalizar_filas([fila_mx(*o) for o in octubre[:10]])
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar_bloque(hoja, mx, "2026-10-01")
    assert hoja.escrituras == []


def test_forzar_omite_la_salvaguarda(monkeypatch):
    monkeypatch.setenv("FORZAR", "1")
    octubre = [("2026-10-01", "08:%02d:00" % i, "#C%d" % i, "#R%d" % i) for i in range(40)]
    hoja = hoja_con(cerrado=[], octubre=octubre)
    m.refrescar_bloque(hoja, m.normalizar_filas([fila_mx(*o) for o in octubre[:10]]), "2026-10-01")
    assert len(hoja.escrituras) == 1 and hoja.limpiezas == ["A12:P41"]


def test_dry_run_no_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    hoja = hoja_con(cerrado=[], octubre=[("2026-10-01", "08:00:00", "#C1", "#R1")])
    r = m.refrescar_bloque(hoja, m.normalizar_filas([fila_mx("2026-10-01", "08:00:00", "#C1", "#R1", estatus="RETURNED")]), "2026-10-01")
    assert hoja.escrituras == [] and hoja.limpiezas == [] and r["estatus"] == 1


def test_sin_filas_de_maxinet_no_escribe():
    hoja = hoja_con(cerrado=[], octubre=[("2026-10-01", "08:00:00", "#C1", "#R1")])
    m.refrescar_bloque(hoja, [], "2026-10-01")
    assert hoja.escrituras == []


def test_id_con_signo_de_pesos_se_escribe_como_texto():
    hoja = hoja_con(cerrado=[], octubre=[("2026-10-01", "08:00:00", "#C1", "#R1")])
    m.refrescar_bloque(hoja, m.normalizar_filas([fila_mx("2026-10-01", "08:00:00", "$3501086", "$3501087")]), "2026-10-01")
    v = hoja.escrituras[0][1][0]
    assert v[2] == "'$3501086" and v[8] == "'$3501087"
