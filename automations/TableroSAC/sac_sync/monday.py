"""Cliente de lectura de la API GraphQL de monday. Sólo consulta: no envía mutaciones.

Las consultas son items_page y next_items_page, con fragmentos que exponen display_value
en reflejos, relaciones, fórmulas y subelementos, tipos que la herramienta MCP
get_board_items_page no soporta.
"""
from __future__ import annotations

import logging
import time

import requests

from .config import Esquema

log = logging.getLogger("sac_sync.monday")

URL_API = "https://api.monday.com/v2"
# Versión "current" de la API al 7-oct-2026.
VERSION_API_POR_DEFECTO = "2026-07"
# Elementos por página; con tantas columnas reflejadas, más elementos exceden el límite de complejidad.
TAM_PAGINA = 100
TAM_PAGINA_MINIMO = 10
MAX_INTENTOS = 8

# Códigos de error de monday que se resuelven reintentando más tarde.
CODIGOS_REINTENTABLES = {
    "COMPLEXITY_BUDGET_EXHAUSTED", "RATE_LIMIT_EXCEEDED", "RateLimitExceeded",
    "IP_RATE_LIMIT_EXCEEDED", "CONCURRENCY_LIMIT_EXCEEDED",
}

# Campos de cada elemento; column_values se limita a las columnas del esquema.
_CAMPOS_ITEM = """
      id
      name
      group { id title }
      column_values(ids: $ids) {
        id
        type
        text
        ... on MirrorValue { display_value }
        ... on BoardRelationValue { display_value }
        ... on FormulaValue { display_value }
        ... on SubtasksValue { display_value }
      }
"""

# Primera página de un grupo: filtra por grupo y devuelve el cursor para continuar.
PRIMERA_PAGINA = """
query ($tablero: ID!, $limite: Int!, $filtro: ItemsQuery, $ids: [String!]) {
  boards(ids: [$tablero]) {
    items_page(limit: $limite, query_params: $filtro) {
      cursor
      items {""" + _CAMPOS_ITEM + """      }
    }
  }
}
"""

# Páginas siguientes: continúan desde el cursor de la anterior.
SIGUIENTE_PAGINA = """
query ($cursor: String!, $limite: Int!, $ids: [String!]) {
  next_items_page(limit: $limite, cursor: $cursor) {
    cursor
    items {""" + _CAMPOS_ITEM + """    }
  }
}
"""

# Columnas, grupos y total de elementos del tablero.
ESTRUCTURA_TABLERO = """
query ($tablero: ID!) {
  boards(ids: [$tablero]) {
    items_count
    columns { id title type }
    groups { id title }
  }
}
"""


class ErrorMonday(RuntimeError):
    """monday rechazó la petición o no respondió bien tras los reintentos."""


class ComplejidadExcedida(ErrorMonday):
    """La consulta supera el límite de complejidad por consulta de monday."""


def _segundos(valor) -> float | None:
    """Convierte a segundos no negativos; devuelve None si el valor no es numérico."""
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return None


def _codigo(error: dict) -> str:
    """Código de extensión de un error GraphQL de monday, o '' si no trae."""
    return (error.get("extensions") or {}).get("code") or ""


