"""Pruebas de la sincronización de un grupo con la pestaña de sus subelementos."""
import logging

from datos_subelementos import ESQUEMA_SUB, GRUPO_A, GRUPO_B, subelemento, ticket
from fakes_sac import FakeHoja, FakeLibro, FakeMondaySub
from sac_sync.monday import ErrorMonday
from sac_sync.sincronizar import sincronizar

TABLA = ESQUEMA_SUB.subelementos
HOJA_T, HOJA_S = GRUPO_A.hoja, GRUPO_A.hoja_subelementos
ESCRITURAS = {"update", "batch_clear", "add_rows"}
CON_PADRE = ESQUEMA_SUB.ids_columnas_con_padre


def viejas(tabla, cantidad):
    """Filas de datos de una corrida anterior: texto en las columnas y un número en la clave."""
    return [[1000 + i if j == tabla.indice_clave else "viejo" for j in range(len(tabla.columnas))]
            for i in range(cantidad)]


def hoja_de(titulo, tabla, filas_viejas=0, row_count=1000):
    """Pestaña con los encabezados de la tabla y filas de datos viejos."""
    return FakeHoja(titulo, row_count=row_count, col_count=len(tabla.columnas),
                    encabezados=tabla.encabezados, filas=viejas(tabla, filas_viejas))


def claves(hoja, tabla):
    """Valores de la columna clave de una pestaña, en orden de fila."""
    columna = tabla.indice_clave + 1
    filas = sorted(r for (r, c) in hoja.celdas if c == columna and r > 1)
    return [hoja.celdas[(r, columna)] for r in filas]


def tickets_de_prueba():
    """Tres tickets: dos con subelementos y uno sin ninguno."""
    return [ticket(100, subelementos=[subelemento(7001), subelemento(7002)]),
            ticket(101, subelementos=[subelemento(7003)]),
            ticket(102)]


def pestanas(filas_viejas_tickets=0, filas_viejas_sub=0):
    """Las pestañas de tickets y de subelementos del grupo A, con sus encabezados."""
    return (hoja_de(HOJA_T, ESQUEMA_SUB, filas_viejas_tickets), hoja_de(HOJA_S, TABLA, filas_viejas_sub))


def test_dos_pestanas_desde_una_sola_lectura_de_monday():
    """Los tickets y sus subelementos salen de la misma lectura, cada uno en su pestaña y en el orden de monday."""
    tickets, subs = pestanas()
    monday = FakeMondaySub({"grupo_a": tickets_de_prueba()})
    r_t, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs]), [GRUPO_A])

    assert (r_t.hoja, r_s.hoja) == (HOJA_T, HOJA_S) and r_t.error is None and r_s.error is None
    assert (r_t.filas_escritas, r_s.filas_escritas) == (3, 3)
    assert claves(tickets, ESQUEMA_SUB) == [100, 101, 102] and claves(subs, TABLA) == [7001, 7002, 7003]
    assert [subs.celdas[(r, 1)] for r in (2, 3, 4)] == [100, 100, 101]
    assert monday.lecturas == [("grupo_a", CON_PADRE, TABLA.ids_columnas)] and monday.validaciones == 1


def test_la_pestana_de_subelementos_se_escribe_primero_y_se_limpia_despues():
    """Las filas nuevas entran antes de borrar las viejas que sobran, y el encabezado no se toca."""
    _, subs = pestanas(filas_viejas_sub=5)
    monday = FakeMondaySub({"grupo_a": [ticket(100, subelementos=[subelemento(7001), subelemento(7002)])]})
    r_t, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([hoja_de(HOJA_T, ESQUEMA_SUB), subs]), [GRUPO_A])

    assert r_s.error is None and r_s.filas_antes == 5 and r_s.filas_escritas == 2
    assert claves(subs, TABLA) == [7001, 7002] and subs.celdas[(1, 1)] == "Folio"
    llamadas = subs.nombres_de_llamadas()
    assert llamadas.index("update") < llamadas.index("batch_clear")


def test_dos_corridas_seguidas_dejan_las_dos_pestanas_igual():
    """Idempotencia: repetir la sincronización no duplica ni cambia nada en ninguna pestaña."""
    tickets, subs = pestanas()
    monday = FakeMondaySub({"grupo_a": tickets_de_prueba()})
    libro = FakeLibro([tickets, subs])
    sincronizar(ESQUEMA_SUB, monday, libro, [GRUPO_A])
    primera = (dict(tickets.celdas), dict(subs.celdas))
    resultados = sincronizar(ESQUEMA_SUB, monday, libro, [GRUPO_A])
    assert (dict(tickets.celdas), dict(subs.celdas)) == primera
    assert [r.filas_escritas for r in resultados] == [3, 3]


