"""Pruebas de la orquestación: escritura idempotente, dry-run y protecciones."""
import logging

from datos_sac import ESQUEMA, INDICE_FOLIO, fila_vieja, item_completo
from fakes_sac import FakeHoja, FakeLibro, FakeMonday
from sac_sync.sincronizar import sincronizar

GRUPO_A, GRUPO_B = ESQUEMA.grupos
ESCRITURAS = {"update", "batch_clear", "add_rows"}


def hoja_con(titulo, filas_viejas=0, row_count=1000):
    """Pestaña con los encabezados del esquema y filas de datos viejos."""
    return FakeHoja(titulo, row_count=row_count, encabezados=ESQUEMA.encabezados,
                    filas=[fila_vieja(i) for i in range(filas_viejas)])


def folios(hoja):
    """Folios (columna clave) que tiene la pestaña, en orden de fila."""
    filas = sorted(r for (r, c) in hoja.celdas if c == INDICE_FOLIO + 1 and r > 1)
    return [hoja.celdas[(r, INDICE_FOLIO + 1)] for r in filas]


def test_escribe_primero_y_limpia_despues_lo_que_sobra():
    """La pestaña se llena con las filas nuevas y sólo después se borran las viejas que sobran."""
    hoja = hoja_con(GRUPO_A.hoja, filas_viejas=5)
    monday = FakeMonday({"grupo_a": [item_completo(1), item_completo(2)]})
    resultado, = sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A])

    assert resultado.error is None and resultado.filas_escritas == 2 and resultado.filas_antes == 5
    assert folios(hoja) == [1, 2]
    assert hoja.nombres_de_llamadas().index("update") < hoja.nombres_de_llamadas().index("batch_clear")
    assert hoja.celdas[(1, 1)] == "Nombre"


def test_dos_corridas_seguidas_dejan_la_pestana_igual():
    """Idempotencia: repetir la sincronización no duplica ni cambia nada."""
    hoja = hoja_con(GRUPO_A.hoja)
    monday = FakeMonday({"grupo_a": [item_completo(1), item_completo(2), item_completo(3)]})
    sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A])
    primera = dict(hoja.celdas)
    resultado, = sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A])
    assert resultado.filas_escritas == 3 and hoja.celdas == primera


def test_no_toca_encabezados_ni_otras_pestanas():
    """Sólo cambia la pestaña pedida, de la fila 2 en adelante."""
    pedida, otra = hoja_con(GRUPO_A.hoja, 3), hoja_con(GRUPO_B.hoja, 4)
    antes_otra = dict(otra.celdas)
    sincronizar(ESQUEMA, FakeMonday({"grupo_a": [item_completo(1)]}), FakeLibro([pedida, otra]), [GRUPO_A])
    assert otra.celdas == antes_otra and otra.llamadas.count(("update",)) == 0
    assert [pedida.celdas[(1, c)] for c in range(1, 12)] == ESQUEMA.encabezados


def test_dry_run_no_escribe_nada():
    """En dry-run se lee monday y se revisa la pestaña, pero no hay ninguna llamada de escritura."""
    hoja = hoja_con(GRUPO_A.hoja, filas_viejas=3)
    antes = dict(hoja.celdas)
    monday = FakeMonday({"grupo_a": [item_completo(1), item_completo(2)]})
    resultado, = sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A], dry_run=True)
    assert resultado.error is None and resultado.filas_monday == 2 and resultado.filas_escritas == 0
    assert not ESCRITURAS & set(hoja.nombres_de_llamadas())
    assert hoja.spreadsheet.solicitudes == [] and hoja.celdas == antes


def test_dry_run_sin_libro_solo_lee_monday():
    """Sin credenciales de Google el dry-run termina bien, sólo con el conteo de monday."""
    monday = FakeMonday({"grupo_a": [item_completo(1)]})
    resultado, = sincronizar(ESQUEMA, monday, None, [GRUPO_A], dry_run=True)
    assert resultado.error is None and resultado.filas_monday == 1 and resultado.filas_antes is None


def test_comparar_registra_conteos_y_nunca_valores(caplog):
    """La comparación llega al registro como conteos por columna, sin el contenido de las celdas."""
    hoja = hoja_con(GRUPO_A.hoja)
    secreto = "NOMBRE-DE-CLIENTE-SECRETO"
    monday = FakeMonday({"grupo_a": [item_completo(1, nombre=secreto)]})
    with caplog.at_level(logging.INFO, logger="sac_sync"):
        sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A], dry_run=True, comparar_con_hoja=True)
    assert "comparación:" in caplog.text and secreto not in caplog.text


def test_encabezados_distintos_no_escriben_y_no_detienen_a_las_demas_pestanas():
    """Una pestaña con encabezados que no son los del esquema queda intacta y se sigue con la siguiente."""
    mala = FakeHoja(GRUPO_A.hoja, encabezados=["otro"] * 11, filas=[fila_vieja(0)])
    buena = hoja_con(GRUPO_B.hoja)
    monday = FakeMonday({"grupo_a": [item_completo(1)], "grupo_b": [item_completo(2)]})
    resultados = sincronizar(ESQUEMA, monday, FakeLibro([mala, buena]), [GRUPO_A, GRUPO_B])

    assert "encabezados" in resultados[0].error and resultados[1].error is None
    assert not ESCRITURAS & set(mala.nombres_de_llamadas())
    assert folios(buena) == [2]


