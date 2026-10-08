"""Pruebas de la línea de comandos: selección de pestañas y errores de configuración sin red."""
import logging
from pathlib import Path

import pytest

from datos_sac import ESQUEMA
from sac_sync import cli
from sac_sync.config import ErrorConfiguracion, Esquema, Grupo

EJEMPLO = Path(__file__).resolve().parents[1] / "schema.example.json"


@pytest.fixture(autouse=True)
def aislar_entorno(monkeypatch, tmp_path):
    """Evita que las pruebas lean el .env real y restaura el logging que main() reconfigura."""
    raiz = logging.getLogger()
    manejadores, nivel = raiz.handlers[:], raiz.level
    monkeypatch.setattr(cli, "RUTA_ENV", tmp_path / "no-existe.env")
    for variable in ("MONDAY_TOKEN", "SPREADSHEET_ID_SAC", "GOOGLE_CREDS_PATH", "GOOGLE_APPLICATION_CREDENTIALS",
                     "MONDAY_SAC_SCHEMA_JSON"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("MONDAY_SAC_SCHEMA_PATH", str(EJEMPLO))
    yield
    raiz.handlers[:] = manejadores
    raiz.setLevel(nivel)


def test_todas_devuelve_los_grupos_en_el_orden_del_esquema():
    """--todas selecciona todas las pestañas del esquema."""
    assert cli.elegir_grupos(ESQUEMA, True, []) == list(ESQUEMA.grupos)


def test_elegir_por_nombre_ignora_mayusculas_y_acentos():
    """El nombre de la pestaña se reconoce aunque se escriba sin acentos o en minúsculas."""
    assert cli.elegir_grupos(ESQUEMA, False, ["PESTANA a"]) == [ESQUEMA.grupos[0]]


def test_elegir_varias_no_repite_y_respeta_el_orden_del_esquema():
    """Los nombres repetidos se atienden una vez y en el orden del esquema."""
    elegidos = cli.elegir_grupos(ESQUEMA, False, ["Pestana B", "Pestana A", "pestana b"])
    assert elegidos == list(ESQUEMA.grupos)


def test_periodicas_devuelve_solo_las_marcadas_en_el_esquema():
    """--periodicas selecciona únicamente las pestañas con periodica en verdadero."""
    assert cli.elegir_grupos(ESQUEMA, False, [], periodicas=True) == [ESQUEMA.grupos[0]]


def test_periodicas_sin_ninguna_marcada_es_error():
    """Sin pestañas marcadas, --periodicas falla en lugar de no sincronizar nada en silencio."""
    sin_marcas = Esquema(tablero_id=1, grupos=(Grupo("Pestana A", "grupo_a"),), columnas=ESQUEMA.columnas)
    with pytest.raises(ErrorConfiguracion, match="marcada como periódica"):
        cli.elegir_grupos(sin_marcas, False, [], periodicas=True)


def test_nombre_que_no_esta_en_el_esquema_es_error():
    """Un nombre desconocido se rechaza antes de tocar nada."""
    with pytest.raises(ErrorConfiguracion, match="no están en el esquema"):
        cli.elegir_grupos(ESQUEMA, False, ["Pestana A", "No existe"])


def test_el_parser_exige_una_sola_forma_de_elegir_pestanas():
    """El parser acepta exactamente una de las opciones --todas, --hoja o --listar."""
    parser = cli.construir_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--todas", "--hoja", "Pestana A"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--periodicas", "--todas"])
    assert parser.parse_args(["--periodicas", "--dry-run"]).periodicas is True
    args = parser.parse_args(["--hoja", "Pestana A", "--hoja", "Pestana B", "--dry-run", "--comparar"])
    assert args.hoja == ["Pestana A", "Pestana B"] and args.dry_run and args.comparar


