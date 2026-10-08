"""Pruebas del cliente de monday: paginación, reintentos, ajuste de página y validación del esquema."""
import logging

import pytest
import requests

from datos_sac import ESQUEMA
from fakes_sac import FakeRespuesta, FakeSesion
from sac_sync.monday import MAX_INTENTOS, ClienteMonday, ErrorMonday

TOKEN = "token-de-prueba-123"


def cliente(respuestas, tam_pagina=100):
    """Cliente con sesión y pausas falsas; devuelve también la sesión y la lista de pausas pedidas."""
    sesion = FakeSesion(respuestas)
    pausas = []
    c = ClienteMonday(TOKEN, ESQUEMA.tablero_id, "2026-07", sesion=sesion, dormir=pausas.append,
                      tam_pagina=tam_pagina)
    return c, sesion, pausas


def ok(data):
    """Respuesta 200 con datos."""
    return FakeRespuesta(200, {"data": data})


def error(codigo, mensaje="falla", **extension):
    """Respuesta 200 con un error GraphQL."""
    return FakeRespuesta(200, {"errors": [{"message": mensaje, "extensions": {"code": codigo, **extension}}]})


def primera_pagina(items, cursor=None):
    """Respuesta de la primera página de un grupo."""
    return ok({"boards": [{"items_page": {"cursor": cursor, "items": items}}]})


def pagina_siguiente(items, cursor=None):
    """Respuesta de una página posterior."""
    return ok({"next_items_page": {"cursor": cursor, "items": items}})


def test_lee_un_grupo_paginando_por_cursor():
    """Pide la primera página filtrando por grupo y las demás con el cursor de la anterior."""
    c, sesion, _ = cliente([primera_pagina([{"id": "1"}, {"id": "2"}], "c1"), pagina_siguiente([{"id": "3"}])])
    items = c.leer_grupo("grupo_a", ["estado", "folio"])
    assert [i["id"] for i in items] == ["1", "2", "3"]
    primera, segunda = (p["json"] for p in sesion.peticiones)
    assert primera["variables"] == {
        "tablero": ESQUEMA.tablero_id,
        "filtro": {"rules": [{"column_id": "group", "compare_value": ["grupo_a"], "operator": "any_of"}]},
        "ids": ["estado", "folio"], "limite": 100,
    }
    assert segunda["variables"] == {"cursor": "c1", "ids": ["estado", "folio"], "limite": 100}
    assert "items_page(" in primera["query"] and "next_items_page(" in segunda["query"]


def test_la_consulta_trae_display_value_de_reflejos_relaciones_formulas_y_subelementos():
    """Sin estos fragmentos monday no devuelve el valor de esos cuatro tipos de columna."""
    c, sesion, _ = cliente([primera_pagina([])])
    c.leer_grupo("grupo_a", ["estado"])
    consulta = sesion.peticiones[0]["json"]["query"]
    for fragmento in ("MirrorValue", "BoardRelationValue", "FormulaValue", "SubtasksValue"):
        assert f"... on {fragmento} {{ display_value }}" in consulta
    assert "mutation" not in consulta


def test_descarta_elementos_repetidos_entre_paginas():
    """Si el tablero cambia durante la lectura y monday repite un elemento, sólo se conserva una vez."""
    c, _, _ = cliente([primera_pagina([{"id": "1"}, {"id": "2"}], "c1"), pagina_siguiente([{"id": "2"}, {"id": "3"}])])
    assert [i["id"] for i in c.leer_grupo("grupo_a", [])] == ["1", "2", "3"]


def test_el_token_va_en_la_cabecera_y_nunca_en_la_consulta():
    """La autenticación usa la cabecera Authorization junto con la versión de la API."""
    c, sesion, _ = cliente([primera_pagina([])])
    c.leer_grupo("grupo_a", [])
    assert sesion.headers["Authorization"] == TOKEN
    assert sesion.headers["API-Version"] == "2026-07"
    assert TOKEN not in str(sesion.peticiones[0]["json"])


def test_reintenta_ante_429_y_respeta_retry_after():
    """Un 429 espera lo que indica Retry-After y repite la misma consulta."""
    c, sesion, pausas = cliente([FakeRespuesta(429, {}, {"Retry-After": "7"}), primera_pagina([{"id": "1"}])])
    assert len(c.leer_grupo("grupo_a", [])) == 1
    assert pausas == [7.0]
    assert sesion.peticiones[0]["json"] == sesion.peticiones[1]["json"]


def test_reintenta_ante_5xx_con_espera_creciente():
    """Los errores 5xx esperan 5 s, 10 s... y luego se resuelven."""
    c, _, pausas = cliente([FakeRespuesta(503, {}), FakeRespuesta(502, {}), primera_pagina([])])
    c.leer_grupo("grupo_a", [])
    assert pausas == [5, 10]


def test_espera_lo_que_monday_pide_cuando_se_agota_el_presupuesto_de_complejidad():
    """retry_in_seconds es el tiempo en que monday repone el presupuesto; se espera ese tiempo más un segundo."""
    c, _, pausas = cliente([error("COMPLEXITY_BUDGET_EXHAUSTED", retry_in_seconds=12), primera_pagina([])])
    c.leer_grupo("grupo_a", [])
    assert pausas == [13.0]


