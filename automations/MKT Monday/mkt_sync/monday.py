"""Cliente de lectura de la API GraphQL de monday para los leads del tablero. Sólo consulta: no envía
mutaciones. Filtra en monday por tipo de lead y deja que el conteo por mes se haga localmente."""
from __future__ import annotations

import json
import logging
import time

import requests

from .config import Config
from .errores import ErrorMonday

log = logging.getLogger("mkt_sync.monday")

URL_API = "https://api.monday.com/v2"
VERSION_API_POR_DEFECTO = "2026-07"
TAM_PAGINA = 500
MAX_INTENTOS = 8

# Códigos de error de monday que se resuelven reintentando más tarde.
CODIGOS_REINTENTABLES = {
    "COMPLEXITY_BUDGET_EXHAUSTED", "RATE_LIMIT_EXCEEDED", "RateLimitExceeded",
    "IP_RATE_LIMIT_EXCEEDED", "CONCURRENCY_LIMIT_EXCEEDED",
}

ESTRUCTURA_TABLERO = """
query ($tablero: ID!) {
  boards(ids: [$tablero]) {
    columns { id type settings_str }
  }
}
"""

PRIMERA_PAGINA = """
query ($tablero: ID!, $limite: Int!, $filtro: ItemsQuery, $ids: [String!]) {
  boards(ids: [$tablero]) {
    items_page(limit: $limite, query_params: $filtro) {
      cursor
      items { id created_at column_values(ids: $ids) { id text } }
    }
  }
}
"""

SIGUIENTE_PAGINA = """
query ($cursor: String!, $limite: Int!, $ids: [String!]) {
  next_items_page(limit: $limite, cursor: $cursor) {
    cursor
    items { id created_at column_values(ids: $ids) { id text } }
  }
}
"""


def _segundos(valor) -> float | None:
    """Convierte a segundos no negativos; devuelve None si el valor no es numérico."""
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return None


def _codigo(error: dict) -> str:
    """Código de extensión de un error GraphQL de monday, o '' si no trae."""
    return (error.get("extensions") or {}).get("code") or ""


def ids_por_etiqueta(columna: dict) -> dict[str, list[int]]:
    """Etiquetas de una columna de estatus con los ids que monday usa para filtrar; el texto vacío
    (etiqueta sin nombre) se descarta."""
    ajustes = json.loads(columna.get("settings_str") or "{}")
    etiquetas = ajustes.get("labels") or {}
    if isinstance(etiquetas, list):
        etiquetas = {str(e.get("id")): e.get("label") for e in etiquetas}
    por_nombre: dict[str, list[int]] = {}
    for id_etiqueta, nombre in etiquetas.items():
        if nombre:
            por_nombre.setdefault(nombre, []).append(int(id_etiqueta))
    return por_nombre


class ClienteMonday:
    """Lector del tablero de leads con reintentos y paginación por cursor."""

    def __init__(self, token: str, version: str = VERSION_API_POR_DEFECTO, *, sesion=None, dormir=time.sleep):
        """Prepara la sesión HTTP con el token y la versión de la API; `dormir` y `sesion` son inyectables."""
        self._sesion = sesion if sesion is not None else requests.Session()
        self._sesion.headers.update({"Authorization": token, "API-Version": version,
                                     "Content-Type": "application/json"})
        self._dormir = dormir

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
                    raise ErrorMonday(f"monday rechazó el token (HTTP {resp.status_code})")
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

    def validar(self, cfg: Config) -> list[int]:
        """Contrasta la configuración con el tablero real: que el token lo vea, que existan las columnas de
        estado y de tipo, la etiqueta de leads calificados y los tipos incluidos. Devuelve los ids de las
        etiquetas de tipo que se usan como filtro. Los mensajes no nombran columnas ni etiquetas porque el
        registro de GitHub Actions es público."""
        tableros = self._consultar(ESTRUCTURA_TABLERO, {"tablero": cfg.tablero_id}).get("boards") or []
        if not tableros:
            raise ErrorMonday("el token no ve el tablero de leads de la configuración")
        columnas = {c["id"]: c for c in tableros[0]["columns"]}
        for clave, id_columna in (("columna_estado", cfg.columna_estado), ("columna_tipo", cfg.columna_tipo)):
            columna = columnas.get(id_columna)
            if columna is None:
                raise ErrorMonday(f"la {clave} de la configuración ya no existe en el tablero")
            if columna["type"] != "status":
                raise ErrorMonday(f"la {clave} de la configuración ya no es una columna de estatus")
        if cfg.etiqueta_califica not in ids_por_etiqueta(columnas[cfg.columna_estado]):
            raise ErrorMonday("la columna de estado ya no tiene la etiqueta de leads calificados de la configuración")
        tipos = ids_por_etiqueta(columnas[cfg.columna_tipo])
        faltan = [t for t in cfg.tipos_incluidos if t not in tipos]
        if faltan:
            raise ErrorMonday(f"la columna de tipo de lead ya no tiene {len(faltan)} de los tipos de la configuración")
        return sorted({i for t in cfg.tipos_incluidos for i in tipos[t]})

    def leer_leads(self, cfg: Config, ids_tipo: list[int]) -> list[dict]:
        """Lee los leads de los tipos incluidos, con su fecha de creación y su estado, paginando por
        cursor y descartando los que monday repita entre páginas."""
        filtro = {"rules": [{"column_id": cfg.columna_tipo, "compare_value": ids_tipo, "operator": "any_of"}]}
        ids = [cfg.columna_estado]
        datos = self._consultar(PRIMERA_PAGINA, {"tablero": cfg.tablero_id, "limite": TAM_PAGINA,
                                                 "filtro": filtro, "ids": ids})
        tableros = datos.get("boards") or []
        if not tableros:
            raise ErrorMonday("el token no ve el tablero de leads de la configuración")
        pagina = tableros[0]["items_page"]

        leads, vistos = [], set()
        while True:
            for lead in pagina.get("items") or []:
                if lead["id"] not in vistos:
                    vistos.add(lead["id"])
                    leads.append(lead)
            cursor = pagina.get("cursor")
            if not cursor:
                break
            pagina = self._consultar(SIGUIENTE_PAGINA, {"cursor": cursor, "limite": TAM_PAGINA, "ids": ids})["next_items_page"]
        log.debug("monday: %d leads leídos", len(leads))
        return leads
