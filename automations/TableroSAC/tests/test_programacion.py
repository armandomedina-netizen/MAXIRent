"""Pruebas del horario de ejecución: el cron del workflow y la tabla HORARIO del disparador de Apps Script."""
import json
import re
from pathlib import Path

import yaml

CARPETA = Path(__file__).resolve().parents[1]
WORKFLOW = CARPETA.parents[1] / ".github" / "workflows" / "tablero-sac.yml"
DISPARADOR = CARPETA / "apps-script" / "disparador.gs"

DESFASE_CDMX = -6   # CDMX es UTC-6 todo el año desde 2022
MAX_HUECO_HORAS = 2
LIMITE_MANANA = 10
SECRETS_ESPERADOS = {"GOOGLE_CREDS_JSON", "MONDAY_TOKEN", "SPREADSHEET_ID_SAC", "MONDAY_SAC_SCHEMA_JSON"}


def _campo(texto: str, maximo: int) -> list[int]:
    """Expande un campo de cron (*, n, a-b o lista separada por comas) a la lista de valores."""
    valores = []
    for parte in texto.split(","):
        if parte == "*":
            valores.extend(range(maximo + 1))
        elif "-" in parte:
            desde, hasta = parte.split("-")
            valores.extend(range(int(desde), int(hasta) + 1))
        else:
            valores.append(int(parte))
    return sorted(set(valores))


def _workflow() -> dict:
    """El workflow leído como diccionario."""
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _disparadores(datos: dict) -> dict:
    """Sección `on` del workflow; PyYAML la lee con la clave True porque `on` es un booleano de YAML 1.1."""
    return datos["on"] if "on" in datos else datos[True]


def _corridas_del_cron() -> dict[int, list[tuple[int, int]]]:
    """Por día de la semana (0 = domingo ... 6 = sábado, hora CDMX), las (hora, minuto) en que corre el cron."""
    corridas = {dia: [] for dia in range(7)}
    for entrada in _disparadores(_workflow())["schedule"]:
        minuto, hora, dia_mes, mes, dia_semana = entrada["cron"].split()
        assert dia_mes == "*" and mes == "*"
        for dia in _campo(dia_semana, 6):
            for h in _campo(hora, 23):
                local = h + DESFASE_CDMX
                assert 0 <= local <= 23, "el cron cruza la medianoche en CDMX"
                corridas[dia].extend((local, m) for m in _campo(minuto, 59))
    return {dia: sorted(v) for dia, v in corridas.items()}


def _horario_apps_script() -> dict[int, list[int]]:
    """Lee la tabla HORARIO de disparador.gs, escrita como JSON válido; la clave es el día ISO (1 = lunes)."""
    texto = DISPARADOR.read_text(encoding="utf-8")
    tabla = re.search(r"HORARIO:\s*(\{.*?\})", texto, re.DOTALL).group(1)
    return {int(dia): horas for dia, horas in json.loads(tabla).items()}


def test_el_cron_corre_cada_hora_de_lunes_a_viernes_de_7_20_a_17_20():
    """De lunes a viernes el seguro corre a los 20 minutos de cada hora entre las 7 y las 17."""
    corridas = _corridas_del_cron()
    assert all(corridas[dia] == [(h, 20) for h in range(7, 18)] for dia in range(1, 6))


def test_el_cron_del_sabado_termina_a_las_14_20():
    """El sábado el seguro corre de las 7:20 a las 14:20."""
    assert _corridas_del_cron()[6] == [(h, 20) for h in range(7, 15)]


def test_el_cron_no_corre_el_domingo():
    """El domingo no hay corridas."""
    assert _corridas_del_cron()[0] == []


def test_el_cron_da_tres_oportunidades_antes_de_las_10_cada_dia_laboral():
    """Si el disparo exacto falla, el cron tiene al menos tres corridas antes de las 10:00."""
    corridas = _corridas_del_cron()
    assert all(sum(1 for h, _ in corridas[dia] if h < LIMITE_MANANA) >= 3 for dia in range(1, 7))


def test_horario_de_apps_script_de_lunes_a_viernes():
    """Lunes a viernes: 7, 9, 11, 13, 15 y 17 h, con la última a las 17:00."""
    horario = _horario_apps_script()
    assert all(horario[dia] == [7, 9, 11, 13, 15, 17] for dia in range(1, 6))


def test_horario_de_apps_script_del_sabado_cierra_a_las_14():
    """Sábado: 7, 9, 11 y 13 h más la corrida de cierre a las 14:00."""
    assert _horario_apps_script()[6] == [7, 9, 11, 13, 14]


