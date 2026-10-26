"""Orquesta la sincronización: lee cada grupo de monday, arma las filas y las vuelca en su pestaña
y, si el grupo la tiene, en la pestaña de sus subelementos."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import hojas
from .comparar import comparar, formatear_comparacion
from .config import Esquema, Grupo
from .transformar import filas_desde_items, filas_subelementos_desde_items

log = logging.getLogger("sac_sync")

# Filas con datos a partir de las cuales una pestaña no se vacía sin la opción --aceptar-vacio.
UMBRAL_VACIADO = 20


@dataclass
class ResultadoHoja:
    """Resultado de sincronizar una pestaña."""
    hoja: str
    filas_monday: int = 0
    filas_antes: int | None = None   # filas con datos que tenía la pestaña; None si no se consultó
    filas_escritas: int = 0
    filas_agregadas: int = 0         # filas de capacidad que se sumaron a la pestaña
    error: str | None = None


def sincronizar(esquema: Esquema, monday, libro, grupos: list[Grupo], *, dry_run: bool = False,
                comparar_con_hoja: bool = False, aceptar_vacio: bool = False,
                depurar: bool = False) -> list[ResultadoHoja]:
    """Sincroniza cada grupo con su pestaña, y con la de subelementos si la tiene, a partir de una sola
    lectura de monday por grupo. Devuelve un resultado por pestaña. Un error en una pestaña se registra y
    no detiene a las demás. Con `libro` en None sólo se lee monday."""
    resultados = []
    for grupo in grupos:
        resultados.extend(_sincronizar_grupo(grupo, esquema, monday, libro, dry_run=dry_run,
                                             comparar_con_hoja=comparar_con_hoja,
                                             aceptar_vacio=aceptar_vacio, depurar=depurar))
    return resultados


def _registrar_error(resultado: ResultadoHoja, error: Exception, depurar: bool) -> None:
    """Deja el error en el resultado de la pestaña y en el registro."""
    resultado.error = f"{type(error).__name__}: {error}"
    log.error("[%s] %s", resultado.hoja, resultado.error, exc_info=depurar)


def _sincronizar_grupo(grupo: Grupo, esquema: Esquema, monday, libro, *, dry_run: bool,
                       comparar_con_hoja: bool, aceptar_vacio: bool, depurar: bool) -> list[ResultadoHoja]:
    """Lee un grupo de monday y vuelca sus elementos en su pestaña y, si el grupo tiene `hoja_subelementos`,
    sus subelementos en la suya. Las dos pestañas parten de la misma lectura y cada una lleva su
    resultado; la pestaña de subelementos sólo aparece cuando el grupo la define y, si falla algo propio
    de los subelementos, los tickets se sincronizan igual con una lectura sin ellos."""
    con_subelementos = bool(grupo.hoja_subelementos)
    resultado = ResultadoHoja(hoja=grupo.hoja)
    resultado_sub = ResultadoHoja(hoja=grupo.hoja_subelementos) if con_subelementos else None
    resultados = [resultado] + ([resultado_sub] if con_subelementos else [])
    opciones = dict(dry_run=dry_run, comparar_con_hoja=comparar_con_hoja, aceptar_vacio=aceptar_vacio)

    items = None
    if con_subelementos:
        # Un problema con los subelementos (su tablero, sus columnas o su lectura) falla sólo su pestaña:
        # los tickets se leen y se vuelcan sin ellos.
        try:
            monday.validar_subelementos(esquema)
            items = monday.leer_grupo(grupo.grupo_id, esquema.ids_columnas_con_padre,
                                      ids_subelementos=esquema.subelementos.ids_columnas)
        except Exception as e:
            _registrar_error(resultado_sub, e, depurar)
            con_subelementos = False
    if items is None:
        try:
            items = monday.leer_grupo(grupo.grupo_id, esquema.ids_columnas)
        except Exception as e:  # sin lectura de tickets no hay nada que volcar
            _registrar_error(resultado, e, depurar)
            return resultados

    try:
        filas, resumen = filas_desde_items(items, esquema)
        _volcar_en_pestana(grupo.hoja, esquema, filas, resumen, "elementos", libro, resultado, **opciones)
    except Exception as e:  # una pestaña con error no debe impedir la otra
        _registrar_error(resultado, e, depurar)
    if con_subelementos:
        try:
            filas_sub, resumen_sub = filas_subelementos_desde_items(items, esquema.subelementos)
            _volcar_en_pestana(grupo.hoja_subelementos, esquema.subelementos, filas_sub, resumen_sub,
                               "subelementos", libro, resultado_sub, **opciones)
        except Exception as e:
            _registrar_error(resultado_sub, e, depurar)
    return resultados


def _volcar_en_pestana(nombre_hoja: str, tabla, filas: list[list], resumen, unidad: str, libro,
                       resultado: ResultadoHoja, *, dry_run: bool, comparar_con_hoja: bool,
                       aceptar_vacio: bool) -> None:
    """Con libro, revisa la pestaña y (salvo en dry-run) la reescribe con las filas: primero escribe las
    filas nuevas y después limpia lo que sobre, para que nunca quede vacía a media corrida. Termina
    verificando que la pestaña quedó con las filas de monday. `tabla` aporta las columnas, los
    encabezados y la columna clave; `unidad` es lo que cuentan las filas ("elementos" o "subelementos")."""
    etiqueta = f"[{nombre_hoja}]"
    ncols = len(tabla.columnas)
    resultado.filas_monday = len(filas)
    log.info("%s monday: %d %s", etiqueta, len(filas), unidad)
    for linea in resumen.advertencias():
        log.warning("%s %s", etiqueta, linea)

    if libro is None:
        log.info("%s dry-run sin conexión a Google: la pestaña no se revisó", etiqueta)
        return

    hoja = libro.worksheet(nombre_hoja)
    hojas.verificar_encabezados(hoja, tabla.encabezados)
    # Las filas se cuentan por la columna clave (o por la A): una celda de texto puede quedar en blanco, la clave no.
    columna_conteo = (tabla.indice_clave if tabla.indice_clave is not None else 0) + 1
    antes = hojas.contar_filas_con_datos(hoja, columna_conteo)
    resultado.filas_antes = antes
    log.info("%s pestaña: %d filas con datos y %d de capacidad; por escribir %d",
             etiqueta, antes, hoja.row_count, len(filas))

    if comparar_con_hoja:
        for linea in formatear_comparacion(comparar(filas, hojas.leer_datos(hoja, ncols), tabla)):
            log.info("%s %s", etiqueta, linea)

    if dry_run:
        faltan = max(0, len(filas) + 1 - hoja.row_count)
        log.info("%s dry-run: no se escribió nada (faltarían %d filas de capacidad)", etiqueta, faltan)
        return

    # Un grupo que de pronto llega vacío puede ser una lectura fallida; sólo se acepta pasando --aceptar-vacio.
    if not filas and antes > UMBRAL_VACIADO and not aceptar_vacio:
        raise hojas.ErrorHoja(f"monday devolvió 0 {unidad} y la pestaña tiene {antes} filas con datos; "
                              "no se vació sin --aceptar-vacio")

    resultado.filas_agregadas = hojas.asegurar_filas(hoja, len(filas) + 1, ncols)
    resultado.filas_escritas = hojas.escribir_filas(hoja, filas, ncols)
    hojas.limpiar_sobrantes(hoja, len(filas) + 2, ncols)
    despues = hojas.contar_filas_con_datos(hoja, columna_conteo)
    log.info("%s escritas %d filas de %d columnas (+%d de capacidad); filas con datos ahora: %d",
             etiqueta, resultado.filas_escritas, ncols, resultado.filas_agregadas, despues)
    if despues != len(filas):
        raise hojas.ErrorHoja(f"verificación: la pestaña quedó con {despues} filas con datos y monday trajo {len(filas)}")