class ClienteMonday:
    """Lector del tablero de monday con reintentos, paginación por cursor y ajuste del tamaño de página."""

    def __init__(self, token: str, tablero_id: int, version: str = VERSION_API_POR_DEFECTO, *,
                 sesion=None, dormir=time.sleep, tam_pagina: int = TAM_PAGINA):
        """Prepara la sesión HTTP con el token y la versión de la API; `dormir` y `sesion` son inyectables."""
        self._tablero = tablero_id
        self._sesion = sesion if sesion is not None else requests.Session()
        self._sesion.headers.update({"Authorization": token, "API-Version": version,
                                     "Content-Type": "application/json"})
        self._dormir = dormir
        self._limite = tam_pagina

    def _consultar(self, consulta: str, variables: dict) -> dict:
        """Ejecuta una consulta GraphQL y devuelve `data`. Reintenta ante 429, 5xx, cortes de red y
        límites de monday, esperando lo que monday indica cuando lo indica; los errores de
        autenticación y los demás errores GraphQL se lanzan sin reintentar."""
        motivo = ""
        for intento in range(1, MAX_INTENTOS + 1):
            try:
                resp = self._sesion.post(URL_API, json={"query": consulta, "variables": variables}, timeout=120)
            except (requests.ConnectionError, requests.Timeout) as e:
                motivo, espera = type(e).__name__, min(5 * intento, 60)
            else:
                if resp.status_code in (401, 403):
                    raise ErrorMonday(f"monday rechazó las credenciales (HTTP {resp.status_code})")
                if resp.status_code == 429 or resp.status_code >= 500:
                    motivo = f"HTTP {resp.status_code}"
                    espera = _segundos(resp.headers.get("Retry-After")) or min(5 * intento, 60)
                else:
                    try:
                        cuerpo = resp.json()
                    except ValueError:
                        raise ErrorMonday(f"monday respondió algo que no es JSON (HTTP {resp.status_code})") from None
                    errores = cuerpo.get("errors") or []
                    if not errores:
                        return cuerpo.get("data") or {}
                    codigos = {_codigo(e) for e in errores}
                    mensajes = " | ".join(str(e.get("message", ""))[:200] for e in errores)
                    if "maxComplexityExceeded" in codigos or "exceeds max complexity" in mensajes:
                        raise ComplejidadExcedida(mensajes)
                    if codigos & CODIGOS_REINTENTABLES and "DAILY_LIMIT_EXCEEDED" not in codigos:
                        motivo = "límite de monday (" + ", ".join(sorted(codigos & CODIGOS_REINTENTABLES)) + ")"
                        # retry_in_seconds es lo que monday tarda en reponer el presupuesto de complejidad.
                        pedida = max((_segundos((e.get("extensions") or {}).get("retry_in_seconds")) or 0
                                      for e in errores), default=0)
                        espera = max(pedida + 1, min(5 * intento, 60))
                    else:
                        raise ErrorMonday(f"monday devolvió un error ({', '.join(sorted(codigos)) or 'sin código'}): {mensajes}")
            if intento == MAX_INTENTOS:
                raise ErrorMonday(f"monday no respondió bien tras {MAX_INTENTOS} intentos ({motivo})")
            log.warning("monday: %s; reintento %d de %d en %d s", motivo, intento, MAX_INTENTOS - 1, espera)
            self._dormir(espera)

    def _con_ajuste(self, consulta: str, variables: dict) -> dict:
        """Ejecuta la consulta con el tamaño de página vigente; si excede la complejidad por consulta,
        lo reduce a la mitad (hasta el mínimo) y repite."""
        while True:
            try:
                return self._consultar(consulta, {**variables, "limite": self._limite})
            except ComplejidadExcedida:
                if self._limite <= TAM_PAGINA_MINIMO:
                    raise ErrorMonday(f"la consulta excede el límite de complejidad aun con páginas de {self._limite} elementos") from None
                self._limite = max(TAM_PAGINA_MINIMO, self._limite // 2)
                log.warning("monday: consulta demasiado compleja; ahora de %d elementos por página", self._limite)

    def validar_esquema(self, esquema: Esquema) -> int:
        """Contrasta el esquema con el tablero real: que el token lo vea y que existan sus grupos y
        columnas. Los títulos que cambiaron sólo se avisan. Devuelve el total de elementos del tablero."""
        tableros = self._consultar(ESTRUCTURA_TABLERO, {"tablero": esquema.tablero_id}).get("boards") or []
        if not tableros:
            raise ErrorMonday("el token no ve el tablero del esquema")
        tablero = tableros[0]
        columnas = {c["id"]: c for c in tablero["columns"]}
        grupos = {g["id"]: g for g in tablero["groups"]}

        faltan = [c.encabezado for c in esquema.columnas if c.origen == "columna" and c.columna_id not in columnas]
        if faltan:
            raise ErrorMonday(f"columnas del esquema que ya no existen en el tablero: {faltan}")
        faltan = [g.hoja for g in esquema.grupos if g.grupo_id not in grupos]
        if faltan:
            raise ErrorMonday(f"grupos del esquema que ya no existen en el tablero: {faltan}")

        for c in esquema.columnas:
            if c.origen == "columna" and columnas[c.columna_id]["title"] != c.encabezado:
                log.warning("el título de la columna '%s' cambió en monday", c.encabezado)
        for g in esquema.grupos:
            if grupos[g.grupo_id]["title"] != g.hoja:
                log.warning("el título del grupo de la pestaña '%s' cambió en monday", g.hoja)
        return int(tablero.get("items_count") or 0)

    def leer_grupo(self, grupo_id: str, ids_columnas: list[str]) -> list[dict]:
        """Lee todos los elementos de un grupo, en el orden del tablero, paginando por cursor y
        descartando los que monday repita entre páginas."""
        filtro = {"rules": [{"column_id": "group", "compare_value": [grupo_id], "operator": "any_of"}]}
        datos = self._con_ajuste(PRIMERA_PAGINA, {"tablero": self._tablero, "filtro": filtro, "ids": ids_columnas})
        tableros = datos.get("boards") or []
        if not tableros:
            raise ErrorMonday("el token no ve el tablero del esquema")
        pagina = tableros[0]["items_page"]

        items, vistos, duplicados, paginas = [], set(), 0, 1
        while True:
            for item in pagina.get("items") or []:
                if item["id"] in vistos:
                    duplicados += 1
                    continue
                vistos.add(item["id"])
                items.append(item)
            cursor = pagina.get("cursor")
            if not cursor:
                break
            pagina = self._con_ajuste(SIGUIENTE_PAGINA, {"cursor": cursor, "ids": ids_columnas})["next_items_page"]
            paginas += 1
        if duplicados:
            log.warning("monday repitió %d elementos entre páginas (el tablero cambió durante la lectura); se descartaron", duplicados)
        log.info("monday: %d elementos leídos en %d páginas", len(items), paginas)
        return items
