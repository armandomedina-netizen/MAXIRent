import hojas_apoyo as h
from anomalias import Alerta
from tests.fakes import HojaFalsa, LibroFalso


def indice(lista=("TALLER TALLER", "USO INTERNO"), patron=""):
    return HojaFalsa(h.PESTANA_INDICE, {"A2:A": [[n] for n in lista], "B2": [[patron]] if patron else [], "A1:A": [["NO SON CLIENTES"]] + [[n] for n in lista]})


def test_si_faltan_las_pestanas_de_apoyo_no_pasa_nada():
    libro = LibroFalso()
    assert h.escribir_estado(libro, {"tickets_maxinet": 5}) is False
    assert h.escribir_alertas(libro, []) == 0
    assert h.actualizar_revisar_nombres(libro, [(1, "CUALQUIERA")]) == (0, 0, 0)
    assert h.leer_lista_no_clientes(libro) == set()


def test_el_sello_escribe_solo_las_celdas_conocidas():
    fuentes = HojaFalsa(h.PESTANA_FUENTES)
    assert h.escribir_estado(LibroFalso(fuentes), {"tickets_maxinet": 1644, "ultima_sincronizacion": "hoy", "otro": 1})
    assert dict((r, v[0][0]) for r, v in fuentes.escrituras) == {"B4": 1644, "B3": "hoy"}


def test_el_sello_en_dry_run_no_escribe():
    fuentes = HojaFalsa(h.PESTANA_FUENTES)
    h.escribir_estado(LibroFalso(fuentes), {"tickets_maxinet": 1}, dry_run=True)
    assert fuentes.escrituras == []


def test_las_alertas_reemplazan_lo_anterior():
    ws = HojaFalsa(h.PESTANA_ALERTAS, row_count=50)
    a = [Alerta(1662, "VERIFICACIÓN", "CERRADO", "Fecha del evento", "2027-10-12", "motivo", "qué hacer")]
    assert h.escribir_alertas(LibroFalso(ws), a) == 1
    assert ws.limpiezas == ["A2:G50"]
    assert ws.escrituras == [("A2", [[1662, "VERIFICACIÓN", "CERRADO", "Fecha del evento", "2027-10-12", "motivo", "qué hacer"]])]
    ws2 = HojaFalsa(h.PESTANA_ALERTAS)
    h.escribir_alertas(LibroFalso(ws2), [])
    assert ws2.limpiezas and ws2.escrituras == []         # sin alertas: sólo se limpia


def test_nombres_nuevos_se_avisan_una_sola_vez():
    revisar = HojaFalsa(h.PESTANA_REVISAR)
    libro = LibroFalso(indice(), revisar)
    nuevos, agregados, pendientes = h.actualizar_revisar_nombres(libro, [(10, "REPOSICION"), (11, "REPOSICION"), (12, "EMPRESA EJEMPLO SA DE CV")])
    assert (nuevos, agregados, pendientes) == (1, 0, 1)
    assert revisar.escrituras == [("A2", [["REPOSICION", 2, 10, "nombre corto sin sufijo legal", "", ""]])]
    # segunda corrida: el nombre ya está en la pestaña, sólo se refrescan sus conteos
    revisar2 = HojaFalsa(h.PESTANA_REVISAR, {"A2:F": [["REPOSICION", 2, 10, "motivo", "", ""]]})
    nuevos, agregados, pendientes = h.actualizar_revisar_nombres(LibroFalso(indice(), revisar2), [(10, "REPOSICION"), (11, "REPOSICION"), (13, "REPOSICION")])
    assert (nuevos, agregados, pendientes) == (0, 0, 1)
    assert revisar2.escrituras == [("B2:C2", [[3, 10]])]


def test_un_nombre_marcado_interna_se_agrega_a_la_lista():
    revisar = HojaFalsa(h.PESTANA_REVISAR, {"A2:F": [["REPOSICION", 2, 10, "motivo", "interna", ""]]})
    idx = indice()
    nuevos, agregados, pendientes = h.actualizar_revisar_nombres(LibroFalso(idx, revisar), [(10, "REPOSICION")])
    assert (nuevos, agregados, pendientes) == (0, 1, 0)
    assert idx.escrituras == [("A4", [["REPOSICION"]])]        # debajo de A1 (rótulo) y las dos entradas
    assert revisar.escrituras and revisar.escrituras[-1][0] == "F2"


def test_un_nombre_marcado_cliente_deja_de_avisarse():
    revisar = HojaFalsa(h.PESTANA_REVISAR, {"A2:F": [["REPOSICION", 2, 10, "motivo", "CLIENTE", ""]]})
    nuevos, agregados, pendientes = h.actualizar_revisar_nombres(LibroFalso(indice(), revisar), [(10, "REPOSICION"), (12, "REPOSICION")])
    assert (nuevos, agregados, pendientes) == (0, 0, 0)
    assert revisar.escrituras == []


def test_el_patron_de_la_celda_manda_sobre_el_de_omision():
    idx = indice(patron="^(MI CUENTA)( |$)")
    assert h.leer_patron(LibroFalso(idx)).search("MI CUENTA 2")
    assert not h.leer_patron(LibroFalso(idx)).search("TALLER")


def test_dry_run_no_escribe_en_revisar_nombres():
    revisar = HojaFalsa(h.PESTANA_REVISAR)
    idx = indice()
    h.actualizar_revisar_nombres(LibroFalso(idx, revisar), [(10, "REPOSICION")], dry_run=True)
    assert revisar.escrituras == [] and idx.escrituras == []
