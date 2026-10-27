"""Pestañas de apoyo del libro de Gestoría que mantiene el sync: FUENTES (sello de la última corrida),
ALERTAS DE DATOS y REVISAR NOMBRES.

Ninguna crea pestañas: si falta alguna se omite con un aviso en el log (el diseño de cada pestaña lo hace
una persona). Ninguna toca los datos de 'GESTORIA CP - LP'. Todas escriben sólo conteos, folios y nombres de
cuentas; ningún dato personal de conductores.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import gspread

from anomalias import Alerta
from cuentas_internas import compilar_patron, normalizar, nombres_por_revisar, clasificar

log = logging.getLogger("gestoria_lp_cp_sync")

PESTANA_INDICE = "ÍNDICE SINIESTRALIDAD"
PESTANA_FUENTES = "FUENTES"
PESTANA_ALERTAS = "ALERTAS DE DATOS"
PESTANA_REVISAR = "REVISAR NOMBRES"
CELDA_PATRON = "B2"          # en ÍNDICE SINIESTRALIDAD; B1 trae el rótulo
LISTA_RANGO = "A2:A"         # lista 'NO SON CLIENTES' en ÍNDICE SINIESTRALIDAD

# Celdas de la pestaña FUENTES que escribe el sync (rótulo en A, valor en B).
CELDAS_ESTADO = {
    "ultima_sincronizacion": "B3",
    "tickets_maxinet": "B4",
    "folios_hoja": "B5",
    "ultima_corrida": "B6",
    "alertas": "B7",
    "nombres_por_revisar": "B8",
}
ENCABEZADOS_ALERTAS = ["FOLIO", "TIPO", "ESTATUS", "CAMPO", "VALOR EN MAXINET", "MOTIVO", "QUÉ HACER"]
ENCABEZADOS_REVISAR = ["NOMBRE", "TICKETS", "PRIMER FOLIO", "MOTIVO DEL AVISO", "ESTADO", "AGREGADA A LA LISTA"]
ESTADOS_VALIDOS = {"INTERNA", "CLIENTE"}


def ahora_cdmx() -> str:
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("America/Mexico_City"))
    except Exception:  # sin base de zonas horarias: México no tiene horario de verano desde 2022
        ahora = datetime.now(timezone(timedelta(hours=-6)))
    return ahora.strftime("%Y-%m-%d %H:%M") + " (hora CDMX)"


def _pestana(libro, nombre: str):
    try:
        return libro.worksheet(nombre)
    except gspread.WorksheetNotFound:
        log.info("No existe la pestaña '%s'; se omite.", nombre)
        return None


def leer_lista_no_clientes(libro) -> set[str]:
    ws = _pestana(libro, PESTANA_INDICE)
    if ws is None:
        return set()
    return {normalizar(f[0]) for f in ws.get(LISTA_RANGO) if f and f[0].strip()}


def leer_patron(libro):
    ws = _pestana(libro, PESTANA_INDICE)
    celda = ws.get(CELDA_PATRON) if ws is not None else None
    return compilar_patron(celda[0][0] if celda and celda[0] else None)


def escribir_estado(libro, datos: dict, dry_run: bool = False) -> bool:
    """Escribe el sello de la última corrida en FUENTES (sólo las celdas de CELDAS_ESTADO que vengan en datos)."""
    ws = _pestana(libro, PESTANA_FUENTES)
    if ws is None:
        return False
    cambios = [{"range": CELDAS_ESTADO[k], "values": [[v]]} for k, v in datos.items() if k in CELDAS_ESTADO]
    if dry_run or not cambios:
        return bool(cambios)
    ws.batch_update(cambios, value_input_option="USER_ENTERED")
    return True


def escribir_alertas(libro, alertas: list[Alerta], dry_run: bool = False) -> int:
    """Reemplaza el contenido de ALERTAS DE DATOS (A2:G) por las alertas de esta corrida."""
    ws = _pestana(libro, PESTANA_ALERTAS)
    if ws is None:
        return len(alertas)
    if dry_run:
        return len(alertas)
    ws.batch_clear([f"A2:G{max(ws.row_count, 2)}"])
    if alertas:
        filas = [[a.folio, a.tipo, a.estatus, a.campo, a.valor, a.motivo, a.sugerencia] for a in alertas]
        if len(filas) + 1 > ws.row_count:
            ws.add_rows(len(filas) + 1 - ws.row_count)
        ws.update(values=filas, range_name="A2", value_input_option="RAW")
    return len(alertas)


def actualizar_revisar_nombres(libro, tickets: list[tuple[int, str]], dry_run: bool = False) -> tuple[int, int, int]:
    """Mantiene REVISAR NOMBRES y agrega a la lista 'NO SON CLIENTES' los nombres que una persona confirmó.

    - Nombres sin clasificar que parecen una cuenta interna, y nombres que sólo clasifica el patrón, se agregan
      con ESTADO vacío (sus tickets se actualizan en cada corrida).
    - ESTADO = INTERNA: el nombre se agrega a ÍNDICE SINIESTRALIDAD!A (sólo agrega, nunca borra) y se anota la fecha.
    - ESTADO = CLIENTE: deja de avisarse (y BDATOS lo cuenta como cliente aunque el patrón lo cubra).
    - Primera corrida (pestaña vacía): los nombres sin clasificar que ya existían se siembran con ESTADO = CLIENTE
      ("línea base") para no inundar la pestaña; los que sólo cubre el patrón quedan para confirmar.
    Devuelve (nombres nuevos avisados, nombres agregados a la lista, pendientes de decidir).
    """
    ws = _pestana(libro, PESTANA_REVISAR)
    if ws is None:
        return 0, 0, 0
    indice = _pestana(libro, PESTANA_INDICE)
    lista = leer_lista_no_clientes(libro)
    patron = leer_patron(libro)

    filas = ws.get("A2:F") or []
    existentes: dict[str, dict] = {}
    for i, f in enumerate(filas):
        f = list(f) + [""] * (6 - len(f))
        n = normalizar(f[0])
        if n:
            existentes[n] = {"fila": 2 + i, "estado": f[4].strip().upper(), "agregada": f[5].strip()}
    semilla = not existentes

    avisos = nombres_por_revisar(tickets, lista, set(existentes), patron)
    ya_avisados = {n: d for n, d in existentes.items() if d["estado"] not in ESTADOS_VALIDOS}

    # confirmados como internos que todavía no están en la lista manual (el patrón no basta: puede cambiar)
    por_agregar = [n for n, d in existentes.items() if d["estado"] == "INTERNA" and not d["agregada"] and n not in lista]
    marcar_agregadas = [n for n, d in existentes.items() if d["estado"] == "INTERNA" and not d["agregada"] and n in lista]

    conteo: dict[str, list[int]] = {}
    for folio, nombre in tickets:
        conteo.setdefault(normalizar(nombre), []).append(folio)

    pendientes = len(ya_avisados) + sum(1 for a in avisos if a.por_patron or not semilla)
    if dry_run:
        return len(avisos), len(por_agregar), pendientes

    hoy = date.today().isoformat()
    cambios = []
    for n, d in ya_avisados.items():
        folios = conteo.get(n, [])
        cambios.append({"range": f"B{d['fila']}:C{d['fila']}", "values": [[len(folios), min(folios) if folios else ""]]})
    if por_agregar and indice is not None:
        col_a = indice.get("A1:A") or []
        siguiente = 1 + max((i for i, f in enumerate(col_a) if f and f[0].strip()), default=0) + 1
        if siguiente + len(por_agregar) - 1 > indice.row_count:
            indice.add_rows(siguiente + len(por_agregar) - 1 - indice.row_count)
        indice.update(values=[[n] for n in por_agregar], range_name=f"A{siguiente}", value_input_option="RAW")
    for n in por_agregar + marcar_agregadas:
        cambios.append({"range": f"F{existentes[n]['fila']}", "values": [[hoy]]})
    if cambios:
        ws.batch_update(cambios, value_input_option="USER_ENTERED")

    if avisos:
        primera = 2 + max((d["fila"] - 2 for d in existentes.values()), default=-1) + 1
        nuevas = []
        for a in avisos:
            if semilla and not a.por_patron:
                nuevas.append([a.nombre, a.tickets, a.primer_folio, "Línea base: ya existía al activar el aviso", "CLIENTE", ""])
            else:
                nuevas.append([a.nombre, a.tickets, a.primer_folio, "; ".join(a.razones), "", ""])
        if primera + len(nuevas) - 1 > ws.row_count:
            ws.add_rows(primera + len(nuevas) - 1 - ws.row_count)
        ws.update(values=nuevas, range_name=f"A{primera}", value_input_option="RAW")
    return len(avisos), len(por_agregar), pendientes
