import copy
import re
from pathlib import Path

import pytest
from gspread.exceptions import APIError

import filtros_sheets
from tests.fakes import ClienteFalso, copiar, error_api, hoja

HOJA = 1
LIBRO = "libro"


def cliente(*ocultas, con_filtro=True, titulo="DATOS"):
    """Cliente simulado con el parche instalado (una clase nueva por prueba para no contaminar a las demás)."""
    clase = type("ClientePrueba", (ClienteFalso,), {})
    filtros_sheets.instalar(clase)
    return clase({HOJA: hoja(titulo, ocultas, con_filtro)})


def pedir(c, *peticiones):
    return c.batch_update(LIBRO, {"requests": list(peticiones)})


# ---------------------------------------------------------------- sin filtro: no cambia nada
def test_sin_filas_filtradas_pasa_directo_y_no_consulta_nada():
    c = cliente()
    pedir(c, copiar(HOJA, 10))
    assert len(c.llamadas) == 1 and c.consultas == []


def test_destino_con_filas_filtradas_no_activa_el_reintento():
    c = cliente(21, 22, 23)                       # ocultas en el DESTINO (filas 20..24 base 0)
    pedir(c, copiar(HOJA, 10, destino=(20, 25)))
    assert len(c.llamadas) == 1 and c.consultas == []


# ---------------------------------------------------------------- etapa 1: modelo visible más cercano
def test_origen_oculto_usa_la_fila_visible_mas_cercana_hacia_arriba():
    c = cliente(9)                                # la fila 10 (base 1) = índice 9 está oculta
    pedir(c, copiar(HOJA, 10))
    assert len(c.llamadas) == 2
    fuente = c.llamadas[1][0]["copyPaste"]["source"]
    assert (fuente["startRowIndex"], fuente["endRowIndex"]) == (8, 9)      # fila 9 (base 1)
    assert c.hojas[HOJA]["ocultas"] == {9}                                  # el filtro no se tocó
    assert not any("clearBasicFilter" in p for ll in c.llamadas for p in ll)


def test_salta_varias_filas_ocultas_seguidas():
    c = cliente(9, 8, 7)
    pedir(c, copiar(HOJA, 10))
    fuente = c.llamadas[1][0]["copyPaste"]["source"]
    assert fuente["startRowIndex"] == 6                                     # fila 7 (base 1)


def test_conserva_el_resto_de_la_peticion_y_el_destino():
    c = cliente(9)
    otra = {"repeatCell": {"range": {"sheetId": HOJA, "startRowIndex": 0, "endRowIndex": 1}, "cell": {}, "fields": "x"}}
    original = copiar(HOJA, 10, destino=(20, 25), tipo="PASTE_FORMULA")
    copia = copy.deepcopy(original)
    pedir(c, otra, original)
    enviada = c.llamadas[1]
    assert enviada[0] == otra
    assert enviada[1]["copyPaste"]["destination"] == copia["copyPaste"]["destination"]
    assert enviada[1]["copyPaste"]["pasteType"] == "PASTE_FORMULA"
    assert original == copia                                                # no se modifica la petición del llamador


def test_varias_copias_se_corrigen_cada_una():
    c = cliente(9, 4)
    pedir(c, copiar(HOJA, 10, tipo="PASTE_FORMAT"), copiar(HOJA, 5, tipo="PASTE_FORMULA"))
    origenes = [p["copyPaste"]["source"]["startRowIndex"] for p in c.llamadas[1]]
    assert origenes == [8, 3]


def test_titulo_con_comilla_se_escapa_en_el_rango():
    c = cliente(9, titulo="Ventas d'abril")
    pedir(c, copiar(HOJA, 10))
    rango = next(q["ranges"][0] for q in c.consultas if q.get("includeGridData"))
    assert rango.startswith("'Ventas d''abril'!A")
    assert len(c.llamadas) == 2


# ---------------------------------------------------------------- etapa 2: filtro suspendido y restaurado
def test_sin_fila_visible_suspende_el_filtro_y_lo_restaura_igual():
    c = cliente(*range(1, 10))                    # todas las filas de datos hasta la 10 ocultas; sólo el encabezado (fila 1) visible
    filtro_antes = copy.deepcopy(c.hojas[HOJA]["filtro"])
    ocultas_antes = set(c.hojas[HOJA]["ocultas"])
    pedir(c, copiar(HOJA, 10))
    tipos = [next(iter(p)) for ll in c.llamadas for p in ll]
    assert tipos == ["copyPaste", "clearBasicFilter", "copyPaste", "setBasicFilter"]
    assert c.llamadas[2][0]["copyPaste"]["source"]["startRowIndex"] == 9      # el modelo sigue siendo la fila 10, no el encabezado
    assert c.hojas[HOJA]["filtro"] == filtro_antes
    assert c.hojas[HOJA]["ocultas"] == ocultas_antes