def test_un_ticket_que_sale_del_grupo_se_lleva_sus_subelementos():
    """La pestaña de subelementos refleja a monday: sin el ticket en el grupo, sus subelementos desaparecen."""
    tickets, subs = pestanas()
    libro = FakeLibro([tickets, subs])
    sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}), libro, [GRUPO_A])
    solo_el_segundo = FakeMondaySub({"grupo_a": tickets_de_prueba()[1:2]})
    sincronizar(ESQUEMA_SUB, solo_el_segundo, libro, [GRUPO_A])
    assert claves(tickets, ESQUEMA_SUB) == [101] and claves(subs, TABLA) == [7003]


def test_un_subelemento_repetido_se_escribe_una_sola_vez():
    """El ID es la clave: si monday lo entrega dos veces, la pestaña queda con una fila y la verificación cuadra."""
    items = [ticket(100, subelementos=[subelemento(7001)]), ticket(101, subelementos=[subelemento(7001)])]
    tickets, subs = pestanas()
    r_t, r_s = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": items}), FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_s.error is None and r_s.filas_monday == 1 and claves(subs, TABLA) == [7001]


def test_un_grupo_sin_pestana_de_subelementos_no_los_pide():
    """El grupo B no define hoja_subelementos: ni se validan ni se leen subelementos, y no hay resultado extra."""
    hoja_b = hoja_de(GRUPO_B.hoja, ESQUEMA_SUB)
    monday = FakeMondaySub({"grupo_b": [ticket(200, grupo="Pestana B")]})
    resultado, = sincronizar(ESQUEMA_SUB, monday, FakeLibro([hoja_b]), [GRUPO_B])
    assert resultado.error is None and claves(hoja_b, ESQUEMA_SUB) == [200]
    assert monday.lecturas == [("grupo_b", ESQUEMA_SUB.ids_columnas, None)] and monday.validaciones == 0


def test_todas_las_pestanas_salen_en_el_orden_del_esquema():
    """Con los dos grupos hay tres resultados: tickets A, subelementos A y tickets B."""
    tickets, subs = pestanas()
    hoja_b = hoja_de(GRUPO_B.hoja, ESQUEMA_SUB)
    monday = FakeMondaySub({"grupo_a": tickets_de_prueba(), "grupo_b": [ticket(200, grupo="Pestana B")]})
    resultados = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs, hoja_b]), [GRUPO_A, GRUPO_B])
    assert [r.hoja for r in resultados] == [HOJA_T, HOJA_S, GRUPO_B.hoja]
    assert all(r.error is None for r in resultados)


def test_no_toca_las_otras_pestanas():
    """Sólo cambian las pestañas del grupo pedido; las demás quedan intactas y sin llamadas."""
    tickets, subs = pestanas()
    otra = hoja_de(GRUPO_B.hoja, ESQUEMA_SUB, filas_viejas=4)
    antes = dict(otra.celdas)
    sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}), FakeLibro([tickets, subs, otra]), [GRUPO_A])
    assert otra.celdas == antes and otra.llamadas == []


def test_encabezados_distintos_en_subelementos_no_detienen_la_pestana_de_tickets():
    """Una pestaña de subelementos con otros encabezados queda intacta y los tickets se sincronizan igual."""
    tickets = hoja_de(HOJA_T, ESQUEMA_SUB)
    mala = FakeHoja(HOJA_S, encabezados=["otro"] * len(TABLA.columnas), filas=viejas(TABLA, 2))
    r_t, r_s = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}),
                           FakeLibro([tickets, mala]), [GRUPO_A])
    assert r_t.error is None and "encabezados" in r_s.error
    assert not ESCRITURAS & set(mala.nombres_de_llamadas())
    assert claves(tickets, ESQUEMA_SUB) == [100, 101, 102]


