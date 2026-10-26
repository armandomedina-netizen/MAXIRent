"""Pruebas de la lectura de subelementos con el cliente de monday."""
import pytest

from datos_subelementos import ESQUEMA_SUB, ticket, ticket_sin_clave_subitems
from fakes_sac import FakeRespuesta, FakeSesion
from sac_sync.monday import (PRIMERA_PAGINA, SIGUIENTE_PAGINA, ClienteMonday, ErrorMonday,
                             consulta_primera_pagina, consulta_siguiente_pagina)

TOKEN = "token-de-prueba-123"
FRAGMENTOS = ("MirrorValue", "BoardRelationValue", "FormulaValue", "SubtasksValue")


def cliente(respuestas, esquema=ESQUEMA_SUB):
    """Cliente con sesión y pausas falsas; devuelve también la sesión."""
    sesion = FakeSesion(respuestas)
    return ClienteMonday(TOKEN, esquema.tablero_id, "2026-07", sesion=sesion, dormir=lambda s: None), sesion


def ok(data):
    """Respuesta 200 con datos."""
    return FakeRespuesta(200, {"data": data})


def primera_pagina(items, cursor=None):
    """Respuesta de la primera página de un grupo."""
    return ok({"boards": [{"items_page": {"cursor": cursor, "items": items}}]})


def pagina_siguiente(items, cursor=None):
    """Respuesta de una página posterior."""
    return ok({"next_items_page": {"cursor": cursor, "items": items}})


def estructura(esquema):
    """Respuesta de la estructura del tablero de tickets construida a partir de un esquema."""
    columnas = [{"id": c.columna_id, "title": c.encabezado, "type": "text"}
                for c in esquema.columnas if c.origen == "columna"]
    grupos = [{"id": g.grupo_id, "title": g.hoja} for g in esquema.grupos]
    return ok({"boards": [{"items_count": 42, "columns": columnas, "groups": grupos}]})


def estructura_columnas(omitir_sub=None, omitir_ticket=None, sin_tablero_sub=False):
    """Respuesta de las columnas de los dos tableros (tickets y subelementos) a partir del esquema de pruebas."""
    ids_ticket = ESQUEMA_SUB.ids_columnas_con_padre
    ids_sub = ESQUEMA_SUB.subelementos.ids_columnas
    tableros = [{"id": "1000000001", "columns": [{"id": i} for i in ids_ticket if i != omitir_ticket]}]
    if not sin_tablero_sub:
        tableros.append({"id": "1000000003", "columns": [{"id": i} for i in ids_sub if i != omitir_sub]})
    return ok({"boards": tableros})


def test_las_consultas_sin_subelementos_son_las_de_siempre():
    """Sin subelementos la consulta no declara $ids_sub ni pide subitems."""
    assert consulta_primera_pagina() == PRIMERA_PAGINA and consulta_siguiente_pagina() == SIGUIENTE_PAGINA
    for consulta in (PRIMERA_PAGINA, SIGUIENTE_PAGINA):
        assert "subitems" not in consulta and "ids_sub" not in consulta


@pytest.mark.parametrize("construir", [consulta_primera_pagina, consulta_siguiente_pagina])
def test_la_consulta_con_subelementos_declara_la_variable_y_los_pide(construir):
    """El bloque de subelementos usa $ids_sub y repite los fragmentos de display_value; el ticket padre no se pide aparte."""
    consulta = construir(True)
    assert "$ids_sub: [String!]" in consulta
    assert "subitems {" in consulta and "column_values(ids: $ids_sub)" in consulta
    assert "parent_item" not in consulta
    for fragmento in FRAGMENTOS:
        assert consulta.count(f"... on {fragmento} {{ display_value }}") == 2
    assert "mutation" not in consulta


def test_leer_grupo_con_subelementos_pasa_ids_sub_en_cada_pagina():
    """Las dos páginas piden los subelementos con las mismas columnas y devuelven los elementos con su lista."""
    c, sesion = cliente([primera_pagina([ticket(1), ticket(2)], "c1"), pagina_siguiente([ticket(3)])])
    items = c.leer_grupo("grupo_a", ["estado"], ["s_area"])
    primera, segunda = (p["json"] for p in sesion.peticiones)
    assert primera["variables"]["ids_sub"] == ["s_area"] and segunda["variables"]["ids_sub"] == ["s_area"]
    assert "subitems {" in primera["query"] and "subitems {" in segunda["query"]
    assert [i["id"] for i in items] == ["1", "2", "3"] and all(i["subitems"] == [] for i in items)


