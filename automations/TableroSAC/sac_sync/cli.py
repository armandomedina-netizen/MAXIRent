"""Línea de comandos de la sincronización monday -> Google Sheets."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import unicodedata
from pathlib import Path

from dotenv import load_dotenv

from . import hojas
from .config import ErrorConfiguracion, Esquema, Grupo, cargar_esquema
from .monday import ClienteMonday, ErrorMonday, VERSION_API_POR_DEFECTO
from .registro import configurar_registro
from .sincronizar import sincronizar

log = logging.getLogger("sac_sync")

RUTA_ENV = Path(__file__).resolve().parents[1] / ".env"


def construir_parser() -> argparse.ArgumentParser:
    """Define las opciones de la línea de comandos."""
    p = argparse.ArgumentParser(
        prog="monday_sac_sync.py",
        description="Vuelca los grupos del tablero de tickets de SAC de monday en las pestañas de un Google Sheet "
                    "(de la fila 2 en adelante). monday es de solo lectura.",
    )
    destino = p.add_mutually_exclusive_group(required=True)
    destino.add_argument("--todas", action="store_true", help="sincroniza todas las pestañas del esquema")
    destino.add_argument("--periodicas", action="store_true",
                         help="sincroniza las pestañas marcadas como periódicas en el esquema")
    destino.add_argument("--hoja", action="append", metavar="NOMBRE",
                         help="sincroniza esa pestaña (se puede repetir; no distingue mayúsculas ni acentos)")
    destino.add_argument("--listar", action="store_true", help="muestra las pestañas del esquema y termina")
    p.add_argument("--dry-run", action="store_true", help="lee monday y revisa la pestaña, pero no escribe nada")
    p.add_argument("--comparar", action="store_true",
                   help="compara contra lo que ya hay en la pestaña y cuenta las diferencias por columna")
    p.add_argument("--aceptar-vacio", action="store_true",
                   help="permite vaciar una pestaña con muchos datos cuando monday devuelve 0 elementos")
    p.add_argument("--depurar", action="store_true",
                   help="muestra el traceback de los errores (puede incluir datos; sólo para uso local)")
    return p


def _normalizar(texto: str) -> str:
    """Minúsculas y sin acentos, para comparar nombres de pestaña."""
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).casefold().strip()


def elegir_grupos(esquema: Esquema, todas: bool, nombres: list[str], periodicas: bool = False) -> list[Grupo]:
    """Devuelve los grupos pedidos (todos, los marcados como periódicos o los nombrados), sin repetir y
    en el orden del esquema; lanza ErrorConfiguracion si no hay ninguno marcado como periódico o si
    algún nombre no corresponde a una pestaña del esquema."""
    if todas:
        return list(esquema.grupos)
    if periodicas:
        marcados = [g for g in esquema.grupos if g.periodica]
        if not marcados:
            raise ErrorConfiguracion("ninguna pestaña del esquema está marcada como periódica")
        return marcados
    por_nombre = {_normalizar(g.hoja): g for g in esquema.grupos}
    elegidos, desconocidos = [], []
    for nombre in nombres:
        grupo = por_nombre.get(_normalizar(nombre))
        if grupo is None:
            desconocidos.append(nombre)
        else:
            elegidos.append(grupo)
    if desconocidos:
        raise ErrorConfiguracion(f"pestañas que no están en el esquema: {desconocidos}")
    return [g for g in esquema.grupos if g in elegidos]


def _cliente_monday(esquema: Esquema) -> ClienteMonday:
    """Crea el cliente de monday con el token y la versión de la API del entorno."""
    token = (os.environ.get("MONDAY_TOKEN") or "").strip()
    if not token:
        raise ErrorConfiguracion("falta la variable MONDAY_TOKEN")
    version = os.environ.get("MONDAY_API_VERSION") or VERSION_API_POR_DEFECTO
    return ClienteMonday(token, esquema.tablero_id, version)


def _abrir_libro(dry_run: bool, comparar_con_hoja: bool):
    """Abre el libro de Google Sheets. Un dry-run sin comparación puede seguir sin credenciales de
    Google: devuelve None y entonces sólo se lee monday."""
    ruta = os.environ.get("GOOGLE_CREDS_PATH") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    id_libro = (os.environ.get("SPREADSHEET_ID_SAC") or "").strip()
    if not ruta or not id_libro:
        if dry_run and not comparar_con_hoja:
            log.warning("faltan las credenciales de Google o el ID del Sheet: el dry-run sólo lee monday")
            return None
        raise ErrorConfiguracion("faltan GOOGLE_CREDS_PATH (o GOOGLE_APPLICATION_CREDENTIALS) y SPREADSHEET_ID_SAC")
    if Path(ruta).is_dir():
        raise ErrorConfiguracion("GOOGLE_CREDS_PATH apunta a una carpeta, no al archivo JSON de la cuenta de servicio")
    if not Path(ruta).is_file():
        raise ErrorConfiguracion("el archivo de credenciales de Google no existe en la ruta configurada")
    return hojas.conectar(ruta, id_libro)


def _forzar_utf8() -> None:
    """Fuerza UTF-8 en stdout para que los acentos de los nombres de pestaña no fallen en consolas cp1252."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def main(argv=None) -> int:
    """Punto de entrada: devuelve 0 si todas las pestañas pedidas quedaron bien y 1 si hubo algún error."""
    _forzar_utf8()
    args = construir_parser().parse_args(argv)
    load_dotenv(RUTA_ENV)
    filtro = configurar_registro([os.environ.get("MONDAY_TOKEN"), os.environ.get("SPREADSHEET_ID_SAC")])

    try:
        esquema = cargar_esquema()
        filtro.agregar(esquema.tablero_id)
        if args.listar:
            for grupo in esquema.grupos:
                print(grupo.hoja)
            return 0
        grupos = elegir_grupos(esquema, args.todas, args.hoja or [], args.periodicas)
        monday = _cliente_monday(esquema)
        total = monday.validar_esquema(esquema)
        log.info("monday: el tablero reporta %d elementos en total", total)
        libro = _abrir_libro(args.dry_run, args.comparar)
    except (ErrorConfiguracion, ErrorMonday, hojas.ErrorHoja) as e:
        log.error("%s", e)
        return 1
    except Exception as e:  # errores de conexión con Google u otros de librerías
        log.error("%s: %s", type(e).__name__, e, exc_info=args.depurar)
        return 1

    modo = "dry-run" if args.dry_run else "escritura"
    log.info("inicio (%s) de %d pestañas", modo, len(grupos))
    resultados = sincronizar(esquema, monday, libro, grupos, dry_run=args.dry_run,
                             comparar_con_hoja=args.comparar, aceptar_vacio=args.aceptar_vacio,
                             depurar=args.depurar)
    for r in resultados:
        if r.error:
            log.info("resumen [%s]: con error", r.hoja)
        elif args.dry_run:
            log.info("resumen [%s]: %d filas en monday (dry-run, sin escribir)", r.hoja, r.filas_monday)
        else:
            log.info("resumen [%s]: %d filas en monday, %d escritas", r.hoja, r.filas_monday, r.filas_escritas)
    con_error = [r.hoja for r in resultados if r.error]
    if con_error:
        log.error("terminó con error en %d de %d pestañas: %s", len(con_error), len(resultados), ", ".join(con_error))
        return 1
    log.info("terminó sin errores")
    return 0
