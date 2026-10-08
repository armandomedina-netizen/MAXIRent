"""Pruebas de la carga y validación del esquema."""
import copy
import json
from pathlib import Path

import pytest

from sac_sync.config import ErrorConfiguracion, cargar_esquema, esquema_desde_dict

EJEMPLO = Path(__file__).resolve().parents[1] / "schema.example.json"


def _base() -> dict:
    """El esquema de ejemplo como diccionario nuevo en cada llamada."""
    return json.loads(EJEMPLO.read_text(encoding="utf-8"))


def test_el_ejemplo_del_repositorio_es_valido():
    """schema.example.json carga sin errores y trae las 12 columnas esperadas."""
    esquema = cargar_esquema({"MONDAY_SAC_SCHEMA_PATH": str(EJEMPLO)})
    assert len(esquema.columnas) == 12
    assert [g.hoja for g in esquema.grupos] == ["Pestana A", "Pestana B"]


def test_propiedades_del_esquema():
    """Los encabezados siguen el orden de las columnas, los IDs excluyen nombre y grupo y la clave se ubica."""
    esquema = esquema_desde_dict(_base())
    assert esquema.encabezados[0] == "Nombre" and esquema.encabezados[-1] == "Grupo"
    assert "col_estado" in esquema.ids_columnas
    assert len(esquema.ids_columnas) == len(esquema.columnas) - 2
    assert esquema.indice_clave == 6


def test_la_marca_periodica_es_opcional_y_por_defecto_falsa():
    """Un grupo sin la clave periodica no entra en la sincronización periódica."""
    esquema = esquema_desde_dict(_base())
    assert [g.periodica for g in esquema.grupos] == [True, False]


def test_tablero_como_texto_de_digitos_se_acepta():
    """El ID del tablero puede venir como texto numérico."""
    datos = _base()
    datos["tablero_id"] = "1000000002"
    assert esquema_desde_dict(datos).tablero_id == 1000000002


def test_el_json_en_linea_tiene_prioridad_sobre_el_archivo():
    """MONDAY_SAC_SCHEMA_JSON se usa aunque también se indique una ruta."""
    en_linea = _base()
    en_linea["tablero_id"] = 42
    entorno = {"MONDAY_SAC_SCHEMA_JSON": json.dumps(en_linea), "MONDAY_SAC_SCHEMA_PATH": str(EJEMPLO)}
    assert cargar_esquema(entorno).tablero_id == 42


def test_archivo_inexistente_lanza_error_de_configuracion(tmp_path):
    """Una ruta que no existe se informa como error de configuración."""
    with pytest.raises(ErrorConfiguracion, match="no se encontró"):
        cargar_esquema({"MONDAY_SAC_SCHEMA_PATH": str(tmp_path / "no-existe.json")})


def test_json_invalido_lanza_error_de_configuracion():
    """Un JSON mal formado se informa sin volcar su contenido."""
    with pytest.raises(ErrorConfiguracion, match="no es JSON válido"):
        cargar_esquema({"MONDAY_SAC_SCHEMA_JSON": "{ esto no es json"})


CASOS_INVALIDOS = {
    "tablero_invalido": lambda d: d.update(tablero_id=0),
    "clave_desconocida": lambda d: d.update(extra=1),
    "grupos_vacios": lambda d: d.update(grupos=[]),
    "pestana_repetida": lambda d: d["grupos"].append({"hoja": "Pestana A", "grupo_id": "otro"}),
    "grupo_repetido": lambda d: d["grupos"].append({"hoja": "Otra", "grupo_id": "grupo_a"}),
    "grupo_con_clave_extra": lambda d: d["grupos"][0].update(color="rojo"),
    "periodica_no_booleana": lambda d: d["grupos"][0].update(periodica="si"),
    "encabezado_repetido": lambda d: d["columnas"].append({"encabezado": "Estado", "columna_id": "otra"}),
    "columna_id_repetido": lambda d: d["columnas"].append({"encabezado": "Otra", "columna_id": "col_estado"}),
    "tipo_desconocido": lambda d: d["columnas"][1].update(tipo="moneda"),
    "origen_desconocido": lambda d: d["columnas"][1].update(origen="otro"),
    "falta_columna_id": lambda d: d["columnas"][1].pop("columna_id"),
    "nombre_con_columna_id": lambda d: d["columnas"][0].update(columna_id="x"),
    "nombre_con_tipo_distinto_de_texto": lambda d: d["columnas"][0].update(tipo="numero"),
    "dos_claves": lambda d: d["columnas"][1].update(clave=True),
    "clave_no_booleana": lambda d: d["columnas"][1].update(clave="si"),
}


@pytest.mark.parametrize("caso", CASOS_INVALIDOS)
def test_esquemas_invalidos_se_rechazan(caso):
    """Cada defecto del esquema se detecta antes de tocar monday o Sheets."""
    datos = copy.deepcopy(_base())
    CASOS_INVALIDOS[caso](datos)
    with pytest.raises(ErrorConfiguracion):
        esquema_desde_dict(datos)
