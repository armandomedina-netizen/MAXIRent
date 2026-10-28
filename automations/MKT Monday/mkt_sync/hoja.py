"""Hoja de Google: busca la fila del periodo y actualiza leads recibidos y calificados sin tocar nada más."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import gspread
from google.oauth2 import service_account
from gspread.utils import ValueRenderOption

from .config import Config
from .errores import ErrorHoja

log = logging.getLogger("mkt_sync.hoja")

ALCANCE = ["https://www.googleapis.com/auth/spreadsheets"]
# Sheets cuenta los días de una fecha desde esta fecha.
ORIGEN_SERIE = date(1899, 12, 30)
MESES = {
    "ene": 1, "enero": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3, "abr": 4, "abril": 4,
    "may": 5, "mayo": 5, "jun": 6, "junio": 6, "jul": 7, "julio": 7, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "oct": 10, "octubre": 10, "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12,
}


@dataclass(frozen=True)
class Resultado:
    """Qué pasó con la fila del periodo: dónde está, qué valores tenía, cuáles quedan y si se escribió."""

    fila: int
    antes: tuple
    despues: tuple[int, int]
    escrito: bool


def abrir_libro(ruta_credenciales: str, id_libro: str) -> gspread.Spreadsheet:
    """Abre el libro con la cuenta de servicio. Si Google lo rechaza, el mensaje dice con qué cuenta
    hay que compartirlo."""
    try:
        creds = service_account.Credentials.from_service_account_file(ruta_credenciales, scopes=ALCANCE)
    except (OSError, ValueError):
        raise ErrorHoja("no se pudieron leer las credenciales de Google (GOOGLE_CREDS_PATH)") from None
    try:
        return gspread.authorize(creds).open_by_key(id_libro)
    except (gspread.exceptions.APIError, gspread.exceptions.SpreadsheetNotFound) as e:
        codigo = getattr(getattr(e, "response", None), "status_code", "?")
        raise ErrorHoja(f"Google no dio acceso al libro (HTTP {codigo}); compártelo como editor con "
                        f"{creds.service_account_email}") from None


def parsear_periodo(valor) -> tuple[int, int] | None:
    """(año, mes) de la celda de periodo, sea fecha (número de serie) o texto como 'oct 2026'; None si
    no es un periodo."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        try:
            dia = ORIGEN_SERIE + timedelta(days=int(valor))
        except OverflowError:
            return None
        return dia.year, dia.month
    if isinstance(valor, str):
        partes = valor.strip().lower().replace(".", "").split()
        if len(partes) == 2 and partes[0] in MESES and partes[1].isdigit() and len(partes[1]) == 4:
            return int(partes[1]), MESES[partes[0]]
    return None


def buscar_fila(periodos: list, primera_fila: int, anio: int, mes: int) -> int:
    """Número de fila del periodo dentro de la columna de periodos, que empieza en `primera_fila`.
    Falla si no hay fila de ese periodo o si hay más de una, para no escribir en la equivocada."""
    filas = [primera_fila + i for i, valor in enumerate(periodos) if parsear_periodo(valor) == (anio, mes)]
    if not filas:
        raise ErrorHoja(f"la hoja no tiene fila para el periodo {anio}-{mes:02d}; agrega la fila del periodo")
    if len(filas) > 1:
        raise ErrorHoja(f"la hoja tiene {len(filas)} filas para el periodo {anio}-{mes:02d}: {filas}")
    return filas[0]


def leer_periodos(hoja: gspread.Worksheet, cfg: Config) -> list:
    """Valores sin formato de la columna de periodos desde la primera fila de la tabla."""
    rango = f"{cfg.columna_periodo}{cfg.primera_fila}:{cfg.columna_periodo}"
    datos = hoja.get(rango, value_render_option=ValueRenderOption.unformatted)
    return [fila[0] if fila else None for fila in datos]


def _leer_celda(hoja: gspread.Worksheet, celda: str):
    """Contenido de una celda como se escribió (una fórmula se ve como fórmula); None si está vacía."""
    datos = hoja.get(celda, value_render_option=ValueRenderOption.formula)
    return datos[0][0] if datos and datos[0] else None


def actualizar_mes(hoja: gspread.Worksheet, cfg: Config, anio: int, mes: int, recibidos: int, calificados: int,
                   *, simular: bool = False, forzar: bool = False) -> Resultado:
    """Escribe leads recibidos y calificados en la fila del periodo, sólo en las celdas que cambian. No
    sobrescribe una celda con fórmula y no baja a cero un total que ya tiene leads salvo que se fuerce,
    porque un cero suele ser una lectura fallida y no un mes sin leads."""
    fila = buscar_fila(leer_periodos(hoja, cfg), cfg.primera_fila, anio, mes)
    celdas = (f"{cfg.columna_recibidos}{fila}", f"{cfg.columna_calificados}{fila}")
    actuales = tuple(_leer_celda(hoja, celda) for celda in celdas)
    for celda, valor in zip(celdas, actuales):
        if isinstance(valor, str) and valor.startswith("="):
            raise ErrorHoja(f"la celda {celda} tiene una fórmula; no se sobrescribe")
    if not forzar and recibidos == 0 and isinstance(actuales[0], (int, float)) and actuales[0] > 0:
        raise ErrorHoja("monday devolvió 0 leads recibidos y la hoja ya tiene un total mayor que cero; "
                        "no se escribe (usa --forzar si es correcto)")
    nuevos = (recibidos, calificados)
    cambios = [(celda, valor) for celda, valor, actual in zip(celdas, nuevos, actuales) if actual != valor]
    if cambios and not simular:
        for celda, valor in cambios:
            hoja.update(values=[[valor]], range_name=celda, value_input_option="RAW")
    return Resultado(fila=fila, antes=actuales, despues=nuevos, escrito=bool(cambios) and not simular)
