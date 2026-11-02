from datetime import datetime

from mkt_sync.conteo import ZONA, contar_mes, mes_de_creacion, periodos_a_actualizar

ESTADO = "col_estado"


def lead(creado, estado):
    """Lead con la forma que devuelve monday: fecha de creación en UTC y el texto de la columna de estado."""
    return {"id": creado + str(estado), "created_at": creado, "column_values": [{"id": ESTADO, "text": estado}]}


def test_el_mes_se_toma_en_hora_de_ciudad_de_mexico():
    assert mes_de_creacion("2026-10-01T05:59:59Z") == (2026, 9)
    assert mes_de_creacion("2026-10-01T06:00:00Z") == (2026, 10)
    assert mes_de_creacion("2026-11-01T05:59:59Z") == (2026, 10)


def test_cuenta_recibidos_y_calificados_solo_del_mes():
    leads = [
        lead("2026-10-02T15:00:00Z", "Califica"),
        lead("2026-10-03T15:00:00Z", "No califica"),
        lead("2026-10-04T15:00:00Z", "Califica"),
        lead("2026-09-30T15:00:00Z", "Califica"),
        lead("2025-10-02T15:00:00Z", "Califica"),
    ]
    assert contar_mes(leads, ESTADO, "Califica", 2026, 10) == (3, 2)


def test_lead_sin_estado_cuenta_como_recibido_y_no_como_calificado():
    leads = [lead("2026-10-02T15:00:00Z", None), {"id": "x", "created_at": "2026-10-02T15:00:00Z", "column_values": []}]
    assert contar_mes(leads, ESTADO, "Califica", 2026, 10) == (2, 0)


def test_mes_sin_leads():
    assert contar_mes([], ESTADO, "Califica", 2026, 10) == (0, 0)


def hora(anio, mes, dia):
    """Las 9:00 hora de Ciudad de México del día indicado."""
    return datetime(anio, mes, dia, 9, 0, tzinfo=ZONA)


def test_los_primeros_tres_dias_se_actualiza_tambien_el_mes_anterior():
    assert periodos_a_actualizar(hora(2026, 11, 1)) == [(2026, 10), (2026, 11)]
    assert periodos_a_actualizar(hora(2026, 11, 3)) == [(2026, 10), (2026, 11)]


def test_despues_del_tercer_dia_solo_el_mes_en_curso():
    assert periodos_a_actualizar(hora(2026, 11, 4)) == [(2026, 11)]
    assert periodos_a_actualizar(hora(2026, 10, 31)) == [(2026, 10)]


def test_en_enero_el_mes_anterior_es_diciembre_del_anio_anterior():
    assert periodos_a_actualizar(hora(2027, 1, 2)) == [(2026, 12), (2027, 1)]
