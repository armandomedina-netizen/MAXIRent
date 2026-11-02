import json

import pytest

from mkt_sync.config import cargar_config
from mkt_sync.errores import ErrorConfig

BASE = {"tablero_id": 123, "columna_estado": "estado", "etiqueta_califica": "Califica",
        "columna_tipo": "tipo", "tipos_incluidos": ["A", "B"]}


def texto(**cambios):
    """JSON de configuración válido con los cambios indicados; un valor None quita la clave."""
    datos = {**BASE, **cambios}
    return json.dumps({k: v for k, v in datos.items() if v is not None})


def test_configuracion_valida_con_valores_por_defecto_de_la_hoja():
    cfg = cargar_config(texto())
    assert cfg.tablero_id == 123 and cfg.tipos_incluidos == ("A", "B")
    assert (cfg.hoja, cfg.columna_periodo, cfg.columna_recibidos, cfg.columna_calificados, cfg.primera_fila) == ("MKT", "F", "G", "H", 4)


def test_acepta_parametros_de_la_hoja():
    cfg = cargar_config(texto(hoja="Otra", columna_periodo="B", columna_recibidos="C", columna_calificados="D", primera_fila=2))
    assert (cfg.hoja, cfg.columna_periodo, cfg.columna_recibidos, cfg.columna_calificados, cfg.primera_fila) == ("Otra", "B", "C", "D", 2)


@pytest.mark.parametrize("cambios", [
    {"tablero_id": None},
    {"tablero_id": 0},
    {"tablero_id": "abc"},
    {"columna_estado": ""},
    {"tipos_incluidos": []},
    {"tipos_incluidos": "A"},
    {"tipos_incluidos": ["A", ""]},
    {"columna_periodo": "f"},
    {"columna_recibidos": "G1"},
    {"primera_fila": 0},
    {"primera_fila": True},
    {"hoja": ""},
    {"clave_inventada": 1},
])
def test_rechaza_configuraciones_invalidas(cambios):
    with pytest.raises(ErrorConfig):
        cargar_config(texto(**cambios))


def test_rechaza_json_invalido_y_no_objeto():
    with pytest.raises(ErrorConfig):
        cargar_config("{no es json")
    with pytest.raises(ErrorConfig):
        cargar_config("[1, 2]")


def test_el_ejemplo_del_repositorio_no_se_puede_usar_tal_cual():
    from pathlib import Path
    ejemplo = (Path(__file__).resolve().parent.parent / "config.example.json").read_text(encoding="utf-8")
    with pytest.raises(ErrorConfig):
        cargar_config(ejemplo)
