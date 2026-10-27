from datetime import date

import pandas as pd

from anomalias import detectar

HOY = date(2026, 10, 26)


def fila(folio, fecha="2026-10-10", creado="2026-10-10 09:00:00", tipo="SINIESTRO", sucursal="LP", placa="AAA111", reserva="#R1",
         estatus="ABIERTO"):
    return {"id": folio, "estatus": estatus, "fecha_evento": fecha, "nombreTipo": tipo, "FromSite": sucursal,
            "registrationNo": placa, "bookingNo": reserva, "created_at": creado}


def alertas(*filas):
    return detectar(pd.DataFrame(list(filas)), HOY)


def test_un_ticket_normal_no_genera_alertas():
    assert alertas(fila(1600)) == []


def test_ano_de_dos_digitos():
    a = alertas(fila(1683, fecha="0026-02-19", creado="2026-10-20 16:24:14"))
    assert [(x.folio, x.campo) for x in a] == [(1683, "Fecha del evento")]
    assert "dos dígitos" in a[0].motivo


def test_evento_posterior_a_la_creacion():
    a = alertas(fila(1662, fecha="2027-10-12", creado="2026-10-12 17:20:43", tipo="VERIFICACIÓN"))
    assert len(a) == 1 and "posterior" in a[0].motivo
    assert alertas(fila(1663, fecha="2026-10-11", creado="2026-10-10 23:00:00")) == []     # un día de margen


def test_evento_muy_anterior_a_la_creacion():
    a = alertas(fila(1108, fecha="2023-04-06", creado="2026-04-07 10:00:00"))
    assert len(a) == 1 and "anterior" in a[0].motivo
    # una captura tardía de ~20 meses es legítima y no se avisa
    assert alertas(fila(845, fecha="2024-01-15", creado="2025-11-28 10:00:00")) == []


def test_anio_fuera_de_rango():
    a = alertas(fila(1, fecha="2019-05-01", creado="2019-05-02 10:00:00"))
    assert len(a) == 1 and "fuera de rango" in a[0].motivo


def test_sucursal_vacia_solo_desde_el_folio_1500():
    assert alertas(fila(1499, sucursal="")) == []                 # tickets viejos: la sucursal la curó el equipo
    a = alertas(fila(1700, sucursal=""))
    assert [(x.folio, x.campo) for x in a] == [(1700, "Sucursal")]
    assert alertas(fila(1701, sucursal="CP")) == []


def test_posible_duplicado_de_siniestro():
    a = alertas(fila(1646, creado="2026-10-08 10:00:00", fecha="2026-10-08"),
                fila(1647, creado="2026-10-08 10:00:20", fecha="2026-10-08"))
    assert [(x.folio, x.campo) for x in a] == [(1647, "Folio")]
    assert "folio 1646" in a[0].motivo
    # separados por horas o con otra reserva no son duplicado; los tipos que no cuentan en el índice tampoco
    assert alertas(fila(1, creado="2026-10-08 10:00:00", fecha="2026-10-08"), fila(2, creado="2026-10-08 15:00:00", fecha="2026-10-08")) == []
    assert alertas(fila(1, fecha="2026-10-08", creado="2026-10-08 10:00:00"),
                   fila(2, fecha="2026-10-08", creado="2026-10-08 10:00:05", reserva="#R2")) == []
    assert alertas(fila(1, tipo="VERIFICACIÓN", fecha="2026-10-08", creado="2026-10-08 10:00:00"),
                   fila(2, tipo="VERIFICACIÓN", fecha="2026-10-08", creado="2026-10-08 10:00:05")) == []


def test_datos_vacios_o_raros_no_tumban_la_deteccion():
    a = alertas({"id": "x", "estatus": None, "fecha_evento": None, "nombreTipo": None, "FromSite": None,
                 "registrationNo": None, "bookingNo": None, "created_at": None},
                fila(1600, fecha="basura", creado="tampoco"))
    assert [x.campo for x in a] == ["Fecha del evento"]
