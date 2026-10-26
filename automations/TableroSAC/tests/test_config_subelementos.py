"""Pruebas de la sección de subelementos del esquema."""
from pathlib import Path

import pytest

from datos_sac import ESQUEMA
from datos_subelementos import ESQUEMA_SUB, GRUPO_A, GRUPO_B, INDICE_ID_SUBELEMENTO, datos_esquema
from sac_sync.config import ErrorConfiguracion, cargar_esquema, esquema_desde_dict

EJEMPLO = Path(__file__).resolve().parents[1] / "schema.example.json"


def test_el_esquema_sin_la_seccion_sigue_siendo_valido():
    """Compatibilidad: sin sección de subelementos ningún grupo tiene pestaña de subelementos."""
    assert ESQUEMA.subelementos is None
    assert all(g.hoja_subelementos is None for g in ESQUEMA.grupos)


def test_la_seccion_de_subelementos_se_carga_y_se_liga_a_su_grupo():
    """La pestaña de subelementos pertenece al grupo que la declara; el otro grupo no tiene."""
    assert ESQUEMA_SUB.subelementos.tablero_id == 1000000003
    assert GRUPO_A.hoja_subelementos == "Pestana S"
    assert GRUPO_B.hoja_subelementos is None


def test_la_tabla_de_subelementos_tiene_sus_propias_propiedades():
    """Encabezados en orden, clave en el ID del subelemento y sólo las columnas de monday en ids_columnas."""
    tabla = ESQUEMA_SUB.subelementos
    assert tabla.encabezados[:5] == ["Folio", "Solicitud", "Placa", "ID subelemento", "Subelemento"]
    assert tabla.indice_clave == INDICE_ID_SUBELEMENTO
    assert tabla.ids_columnas == ["s_personas", "s_area", "s_relacion", "s_horas_sla", "s_fecha",
                                  "s_cronometro", "s_horas"]


def test_las_columnas_del_ticket_no_incluyen_las_de_subelementos():
    """ids_columnas del esquema sigue siendo sólo lo que se pide de cada ticket."""
    assert ESQUEMA_SUB.ids_columnas == ["estado", "placa", "folio"]


def test_el_ejemplo_del_repositorio_incluye_la_seccion_de_subelementos():
    """schema.example.json documenta el formato con IDs de mentira."""
    esquema = cargar_esquema({"MONDAY_SAC_SCHEMA_PATH": str(EJEMPLO)})
    assert esquema.grupos[0].hoja_subelementos == "Pestana S"
    assert esquema.subelementos.tablero_id == 1000000002
    assert len(esquema.subelementos.columnas) == 13 and esquema.subelementos.indice_clave == 3
    assert [c.origen for c in esquema.subelementos.columnas[-2:]] == ["creado", "en_marcha"]


def test_agregar_una_columna_del_ticket_a_las_filas_de_subelementos_es_solo_configuracion():
    """El VIN futuro entra como una columna padre_columna más y un encabezado más."""
    datos = datos_esquema()
    datos["columnas"].append({"encabezado": "VIN", "columna_id": "vin"})
    datos["subelementos"]["columnas"].insert(3, {"encabezado": "VIN", "origen": "padre_columna", "columna_id": "vin"})
    esquema = esquema_desde_dict(datos)
    assert esquema.subelementos.encabezados[3] == "VIN"
    assert esquema.subelementos.indice_clave == INDICE_ID_SUBELEMENTO + 1


def test_una_columna_del_ticket_solo_para_subelementos_se_pide_aunque_no_este_en_su_pestana():
    """El valor del ticket que se copia a los subelementos no tiene que ser una columna de la pestaña de tickets."""
    datos = datos_esquema()
    datos["subelementos"]["columnas"].insert(3, {"encabezado": "VIN", "origen": "padre_columna", "columna_id": "vin"})
    esquema = esquema_desde_dict(datos)
    assert "vin" not in esquema.ids_columnas
    assert esquema.subelementos.ids_padre == ["placa", "vin"]
    assert esquema.ids_columnas_con_padre == ["estado", "placa", "folio", "vin"]