def test_leer_grupo_sin_ids_de_subelementos_no_pide_subitems():
    """Compatibilidad: sin la lista de columnas de subelementos la consulta y las variables no cambian."""
    c, sesion = cliente([primera_pagina([{"id": "1"}])])
    c.leer_grupo("grupo_a", ["estado"])
    peticion = sesion.peticiones[0]["json"]
    assert "ids_sub" not in peticion["variables"] and "subitems" not in peticion["query"]


def test_un_elemento_sin_la_clave_subitems_es_un_error():
    """Si se pidieron subelementos y monday no los devuelve, no se entrega un grupo sin subelementos."""
    c, _ = cliente([primera_pagina([ticket_sin_clave_subitems(1)])])
    with pytest.raises(ErrorMonday, match="subelementos"):
        c.leer_grupo("grupo_a", ["estado"], ["s_area"])


def test_un_subitems_nulo_es_un_error():
    """La API devuelve una lista vacía cuando no hay subelementos; un nulo es una respuesta incompleta."""
    elemento = ticket(1)
    elemento["subitems"] = None
    c, _ = cliente([primera_pagina([elemento])])
    with pytest.raises(ErrorMonday, match="subelementos"):
        c.leer_grupo("grupo_a", ["estado"], ["s_area"])


def test_la_lista_vacia_de_subitems_es_valida():
    """Un ticket sin subelementos llega con una lista vacía y se conserva."""
    c, _ = cliente([primera_pagina([ticket(1, subelementos=[])])])
    assert c.leer_grupo("grupo_a", ["estado"], ["s_area"])[0]["subitems"] == []


def test_validar_esquema_no_consulta_el_tablero_de_subelementos():
    """La validación de los tickets no depende de los subelementos: un problema ahí falla sólo su pestaña."""
    c, sesion = cliente([estructura(ESQUEMA_SUB)])
    assert c.validar_esquema(ESQUEMA_SUB) == 42 and len(sesion.peticiones) == 1


def test_validar_subelementos_pide_las_columnas_de_los_dos_tableros_en_una_consulta():
    """Con todo en su lugar no hay error, y una sola consulta lleva los dos tableros."""
    c, sesion = cliente([estructura_columnas()])
    c.validar_subelementos(ESQUEMA_SUB)
    assert [p["json"]["variables"] for p in sesion.peticiones] == [{"tableros": [1000000001, 1000000003]}]


def test_validar_subelementos_detecta_una_columna_de_subelementos_que_ya_no_existe():
    """Una columna borrada en el tablero de subelementos se informa antes de leer."""
    c, _ = cliente([estructura_columnas(omitir_sub="s_area")])
    with pytest.raises(ErrorMonday, match="columnas de subelementos"):
        c.validar_subelementos(ESQUEMA_SUB)


def test_validar_subelementos_detecta_una_columna_del_ticket_que_ya_no_existe():
    """La columna del ticket que se copia a las filas también se comprueba."""
    c, _ = cliente([estructura_columnas(omitir_ticket="placa")])
    with pytest.raises(ErrorMonday, match="columnas del ticket"):
        c.validar_subelementos(ESQUEMA_SUB)


def test_validar_subelementos_con_el_tablero_de_subelementos_no_visible():
    """Sin acceso al tablero de subelementos la validación falla con un mensaje claro."""
    c, _ = cliente([estructura_columnas(sin_tablero_sub=True)])
    with pytest.raises(ErrorMonday, match="no ve el tablero de subelementos"):
        c.validar_subelementos(ESQUEMA_SUB)


def test_los_mensajes_de_validacion_no_llevan_ids():
    """Los errores nombran los encabezados, nunca los IDs de columna ni de tablero."""
    c, _ = cliente([estructura_columnas(omitir_sub="s_area")])
    with pytest.raises(ErrorMonday) as error:
        c.validar_subelementos(ESQUEMA_SUB)
    assert "s_area" not in str(error.value) and "1000000003" not in str(error.value)
