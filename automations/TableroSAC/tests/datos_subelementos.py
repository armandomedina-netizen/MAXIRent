"""Esquema y elementos de monday de mentira, con subelementos, para las pruebas."""
import copy

from datos_sac import cv
from sac_sync.config import esquema_desde_dict

COLUMNAS_TICKET = [
    {"encabezado": "Nombre", "origen": "nombre"},
    {"encabezado": "Estado", "columna_id": "estado"},
    {"encabezado": "Placa", "columna_id": "placa"},
    {"encabezado": "Folio", "columna_id": "folio", "tipo": "numero", "clave": True},
    {"encabezado": "Grupo", "origen": "grupo"},
]

COLUMNAS_SUBELEMENTO = [
    {"encabezado": "Folio", "origen": "padre_id", "tipo": "numero"},
    {"encabezado": "Solicitud", "origen": "padre_nombre"},
    {"encabezado": "Placa", "origen": "padre_columna", "columna_id": "placa"},
    {"encabezado": "ID subelemento", "origen": "id", "tipo": "numero", "clave": True},
    {"encabezado": "Subelemento", "origen": "nombre"},
    {"encabezado": "Encargado", "columna_id": "s_personas"},
    {"encabezado": "Area", "columna_id": "s_area"},
    {"encabezado": "Relacion SLA", "columna_id": "s_relacion"},
    {"encabezado": "Horas estimadas", "columna_id": "s_horas_sla", "tipo": "numero"},
    {"encabezado": "Fecha limite", "columna_id": "s_fecha", "tipo": "fecha"},
    {"encabezado": "Cronometro", "columna_id": "s_cronometro", "tipo": "duracion"},
    {"encabezado": "Horas", "columna_id": "s_horas", "tipo": "numero"},
]


def datos_esquema() -> dict:
    """Diccionario del esquema con subelementos; cada llamada devuelve uno nuevo para poder mutarlo."""
    return {
        "tablero_id": 1000000001,
        "grupos": [
            {"hoja": "Pestana A", "grupo_id": "grupo_a", "periodica": True, "hoja_subelementos": "Pestana S"},
            {"hoja": "Pestana B", "grupo_id": "grupo_b"},
        ],
        "columnas": copy.deepcopy(COLUMNAS_TICKET),
        "subelementos": {"tablero_id": 1000000003, "columnas": copy.deepcopy(COLUMNAS_SUBELEMENTO)},
    }


ESQUEMA_SUB = esquema_desde_dict(datos_esquema())
GRUPO_A, GRUPO_B = ESQUEMA_SUB.grupos
INDICE_ID_SUBELEMENTO = 3


def subelemento(id_, nombre="Subelemento", encargado="", area="Operaciones", relacion="", horas_sla="",
                fecha="", cronometro="1:00:00", horas="0"):
    """Un subelemento de monday con todas las columnas del esquema de pruebas."""
    return {"id": str(id_), "name": nombre, "column_values": [
        cv("s_personas", "people", encargado),
        cv("s_area", "dropdown", area),
        cv("s_relacion", "board_relation", None, dv=relacion),
        cv("s_horas_sla", "mirror", None, dv=horas_sla),
        cv("s_fecha", "date", fecha),
        cv("s_cronometro", "time_tracking", cronometro),
        cv("s_horas", "formula", "", dv=horas),
    ]}


def ticket(folio, nombre="Ticket", placa="P-1", subelementos=(), estado="En Proceso", grupo="Pestana A"):
    """Un elemento de monday (el ticket) con sus subelementos; una lista vacía es lo que devuelve la API
    para un ticket sin subelementos."""
    return {"id": str(folio), "name": nombre, "group": {"id": "g", "title": grupo}, "column_values": [
        cv("estado", "status", estado),
        cv("placa", "text", placa),
        cv("folio", "item_id", str(folio)),
    ], "subitems": list(subelementos)}


def ticket_sin_clave_subitems(folio):
    """Un ticket como lo devolvería monday si no entregara el campo subitems."""
    elemento = ticket(folio)
    del elemento["subitems"]
    return elemento
