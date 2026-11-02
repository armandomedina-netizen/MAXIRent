"""Tolerancia a filtros de Google Sheets para las automatizaciones.

Problema (2-nov-2026, Encuestas CP): con un filtro básico activo en la hoja, Google Sheets rechaza un `copyPaste` con
"This operation is not supported on a range with a filtered out row" cuando el ORIGEN de la copia (la fila modelo de
formato o de fórmulas) tiene una fila oculta por el filtro. Probado contra la API real: un destino con filas filtradas,
`repeatCell`, `insertDimension`, `updateCells` y la escritura de valores funcionan con filtro; sólo falla el origen oculto.

Solución: se instala sobre `HTTPClient.batch_update` de gspread, así que cubre todas las llamadas sin tocarlas una por
una, y no hace nada mientras Sheets acepte la petición. Sólo cuando Sheets rechaza una copia por una fila filtrada:

  1. Si el origen es una sola fila, la copia se rehace tomando como modelo la fila VISIBLE más cercana hacia arriba
     (las fórmulas se ajustan solas a la fila destino y el formato es el de una fila de datos igual de reciente).
  2. Si no hay una fila visible o el origen abarca varias filas, se suspende el filtro de esa hoja, se ejecuta la
     petición y se restaura el MISMO filtro (rango, criterios y orden) en un bloque `finally`. Si la restauración
     fallara, se registra y se levanta un error para que la guardia lo vea.

No se imprimen datos de las hojas: sólo conteos y el nombre de la pestaña.
"""
import copy
import logging

import gspread
from gspread.http_client import HTTPClient

log = logging.getLogger("filtros_sheets")

MENSAJE_FILA_FILTRADA = "filtered out row"
# Hasta cuántas filas hacia arriba se busca una fila visible para usarla como modelo.
VENTANA_BUSQUEDA = 3000


def _es_fila_filtrada(error: Exception) -> bool:
    return MENSAJE_FILA_FILTRADA in str(error)


def _hojas(cliente, libro_id: str) -> dict:
    """{sheetId: {"titulo": ..., "filtro": filtro básico o None}} del libro."""
    meta = cliente.fetch_sheet_metadata(libro_id, params={"fields": "sheets(properties(sheetId,title),basicFilter)"})
    return {h["properties"]["sheetId"]: {"titulo": h["properties"].get("title", ""), "filtro": h.get("basicFilter")}
            for h in meta.get("sheets", [])}


def _filas_ocultas(cliente, libro_id: str, titulo: str, desde: int, hasta: int) -> set:
    """Índices (base 0) de las filas ocultas POR FILTRO dentro de [desde, hasta)."""
    if hasta <= desde:
        return set()
    titulo_a1 = titulo.replace("'", "''")
    meta = cliente.fetch_sheet_metadata(libro_id, params={
        "ranges": [f"'{titulo_a1}'!A{desde + 1}:A{hasta}"],
        "includeGridData": True,
        "fields": "sheets(data(startRow,rowMetadata(hiddenByFilter)))",
    })
    ocultas = set()
    for hoja in meta.get("sheets", []):
        for bloque in hoja.get("data", []):
            inicio = bloque.get("startRow", 0)
            for i, fila in enumerate(bloque.get("rowMetadata", []) or []):
                if fila.get("hiddenByFilter"):
                    ocultas.add(inicio + i)
    return ocultas