def test_reduce_la_pagina_si_la_consulta_excede_la_complejidad_por_consulta():
    """El tamaño de página baja a la mitad y se conserva para las páginas siguientes."""
    c, sesion, _ = cliente([
        error("maxComplexityExceeded", "Query has complexity of 6, which exceeds max complexity of 5"),
        primera_pagina([{"id": "1"}], "c1"), pagina_siguiente([{"id": "2"}]),
    ])
    assert len(c.leer_grupo("grupo_a", [])) == 2
    assert [p["json"]["variables"]["limite"] for p in sesion.peticiones] == [100, 50, 50]


def test_con_la_pagina_en_el_minimo_ya_no_se_reduce():
    """Si ni con el tamaño mínimo cabe la consulta, falla con un error claro."""
    c, _, _ = cliente([error("maxComplexityExceeded", "exceeds max complexity")], tam_pagina=10)
    with pytest.raises(ErrorMonday, match="complejidad"):
        c.leer_grupo("grupo_a", [])


def test_credenciales_rechazadas_no_se_reintentan():
    """Un 401 corta de inmediato, sin pausas."""
    c, sesion, pausas = cliente([FakeRespuesta(401, {})])
    with pytest.raises(ErrorMonday, match="credenciales"):
        c.leer_grupo("grupo_a", [])
    assert len(sesion.peticiones) == 1 and pausas == []


@pytest.mark.parametrize("codigo", ["InvalidColumnIdException", "DAILY_LIMIT_EXCEEDED"])
def test_errores_graphql_que_no_se_resuelven_esperando_no_se_reintentan(codigo):
    """Un error de consulta o el límite diario no mejoran reintentando."""
    c, sesion, pausas = cliente([error(codigo, "no se puede")])
    with pytest.raises(ErrorMonday, match=codigo):
        c.leer_grupo("grupo_a", [])
    assert len(sesion.peticiones) == 1 and pausas == []


def test_cortes_de_red_se_reintentan_hasta_rendirse():
    """Tras MAX_INTENTOS fallos de conexión lanza ErrorMonday, con una pausa entre intentos."""
    c, sesion, pausas = cliente([requests.ConnectionError()] * MAX_INTENTOS)
    with pytest.raises(ErrorMonday, match="no respondió bien"):
        c.leer_grupo("grupo_a", [])
    assert len(sesion.peticiones) == MAX_INTENTOS and len(pausas) == MAX_INTENTOS - 1


def test_respuesta_que_no_es_json_lanza_error():
    """Un cuerpo ilegible se informa sin reintentar."""
    c, _, _ = cliente([FakeRespuesta(200, None)])
    with pytest.raises(ErrorMonday, match="no es JSON"):
        c.leer_grupo("grupo_a", [])


def test_tablero_no_visible_para_el_token():
    """Si boards viene vacío el token no tiene acceso al tablero."""
    c, _, _ = cliente([ok({"boards": []})])
    with pytest.raises(ErrorMonday, match="no ve el tablero"):
        c.leer_grupo("grupo_a", [])


def estructura(omitir_columna=None, omitir_grupo=None, titulo_columna=None, total=42):
    """Respuesta de la estructura del tablero construida a partir del esquema de pruebas."""
    columnas = [{"id": col.columna_id, "title": col.encabezado, "type": "text"}
                for col in ESQUEMA.columnas if col.origen == "columna" and col.columna_id != omitir_columna]
    if titulo_columna:
        columnas[0]["title"] = titulo_columna
    grupos = [{"id": g.grupo_id, "title": g.hoja} for g in ESQUEMA.grupos if g.grupo_id != omitir_grupo]
    return ok({"boards": [{"items_count": total, "columns": columnas, "groups": grupos}]})


def test_validar_esquema_devuelve_el_total_de_elementos():
    """Con todo en su lugar devuelve el total de elementos del tablero."""
    c, _, _ = cliente([estructura()])
    assert c.validar_esquema(ESQUEMA) == 42


def test_validar_esquema_detecta_una_columna_que_ya_no_existe():
    """Una columna borrada en monday impide escribir una columna del Sheet en blanco sin avisar."""
    c, _, _ = cliente([estructura(omitir_columna="telefono")])
    with pytest.raises(ErrorMonday, match="columnas del esquema"):
        c.validar_esquema(ESQUEMA)


def test_validar_esquema_detecta_un_grupo_que_ya_no_existe():
    """Un grupo borrado en monday se informa antes de leer."""
    c, _, _ = cliente([estructura(omitir_grupo="grupo_b")])
    with pytest.raises(ErrorMonday, match="grupos del esquema"):
        c.validar_esquema(ESQUEMA)


def test_validar_esquema_solo_avisa_si_cambio_un_titulo(caplog):
    """Un título renombrado en monday no detiene la corrida, sólo queda registrado."""
    c, _, _ = cliente([estructura(titulo_columna="Otro titulo")])
    with caplog.at_level(logging.WARNING, logger="sac_sync.monday"):
        assert c.validar_esquema(ESQUEMA) == 42
    assert "cambió en monday" in caplog.text


def test_validar_esquema_con_tablero_no_visible():
    """Sin acceso al tablero la validación falla con un mensaje claro."""
    c, _, _ = cliente([ok({"boards": []})])
    with pytest.raises(ErrorMonday, match="no ve el tablero"):
        c.validar_esquema(ESQUEMA)