def test_listar_imprime_las_pestanas_y_termina_sin_red(capsys):
    """--listar sólo necesita el esquema: no pide token ni credenciales."""
    assert cli.main(["--listar"]) == 0
    assert capsys.readouterr().out.split("\n")[:2] == ["Pestana A", "Pestana B"]


def test_sin_token_termina_con_error_antes_de_conectarse(capsys):
    """La falta de MONDAY_TOKEN se informa y devuelve 1. main() imprime el registro en stdout."""
    assert cli.main(["--todas", "--dry-run"]) == 1
    assert "MONDAY_TOKEN" in capsys.readouterr().out


def test_pestana_desconocida_termina_con_error(monkeypatch, capsys):
    """Un nombre de pestaña que no está en el esquema devuelve 1."""
    monkeypatch.setenv("MONDAY_TOKEN", "token-de-prueba-123")
    assert cli.main(["--hoja", "No existe", "--dry-run"]) == 1
    assert "no están en el esquema" in capsys.readouterr().out


def test_esquema_inexistente_termina_con_error(monkeypatch, tmp_path, capsys):
    """Sin archivo de esquema se informa y devuelve 1."""
    monkeypatch.setenv("MONDAY_SAC_SCHEMA_PATH", str(tmp_path / "no-existe.json"))
    assert cli.main(["--listar"]) == 1
    assert "no se encontró" in capsys.readouterr().out


def test_el_token_no_aparece_en_el_registro_aunque_un_error_lo_traiga(monkeypatch, capsys):
    """El filtro de secretos enmascara el token si un mensaje de error de una librería lo incluye."""
    monkeypatch.setenv("MONDAY_TOKEN", "token-de-prueba-123")

    def falla(*_):
        """Simula un error de conexión cuyo mensaje trae el token."""
        raise RuntimeError("fallo con token-de-prueba-123 en la cabecera")

    monkeypatch.setattr(cli.ClienteMonday, "validar_esquema", falla)
    assert cli.main(["--todas", "--dry-run"]) == 1
    salida = capsys.readouterr().out
    assert "RuntimeError" in salida and "token-de-prueba-123" not in salida


def test_dry_run_sin_credenciales_de_google_devuelve_none(caplog):
    """Un dry-run sin --comparar puede seguir leyendo sólo monday."""
    with caplog.at_level(logging.WARNING):
        assert cli._abrir_libro(dry_run=True, comparar_con_hoja=False) is None


def test_escribir_o_comparar_sin_credenciales_de_google_es_error():
    """Escribir y comparar sí necesitan las credenciales de Google y el ID del Sheet."""
    with pytest.raises(ErrorConfiguracion, match="faltan GOOGLE_CREDS_PATH"):
        cli._abrir_libro(dry_run=False, comparar_con_hoja=False)
    with pytest.raises(ErrorConfiguracion, match="faltan GOOGLE_CREDS_PATH"):
        cli._abrir_libro(dry_run=True, comparar_con_hoja=True)


def test_credenciales_de_google_apuntando_a_una_carpeta(monkeypatch, tmp_path):
    """Una ruta que es una carpeta se distingue de una que no existe."""
    monkeypatch.setenv("GOOGLE_CREDS_PATH", str(tmp_path))
    monkeypatch.setenv("SPREADSHEET_ID_SAC", "id-de-prueba-123")
    with pytest.raises(ErrorConfiguracion, match="carpeta"):
        cli._abrir_libro(dry_run=False, comparar_con_hoja=False)


def test_credenciales_de_google_en_una_ruta_que_no_existe(monkeypatch, tmp_path):
    """Una ruta de credenciales inexistente se informa sin intentar conectarse."""
    monkeypatch.setenv("GOOGLE_CREDS_PATH", str(tmp_path / "no-existe.json"))
    monkeypatch.setenv("SPREADSHEET_ID_SAC", "id-de-prueba-123")
    with pytest.raises(ErrorConfiguracion, match="no existe"):
        cli._abrir_libro(dry_run=False, comparar_con_hoja=False)
