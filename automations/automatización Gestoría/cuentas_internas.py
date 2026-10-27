"""Clasificación de cuentas internas (no clientes) a partir del campo Cliente de Maxinet.

Sin I/O: recibe cadenas y devuelve decisiones, para poder probarlo sin tocar Sheets ni Maxinet.
Equivale al criterio vigente de BDATOS (CLIENTE = NO si el nombre está en la lista manual
'NO SON CLIENTES') ampliado con una regla de prefijos y sufijos y con una señal de aviso
para nombres desconocidos que 'parecen' una cuenta interna.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Misma normalización que TRIM() + UPPER() de Google Sheets (TRIM también junta espacios internos).
def normalizar(nombre: str | None) -> str:
    return re.sub(r" +", " ", (nombre or "").strip()).upper()

# Nivel 1: se clasifica solo (precisión 100 % sobre los nombres de cliente real conocidos).
# Se edita aquí o en la celda de patrón del libro, nunca dentro de la lógica.
PATRON_INTERNA = (
    r"^(TALLER|TRASLADO|GESTORIA|SEMINUEVOS|RELEVOS|OTROS|RECOLECCION|LEVANTAMIENTO DA[ÑN]OS"
    r"|ENDEREZADO Y PINTURA|PREVIA|USO INTERNO|MECANICOS USO INTERNO|T\.(PREVENTIVO|CORRECTIVO)"
    r"|HYP|EXT\.|LOGISTICA TRASLADO"
    r"|PERDIDA TOTAL|ROBADO|VENDIDO|EN TRANSITO|ABUSO DE CONFIANZA|SERVICIO EXTERNO)( |$)"
    r"|( TALLER EXTERNOS?| HYP EXT)$"
)
_RE_INTERNA = re.compile(PATRON_INTERNA)


def compilar_patron(texto: str | None) -> re.Pattern:
    """El patrón vive en una celda del libro (ÍNDICE SINIESTRALIDAD!B2) para que se amplíe sin tocar el código;
    una celda vacía o con una expresión inválida no debe tumbar la corrida: se usa el patrón por omisión."""
    texto = (texto or "").strip()
    if not texto:
        return _RE_INTERNA
    try:
        return re.compile(texto)
    except re.error:
        return _RE_INTERNA

# Nivel 2: solo AVISA (no cambia la clasificación). Aprende de las formas que ya tuvieron las cuentas internas.
_PALABRAS_VACIAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "E", "EL", "EN", "A", "S", "SA", "CV", "RL", "SAPI", "SAS",
                    "INC", "SC", "AC", "LP", "CP", "II", "SRL"}
_RE_SUFIJO_LEGAL = re.compile(r"(\bS\.?A\.?\b|\bS\.? ?DE ?R\.?L\.?\b|\bSAPI\b|\bSAS\b|\bC\.?V\.?\b|\bA\.?C\.?\b"
                              r"|\bS\.?C\.?\b|SOCIEDAD|\bINC\b|\bSRL\b)")
_RE_PALABRA_CLAVE = re.compile(r"(TALLER|\bHYP\b|\bEXT\b|\bEXT\.|INTERNO|TRASLADO|SEMINUEV|GESTORIA|CORRECTIVO|PREVENTIVO"
                               r"|PREVIA|RELEVO|OTROS|RECOLECCION|LEVANTAMIENTO|ENDEREZADO|HOJALATERIA)")


@dataclass(frozen=True)
class Decision:
    es_interna: bool
    motivo: str  # 'lista' | 'regla' | ''


def clasificar(nombre: str | None, lista: set[str], patron: re.Pattern | None = None) -> Decision:
    """lista = nombres ya normalizados (la lista manual 'NO SON CLIENTES')."""
    n = normalizar(nombre)
    if not n:
        return Decision(False, "")
    if n in lista:
        return Decision(True, "lista")
    if (patron or _RE_INTERNA).search(n):
        return Decision(True, "regla")
    return Decision(False, "")


def senales_de_cuenta_interna(nombre: str | None) -> list[str]:
    """Razones por las que un nombre NO clasificado se parece a una cuenta interna (vacío = no avisar)."""
    n = normalizar(nombre)
    if not n:
        return []
    razones: list[str] = []
    if _RE_PALABRA_CLAVE.search(n):
        razones.append("contiene palabra de cuenta interna")
    palabras = [p for p in re.split(r"[ ,]+", n) if p and p not in _PALABRAS_VACIAS and len(p) > 2]
    if len(palabras) != len(set(palabras)):
        razones.append("palabra repetida")
    if not _RE_SUFIJO_LEGAL.search(n) and len(n.split(" ")) <= 2:
        razones.append("nombre corto sin sufijo legal")
    return razones


@dataclass(frozen=True)
class Aviso:
    nombre: str
    tickets: int
    primer_folio: int
    razones: tuple[str, ...]
    por_patron: bool = False   # ya cuenta como interna sólo porque el patrón la cubre: una persona debe confirmarlo


def nombres_por_revisar(tickets: list[tuple[int, str]], lista: set[str], revisados: set[str],
                        patron: re.Pattern | None = None) -> list[Aviso]:
    """tickets = [(folio, nombre_cliente)]. Devuelve los nombres que una persona debe confirmar y que nadie ha
    revisado todavía (revisados = nombres ya confirmados como cliente o como interna, o ya avisados):
      - los que NO clasifica ni la lista ni el patrón pero se parecen a una cuenta interna (siguen contando como cliente);
      - los que clasifica SÓLO el patrón (ya cuentan como interna, pero un cliente real con un nombre parecido
        saldría del índice en silencio; la confirmación lo evita)."""
    acum: dict[str, list[int]] = {}
    for folio, nombre in tickets:
        n = normalizar(nombre)
        if not n or n in revisados:
            continue
        acum.setdefault(n, []).append(folio)
    avisos = []
    for n, folios in acum.items():
        d = clasificar(n, lista, patron)
        if d.es_interna and d.motivo == "lista":
            continue
        if d.es_interna:
            avisos.append(Aviso(n, len(folios), min(folios), ("clasificada como interna por el patrón; confirmar",), True))
        elif razones := senales_de_cuenta_interna(n):
            avisos.append(Aviso(n, len(folios), min(folios), tuple(razones)))
    return sorted(avisos, key=lambda a: a.primer_folio)
