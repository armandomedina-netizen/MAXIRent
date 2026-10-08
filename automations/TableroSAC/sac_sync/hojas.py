"""Lectura y escritura en las pestañas de Google Sheets. Sólo toca los datos (de la fila 2 en
adelante): no crea ni borra pestañas, no cambia encabezados ni formatos, salvo repetir el
formato de la última fila en las filas que agrega.
"""
from __future__ import annotations

import json
import logging
import time

import gspread
from google.oauth2 import service_account
from gspread.exceptions import APIError
from gspread.http_client import HTTPClient

log = logging.getLogger("sac_sync.hojas")

# Permiso de lectura y escritura sobre hojas de cálculo.
ALCANCE = ["https://www.googleapis.com/auth/spreadsheets"]
# Tope de filas y de bytes por petición de escritura.
TAM_LOTE_FILAS = 400
MAX_BYTES_LOTE = 4_000_000
# Filas extra al ampliar una pestaña, para no ampliarla en cada corrida.
HOLGURA_FILAS = 100


class ErrorHoja(RuntimeError):
    """Una pestaña no está como el esquema espera, o la escritura no quedó bien."""


def letra_columna(n: int) -> str:
    """Convierte el número de columna (1 = A) a su letra de Sheets."""
    letras = ""
    while n > 0:
        n, resto = divmod(n - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def instalar_reintentos_gspread() -> None:
    """Hace que gspread reintente ante 429 y, sólo en lecturas, ante 5xx. La cuota de lecturas de
    Google Sheets es por usuario y la comparten todos los procesos de la misma cuenta de servicio;
    un 429 se rechaza antes de procesarse, por eso reintentarlo no duplica escrituras."""
    if getattr(HTTPClient.request, "_sac_reintentos", False):
        return
    original = HTTPClient.request

    def con_reintentos(self, method, *args, **kwargs):
        """Envuelve la petición original con la política de reintentos."""
        for intento in range(1, 7):
            try:
                return original(self, method, *args, **kwargs)
            except APIError as e:
                codigo = getattr(e.response, "status_code", None)
                reintentable = codigo == 429 or (codigo in (500, 502, 503) and str(method).lower() == "get")
                if not reintentable or intento == 6:
                    raise
                espera = 20 * intento
                log.warning("Google Sheets respondió %s; reintento %d de 5 en %d s", codigo, intento, espera)
                time.sleep(espera)

    con_reintentos._sac_reintentos = True
    HTTPClient.request = con_reintentos


def conectar(ruta_credenciales: str, id_libro: str):
    """Abre el libro de Google Sheets con la cuenta de servicio."""
    instalar_reintentos_gspread()
    creds = service_account.Credentials.from_service_account_file(ruta_credenciales, scopes=ALCANCE)
    return gspread.authorize(creds).open_by_key(id_libro)


def verificar_encabezados(hoja, encabezados: list[str]) -> None:
    """Compara la fila 1 con los encabezados del esquema y lanza ErrorHoja si difieren."""
    actuales = hoja.row_values(1)
    if actuales[:len(encabezados)] == list(encabezados):
        return
    distintas = [letra_columna(i + 1) for i, esperado in enumerate(encabezados)
                 if i >= len(actuales) or actuales[i] != esperado]
    raise ErrorHoja(f"los encabezados de la fila 1 no coinciden con el esquema (columnas {', '.join(distintas)}); "
                    "no se escribió nada")


def contar_filas_con_datos(hoja, columna: int = 1) -> int:
    """Cuenta las filas de datos (sin el encabezado) hasta la última celda con contenido de una columna."""
    valores = hoja.col_values(columna)
    while valores and valores[-1] == "":
        valores.pop()
    return max(0, len(valores) - 1)


def leer_datos(hoja, ncols: int) -> list[list]:
    """Lee los valores sin formato (fechas y duraciones como número de serie) desde A2 hasta el
    final de la pestaña, completando con None las celdas finales que la API omite."""
    if hoja.row_count < 2:
        return []
    bruto = hoja.get(f"A2:{letra_columna(ncols)}{hoja.row_count}", value_render_option="UNFORMATTED_VALUE")
    return [list(fila) + [None] * (ncols - len(fila)) for fila in bruto]


def asegurar_filas(hoja, filas_necesarias: int, ncols: int) -> int:
    """Amplía la pestaña si no alcanza para las filas necesarias (con holgura) y repite en las filas
    nuevas el formato de la última fila existente. Devuelve cuántas filas agregó."""
    if hoja.row_count >= filas_necesarias:
        return 0
    ultima = hoja.row_count
    agregar = filas_necesarias - ultima + HOLGURA_FILAS
    hoja.add_rows(agregar)
    # Las filas agregadas no siempre heredan el formato de fecha y duración de las columnas.
    hoja.spreadsheet.batch_update({"requests": [{"copyPaste": {
        "source": {"sheetId": hoja.id, "startRowIndex": ultima - 1, "endRowIndex": ultima,
                   "startColumnIndex": 0, "endColumnIndex": ncols},
        "destination": {"sheetId": hoja.id, "startRowIndex": ultima, "endRowIndex": ultima + agregar,
                        "startColumnIndex": 0, "endColumnIndex": ncols},
        "pasteType": "PASTE_FORMAT",
        "pasteOrientation": "NORMAL",
    }}]})
    return agregar


def _celdas(fila: list, ncols: int) -> list:
    """Prepara una fila para la API: None pasa a "" porque un null se saltaría la celda y dejaría el
    valor anterior. Lanza ErrorHoja si la fila no tiene exactamente ncols celdas."""
    if len(fila) != ncols:
        raise ErrorHoja(f"una fila trae {len(fila)} columnas y el esquema {ncols}")
    return ["" if v is None else v for v in fila]


def _lotes(filas: list[list], ncols: int):
    """Reparte las filas en lotes limitados por número de filas y por bytes; produce (índice de la
    primera fila del lote, filas del lote)."""
    lote, bytes_lote, inicio = [], 0, 0
    for i, fila in enumerate(filas):
        celdas = _celdas(fila, ncols)
        peso = len(json.dumps(celdas, ensure_ascii=False).encode("utf-8"))
        if lote and (len(lote) >= TAM_LOTE_FILAS or bytes_lote + peso > MAX_BYTES_LOTE):
            yield inicio, lote
            lote, bytes_lote, inicio = [], 0, i
        lote.append(celdas)
        bytes_lote += peso
    if lote:
        yield inicio, lote


def escribir_filas(hoja, filas: list[list], ncols: int) -> int:
    """Escribe las filas desde A2 en lotes con valueInputOption RAW. Devuelve cuántas escribió."""
    letra = letra_columna(ncols)
    escritas = 0
    for inicio, lote in _lotes(filas, ncols):
        primera = 2 + inicio
        hoja.update(values=lote, range_name=f"A{primera}:{letra}{primera + len(lote) - 1}",
                    value_input_option="RAW")
        escritas += len(lote)
    return escritas


def limpiar_sobrantes(hoja, desde_fila: int, ncols: int) -> bool:
    """Borra los valores (no los formatos) desde una fila hasta el final de la pestaña. Se ejecuta
    después de escribir para que la pestaña no quede vacía a media corrida. Devuelve si hubo algo
    que limpiar."""
    if desde_fila > hoja.row_count:
        return False
    hoja.batch_clear([f"A{desde_fila}:{letra_columna(ncols)}{hoja.row_count}"])
    return True