def _con_modelos_visibles(cliente, libro_id: str, peticiones: list, hojas: dict):
    """Copia de `peticiones` con cada copyPaste de origen de una sola fila oculta apuntando a la fila visible más cercana
    hacia arriba. Devuelve None si no se pudo cambiar nada (hay que pasar a la etapa 2)."""
    cambiadas = 0
    resultado = []
    for p in peticiones:
        cp = p.get("copyPaste") if isinstance(p, dict) else None
        origen = cp.get("source") if cp else None
        # Sin filtro básico no hay encabezado conocido que acote la búsqueda de un modelo: no se intenta la etapa 1.
        if not origen or "endRowIndex" not in origen or not hojas.get(origen.get("sheetId"), {}).get("filtro"):
            resultado.append(p)
            continue
        r1 = origen.get("startRowIndex", 0)
        r2 = origen["endRowIndex"]
        titulo = hojas[origen["sheetId"]]["titulo"]
        # La fila de encabezado del filtro nunca se oculta, pero no es un modelo válido: se busca sólo debajo de ella.
        filtro = hojas[origen["sheetId"]]["filtro"]
        piso = filtro["range"].get("startRowIndex", 0) + 1
        busqueda_desde = max(piso, r1 - VENTANA_BUSQUEDA)
        ocultas = _filas_ocultas(cliente, libro_id, titulo, busqueda_desde, r2)
        if not any(r in ocultas for r in range(r1, r2)):
            resultado.append(p)
            continue
        if r2 - r1 != 1:
            return None                       # origen de varias filas con alguna oculta: etapa 2
        modelo = next((r for r in range(r1 - 1, busqueda_desde - 1, -1) if r not in ocultas), None)
        if modelo is None:                    # sin fila de datos visible debajo del encabezado: etapa 2
            return None
        nuevo = copy.deepcopy(p)
        nuevo["copyPaste"]["source"]["startRowIndex"] = modelo
        nuevo["copyPaste"]["source"]["endRowIndex"] = modelo + 1
        resultado.append(nuevo)
        cambiadas += 1
        log.warning("%s: la fila modelo %d está oculta por un filtro; se usa la fila visible %d.", titulo, r1 + 1, modelo + 1)
    return resultado if cambiadas else None


def _restaurar_filtros(cliente, original, libro_id: str, quitados: list, hojas: dict) -> None:
    try:
        original(cliente, libro_id, {"requests": [{"setBasicFilter": {"filter": f}} for _, f in quitados]})
    except Exception as e:
        nombres = ", ".join(hojas[s]["titulo"] for s, _ in quitados)
        log.error("NO se pudo restaurar el filtro de: %s (%s). Hay que volver a ponerlo a mano.", nombres, type(e).__name__)
        raise RuntimeError(f"No se pudo restaurar el filtro de: {nombres}") from e


def _con_filtro_suspendido(cliente, original, libro_id: str, cuerpo: dict, peticiones: list, hojas: dict, error: Exception):
    """Etapa 2: suspende el filtro básico de las hojas que usa la petición, la ejecuta y lo restaura igual."""
    ids = []
    for p in peticiones:
        cp = p.get("copyPaste") if isinstance(p, dict) else None
        sid = ((cp or {}).get("source") or {}).get("sheetId")
        if sid in hojas and hojas[sid]["filtro"] and sid not in ids:
            ids.append(sid)
    con_filtro = [(sid, hojas[sid]["filtro"]) for sid in ids]
    if not con_filtro:
        raise error                           # el rechazo no viene de un filtro básico: nada que suspender
    quitados = []
    try:
        original(cliente, libro_id, {"requests": [{"clearBasicFilter": {"sheetId": sid}} for sid, _ in con_filtro]})
        quitados = con_filtro
        log.warning("Se suspendió el filtro de %d hoja(s) para completar la petición; se restaura al terminar.", len(quitados))
        return original(cliente, libro_id, cuerpo)
    finally:
        if quitados:
            _restaurar_filtros(cliente, original, libro_id, quitados, hojas)
            log.info("Filtro restaurado en %d hoja(s).", len(quitados))


def instalar(cliente=HTTPClient) -> None:
    """Instala la tolerancia a filtros en `cliente.batch_update`. Es idempotente (no se anida)."""
    if getattr(cliente.batch_update, "_tolera_filtros", False):
        return
    original = cliente.batch_update

    def batch_update(self, id, body):
        try:
            return original(self, id, body)
        except gspread.exceptions.APIError as e:
            if not _es_fila_filtrada(e):
                raise
            log.warning("Google Sheets rechazó una copia porque la fila modelo está oculta por un filtro; se reintenta.")
            cuerpo = body or {}
            peticiones = list(cuerpo.get("requests", []))
            hojas = _hojas(self, id)
            nuevas = _con_modelos_visibles(self, id, peticiones, hojas)
            if nuevas is not None:
                try:
                    return original(self, id, {**cuerpo, "requests": nuevas})
                except gspread.exceptions.APIError as e2:
                    if not _es_fila_filtrada(e2):
                        raise
            return _con_filtro_suspendido(self, original, id, cuerpo, peticiones, hojas, e)

    batch_update._tolera_filtros = True
    cliente.batch_update = batch_update
