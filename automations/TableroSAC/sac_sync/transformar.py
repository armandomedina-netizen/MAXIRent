"""Convierte un elemento de monday en una fila del Sheet con celdas tipadas.

Las celdas se escriben sin que Sheets las reinterprete: los números van como números,
las fechas y duraciones como número de serie y el resto como texto literal. Así un texto
que empiece con "=", "+" o "-", o que parezca número o fecha (una placa, un teléfono con
ceros), se conserva tal como está en monday.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .config import Columna, Esquema

# Tipos de columna de monday cuyo valor legible está en display_value y no en text.
TIPOS_CON_DISPLAY_VALUE = frozenset({"mirror", "board_relation", "formula", "subtasks"})

# Día cero de los números de serie de fecha de Google Sheets.
EPOCA_SHEETS = date(1899, 12, 30)
# Límite de caracteres por celda en Google Sheets.
MAX_CARACTERES_CELDA = 50_000
# Mayor entero que un double (el número de Sheets) representa sin perder dígitos.
MAX_ENTERO_EXACTO = 2**53

# Entero o decimal, con o sin signo.
_RE_NUMERO = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
# Número con coma de millares ("1,234.5").
_RE_NUMERO_CON_MILES = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
# AAAA-MM-DD con hora opcional (HH:MM o HH:MM:SS).
_RE_FECHA = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$")
# H:MM:SS con horas sin tope.
_RE_DURACION = re.compile(r"^(\d+):(\d{2}):(\d{2})$")


@dataclass
class ResumenLimpieza:
    """Conteos de lo que no cuadró con el esquema durante la limpieza; no guarda valores."""
    filas: int = 0
    celdas_acotadas: int = 0
    no_reconocidos: Counter = field(default_factory=Counter)     # encabezado -> valores que no cuadraron con su tipo
    columnas_ausentes: Counter = field(default_factory=Counter)  # encabezado -> elementos sin esa columna en la respuesta

    def advertencias(self) -> list[str]:
        """Convierte los conteos en líneas de aviso para el registro."""
        lineas = []
        for encabezado, n in sorted(self.no_reconocidos.items()):
            lineas.append(f"columna '{encabezado}': {n} valores no cuadran con su tipo y se escribieron como texto")
        for encabezado, n in sorted(self.columnas_ausentes.items()):
            lineas.append(f"columna '{encabezado}': monday no la devolvió en {n} elementos y quedó en blanco")
        if self.celdas_acotadas:
            lineas.append(f"{self.celdas_acotadas} celdas superaban {MAX_CARACTERES_CELDA} caracteres y se recortaron")
        return lineas


def a_numero(texto: str) -> int | float | None:
    """Convierte un texto numérico a int o float; devuelve None si no es un número exacto."""
    t = texto.strip()
    if _RE_NUMERO_CON_MILES.match(t):
        t = t.replace(",", "")
    elif not _RE_NUMERO.match(t):
        return None
    if "." in t:
        return float(t)
    n = int(t)
    return n if abs(n) <= MAX_ENTERO_EXACTO else None


def a_serial_fecha(texto: str) -> int | float | None:
    """Convierte 'AAAA-MM-DD' (con hora opcional) al número de serie de fecha de Sheets: los días
    desde 1899-12-30 más la fracción del día. Devuelve None si el texto no es una fecha válida."""
    m = _RE_FECHA.match(texto.strip())
    if not m:
        return None
    anio, mes, dia, hora, minuto, segundo = m.groups()
    try:
        dias = (date(int(anio), int(mes), int(dia)) - EPOCA_SHEETS).days
    except ValueError:
        return None
    if hora is None:
        return dias
    h, mi, s = int(hora), int(minuto), int(segundo or 0)
    if h > 23 or mi > 59 or s > 59:
        return None
    return dias + (h * 3600 + mi * 60 + s) / 86400


def a_serial_duracion(texto: str) -> float | None:
    """Convierte 'H:MM:SS' (horas sin tope) en fracción de día, que es como Sheets guarda una duración."""
    m = _RE_DURACION.match(texto.strip())
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    if mi > 59 or s > 59:
        return None
    return (h * 3600 + mi * 60 + s) / 86400


_CONVERSORES = {"numero": a_numero, "fecha": a_serial_fecha, "duracion": a_serial_duracion}


def valor_crudo(columna_monday: dict) -> str | None:
    """Elige la fuente del valor de una columna de monday: display_value en reflejos, relaciones,
    fórmulas y subelementos, y text en el resto. El texto "null" que monday devuelve en las
    fórmulas vacías cuenta como vacío."""
    if columna_monday.get("type") in TIPOS_CON_DISPLAY_VALUE:
        valor = columna_monday.get("display_value")
        if valor is None:
            valor = columna_monday.get("text")
        return None if valor == "null" else valor
    return columna_monday.get("text")


def limpiar_celda(valor: str | None, columna: Columna, resumen: ResumenLimpieza):
    """Convierte el valor crudo al tipo de la columna. Lo vacío queda en None (celda en blanco) y
    lo que no cuadra con su tipo se conserva como texto."""
    if valor is None or valor == "":
        return None
    if columna.tipo != "texto":
        if valor.strip() == "":
            return None
        # Una duración con varios valores separados por coma no se convierte y queda como texto.
        if columna.tipo == "duracion" and "," in valor:
            return _acotar(valor, resumen)
        convertido = _CONVERSORES[columna.tipo](valor)
        if convertido is not None:
            return convertido
        resumen.no_reconocidos[columna.encabezado] += 1
    return _acotar(valor, resumen)


def _acotar(texto: str, resumen: ResumenLimpieza) -> str:
    """Recorta el texto al máximo de caracteres por celda y lleva la cuenta de los recortes."""
    if len(texto) > MAX_CARACTERES_CELDA:
        resumen.celdas_acotadas += 1
        return texto[:MAX_CARACTERES_CELDA]
    return texto


def fila_desde_item(item: dict, esquema: Esquema, resumen: ResumenLimpieza) -> list:
    """Arma la fila de un elemento: una celda por columna del esquema, en su orden."""
    por_id = {cv["id"]: cv for cv in item.get("column_values") or []}
    fila = []
    for columna in esquema.columnas:
        if columna.origen == "nombre":
            crudo = item.get("name")
        elif columna.origen == "grupo":
            crudo = (item.get("group") or {}).get("title")
        else:
            cv = por_id.get(columna.columna_id)
            if cv is None:
                resumen.columnas_ausentes[columna.encabezado] += 1
                crudo = None
            else:
                crudo = valor_crudo(cv)
                # El ID del elemento respalda a la columna de tipo item_id cuando su texto viene vacío.
                if not crudo and cv.get("type") == "item_id":
                    crudo = item.get("id")
        fila.append(limpiar_celda(crudo, columna, resumen))
    resumen.filas += 1
    return fila


def filas_desde_items(items: list[dict], esquema: Esquema) -> tuple[list[list], ResumenLimpieza]:
    """Convierte una lista de elementos en filas y devuelve también el resumen de la limpieza."""
    resumen = ResumenLimpieza()
    return [fila_desde_item(item, esquema, resumen) for item in items], resumen
