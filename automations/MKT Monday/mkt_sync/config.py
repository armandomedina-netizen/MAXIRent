"""Configuración de la sincronización: el JSON con los IDs reales de monday y los parámetros de la hoja."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errores import ErrorConfig

CARPETA = Path(__file__).resolve().parent.parent
RUTA_POR_DEFECTO = CARPETA / "private" / "mkt-monday-config.json"
OBLIGATORIAS = {"tablero_id", "columna_estado", "etiqueta_califica", "columna_tipo", "tipos_incluidos"}
OPCIONALES = {"hoja", "columna_periodo", "columna_recibidos", "columna_calificados", "primera_fila"}
_LETRA_COLUMNA = re.compile(r"[A-Z]{1,3}")


@dataclass(frozen=True)
class Config:
    """Qué leer en monday y en qué celdas de la hoja escribirlo."""

    tablero_id: int
    columna_estado: str
    etiqueta_califica: str
    columna_tipo: str
    tipos_incluidos: tuple[str, ...]
    hoja: str = "MKT"
    columna_periodo: str = "F"
    columna_recibidos: str = "G"
    columna_calificados: str = "H"
    primera_fila: int = 4


def _texto_json() -> str:
    """JSON de configuración: la variable MKT_MONDAY_CONFIG_JSON (el secret de GitHub Actions) y, si no
    existe, el archivo de MKT_MONDAY_CONFIG_PATH o el de private/ dentro de esta carpeta."""
    en_linea = os.getenv("MKT_MONDAY_CONFIG_JSON", "").strip()
    if en_linea:
        return en_linea
    ruta = Path(os.getenv("MKT_MONDAY_CONFIG_PATH") or RUTA_POR_DEFECTO)
    try:
        return ruta.read_text(encoding="utf-8")
    except OSError as e:
        raise ErrorConfig(f"no se pudo leer la configuración de monday en {ruta}: {e.strerror}") from None


def cargar_config(texto: str | None = None) -> Config:
    """Lee y valida la configuración. Rechaza claves desconocidas para que un error de dedo no pase en
    silencio, y los valores de ejemplo (tablero 0) para que no se corra sin haberla llenado."""
    crudo = texto if texto is not None else _texto_json()
    try:
        datos = json.loads(crudo)
    except ValueError:
        raise ErrorConfig("la configuración de monday no es un JSON válido") from None
    if not isinstance(datos, dict):
        raise ErrorConfig("la configuración de monday debe ser un objeto JSON")
    faltan = OBLIGATORIAS - datos.keys()
    if faltan:
        raise ErrorConfig(f"faltan claves en la configuración de monday: {sorted(faltan)}")
    sobran = datos.keys() - OBLIGATORIAS - OPCIONALES
    if sobran:
        raise ErrorConfig(f"claves desconocidas en la configuración de monday: {sorted(sobran)}")

    try:
        tablero_id = int(datos["tablero_id"])
    except (TypeError, ValueError):
        raise ErrorConfig("tablero_id debe ser un número") from None
    if tablero_id <= 0:
        raise ErrorConfig("tablero_id es el valor de ejemplo; llena la configuración con los IDs reales")
    for clave in ("columna_estado", "etiqueta_califica", "columna_tipo"):
        if not isinstance(datos[clave], str) or not datos[clave].strip():
            raise ErrorConfig(f"{clave} debe ser un texto no vacío")
    tipos = datos["tipos_incluidos"]
    if not isinstance(tipos, list) or not tipos or not all(isinstance(t, str) and t.strip() for t in tipos):
        raise ErrorConfig("tipos_incluidos debe ser una lista de textos no vacía")

    extra = {}
    for clave in ("columna_periodo", "columna_recibidos", "columna_calificados"):
        if clave in datos:
            if not isinstance(datos[clave], str) or not _LETRA_COLUMNA.fullmatch(datos[clave]):
                raise ErrorConfig(f"{clave} debe ser una letra de columna en mayúsculas, como F")
            extra[clave] = datos[clave]
    if "hoja" in datos:
        if not isinstance(datos["hoja"], str) or not datos["hoja"].strip():
            raise ErrorConfig("hoja debe ser el nombre de la pestaña")
        extra["hoja"] = datos["hoja"]
    if "primera_fila" in datos:
        if not isinstance(datos["primera_fila"], int) or isinstance(datos["primera_fila"], bool) or datos["primera_fila"] < 1:
            raise ErrorConfig("primera_fila debe ser un entero mayor que cero")
        extra["primera_fila"] = datos["primera_fila"]
    return Config(tablero_id=tablero_id, columna_estado=datos["columna_estado"],
                  etiqueta_califica=datos["etiqueta_califica"], columna_tipo=datos["columna_tipo"],
                  tipos_incluidos=tuple(tipos), **extra)