def test_ids_columnas_con_padre_no_repite_las_columnas_ya_pedidas():
    """La Placa ya se pide para la pestaña de tickets: no se pide dos veces."""
    assert ESQUEMA_SUB.ids_columnas_con_padre == ["estado", "placa", "folio"]
    assert ESQUEMA.ids_columnas_con_padre == ESQUEMA.ids_columnas


def _quitar_clave_y_poner_en_otra_columna(d):
    """Mueve la marca de clave del ID del subelemento a una columna de monday."""
    d["subelementos"]["columnas"][3].pop("clave")
    d["subelementos"]["columnas"][5]["clave"] = True


CASOS_INVALIDOS = {
    "hoja_subelementos_sin_la_seccion": lambda d: d.pop("subelementos"),
    "hoja_subelementos_igual_a_otra_pestana": lambda d: d["grupos"][0].update(hoja_subelementos="Pestana B"),
    "dos_grupos_con_la_misma_pestana_de_subelementos": lambda d: d["grupos"][1].update(hoja_subelementos="Pestana S"),
    "hoja_subelementos_vacia": lambda d: d["grupos"][0].update(hoja_subelementos=""),
    "seccion_que_no_es_un_objeto": lambda d: d.update(subelementos=[]),
    "clave_desconocida_en_la_seccion": lambda d: d["subelementos"].update(extra=1),
    "tablero_de_subelementos_invalido": lambda d: d["subelementos"].update(tablero_id=0),
    "columnas_de_subelementos_vacias": lambda d: d["subelementos"].update(columnas=[]),
    "origen_grupo_en_subelementos": lambda d: d["subelementos"]["columnas"][4].update(origen="grupo"),
    "origen_padre_en_la_tabla_de_tickets": lambda d: d["columnas"][0].update(origen="padre_nombre"),
    "tablero_de_subelementos_igual_al_de_tickets": lambda d: d["subelementos"].update(tablero_id=1000000001),
    "sin_columna_padre_id": lambda d: d["subelementos"]["columnas"].pop(0),
    "padre_columna_sin_columna_id": lambda d: d["subelementos"]["columnas"][2].pop("columna_id"),
    "origen_id_con_columna_id": lambda d: d["subelementos"]["columnas"][3].update(columna_id="x"),
    "id_con_tipo_texto": lambda d: d["subelementos"]["columnas"][3].update(tipo="texto"),
    "padre_id_con_tipo_texto": lambda d: d["subelementos"]["columnas"][0].update(tipo="texto"),
    "padre_nombre_con_tipo_numero": lambda d: d["subelementos"]["columnas"][1].update(tipo="numero"),
    "sin_clave_en_subelementos": lambda d: d["subelementos"]["columnas"][3].pop("clave"),
    "clave_en_una_columna_de_monday": _quitar_clave_y_poner_en_otra_columna,
    "encabezados_repetidos_en_subelementos": lambda d: d["subelementos"]["columnas"][5].update(encabezado="Folio"),
    "ids_de_columna_repetidos_en_subelementos": lambda d: d["subelementos"]["columnas"][6].update(columna_id="s_personas"),
    "padre_columna_repetida": lambda d: d["subelementos"]["columnas"].append(
        {"encabezado": "Placa otra vez", "origen": "padre_columna", "columna_id": "placa"}),
}


@pytest.mark.parametrize("caso", CASOS_INVALIDOS)
def test_secciones_de_subelementos_invalidas_se_rechazan(caso):
    """Cada defecto de la sección se detecta antes de tocar monday o Sheets."""
    datos = datos_esquema()
    CASOS_INVALIDOS[caso](datos)
    with pytest.raises(ErrorConfiguracion):
        esquema_desde_dict(datos)


def test_origen_id_es_valido_tambien_en_la_tabla_de_tickets():
    """El ID del elemento se puede usar como columna de la pestaña de tickets, siempre como número."""
    datos = datos_esquema()
    datos["columnas"].append({"encabezado": "ID", "origen": "id", "tipo": "numero"})
    assert esquema_desde_dict(datos).columnas[-1].origen == "id"
    datos["columnas"][-1]["tipo"] = "texto"
    with pytest.raises(ErrorConfiguracion):
        esquema_desde_dict(datos)