def test_pestana_que_no_existe_es_un_error_y_no_se_crea():
    """Si falta la pestaña se informa; el script no crea pestañas."""
    libro = FakeLibro([])
    resultado, = sincronizar(ESQUEMA, FakeMonday({"grupo_a": []}), libro, [GRUPO_A])
    assert resultado.error is not None and "WorksheetNotFound" in resultado.error


def test_no_vacia_una_pestana_con_muchos_datos_si_monday_devuelve_cero():
    """Un grupo que llega vacío de golpe puede ser una lectura fallida: se detiene la escritura."""
    hoja = hoja_con(GRUPO_A.hoja, filas_viejas=50)
    resultado, = sincronizar(ESQUEMA, FakeMonday({"grupo_a": []}), FakeLibro([hoja]), [GRUPO_A])
    assert "aceptar-vacio" in resultado.error
    assert not ESCRITURAS & set(hoja.nombres_de_llamadas()) and len(folios(hoja)) == 50


def test_aceptar_vacio_permite_vaciar_la_pestana():
    """Con --aceptar-vacio, un grupo realmente vacío deja la pestaña sin datos."""
    hoja = hoja_con(GRUPO_A.hoja, filas_viejas=50)
    resultado, = sincronizar(ESQUEMA, FakeMonday({"grupo_a": []}), FakeLibro([hoja]), [GRUPO_A], aceptar_vacio=True)
    assert resultado.error is None and folios(hoja) == []


def test_un_grupo_vacio_con_pocos_datos_se_vacia_sin_pedir_permiso():
    """Los grupos que se vacían con normalidad (pocas filas) no necesitan la opción."""
    hoja = hoja_con(GRUPO_A.hoja, filas_viejas=3)
    resultado, = sincronizar(ESQUEMA, FakeMonday({"grupo_a": []}), FakeLibro([hoja]), [GRUPO_A])
    assert resultado.error is None and folios(hoja) == []


def test_amplia_la_pestana_si_no_alcanza_la_capacidad():
    """Con más elementos que filas de capacidad, agrega filas y escribe todo."""
    hoja = hoja_con(GRUPO_A.hoja, row_count=50)
    monday = FakeMonday({"grupo_a": [item_completo(i) for i in range(1, 121)]})
    resultado, = sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A])
    assert resultado.error is None and resultado.filas_agregadas > 0
    assert hoja.row_count >= 121 and len(folios(hoja)) == 120
    assert hoja.nombres_de_llamadas().index("add_rows") < hoja.nombres_de_llamadas().index("update")


def test_la_verificacion_final_detecta_filas_que_no_quedaron_escritas():
    """Si la pestaña no queda con las filas de monday (por ejemplo, una celda combinada que se traga la escritura), falla."""

    class HojaQueSeTragaUnaFila(FakeHoja):
        """Pestaña que descarta la última fila de cada escritura."""

        def update(self, values=None, range_name=None, value_input_option=None):
            """Escribe todas las filas menos la última."""
            super().update(values=values[:-1], range_name=range_name, value_input_option=value_input_option)

    hoja = HojaQueSeTragaUnaFila(GRUPO_A.hoja, encabezados=ESQUEMA.encabezados)
    monday = FakeMonday({"grupo_a": [item_completo(1), item_completo(2), item_completo(3)]})
    resultado, = sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A])
    assert "verificación" in resultado.error


def test_los_errores_de_monday_se_registran_y_se_sigue_con_la_siguiente_pestana():
    """Un fallo al leer un grupo no impide sincronizar los demás."""

    class MondayQueFallaEnA(FakeMonday):
        """Lanza un error al leer el primer grupo."""

        def leer_grupo(self, grupo_id, ids_columnas):
            """Falla en el grupo A y responde normal en los demás."""
            if grupo_id == "grupo_a":
                raise RuntimeError("monday no respondió")
            return super().leer_grupo(grupo_id, ids_columnas)

    buena = hoja_con(GRUPO_B.hoja)
    resultados = sincronizar(ESQUEMA, MondayQueFallaEnA({"grupo_b": [item_completo(7)]}),
                             FakeLibro([hoja_con(GRUPO_A.hoja), buena]), [GRUPO_A, GRUPO_B])
    assert resultados[0].error.startswith("RuntimeError") and resultados[1].error is None
    assert folios(buena) == [7]


def test_el_registro_solo_lleva_conteos(caplog):
    """Nada de lo escrito en el registro contiene datos de los elementos."""
    hoja = hoja_con(GRUPO_A.hoja)
    secretos = ["NOMBRE-SECRETO", "0123456789", "https://ejemplo.test/x"]
    monday = FakeMonday({"grupo_a": [item_completo(1, nombre=secretos[0], telefono=secretos[1])]})
    with caplog.at_level(logging.INFO, logger="sac_sync"):
        sincronizar(ESQUEMA, monday, FakeLibro([hoja]), [GRUPO_A])
    assert "escritas 1 filas" in caplog.text
    assert not any(s in caplog.text for s in secretos)
