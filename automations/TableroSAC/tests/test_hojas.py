"""Pruebas de la escritura en Google Sheets con pestañas en memoria."""
import pytest
from gspread.exceptions import APIError
from gspread.http_client import HTTPClient

from fakes_sac import FakeHoja
from sac_sync import hojas


@pytest.mark.parametrize("numero, letra", [(1, "A"), (26, "Z"), (27, "AA"), (36, "AJ"), (52, "AZ"), (53, "BA"), (702, "ZZ")])
def test_letra_columna(numero, letra):
    """Convierte el número de columna a su letra de Sheets."""
    assert hojas.letra_columna(numero) == letra


def test_verificar_encabezados_acepta_los_del_esquema_aunque_haya_columnas_extra():
    """Sólo cuentan las primeras columnas del esquema."""
    hoja = FakeHoja(encabezados=["A", "B", "C", "extra"])
    hojas.verificar_encabezados(hoja, ["A", "B", "C"])


def test_verificar_encabezados_informa_que_columnas_difieren():
    """El error nombra las columnas por su letra y no escribe nada."""
    hoja = FakeHoja(encabezados=["A", "X", "C", "Y"])
    with pytest.raises(hojas.ErrorHoja, match="columnas B, D"):
        hojas.verificar_encabezados(hoja, ["A", "B", "C", "D"])


def test_verificar_encabezados_con_menos_columnas_de_las_esperadas():
    """Una fila 1 más corta que el esquema también se rechaza."""
    hoja = FakeHoja(encabezados=["A", "B"])
    with pytest.raises(hojas.ErrorHoja, match="columnas C"):
        hojas.verificar_encabezados(hoja, ["A", "B", "C"])


def test_contar_filas_con_datos():
    """Cuenta las filas debajo del encabezado hasta la última celda con contenido de la columna."""
    hoja = FakeHoja(encabezados=["Folio"], filas=[[1], [2], [3]])
    assert hojas.contar_filas_con_datos(hoja, 1) == 3
    assert hojas.contar_filas_con_datos(FakeHoja(encabezados=["Folio"]), 1) == 0
    assert hojas.contar_filas_con_datos(FakeHoja(), 1) == 0


def test_escribir_filas_usa_raw_y_cambia_none_por_cadena_vacia():
    """Un None se escribe como "" para borrar el valor anterior de la celda; el resto conserva su tipo."""
    hoja = FakeHoja(filas=[["viejo", "viejo", "viejo"]])
    escritas = hojas.escribir_filas(hoja, [["a", None, 1.5], [None, 2, "0012"]], 3)
    assert escritas == 2
    assert hoja.llamadas == [("update", "A2:C3", "RAW", 2)]
    assert hoja.celdas == {(2, 1): "a", (2, 3): 1.5, (3, 2): 2, (3, 3): "0012"}


def test_escribir_filas_parte_en_lotes_de_filas():
    """Mil filas se escriben en lotes de TAM_LOTE_FILAS filas, cada uno en su rango."""
    hoja = FakeHoja(row_count=2000)
    hojas.escribir_filas(hoja, [["x", 1, "y"] for _ in range(1000)], 3)
    assert [llamada[1] for llamada in hoja.llamadas] == ["A2:C401", "A402:C801", "A802:C1001"]


def test_escribir_filas_parte_en_lotes_de_bytes(monkeypatch):
    """Además del número de filas, un lote no pasa del tope de bytes."""
    monkeypatch.setattr(hojas, "MAX_BYTES_LOTE", 30)
    hoja = FakeHoja()
    hojas.escribir_filas(hoja, [["x", 1, "y"] for _ in range(5)], 3)
    assert [llamada[1] for llamada in hoja.llamadas] == ["A2:C3", "A4:C5", "A6:C6"]


def test_escribir_filas_rechaza_una_fila_con_columnas_de_mas_o_de_menos():
    """Una fila que no mide lo que el esquema es un error de programación, no se escribe."""
    with pytest.raises(hojas.ErrorHoja, match="columnas"):
        hojas.escribir_filas(FakeHoja(), [["a", "b"]], 3)


