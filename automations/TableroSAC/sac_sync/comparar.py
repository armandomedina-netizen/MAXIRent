"""Compara las filas que saldrían de monday con lo que ya hay en la pestaña.

Sólo cuenta diferencias por columna, con unas pocas filas de ejemplo: nunca devuelve ni
imprime valores, porque son datos de clientes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import Esquema

MAX_EJEMPLOS = 5


@dataclass
class DiferenciaColumna:
    """Diferencias de una columna: cuántas son de contenido y cuántas sólo de tipo."""
    valor: int = 0                                  # el contenido es distinto
    tipo: int = 0                                   # mismo texto, pero uno es número y el otro texto
    filas: list[int] = field(default_factory=list)  # primeras filas (número de fila de la pestaña) con diferencia

    @property
    def total(self) -> int:
        """Celdas distintas de la columna, de cualquier clase."""
        return self.valor + self.tipo


@dataclass
class Comparacion:
    """Resultado de comparar las filas de monday con las de la pestaña."""
    filas_monday: int
    filas_hoja: int
    comunes: int = 0
    solo_monday: int = 0
    solo_hoja: int = 0
    claves_repetidas: int = 0
    mismo_orden: bool = True
    diferencias: dict[str, DiferenciaColumna] = field(default_factory=dict)

    @property
    def celdas_distintas(self) -> int:
        """Total de celdas distintas entre las filas en común."""
        return sum(d.total for d in self.diferencias.values())

    @property
    def coincide(self) -> bool:
        """Verdadero si no hay filas sin pareja ni celdas distintas."""
        return not (self.solo_monday or self.solo_hoja or self.celdas_distintas)


def _vacio_a_none(v):
    """Trata None y "" como la misma celda en blanco."""
    return None if v is None or v == "" else v


def _es_numero(v) -> bool:
    """Verdadero para int y float, no para bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _como_texto(v) -> str:
    """Representación textual estable: un número entero no lleva decimales."""
    if _es_numero(v):
        return str(int(v)) if float(v).is_integer() else repr(float(v))
    return str(v)


def _comparar_celdas(nuevo, actual) -> str | None:
    """Devuelve None si las celdas son iguales, "valor" si difiere el contenido y "tipo" si sólo
    cambia número contra texto. Los números se comparan con tolerancia de punto flotante."""
    nuevo, actual = _vacio_a_none(nuevo), _vacio_a_none(actual)
    if nuevo is None and actual is None:
        return None
    if nuevo is None or actual is None:
        return "valor"
    if _es_numero(nuevo) and _es_numero(actual):
        return None if math.isclose(nuevo, actual, rel_tol=1e-9, abs_tol=1e-9) else "valor"
    if not _es_numero(nuevo) and not _es_numero(actual):
        return None if str(nuevo) == str(actual) else "valor"
    return "tipo" if _como_texto(nuevo) == _como_texto(actual) else "valor"


def _clave(v):
    """Valor de la columna clave en forma comparable, o None si está en blanco."""
    v = _vacio_a_none(v)
    return None if v is None else _como_texto(v)


def _alinear(nuevas: list[list], actuales: list[list], i_clave: int | None):
    """Empareja filas de monday con filas de la pestaña. Con columna clave las une por su valor
    (la primera aparición en la pestaña); sin ella, por posición. Devuelve los pares
    (posición en nuevas, posición en la pestaña) en el orden de monday y cuántas filas de la
    pestaña repiten una clave."""
    if i_clave is None:
        return [(i, i) for i in range(min(len(nuevas), len(actuales)))], 0

    en_hoja, repetidas = {}, 0
    for pos, fila in enumerate(actuales):
        k = _clave(fila[i_clave])
        if k is None:
            continue
        if k in en_hoja:
            repetidas += 1
        else:
            en_hoja[k] = pos
    pares, usadas = [], set()
    for pos, fila in enumerate(nuevas):
        k = _clave(fila[i_clave])
        p_hoja = en_hoja.get(k) if k is not None else None
        if p_hoja is not None and p_hoja not in usadas:
            pares.append((pos, p_hoja))
            usadas.add(p_hoja)
    return pares, repetidas


def comparar(nuevas: list[list], actuales: list[list], esquema: Esquema) -> Comparacion:
    """Compara las filas que se escribirían (`nuevas`) con lo que hay hoy en la pestaña de la fila 2
    en adelante (`actuales`)."""
    ncols = len(esquema.columnas)
    actuales = [list(fila) + [None] * (ncols - len(fila)) for fila in actuales]
    con_datos = sum(1 for fila in actuales if any(_vacio_a_none(v) is not None for v in fila))
    pares, repetidas = _alinear(nuevas, actuales, esquema.indice_clave)

    resultado = Comparacion(filas_monday=len(nuevas), filas_hoja=con_datos, comunes=len(pares),
                            solo_monday=len(nuevas) - len(pares),
                            solo_hoja=max(0, con_datos - len(pares) - repetidas),
                            claves_repetidas=repetidas)
    posiciones_hoja = [p_hoja for _, p_hoja in pares]
    resultado.mismo_orden = posiciones_hoja == sorted(posiciones_hoja)

    for p_nueva, p_hoja in pares:
        for i, columna in enumerate(esquema.columnas):
            veredicto = _comparar_celdas(nuevas[p_nueva][i], actuales[p_hoja][i])
            if veredicto is None:
                continue
            d = resultado.diferencias.setdefault(columna.encabezado, DiferenciaColumna())
            if veredicto == "tipo":
                d.tipo += 1
            else:
                d.valor += 1
            if len(d.filas) < MAX_EJEMPLOS:
                d.filas.append(p_hoja + 2)
    return resultado


def formatear_comparacion(c: Comparacion) -> list[str]:
    """Convierte una Comparacion en líneas para el registro, sin valores de las celdas."""
    lineas = [f"comparación: monday {c.filas_monday} filas, pestaña {c.filas_hoja}; {c.comunes} en común, "
              f"{c.solo_monday} sólo en monday, {c.solo_hoja} sólo en la pestaña; "
              f"mismo orden: {'sí' if c.mismo_orden else 'no'}"]
    if c.claves_repetidas:
        lineas.append(f"comparación: {c.claves_repetidas} filas de la pestaña repiten la clave")
    if not c.diferencias:
        lineas.append("comparación: las filas en común coinciden en todas las columnas")
    for encabezado, d in c.diferencias.items():
        ejemplos = ", ".join(str(f) for f in d.filas)
        lineas.append(f"comparación: columna '{encabezado}': {d.total} celdas distintas "
                      f"({d.valor} de valor, {d.tipo} de tipo); filas de ejemplo: {ejemplos}")
    return lineas
