"""Detecta datos dudosos en el reporte de Gestoría de Maxinet para avisarlos en la pestaña ALERTAS DE DATOS.

Sin entrada ni salida: recibe el DataFrame de la descarga (columnas de COLUMNAS_SHEET) y devuelve alertas.
No corrige nada: los datos de Maxinet los corrige quien los captura; aquí sólo se señalan para que alguien lo haga.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

TIPOS_INDICADOR = {"SINIESTRO", "DAÑO", "ROBO", "CORRALÓN"}   # los que cuentan en el índice y en el dashboard
ANIO_MIN = 2020
MAX_ADELANTO_DIAS = 1       # un evento no puede ser posterior a la creación del ticket (margen por zona horaria)
MAX_RETRASO_DIAS = 730      # ni anterior en más de dos años (un año mal tecleado)
VENTANA_DUPLICADO_SEG = 600
FOLIO_CON_SUCURSAL = 1500   # desde este folio Maxinet siempre trae FromSite; antes la sucursal la curó el equipo
SUCURSALES = {"LP", "CP"}

_RE_FECHA = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class Alerta:
    folio: int
    tipo: str
    estatus: str
    campo: str
    valor: str
    motivo: str
    sugerencia: str


def _fecha(texto) -> date | None:
    m = _RE_FECHA.search(str(texto or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _creado(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto).strip().replace("T", " ")[:19])
    except ValueError:
        return None


def _texto(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NA else str(v).strip()


def detectar(df: pd.DataFrame, hoy: date) -> list[Alerta]:
    """Devuelve las alertas ordenadas por folio (y por campo dentro de un folio)."""
    alertas: list[Alerta] = []
    filas = []
    for r in df.to_dict("records"):
        try:
            folio = int(r["id"])
        except (TypeError, ValueError):
            continue
        filas.append((folio, r))

    for folio, r in filas:
        tipo, estatus = _texto(r.get("nombreTipo")), _texto(r.get("estatus"))
        texto_fecha = _texto(r.get("fecha_evento"))
        f = _fecha(texto_fecha)
        creado = _creado(r.get("created_at"))

        def alerta(campo, valor, motivo, sugerencia):
            alertas.append(Alerta(folio, tipo, estatus, campo, valor, motivo, sugerencia))

        if f is not None:
            if f.year < 100:
                alerta("Fecha del evento", texto_fecha,
                       "El año trae dos dígitos; Google Sheets lo lee como 20" + f"{f.year:02d}" + ", pero puede ser otro mes o año.",
                       "Confirmar la fecha real y corregirla en Maxinet.")
            elif f.year < ANIO_MIN or f.year > hoy.year + 1:
                alerta("Fecha del evento", texto_fecha, f"Año fuera de rango ({ANIO_MIN} a {hoy.year + 1}).",
                       "Corregir el año en Maxinet.")
            elif creado is not None:
                dias = (f - creado.date()).days
                if dias > MAX_ADELANTO_DIAS:
                    alerta("Fecha del evento", texto_fecha, f"El evento es {dias} días posterior a la creación del ticket.",
                           "Confirmar la fecha real y corregirla en Maxinet.")
                elif -dias > MAX_RETRASO_DIAS:
                    alerta("Fecha del evento", texto_fecha,
                           f"El evento es {-dias} días anterior a la creación del ticket (¿año mal tecleado?).",
                           "Confirmar la fecha real y corregirla en Maxinet.")
        elif texto_fecha:
            alerta("Fecha del evento", texto_fecha, "No se pudo leer la fecha.", "Revisar el formato en Maxinet.")

        sucursal = _texto(r.get("FromSite")).upper()
        if folio >= FOLIO_CON_SUCURSAL and sucursal not in SUCURSALES:
            alerta("Sucursal", sucursal or "(vacía)", "Maxinet debería traer LP o CP; sin eso el ticket no cuenta en ningún índice.",
                   "Corregir la sucursal en Maxinet (o agregarla en la pestaña CORRECCIONES).")

    # Posibles duplicados: mismo vehículo, reserva, fecha y tipo, capturados con segundos de diferencia.
    grupos: dict[tuple, list[tuple[datetime, int, dict]]] = {}
    for folio, r in filas:
        tipo = _texto(r.get("nombreTipo"))
        placa, reserva, creado = _texto(r.get("registrationNo")), _texto(r.get("bookingNo")), _creado(r.get("created_at"))
        if tipo in TIPOS_INDICADOR and placa and reserva and creado is not None:
            grupos.setdefault((placa, reserva, _texto(r.get("fecha_evento")), tipo), []).append((creado, folio, r))
    for miembros in grupos.values():
        miembros.sort(key=lambda x: (x[0], x[1]))
        for (c0, f0, _), (c1, f1, r1) in zip(miembros, miembros[1:]):
            seg = int((c1 - c0).total_seconds())
            if seg <= VENTANA_DUPLICADO_SEG:
                alertas.append(Alerta(f1, _texto(r1.get("nombreTipo")), _texto(r1.get("estatus")), "Folio",
                                      str(f1), f"Posible duplicado del folio {f0}: misma placa, reserva, fecha y tipo, capturado {seg} s después.",
                                      "Cancelar uno de los dos en Maxinet si es el mismo evento."))
    alertas.sort(key=lambda a: (a.folio, a.campo))
    return alertas
