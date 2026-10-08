"""Esquema y elementos de monday de mentira para las pruebas."""
from sac_sync.config import esquema_desde_dict

ESQUEMA = esquema_desde_dict({
    "tablero_id": 1000000001,
    "grupos": [
        {"hoja": "Pestana A", "grupo_id": "grupo_a", "periodica": True},
        {"hoja": "Pestana B", "grupo_id": "grupo_b"},
    ],
    "columnas": [
        {"encabezado": "Nombre", "origen": "nombre"},
        {"encabezado": "Estado", "columna_id": "estado"},
        {"encabezado": "Telefono", "columna_id": "telefono"},
        {"encabezado": "Folio", "columna_id": "folio", "tipo": "numero", "clave": True},
        {"encabezado": "Dias", "columna_id": "dias", "tipo": "numero"},
        {"encabezado": "Enlace", "columna_id": "enlace"},
        {"encabezado": "Registro", "columna_id": "registro", "tipo": "fecha"},
        {"encabezado": "Limite", "columna_id": "limite", "tipo": "fecha"},
        {"encabezado": "Cronometro", "columna_id": "cronometro", "tipo": "duracion"},
        {"encabezado": "Tiempo areas", "columna_id": "areas", "tipo": "duracion"},
        {"encabezado": "Grupo", "origen": "grupo"},
    ],
})

INDICE_FOLIO = 3


def cv(id_, tipo, text=None, dv=None):
    """Una columna de monday tal como la devuelve la API; display_value sólo en los tipos que lo traen."""
    columna = {"id": id_, "type": tipo, "text": text}
    if dv is not None:
        columna["display_value"] = dv
    return columna


def item(id_, nombre, grupo, columnas):
    """Un elemento de monday con sus columnas."""
    return {"id": id_, "name": nombre, "group": {"id": "g", "title": grupo}, "column_values": list(columnas)}


def item_completo(folio, nombre="Elemento", estado="Atendido", telefono="0123456789",
                  registro="2026-10-06 14:28", cronometro="2:08:47", grupo="Pestana A"):
    """Un elemento con todas las columnas del esquema de pruebas."""
    return item(str(folio), nombre, grupo, [
        cv("estado", "status", estado),
        cv("telefono", "mirror", dv=telefono),
        cv("folio", "item_id", str(folio)),
        cv("dias", "formula", "", dv="0.5"),
        cv("enlace", "formula", "", dv="https://ejemplo.test/x"),
        cv("registro", "date", registro),
        cv("limite", "date", ""),
        cv("cronometro", "time_tracking", cronometro),
        cv("areas", "mirror", dv=""),
    ])


def fila_vieja(i):
    """Una fila de datos viejos de la pestaña, con Folio, para comprobar que se sobrescribe y se limpia."""
    fila = [None] * len(ESQUEMA.columnas)
    fila[0] = "viejo"
    fila[INDICE_FOLIO] = 900 + i
    return fila