def test_apps_script_no_corre_el_domingo():
    """El domingo (día ISO 7) no está en la tabla."""
    assert 7 not in _horario_apps_script()


def test_ningun_hueco_del_horario_pasa_de_dos_horas():
    """Entre dos corridas del mismo día pasan como máximo 2 horas."""
    for dia, horas in _horario_apps_script().items():
        huecos = [siguiente - anterior for anterior, siguiente in zip(horas, horas[1:])]
        assert max(huecos) <= MAX_HUECO_HORAS, f"día {dia}"


def test_la_informacion_esta_lista_antes_de_las_10_y_con_a_lo_mas_una_hora():
    """Hay al menos dos corridas antes de las 10:00 y la última cae a lo más una hora antes."""
    for dia, horas in _horario_apps_script().items():
        antes = [h for h in horas if h < LIMITE_MANANA]
        assert len(antes) >= 2 and LIMITE_MANANA - max(antes) <= 1, f"día {dia}"


def test_el_cron_respalda_cada_hora_del_disparo_exacto():
    """Cada hora del disparo exacto tiene su corrida de seguro a los 20 minutos."""
    corridas = _corridas_del_cron()
    for dia, horas in _horario_apps_script().items():
        horas_cron = [h for h, _ in corridas[dia]]
        assert all(h in horas_cron for h in horas), f"día {dia}"


def test_el_workflow_se_puede_lanzar_a_mano_y_no_se_encima():
    """Tiene workflow_dispatch, no cancela una corrida en curso, no pide permisos de escritura y tiene tope de tiempo."""
    datos = _workflow()
    assert "workflow_dispatch" in _disparadores(datos)
    assert datos["concurrency"] == {"group": "tablero-sac", "cancel-in-progress": False}
    assert datos["permissions"] == {"contents": "read"}
    assert datos["jobs"]["sync"]["timeout-minutes"] <= 15


def test_el_workflow_sincroniza_solo_las_pestanas_periodicas():
    """El comando no lleva nombres de pestañas ni sincroniza las demás."""
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert "python monday_sac_sync.py --periodicas" in texto
    assert "--todas" not in texto and "--hoja" not in texto


def test_el_workflow_solo_usa_los_secrets_esperados():
    """Los valores sensibles llegan únicamente por secrets; nada va escrito en el archivo."""
    texto = WORKFLOW.read_text(encoding="utf-8")
    assert set(re.findall(r"\$\{\{\s*secrets\.([A-Z_]+)\s*\}\}", texto)) == SECRETS_ESPERADOS


def test_el_disparador_no_lleva_el_token_escrito():
    """El token de GitHub sale de las propiedades del script, no del código."""
    texto = DISPARADOR.read_text(encoding="utf-8")
    assert not re.search(r"github_pat_|ghp_|gho_|ghs_", texto)
    assert "getProperty(TABLERO_SAC.PROPIEDAD_TOKEN)" in texto


def test_el_disparador_no_choca_con_otros_archivos_del_proyecto():
    """Declara un solo nombre global de configuración y todas sus funciones llevan TableroSac en el nombre."""
    texto = DISPARADOR.read_text(encoding="utf-8")
    assert re.findall(r"^(?:const|let|var)\s+(\w+)", texto, re.MULTILINE) == ["TABLERO_SAC"]
    funciones = re.findall(r"^function\s+(\w+)", texto, re.MULTILINE)
    assert funciones and all("tablerosac" in nombre.lower() for nombre in funciones)


def test_el_disparador_verifica_la_zona_horaria_antes_de_crear_los_activadores():
    """Una zona del proyecto con otro desfase haría que los activadores corrieran a horas que el filtro descarta."""
    texto = DISPARADOR.read_text(encoding="utf-8")
    cuerpo = re.search(r"function crearDisparadoresTableroSac\(\) \{(.*?)\n\}", texto, re.DOTALL).group(1)
    assert cuerpo.strip().startswith("tableroSacVerificarZona_();")
    assert "Utilities.formatDate(ahora, zonaProyecto, 'Z')" in texto


def test_el_disparador_ofrece_una_prueba_manual_y_la_creacion_de_disparadores():
    """Las funciones que se ejecutan a mano desde el editor existen con el nombre que documenta programacion.md."""
    funciones = set(re.findall(r"^function\s+(\w+)", DISPARADOR.read_text(encoding="utf-8"), re.MULTILINE))
    assert {"ejecutarTableroSac", "probarDisparoTableroSac", "crearDisparadoresTableroSac"} <= funciones