def test_encabezados_distintos_en_tickets_no_detienen_la_pestana_de_subelementos():
    """Una pestaña de tickets con otros encabezados queda intacta y los subelementos se sincronizan igual."""
    mala = FakeHoja(HOJA_T, encabezados=["otro"] * len(ESQUEMA_SUB.columnas), filas=viejas(ESQUEMA_SUB, 2))
    subs = hoja_de(HOJA_S, TABLA)
    r_t, r_s = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}),
                           FakeLibro([mala, subs]), [GRUPO_A])
    assert "encabezados" in r_t.error and r_s.error is None
    assert not ESCRITURAS & set(mala.nombres_de_llamadas())
    assert claves(subs, TABLA) == [7001, 7002, 7003]


def test_una_pestana_de_subelementos_que_no_existe_se_informa_y_no_se_crea():
    """Si falta la pestaña, sólo ese resultado queda con error; el script no crea pestañas."""
    tickets = hoja_de(HOJA_T, ESQUEMA_SUB)
    r_t, r_s = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}), FakeLibro([tickets]), [GRUPO_A])
    assert r_t.error is None and "WorksheetNotFound" in r_s.error
    assert claves(tickets, ESQUEMA_SUB) == [100, 101, 102]


def test_dry_run_no_escribe_en_ninguna_de_las_dos_pestanas():
    """En dry-run se lee monday y se revisan las pestañas, pero no hay ninguna llamada de escritura."""
    tickets, subs = pestanas(filas_viejas_tickets=3, filas_viejas_sub=2)
    antes = (dict(tickets.celdas), dict(subs.celdas))
    resultados = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}),
                             FakeLibro([tickets, subs]), [GRUPO_A], dry_run=True)
    assert [r.filas_monday for r in resultados] == [3, 3] and [r.filas_escritas for r in resultados] == [0, 0]
    assert all(r.error is None for r in resultados)
    assert not ESCRITURAS & (set(tickets.nombres_de_llamadas()) | set(subs.nombres_de_llamadas()))
    assert (dict(tickets.celdas), dict(subs.celdas)) == antes


def test_dry_run_sin_libro_solo_lee_monday():
    """Sin credenciales de Google el dry-run termina bien, sólo con los conteos de monday."""
    resultados = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}), None, [GRUPO_A], dry_run=True)
    assert [r.filas_monday for r in resultados] == [3, 3]
    assert all(r.error is None and r.filas_antes is None for r in resultados)


def test_comparar_en_subelementos_registra_conteos_y_nunca_valores(caplog):
    """La comparación de la pestaña de subelementos llega al registro como conteos, sin el contenido de las celdas."""
    secretos = ["NOMBRE-DE-CLIENTE-SECRETO", "persona@ejemplo.test"]
    items = [ticket(100, nombre=secretos[0], subelementos=[subelemento(7001, nombre=secretos[0], encargado=secretos[1])])]
    tickets, subs = pestanas()
    with caplog.at_level(logging.INFO, logger="sac_sync"):
        sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": items}), FakeLibro([tickets, subs]), [GRUPO_A],
                    dry_run=True, comparar_con_hoja=True)
    assert f"[{HOJA_S}] comparación:" in caplog.text
    assert not any(s in caplog.text for s in secretos)


def test_no_vacia_la_pestana_de_subelementos_con_muchos_datos_si_monday_no_trae_ninguno():
    """Sin subelementos de golpe puede ser una lectura fallida: la pestaña no se vacía sin --aceptar-vacio."""
    tickets, subs = pestanas(filas_viejas_sub=50)
    monday = FakeMondaySub({"grupo_a": [ticket(100), ticket(101)]})
    r_t, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_t.error is None and "aceptar-vacio" in r_s.error and "subelementos" in r_s.error
    assert not ESCRITURAS & set(subs.nombres_de_llamadas()) and len(claves(subs, TABLA)) == 50


def test_aceptar_vacio_permite_vaciar_la_pestana_de_subelementos():
    """Con --aceptar-vacio, un grupo realmente sin subelementos deja la pestaña sin datos."""
    tickets, subs = pestanas(filas_viejas_sub=50)
    monday = FakeMondaySub({"grupo_a": [ticket(100), ticket(101)]})
    _, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs]), [GRUPO_A], aceptar_vacio=True)
    assert r_s.error is None and claves(subs, TABLA) == []


def test_si_falla_la_validacion_de_subelementos_los_tickets_se_sincronizan_sin_ellos():
    """Un problema con el tablero o las columnas de subelementos falla sólo su pestaña, que ni se abre."""
    tickets, subs = pestanas(filas_viejas_sub=3)
    monday = FakeMondaySub({"grupo_a": tickets_de_prueba()}, error_validacion=ErrorMonday("el tablero no responde"))
    r_t, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_t.error is None and claves(tickets, ESQUEMA_SUB) == [100, 101, 102]
    assert r_s.error.startswith("ErrorMonday") and subs.llamadas == []
    assert monday.lecturas == [("grupo_a", ESQUEMA_SUB.ids_columnas, None)]


