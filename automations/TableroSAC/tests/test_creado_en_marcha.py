"""Pruebas de los orígenes "creado" (fecha de creación) y "en_marcha" (cronómetro corriendo)."""
import pytest

from datos_subelementos import datos_esquema, subelemento, ticket
from fakes_sac import FakeRespuesta, FakeSesion
from sac_sync.config import ErrorConfiguracion, esquema_desde_dict
from sac_sync.monday import ClienteMonday, ErrorMonday, consulta_primera_pagina, consulta_siguiente_pagina
from sac_sync.transformar import a_fecha_local, a_serial_fecha, filas_subelementos_desde_items

CREADO = {"encabezado": "Creado", "origen": "creado", "tipo": "fecha"}
EN_MARCHA = {"encabezado": "En marcha", "origen": "en_marcha", "columna_id": "s_cronometro"}


def esquema_con_extras():
    """Esquema de subelementos con las dos columnas nuevas al final."""
    datos = datos_esquema()
    datos["subelementos"]["columnas"] += [dict(CREADO), dict(EN_MARCHA)]
    return esquema_desde_dict(datos)


def con_running(sub, corriendo):
    """Agrega a la columna de cronómetro del subelemento el dato running, como lo devuelve la API."""
    for columna in sub["column_values"]:
        if columna["id"] == "s_cronometro":
            columna["running"] = corriendo
    return sub


def test_las_columnas_nuevas_se_cargan_y_no_repiten_la_columna_del_cronometro():
    """El cronómetro ya se pide para su duración: en_marcha no lo vuelve a pedir."""
    tabla = esquema_con_extras().subelementos
    assert tabla.encabezados[-2:] == ["Creado", "En marcha"]
    assert tabla.ids_columnas.count("s_cronometro") == 1


def test_en_marcha_de_una_columna_que_no_se_vuelca_tambien_se_pide():
    """Si sólo se informa si corre, la columna de seguimiento igual entra en la consulta."""
    datos = datos_esquema()
    datos["subelementos"]["columnas"] = [c for c in datos["subelementos"]["columnas"] if c.get("columna_id") != "s_cronometro"]
    datos["subelementos"]["columnas"].append(dict(EN_MARCHA))
    assert "s_cronometro" in esquema_desde_dict(datos).subelementos.ids_columnas


@pytest.mark.parametrize("cambio", [
    lambda c: c[-2].update(tipo="texto"),          # creado debe ser fecha
    lambda c: c[-2].update(columna_id="x"),        # creado no lleva columna
    lambda c: c[-1].pop("columna_id"),             # en_marcha necesita su columna
    lambda c: c[-1].update(tipo="numero"),         # en_marcha es texto
])
def test_configuraciones_invalidas_de_las_columnas_nuevas(cambio):
    """Cada error de las columnas nuevas se rechaza antes de tocar monday o Sheets."""
    datos = datos_esquema()
    datos["subelementos"]["columnas"] += [dict(CREADO), dict(EN_MARCHA)]
    cambio(datos["subelementos"]["columnas"])
    with pytest.raises(ErrorConfiguracion):
        esquema_desde_dict(datos)


def test_la_fecha_de_creacion_pasa_de_utc_a_hora_de_mexico():
    """created_at llega en UTC; la celda queda en hora de Ciudad de México (UTC-6)."""
    assert a_fecha_local("2026-10-08T15:30:12Z") == "2026-10-08 09:30:12"
    assert a_fecha_local("2026-10-09T03:00:00Z") == "2026-10-08 21:00:00"
    assert a_fecha_local(None) is None and a_fecha_local("ayer") == "ayer"


def test_filas_con_fecha_de_creacion_y_cronometro():
    """Las dos columnas salen del subelemento: fecha como número de serie y "Sí"/"No"."""
    tabla = esquema_con_extras().subelementos
    corriendo = con_running(subelemento(7001), True)
    corriendo["created_at"] = "2026-10-08T15:30:12Z"
    detenido = con_running(subelemento(7002), False)
    detenido["created_at"] = "2026-10-01T06:00:00Z"
    filas, _ = filas_subelementos_desde_items([ticket(100, subelementos=[corriendo, detenido])], tabla)
    assert filas[0][-2] == pytest.approx(a_serial_fecha("2026-10-08 09:30:12")) and filas[0][-1] == "Sí"
    assert filas[1][-2] == pytest.approx(a_serial_fecha("2026-10-01 00:00:00")) and filas[1][-1] == "No"


def test_sin_dato_del_cronometro_queda_en_blanco_y_se_cuenta():
    """Si monday no devuelve running, la celda queda vacía y el resumen lo cuenta sin valores."""
    tabla = esquema_con_extras().subelementos
    filas, resumen = filas_subelementos_desde_items([ticket(100, subelementos=[subelemento(7001)])], tabla)
    assert filas[0][-1] is None and filas[0][-2] is None
    assert resumen.columnas_ausentes["En marcha"] == 1


@pytest.mark.parametrize("construir", [consulta_primera_pagina, consulta_siguiente_pagina])
def test_la_consulta_pide_created_at_y_running(construir):
    """Tickets y subelementos traen created_at, y las columnas de tiempo su estado running."""
    consulta = construir(True)
    assert consulta.count("created_at") == 2
    assert consulta.count("... on TimeTrackingValue { running }") == 2
    assert "mutation" not in consulta


def test_validar_detecta_la_columna_de_cronometro_que_ya_no_existe():
    """Una columna en_marcha que ya no está en el tablero de subelementos se informa antes de leer."""
    datos = datos_esquema()
    datos["subelementos"]["columnas"].append({"encabezado": "En marcha", "origen": "en_marcha", "columna_id": "s_otro"})
    esquema = esquema_desde_dict(datos)
    ids_ticket = esquema.ids_columnas_con_padre
    ids_sub = [i for i in esquema.subelementos.ids_columnas if i != "s_otro"]
    respuesta = FakeRespuesta(200, {"data": {"boards": [
        {"id": "1000000001", "columns": [{"id": i} for i in ids_ticket]},
        {"id": "1000000003", "columns": [{"id": i} for i in ids_sub]}]}})
    cliente = ClienteMonday("token", esquema.tablero_id, sesion=FakeSesion([respuesta]), dormir=lambda s: None)
    with pytest.raises(ErrorMonday, match="En marcha"):
        cliente.validar_subelementos(esquema)
