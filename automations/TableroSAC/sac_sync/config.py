"""Esquema de la sincronización: relaciona cada grupo del tablero con una pestaña del Sheet
y cada columna del Sheet (en el orden A, B, C...) con su origen en monday.

Los IDs del tablero, de los grupos y de las columnas no se versionan (el repositorio es
público), por eso el esquema se carga de un archivo local ignorado por git o de la
variable de entorno MONDAY_SAC_SCHEMA_JSON.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

TIPOS = ("texto", "numero", "fecha", "duracion")
ORIGENES = ("columna", "nombre", "grupo")

CARPETA_PROYECTO = Path(__file__).resolve().parents[1]
RUTA_ESQUEMA_POR_DEFECTO = CARPETA_PROYECTO / "private" / "monday-sac-schema.json"

_CLAVES_ESQUEMA = {"tablero_id", "grupos", "columnas"}
_CLAVES_GRUPO = {"hoja", "grupo_id", "periodica"}
_CLAVES_COLUMNA = {"encabezado", "origen", "columna_id", "tipo", "clave"}


class ErrorConfiguracion(ValueError):
    """El esquema o las variables de entorno no son válidos."""


@dataclass(frozen=True)
class Grupo:
    """Grupo de monday y la pestaña del Sheet donde se vuelcan sus elementos."""
    hoja: str
    grupo_id: str
    periodica: bool = False        # entra en la sincronización periódica (opción --periodicas)


@dataclass(frozen=True)
class Columna:
    """Una columna del Sheet y de dónde sale su valor en monday."""
    encabezado: str
    origen: str = "columna"        # columna | nombre (item.name) | grupo (item.group.title)
    columna_id: str | None = None
    tipo: str = "texto"            # texto | numero | fecha | duracion
    clave: bool = False            # identifica la fila al comparar con la pestaña


@dataclass(frozen=True)
class Esquema:
    """Tablero de monday, grupos que se sincronizan y columnas del Sheet en su orden."""
    tablero_id: int
    grupos: tuple[Grupo, ...]
    columnas: tuple[Columna, ...]

    @property
    def encabezados(self) -> list[str]:
        """Encabezados de la fila 1, en el orden de las columnas."""
        return [c.encabezado for c in self.columnas]

    @property
    def ids_columnas(self) -> list[str]:
        """IDs de las columnas de monday que se piden en la consulta."""
        return [c.columna_id for c in self.columnas if c.origen == "columna"]

    @property
    def indice_clave(self) -> int | None:
        """Posición de la columna que identifica cada fila, o None si ninguna lo hace."""
        for i, c in enumerate(self.columnas):
            if c.clave:
                return i
        return None


def _exigir(condicion: bool, mensaje: str) -> None:
    """Lanza ErrorConfiguracion con el mensaje cuando la condición es falsa."""
    if not condicion:
        raise ErrorConfiguracion(mensaje)


def _texto(valor, campo: str) -> str:
    """Devuelve el valor si es un texto no vacío; si no, lanza ErrorConfiguracion."""
    _exigir(isinstance(valor, str) and valor != "", f"{campo} debe ser un texto no vacío")
    return valor


def _sin_claves_extra(objeto: dict, permitidas: set, donde: str) -> None:
    """Rechaza las claves que el formato no define, para que un error de dedo no pase en silencio."""
    extra = sorted(set(objeto) - permitidas)
    _exigir(not extra, f"{donde}: claves desconocidas {extra}")


def esquema_desde_dict(datos) -> Esquema:
    """Valida un esquema ya leído de JSON y lo convierte en un Esquema."""
    _exigir(isinstance(datos, dict), "el esquema debe ser un objeto JSON")
    _sin_claves_extra(datos, _CLAVES_ESQUEMA, "esquema")

    tablero = datos.get("tablero_id")
    if isinstance(tablero, str) and tablero.isdigit():
        tablero = int(tablero)
    _exigir(isinstance(tablero, int) and not isinstance(tablero, bool) and tablero > 0,
            "tablero_id debe ser un entero positivo")

    lista_grupos = datos.get("grupos")
    _exigir(isinstance(lista_grupos, list) and lista_grupos, "grupos debe ser una lista no vacía")
    grupos = []
    for i, g in enumerate(lista_grupos, start=1):
        _exigir(isinstance(g, dict), f"grupos[{i}] debe ser un objeto")
        _sin_claves_extra(g, _CLAVES_GRUPO, f"grupos[{i}]")
        periodica = g.get("periodica", False)
        _exigir(isinstance(periodica, bool), f"grupos[{i}].periodica debe ser true o false")
        grupos.append(Grupo(hoja=_texto(g.get("hoja"), f"grupos[{i}].hoja"),
                            grupo_id=_texto(g.get("grupo_id"), f"grupos[{i}].grupo_id"),
                            periodica=periodica))
    _exigir(len({g.hoja for g in grupos}) == len(grupos), "grupos: hay pestañas repetidas")
    _exigir(len({g.grupo_id for g in grupos}) == len(grupos), "grupos: hay IDs de grupo repetidos")

    lista_columnas = datos.get("columnas")
    _exigir(isinstance(lista_columnas, list) and lista_columnas, "columnas debe ser una lista no vacía")
    columnas = []
    for i, c in enumerate(lista_columnas, start=1):
        _exigir(isinstance(c, dict), f"columnas[{i}] debe ser un objeto")
        _sin_claves_extra(c, _CLAVES_COLUMNA, f"columnas[{i}]")
        origen = c.get("origen", "columna")
        _exigir(origen in ORIGENES, f"columnas[{i}].origen debe ser uno de {ORIGENES}")
        tipo = c.get("tipo", "texto")
        _exigir(tipo in TIPOS, f"columnas[{i}].tipo debe ser uno de {TIPOS}")
        clave = c.get("clave", False)
        _exigir(isinstance(clave, bool), f"columnas[{i}].clave debe ser true o false")
        columna_id = c.get("columna_id")
        if origen == "columna":
            _texto(columna_id, f"columnas[{i}].columna_id")
        else:
            _exigir(columna_id is None, f"columnas[{i}]: con origen '{origen}' no lleva columna_id")
            _exigir(tipo == "texto", f"columnas[{i}]: con origen '{origen}' el tipo es texto")
        columnas.append(Columna(encabezado=_texto(c.get("encabezado"), f"columnas[{i}].encabezado"),
                                origen=origen, columna_id=columna_id, tipo=tipo, clave=clave))

    _exigir(len({c.encabezado for c in columnas}) == len(columnas), "columnas: hay encabezados repetidos")
    ids = [c.columna_id for c in columnas if c.origen == "columna"]
    _exigir(len(set(ids)) == len(ids), "columnas: hay IDs de columna repetidos")
    _exigir(sum(c.clave for c in columnas) <= 1, "columnas: sólo una puede ser clave")

    return Esquema(tablero_id=tablero, grupos=tuple(grupos), columnas=tuple(columnas))


def cargar_esquema(entorno=None) -> Esquema:
    """Lee el esquema de MONDAY_SAC_SCHEMA_JSON, de MONDAY_SAC_SCHEMA_PATH o de la ruta por
    defecto, en ese orden de prioridad."""
    entorno = os.environ if entorno is None else entorno
    en_linea = (entorno.get("MONDAY_SAC_SCHEMA_JSON") or "").strip()
    if en_linea:
        texto, origen = en_linea, "MONDAY_SAC_SCHEMA_JSON"
    else:
        ruta = Path(entorno.get("MONDAY_SAC_SCHEMA_PATH") or RUTA_ESQUEMA_POR_DEFECTO)
        if not ruta.is_file():
            raise ErrorConfiguracion(f"no se encontró el archivo del esquema ({ruta.name})")
        texto, origen = ruta.read_text(encoding="utf-8-sig"), ruta.name
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErrorConfiguracion(f"el esquema ({origen}) no es JSON válido: {e.msg} (línea {e.lineno})") from None
    return esquema_desde_dict(datos)