def test_si_falla_la_lectura_con_subelementos_se_reintenta_solo_con_los_tickets():
    """Si monday no devuelve bien los subelementos, los tickets se leen aparte y los subelementos quedan sin tocar."""
    tickets, subs = pestanas(filas_viejas_sub=3)
    monday = FakeMondaySub({"grupo_a": tickets_de_prueba()},
                           error_con_subelementos=ErrorMonday("monday no devolvió los subelementos de un elemento"))
    r_t, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_t.error is None and claves(tickets, ESQUEMA_SUB) == [100, 101, 102]
    assert "subelementos" in r_s.error and subs.llamadas == []
    assert monday.lecturas == [("grupo_a", CON_PADRE, TABLA.ids_columnas), ("grupo_a", ESQUEMA_SUB.ids_columnas, None)]


def test_si_tampoco_se_pueden_leer_los_tickets_las_dos_pestanas_quedan_con_error_y_sin_escribir():
    """Sin lectura de tickets no hay nada que volcar: ninguna de las dos pestañas se toca."""
    tickets, subs = pestanas(filas_viejas_tickets=3, filas_viejas_sub=3)
    monday = FakeMondaySub({"grupo_a": tickets_de_prueba()}, error_con_subelementos=RuntimeError("falló a"),
                           error_sin_subelementos=RuntimeError("falló b"))
    r_t, r_s = sincronizar(ESQUEMA_SUB, monday, FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_t.error.startswith("RuntimeError") and r_s.error.startswith("RuntimeError")
    assert tickets.llamadas == [] and subs.llamadas == []


def test_la_verificacion_final_detecta_subelementos_que_no_quedaron_escritos():
    """Si la pestaña no queda con las filas de monday, ese resultado falla sin afectar al de tickets."""

    class HojaQueSeTragaUnaFila(FakeHoja):
        """Pestaña que descarta la última fila de cada escritura."""

        def update(self, values=None, range_name=None, value_input_option=None):
            """Escribe todas las filas menos la última."""
            super().update(values=values[:-1], range_name=range_name, value_input_option=value_input_option)

    tickets = hoja_de(HOJA_T, ESQUEMA_SUB)
    subs = HojaQueSeTragaUnaFila(HOJA_S, encabezados=TABLA.encabezados)
    r_t, r_s = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": tickets_de_prueba()}), FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_t.error is None and "verificación" in r_s.error


def test_amplia_la_pestana_de_subelementos_si_no_alcanza_la_capacidad():
    """Con más subelementos que filas de capacidad, agrega filas antes de escribir y deja todo."""
    tickets = hoja_de(HOJA_T, ESQUEMA_SUB)
    subs = hoja_de(HOJA_S, TABLA, row_count=5)
    items = [ticket(100, subelementos=[subelemento(7000 + i) for i in range(30)])]
    _, r_s = sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": items}), FakeLibro([tickets, subs]), [GRUPO_A])
    assert r_s.error is None and r_s.filas_agregadas > 0 and subs.row_count >= 31
    assert len(claves(subs, TABLA)) == 30
    llamadas = subs.nombres_de_llamadas()
    assert llamadas.index("add_rows") < llamadas.index("update")


def test_el_registro_de_subelementos_solo_lleva_conteos(caplog):
    """Nada de lo escrito en el registro contiene datos de los tickets ni de sus subelementos."""
    secretos = ["NOMBRE-SECRETO", "persona@ejemplo.test", "COTIZACION-SECRETA"]
    items = [ticket(100, nombre=secretos[0], subelementos=[subelemento(7001, nombre=secretos[2], encargado=secretos[1])])]
    tickets, subs = pestanas()
    with caplog.at_level(logging.INFO, logger="sac_sync"):
        sincronizar(ESQUEMA_SUB, FakeMondaySub({"grupo_a": items}), FakeLibro([tickets, subs]), [GRUPO_A])
    assert f"[{HOJA_S}] monday: 1 subelementos" in caplog.text and f"[{HOJA_S}] escritas 1 filas" in caplog.text
    assert not any(s in caplog.text for s in secretos)