def test_origen_de_varias_filas_con_alguna_oculta_suspende_el_filtro():
    c = cliente(5)
    amplio = copiar(HOJA, 4)
    amplio["copyPaste"]["source"]["endRowIndex"] = 8                         # filas 4..8 (base 1), la 6 oculta
    pedir(c, amplio)
    tipos = [next(iter(p)) for ll in c.llamadas for p in ll]
    assert tipos == ["copyPaste", "clearBasicFilter", "copyPaste", "setBasicFilter"]
    assert c.hojas[HOJA]["ocultas"] == {5}


def test_restaura_el_filtro_aunque_la_peticion_falle_y_relanza_el_error():
    c = cliente(*range(1, 10))
    primera = {"hecho": False}

    def fallar(peticiones):
        if any("copyPaste" in p for p in peticiones) and primera["hecho"] and not c.hojas[HOJA]["filtro"]:
            return error_api(500, "falla interna")
        primera["hecho"] = True

    c.fallar_en = fallar
    # la primera llamada se rechaza por la fila filtrada (lo simula el cliente); la repetida sin filtro falla distinto
    with pytest.raises(APIError) as e:
        pedir(c, copiar(HOJA, 10))
    assert "falla interna" in str(e.value)
    assert c.hojas[HOJA]["filtro"] is not None                              # el filtro quedó restaurado
    assert c.hojas[HOJA]["ocultas"] == set(range(1, 10))


def test_si_no_puede_restaurar_el_filtro_lo_avisa_con_un_error():
    c = cliente(*range(1, 10))

    def fallar(peticiones):
        if any("setBasicFilter" in p for p in peticiones):
            return error_api(503, "no disponible")

    c.fallar_en = fallar
    with pytest.raises(RuntimeError, match="No se pudo restaurar el filtro"):
        pedir(c, copiar(HOJA, 10))


def test_rechazo_por_fila_filtrada_sin_filtro_basico_relanza_el_error_original():
    c = cliente(9, con_filtro=False)              # el fake rechaza, pero no hay filtro básico que suspender
    c.hojas[HOJA]["ocultas"] = set(range(1, 10))
    with pytest.raises(APIError) as e:
        pedir(c, copiar(HOJA, 10))
    assert "filtered out row" in str(e.value)


# ---------------------------------------------------------------- otros errores no se tocan
@pytest.mark.parametrize("codigo, mensaje", [(429, "Quota exceeded"), (400, "Invalid requests[0]: otra cosa"), (503, "unavailable")])
def test_otros_errores_pasan_sin_reintento_ni_consultas(codigo, mensaje):
    c = cliente()
    c.fallar_en = lambda peticiones: error_api(codigo, mensaje)
    with pytest.raises(APIError):
        pedir(c, copiar(HOJA, 10))
    assert len(c.llamadas) == 1 and c.consultas == []


# ---------------------------------------------------------------- instalación
def test_instalar_dos_veces_no_anida():
    clase = type("ClientePrueba", (ClienteFalso,), {})
    filtros_sheets.instalar(clase)
    primero = clase.batch_update
    filtros_sheets.instalar(clase)
    assert clase.batch_update is primero
    c = clase({HOJA: hoja("DATOS", (9,))})
    pedir(c, copiar(HOJA, 10))
    assert len(c.llamadas) == 2


def test_se_instala_sobre_el_cliente_real_de_gspread():
    from gspread.http_client import HTTPClient
    antes = HTTPClient.batch_update
    try:
        filtros_sheets.instalar()
        assert getattr(HTTPClient.batch_update, "_tolera_filtros", False)
    finally:
        HTTPClient.batch_update = antes


# ---------------------------------------------------------------- cobertura: toda automatización con copias lo instala
RAIZ = Path(__file__).resolve().parents[2]
OPERACIONES_SENSIBLES = re.compile(r"copyPaste|cutPaste|sortRange")


def _automatizaciones_con_copias():
    for carpeta in sorted(p for p in RAIZ.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        fuentes = [f for f in carpeta.rglob("*.py") if "tests" not in f.parts and f.name != "conftest.py" and "venv" not in f.parts]
        if any(OPERACIONES_SENSIBLES.search(f.read_text(encoding="utf-8")) for f in fuentes):
            yield carpeta, fuentes


@pytest.mark.parametrize("carpeta, fuentes", list(_automatizaciones_con_copias()), ids=lambda v: getattr(v, "name", ""))
def test_toda_automatizacion_con_copypaste_instala_la_tolerancia(carpeta, fuentes):
    assert any("filtros_sheets.instalar()" in f.read_text(encoding="utf-8") for f in fuentes), \
        f"{carpeta.name} usa copyPaste pero no instala filtros_sheets.instalar()"


def test_nunca_toma_el_encabezado_del_filtro_como_modelo():
    c = cliente(*range(1, 10))                    # solo la fila 1 (encabezado del filtro) queda visible por encima del origen
    pedir(c, copiar(HOJA, 10))
    origenes = [p["copyPaste"]["source"]["startRowIndex"] for ll in c.llamadas for p in ll if "copyPaste" in p]
    assert 0 not in origenes