def test_escribir_cero_filas_no_llama_a_la_api():
    """Sin filas no hay escritura."""
    hoja = FakeHoja()
    assert hojas.escribir_filas(hoja, [], 3) == 0
    assert hoja.llamadas == []


def test_asegurar_filas_amplia_con_holgura_y_copia_el_formato():
    """Al faltar capacidad agrega filas con holgura y repite el formato de la última fila existente."""
    hoja = FakeHoja(row_count=10)
    assert hojas.asegurar_filas(hoja, 15, 3) == 15 - 10 + hojas.HOLGURA_FILAS
    assert hoja.row_count == 15 + hojas.HOLGURA_FILAS
    solicitud = hoja.spreadsheet.solicitudes[0]["requests"][0]["copyPaste"]
    assert solicitud["source"] == {"sheetId": 777, "startRowIndex": 9, "endRowIndex": 10,
                                   "startColumnIndex": 0, "endColumnIndex": 3}
    assert solicitud["destination"]["startRowIndex"] == 10
    assert solicitud["destination"]["endRowIndex"] == hoja.row_count
    assert solicitud["pasteType"] == "PASTE_FORMAT"


def test_asegurar_filas_no_hace_nada_si_alcanza():
    """Con capacidad suficiente no se toca la pestaña."""
    hoja = FakeHoja(row_count=1000)
    assert hojas.asegurar_filas(hoja, 1000, 3) == 0
    assert hoja.llamadas == [] and hoja.spreadsheet.solicitudes == []


def test_limpiar_sobrantes_borra_hasta_el_final_de_la_pestana():
    """Borra desde la fila indicada hasta la última fila de la pestaña."""
    hoja = FakeHoja(row_count=10, filas=[["a"], ["b"], ["c"], ["d"]])
    assert hojas.limpiar_sobrantes(hoja, 4, 3) is True
    assert hoja.llamadas == [("batch_clear", ("A4:C10",))]
    assert (4, 1) not in hoja.celdas and (3, 1) in hoja.celdas


def test_limpiar_sobrantes_no_llama_si_no_hay_nada_que_limpiar():
    """Si la primera fila sobrante ya está fuera de la pestaña, no hay llamada."""
    hoja = FakeHoja(row_count=10)
    assert hojas.limpiar_sobrantes(hoja, 11, 3) is False
    assert hoja.llamadas == []


def test_leer_datos_completa_con_none_las_celdas_finales():
    """La API omite las celdas finales vacías; se completan hasta el ancho del esquema."""
    hoja = FakeHoja(row_count=10, filas=[["a", 1], [None, None, "z"]])
    assert hojas.leer_datos(hoja, 3) == [["a", 1, None], [None, None, "z"]]
    assert hoja.llamadas == [("get", "A2:C10", "UNFORMATTED_VALUE")]


class _RespuestaApi:
    """Respuesta de error de la API de Google con la forma que espera APIError."""

    def __init__(self, codigo):
        """Fija el código HTTP y el cuerpo de error."""
        self.status_code = codigo
        self.text = "error"
        self._cuerpo = {"error": {"code": codigo, "message": "cuota", "status": "ERROR"}}

    def json(self):
        """Cuerpo JSON del error."""
        return self._cuerpo


def test_los_reintentos_de_gspread_repiten_los_429_y_no_los_5xx_de_escritura(monkeypatch):
    """Un 429 se reintenta con pausa; un 500 sólo se reintenta si es una lectura (GET)."""
    llamadas = []
    resultados = [APIError(_RespuestaApi(429)), "listo"]

    def original(self, method, *args, **kwargs):
        """Sustituto de HTTPClient.request que falla una vez con 429."""
        llamadas.append(method)
        resultado = resultados.pop(0)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    pausas = []
    monkeypatch.setattr(HTTPClient, "request", original)
    monkeypatch.setattr(hojas.time, "sleep", pausas.append)
    hojas.instalar_reintentos_gspread()

    assert HTTPClient.request(object(), "post") == "listo"
    assert llamadas == ["post", "post"] and pausas == [20]

    resultados[:] = [APIError(_RespuestaApi(500))]
    with pytest.raises(APIError):
        HTTPClient.request(object(), "post")

    resultados[:] = [APIError(_RespuestaApi(500)), "leido"]
    assert HTTPClient.request(object(), "get") == "leido"
