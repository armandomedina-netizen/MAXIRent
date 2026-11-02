"""Línea de comandos: lee los leads de monday, cuenta los del mes y actualiza la hoja MKT."""
from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import datetime

from dotenv import load_dotenv

from .config import CARPETA, cargar_config
from .conteo import ZONA, contar_mes, periodos_a_actualizar
from .errores import ErrorConfig, ErrorHoja, ErrorMKT
from .hoja import Resultado, abrir_libro, actualizar_mes
from .monday import VERSION_API_POR_DEFECTO, ClienteMonday

log = logging.getLogger("mkt_sync")


def _entorno(nombre: str, *alternativas: str) -> str:
    """Valor de una variable de entorno (o de la primera alternativa que exista); falla si no hay ninguna."""
    for clave in (nombre, *alternativas):
        valor = os.getenv(clave, "").strip().strip("\"'")
        if valor:
            return valor
    raise ErrorConfig(f"falta la variable de entorno {nombre}")


def _mes_indicado(texto: str) -> tuple[int, int]:
    """(año, mes) de --mes AAAA-MM."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", texto)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ErrorConfig("--mes debe tener la forma AAAA-MM, por ejemplo 2026-10")
    return int(m.group(1)), int(m.group(2))


def _informar(anio: int, mes: int, resultado: Resultado, simulado: bool) -> None:
    """Deja en el registro qué pasó con la fila del periodo. El registro de GitHub Actions es público,
    así que ahí no se imprimen las cifras."""
    accion = "simulado (no se escribió)" if simulado else ("actualizado" if resultado.escrito else "sin cambios")
    if os.getenv("GITHUB_ACTIONS") == "true":
        log.info("Periodo %d-%02d, fila %d: %s", anio, mes, resultado.fila, accion)
    else:
        log.info("Periodo %d-%02d, fila %d: recibidos %s -> %d, calificados %s -> %d; %s", anio, mes, resultado.fila,
                 resultado.antes[0], resultado.despues[0], resultado.antes[1], resultado.despues[1], accion)


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: devuelve 0 si la hoja quedó al día y 1 si algo falló. Los periodos se procesan
    uno a uno: si la fila de uno falla, el otro se escribe de todos modos y el código de salida es 1."""
    ap = argparse.ArgumentParser(description="Actualiza leads recibidos y calificados del mes en la hoja MKT.")
    ap.add_argument("--mes", help="único periodo a actualizar como AAAA-MM; por defecto el mes en curso (hora CDMX) "
                                  "y, los primeros días del mes, también el anterior")
    ap.add_argument("--simular", action="store_true", help="calcula y muestra los valores sin escribir en la hoja")
    ap.add_argument("--forzar", action="store_true", help="permite escribir 0 leads sobre un total mayor que cero")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv(CARPETA / ".env")

    fallo = False
    try:
        cfg = cargar_config()
        periodos = [_mes_indicado(args.mes)] if args.mes else periodos_a_actualizar(datetime.now(ZONA))
        cliente = ClienteMonday(_entorno("MONDAY_TOKEN"), os.getenv("MONDAY_API_VERSION") or VERSION_API_POR_DEFECTO)
        leads = cliente.leer_leads(cfg, cliente.validar(cfg))
        libro = abrir_libro(_entorno("GOOGLE_CREDS_PATH", "GOOGLE_APPLICATION_CREDENTIALS"), _entorno("SPREADSHEET_ID_MKT"))
        hoja = libro.worksheet(cfg.hoja)
        for anio, mes in periodos:
            recibidos, calificados = contar_mes(leads, cfg.columna_estado, cfg.etiqueta_califica, anio, mes)
            try:
                resultado = actualizar_mes(hoja, cfg, anio, mes, recibidos, calificados,
                                           simular=args.simular, forzar=args.forzar)
            except ErrorHoja as e:
                log.error("Periodo %d-%02d: %s", anio, mes, e)
                fallo = True
                continue
            _informar(anio, mes, resultado, args.simular)
    except ErrorMKT as e:
        log.error("Error: %s", e)
        return 1
    return 1 if fallo else 0
