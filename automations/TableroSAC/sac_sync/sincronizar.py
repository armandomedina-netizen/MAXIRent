"""Orquesta la sincronización: lee cada grupo de monday, arma las filas y las vuelca en su pestaña."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import hojas
from .comparar import comparar, formatear_comparacion
from .config import Esquema, Grupo
from .transformar import filas_desde_items

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
    """Sincroniza cada grupo con su pestaña y devuelve un resultado por pestaña. Un error en una
    pestaña se registra y no detiene a las demás. Con `libro` en None sólo se lee monday."""
    resultados = []
    for grupo in grupos:
        resultado = ResultadoHoja(hoja=grupo.hoja)
        try:
            _sincronizar_hoja(grupo, esquema, monday, libro, resultado, dry_run=dry_run,
                              comparar_con_hoja=comparar_con_hoja, aceptar_vacio=aceptar_vacio)
        except Exception as e:  # una pestaña con error no debe impedir las demás
            resultado.error = f"{type(e).__name__}: {e}"
            log.error("[%s] %s", grupo.hoja, resultado.error, exc_info=depurar)
        resultados.append(resultado)
    return resultados


def _sincronizar_hoja(grupo: Grupo, esquema: Esquema, monday, libro, resultado: ResultadoHoja, *,
                      dry_run: bool, comparar_con_hoja: bool, aceptar_vacio: bool) -> None:
    """Lee el grupo de monday y, con libro, revisa la pestaña y (salvo en dry-run) la reescribe:
    primero escribe las filas nuevas y después limpia lo que sobre, para que nunca quede vacía a
    media corrida. Termina verificando que la pestaña quedó con las filas de monday."""
    etiqueta = f"[{grupo.hoja}]"
    ncols = len(esquema.columnas)
    items = monday.leer_grupo(grupo.grupo_id, esquema.ids_columnas)
    filas, resumen = filas_desde_items(items, esquema)
    resultado.filas_monday = len(filas)
    log.info("%s monday: %d elementos", etiqueta, len(filas))
    for linea in resumen.advertencias():
        log.warning("%s %s", etiqueta, linea)

    if libro is None:
        log.info("%s dry-run sin conexión a Google: la pestaña no se revisó", etiqueta)
        return

    hoja = libro.worksheet(grupo.hoja)
    hojas.verificar_encabezados(hoja, esquema.encabezados)
    # Las filas se cuentan por la columna clave (o por la A): una celda de texto puede quedar en blanco, la clave no.
    columna_conteo = (esquema.indice_clave if esquema.indice_clave is not None else 0) + 1
    antes = hojas.contar_filas_con_datos(hoja, columna_conteo)
    resultado.filas_antes = antes
    log.info("%s pestaña: %d filas con datos y %d de capacidad; por escribir %d",
             etiqueta, antes, hoja.row_count, len(filas))

    if comparar_con_hoja:
        for linea in formatear_comparacion(comparar(filas, hojas.leer_datos(hoja, ncols), esquema)):
            log.info("%s %s", etiqueta, linea)

    if dry_run:
        faltan = max(0, len(filas) + 1 - hoja.row_count)
        log.info("%s dry-run: no se escribió nada (faltarían %d filas de capacidad)", etiqueta, faltan)
        return

    # Un grupo que de pronto llega vacío puede ser una lectura fallida; sólo se acepta pasando --aceptar-vacio.
    if not filas and antes > UMBRAL_VACIADO and not aceptar_vacio:
        raise hojas.ErrorHoja(f"monday devolvió 0 elementos y la pestaña tiene {antes} filas con datos; "
                              "no se vació sin --aceptar-vacio")

    resultado.filas_agregadas = hojas.asegurar_filas(hoja, len(filas) + 1, ncols)
    resultado.filas_escritas = hojas.escribir_filas(hoja, filas, ncols)
    hojas.limpiar_sobrantes(hoja, len(filas) + 2, ncols)
    despues = hojas.contar_filas_con_datos(hoja, columna_conteo)
    log.info("%s escritas %d filas de %d columnas (+%d de capacidad); filas con datos ahora: %d",
             etiqueta, resultado.filas_escritas, ncols, resultado.filas_agregadas, despues)
    if despues != len(filas):
        raise hojas.ErrorHoja(f"verificación: la pestaña quedó con {despues} filas con datos y monday trajo {len(filas)}")
