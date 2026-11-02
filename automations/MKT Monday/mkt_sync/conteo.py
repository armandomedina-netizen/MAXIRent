"""Conteo de leads recibidos y calificados de un mes."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Mexico_City")
DIAS_CIERRE_MES_ANTERIOR = 3


def mes_de_creacion(creado: str) -> tuple[int, int]:
    """(año, mes) en hora de Ciudad de México de la fecha de creación que monday entrega en UTC."""
    momento = datetime.fromisoformat(creado.replace("Z", "+00:00")).astimezone(ZONA)
    return momento.year, momento.month


def periodos_a_actualizar(ahora: datetime) -> list[tuple[int, int]]:
    """Mes en curso y, durante los primeros días del mes, también el anterior (que va primero), para que
    el cierre de un mes incluya los leads de sus últimos días y los que se calificaron después de la
    última corrida."""
    actual = (ahora.year, ahora.month)
    if ahora.day > DIAS_CIERRE_MES_ANTERIOR:
        return [actual]
    anterior = (ahora.year - 1, 12) if ahora.month == 1 else (ahora.year, ahora.month - 1)
    return [anterior, actual]


def contar_mes(leads: list[dict], columna_estado: str, etiqueta_califica: str, anio: int, mes: int) -> tuple[int, int]:
    """Leads creados en el mes y, de ellos, los que tienen la etiqueta de calificado en la columna de
    estado. Un lead sin estado cuenta como recibido y no como calificado."""
    recibidos = calificados = 0
    for lead in leads:
        if mes_de_creacion(lead["created_at"]) != (anio, mes):
            continue
        recibidos += 1
        estado = next((cv.get("text") for cv in lead.get("column_values") or [] if cv["id"] == columna_estado), None)
        if estado == etiqueta_califica:
            calificados += 1
    return recibidos, calificados
