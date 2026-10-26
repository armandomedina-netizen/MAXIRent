"""Esquema de la sincronización: relaciona cada grupo del tablero con una pestaña del Sheet
y cada columna del Sheet (en el orden A, B, C...) con su origen en monday. Un grupo puede
tener además una pestaña de subelementos, con su propia lista de columnas.

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
# Orígenes del valor de una columna de la pestaña de elementos: una columna de monday, el nombre,
# el título del grupo, el ID del elemento, su fecha de creación o si el cronómetro de una columna
# de seguimiento de tiempo está corriendo ("Sí"/"No").
ORIGENES = ("columna", "nombre", "grupo", "id", "creado", "en_marcha")
# En la pestaña de subelementos, además, los datos del elemento padre (el ticket).
ORIGENES_SUBELEMENTOS = ("columna", "nombre", "id", "creado", "en_marcha", "padre_id", "padre_nombre", "padre_columna")

# Orígenes que leen una columna de monday y por eso llevan columna_id.
_ORIGENES_CON_COLUMNA = ("columna", "padre_columna", "en_marcha")
# Orígenes que leen una columna del propio elemento y por eso se piden en su consulta.
_ORIGENES_DEL_ELEMENTO = ("columna", "en_marcha")
# Orígenes cuyo valor es siempre un texto, siempre un ID numérico o siempre una fecha.
_ORIGENES_DE_TEXTO = ("nombre", "grupo", "padre_nombre", "en_marcha")
_ORIGENES_DE_ID = ("id", "padre_id")
_ORIGENES_DE_FECHA = ("creado",)

CARPETA_PROYECTO = Path(__file__).resolve().parents[1]
RUTA_ESQUEMA_POR_DEFECTO = CARPETA_PROYECTO / "private" / "monday-sac-schema.json"

_CLAVES_ESQUEMA = {"tablero_id", "grupos", "columnas", "subelementos"}
_CLAVES_GRUPO = {"hoja", "grupo_id", "periodica", "hoja_subelementos"}
_CLAVES_COLUMNA = {"encabezado", "origen", "columna_id", "tipo", "clave"}
_CLAVES_SUBELEMENTOS = {"tablero_id", "columnas"}


class ErrorConfiguracion(ValueError):
    """El esquema o las variables de entorno no son válidos."""


@dataclass(frozen=True)
class Grupo:
    """Grupo de monday y la pestaña del Sheet donde se vuelcan sus elementos."""
    hoja: str
    grupo_id: str
    periodica: bool = False                  # entra en la sincronización periódica (opción --periodicas)
    hoja_subelementos: str | None = None     # pestaña donde se vuelcan los subelementos de sus elementos


@dataclass(frozen=True)
class Columna:
    """Una columna del Sheet y de dónde sale su valor en monday."""
    encabezado: str
    origen: str = "columna"        # columna | nombre | grupo | id | creado | en_marcha | padre_id | padre_nombre | padre_columna
    columna_id: str | None = None
    tipo: str = "texto"            # texto | numero | fecha | duracion
    clave: bool = False            # identifica la fila al comparar con la pestaña


class _TablaDeColumnas:
    """Propiedades comunes de las tablas que se definen con una lista ordenada de columnas."""

    @property
    def encabezados(self) -> list[str]:
        """Encabezados de la fila 1, en el orden de las columnas."""
        return [c.encabezado for c in self.columnas]

    @property
    def ids_columnas(self) -> list[str]:
        """IDs de las columnas de monday que se piden en la consulta, sin repetir: las que se vuelcan y
        las de seguimiento de tiempo de las que se informa si el cronómetro corre."""
        ids = []
        for c in self.columnas:
            if c.origen in _ORIGENES_DEL_ELEMENTO and c.columna_id not in ids:
                ids.append(c.columna_id)
        return ids

    @property
    def indice_clave(self) -> int | None:
        """Posición de la columna que identifica cada fila, o None si ninguna lo hace."""
        for i, c in enumerate(self.columnas):
            if c.clave:
                return i
        return None


@dataclass(frozen=True)
class TablaSubelementos(_TablaDeColumnas):
    """Tablero de subelementos de monday y columnas de la pestaña donde se vuelcan, en su orden."""
    tablero_id: int
    columnas: tuple[Columna, ...]

    @property
    def ids_padre(self) -> list[str]:
        """IDs de las columnas del ticket cuyo valor se copia a cada fila de subelemento."""
        return [c.columna_id for c in self.columnas if c.origen == "padre_columna"]


@dataclass(frozen=True)
class Esquema(_TablaDeColumnas):
    """Tablero de monday, grupos que se sincronizan y columnas del Sheet en su orden."""
    tablero_id: int
    grupos: tuple[Grupo, ...]
    columnas: tuple[Columna, ...]
    subelementos: TablaSubelementos | None = None

    @property
    def ids_columnas_con_padre(self) -> list[str]:
        """IDs que se piden de cada ticket cuando se leen también sus subelementos: las columnas de la
        pestaña de tickets y, además, las que se copian a las filas de subelementos y no estén ya ahí."""
        ids = list(self.ids_columnas)
        if self.subelementos is not None:
            ids += [i for i in self.subelementos.ids_padre if i not in ids]
        return ids


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


def _id_de_tablero(valor, campo: str) -> int:
    """Convierte el ID de un tablero (entero o texto de dígitos) y exige que sea positivo."""
    if isinstance(valor, str) and valor.isdigit():
        valor = int(valor)
    _exigir(isinstance(valor, int) and not isinstance(valor, bool) and valor > 0,
            f"{campo} debe ser un entero positivo")
    return valor


def _grupos_desde_lista(lista) -> tuple[Grupo, ...]:
    """Valida la lista de grupos; las pestañas (de elementos y de subelementos) no pueden repetirse."""
    _exigir(isinstance(lista, list) and lista, "grupos debe ser una lista no vacía")
    grupos = []
    for i, g in enumerate(lista, start=1):
        _exigir(isinstance(g, dict), f"grupos[{i}] debe ser un objeto")
        _sin_claves_extra(g, _CLAVES_GRUPO, f"grupos[{i}]")
        periodica = g.get("periodica", False)
        _exigir(isinstance(periodica, bool), f"grupos[{i}].periodica debe ser true o false")
        hoja_subelementos = g.get("hoja_subelementos")
        if hoja_subelementos is not None:
            _texto(hoja_subelementos, f"grupos[{i}].hoja_subelementos")
        grupos.append(Grupo(hoja=_texto(g.get("hoja"), f"grupos[{i}].hoja"),
                            grupo_id=_texto(g.get("grupo_id"), f"grupos[{i}].grupo_id"),
                            periodica=periodica, hoja_subelementos=hoja_subelementos))
    pestanas = [g.hoja for g in grupos] + [g.hoja_subelementos for g in grupos if g.hoja_subelementos]
    _exigir(len(set(pestanas)) == len(pestanas), "grupos: hay pestañas repetidas")
    _exigir(len({g.grupo_id for g in grupos}) == len(grupos), "grupos: hay IDs de grupo repetidos")
    return tuple(grupos)


def _columnas_desde_lista(lista, donde: str, origenes: tuple[str, ...]) -> tuple[Columna, ...]:
    """Valida una lista de columnas y la convierte; `donde` es el prefijo de los mensajes de error y
    `origenes` los orígenes permitidos en esa tabla."""
    _exigir(isinstance(lista, list) and lista, f"{donde} debe ser una lista no vacía")
    columnas = []
    for i, c in enumerate(lista, start=1):
        pos = f"{donde}[{i}]"
        _exigir(isinstance(c, dict), f"{pos} debe ser un objeto")
        _sin_claves_extra(c, _CLAVES_COLUMNA, pos)
        origen = c.get("origen", "columna")
        _exigir(origen in origenes, f"{pos}.origen debe ser uno de {origenes}")
        tipo = c.get("tipo", "texto")
        _exigir(tipo in TIPOS, f"{pos}.tipo debe ser uno de {TIPOS}")
        clave = c.get("clave", False)
        _exigir(isinstance(clave, bool), f"{pos}.clave debe ser true o false")
        columna_id = c.get("columna_id")
        if origen in _ORIGENES_CON_COLUMNA:
            _texto(columna_id, f"{pos}.columna_id")
        else:
            _exigir(columna_id is None, f"{pos}: con origen '{origen}' no lleva columna_id")
        if origen in _ORIGENES_DE_TEXTO:
            _exigir(tipo == "texto", f"{pos}: con origen '{origen}' el tipo es texto")
        if origen in _ORIGENES_DE_ID:
            _exigir(tipo == "numero", f"{pos}: con origen '{origen}' el tipo es numero")
        if origen in _ORIGENES_DE_FECHA:
            _exigir(tipo == "fecha", f"{pos}: con origen '{origen}' el tipo es fecha")
        columnas.append(Columna(encabezado=_texto(c.get("encabezado"), f"{pos}.encabezado"),
                                origen=origen, columna_id=columna_id, tipo=tipo, clave=clave))

    _exigir(len({c.encabezado for c in columnas}) == len(columnas), f"{donde}: hay encabezados repetidos")
    for origen in _ORIGENES_CON_COLUMNA:
        ids = [c.columna_id for c in columnas if c.origen == origen]
        _exigir(len(set(ids)) == len(ids), f"{donde}: hay IDs de columna repetidos")
    _exigir(sum(c.clave for c in columnas) <= 1, f"{donde}: sólo una puede ser clave")
    return tuple(columnas)


def _subelementos_desde_dict(datos, tablero_padre: int) -> TablaSubelementos:
    """Valida la sección de subelementos. La clave de la pestaña es el ID del subelemento, porque el
    Folio del ticket se repite en cada una de sus filas; el Folio entra con el origen padre_id y es la
    llave que relaciona las dos pestañas. Las columnas del ticket que se copian a cada fila no tienen
    que estar en la pestaña de tickets: se piden aparte y se validan contra el tablero."""
    _exigir(isinstance(datos, dict), "subelementos debe ser un objeto")
    _sin_claves_extra(datos, _CLAVES_SUBELEMENTOS, "subelementos")
    tablero = _id_de_tablero(datos.get("tablero_id"), "subelementos.tablero_id")
    _exigir(tablero != tablero_padre, "subelementos.tablero_id debe ser distinto de tablero_id")
    columnas = _columnas_desde_lista(datos.get("columnas"), "subelementos.columnas", ORIGENES_SUBELEMENTOS)
    claves = [c for c in columnas if c.clave]
    _exigir(len(claves) == 1 and claves[0].origen == "id",
            "subelementos.columnas: la clave debe ser una sola columna con origen 'id'")
    _exigir(any(c.origen == "padre_id" for c in columnas),
            "subelementos.columnas: falta una columna con origen 'padre_id' (la llave al ticket)")
    return TablaSubelementos(tablero_id=tablero, columnas=columnas)


def esquema_desde_dict(datos) -> Esquema:
    """Valida un esquema ya leído de JSON y lo convierte en un Esquema."""
    _exigir(isinstance(datos, dict), "el esquema debe ser un objeto JSON")
    _sin_claves_extra(datos, _CLAVES_ESQUEMA, "esquema")

    tablero = _id_de_tablero(datos.get("tablero_id"), "tablero_id")
    grupos = _grupos_desde_lista(datos.get("grupos"))
    columnas = _columnas_desde_lista(datos.get("columnas"), "columnas", ORIGENES)
    subelementos = None
    if "subelementos" in datos:
        subelementos = _subelementos_desde_dict(datos["subelementos"], tablero)
    _exigir(subelementos is not None or not any(g.hoja_subelementos for g in grupos),
            "grupos: hoja_subelementos requiere la sección subelementos")

    return Esquema(tablero_id=tablero, grupos=grupos, columnas=columnas, subelementos=subelementos)


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
