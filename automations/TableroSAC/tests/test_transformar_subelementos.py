"""Pruebas de la limpieza y el aplanado de subelementos en filas."""
import pytest

from datos_sac import cv
from datos_subelementos import ESQUEMA_SUB, datos_esquema, subelemento, ticket
from sac_sync.config import esquema_desde_dict
from sac_sync.transformar import a_serial_duracion, a_serial_fecha, filas_subelementos_desde_items

TABLA = ESQUEMA_SUB.subelementos


def test_una_fila_por_subelemento_en_el_orden_de_monday():
    """Los subelementos se aplanan ticket por ticket, sin reordenar, y un ticket sin subelementos no aporta filas."""
    items = [ticket(100, subelementos=[subelemento(7001), subelemento(7002)]),
             ticket(101, subelementos=[subelemento(7003)]),
             ticket(102, subelementos=[])]
    filas, resumen = filas_subelementos_desde_items(items, TABLA)
    assert [f[3] for f in filas] == [7001, 7002, 7003]
    assert [f[0] for f in filas] == [100, 100, 101]
    assert resumen.filas == 3


def test_los_datos_del_ticket_viajan_a_cada_fila():
    """Folio, nombre del ticket y Placa salen del padre; el ID y el nombre, del subelemento."""
    items = [ticket(100, nombre="Ticket A", placa="P-100", subelementos=[subelemento(7001, nombre="Cotizacion")])]
    fila = filas_subelementos_desde_items(items, TABLA)[0][0]
    assert fila[:5] == [100, "Ticket A", "P-100", 7001, "Cotizacion"]
    assert isinstance(fila[0], int) and isinstance(fila[3], int)


def test_los_tipos_de_las_columnas_del_subelemento():
    """Texto, relación vacía, número, fecha con hora, duración y fórmula numérica, cada una con su tipo."""
    sub = subelemento(7001, encargado="persona@ejemplo.test", area="Operaciones", relacion="Actividad X",
                      horas_sla="24", fecha="2026-10-07 09:00", cronometro="60:45:59", horas="60.7663888889")
    fila = filas_subelementos_desde_items([ticket(100, subelementos=[sub])], TABLA)[0][0]
    assert fila[5:] == ["persona@ejemplo.test", "Operaciones", "Actividad X", 24,
                        pytest.approx(a_serial_fecha("2026-10-07 09:00")),
                        pytest.approx(a_serial_duracion("60:45:59")), pytest.approx(60.7663888889)]


def test_columnas_vacias_quedan_en_blanco_y_el_cero_se_conserva():
    """Una relación, un espejo o una fecha vacíos son celdas en blanco; una fórmula en 0 es el número 0."""
    fila = filas_subelementos_desde_items([ticket(100, subelementos=[subelemento(7001)])], TABLA)[0][0]
    assert fila[5] is None and fila[7] is None and fila[8] is None and fila[9] is None
    assert fila[11] == 0 and isinstance(fila[11], int)


def test_el_null_de_una_formula_vacia_queda_en_blanco():
    """Una fórmula que monday devuelve como "null" es una celda en blanco."""
    fila = filas_subelementos_desde_items([ticket(100, subelementos=[subelemento(7001, horas="null")])], TABLA)[0][0]
    assert fila[11] is None


def test_un_ticket_sin_subelementos_no_genera_filas():
    """La API devuelve una lista vacía para un ticket sin subelementos."""
    filas, resumen = filas_subelementos_desde_items([ticket(100, subelementos=[])], TABLA)
    assert filas == [] and resumen.filas == 0


def test_un_subitems_nulo_se_trata_como_sin_subelementos():
    """La limpieza tolera un valor nulo; es el cliente de monday el que lo rechaza como respuesta incompleta."""
    elemento = ticket(100)
    elemento["subitems"] = None
    assert filas_subelementos_desde_items([elemento], TABLA)[0] == []


def test_placa_ausente_del_ticket_queda_en_blanco_y_se_cuenta():
    """Si monday no devuelve la columna del ticket, cada fila lo cuenta y deja la celda vacía."""
    elemento = ticket(100, subelementos=[subelemento(7001), subelemento(7002)])
    elemento["column_values"] = [c for c in elemento["column_values"] if c["id"] != "placa"]
    filas, resumen = filas_subelementos_desde_items([elemento], TABLA)
    assert [f[2] for f in filas] == [None, None]
    assert resumen.columnas_ausentes["Placa"] == 2


def test_columna_de_subelemento_ausente_se_cuenta():
    """Una columna del subelemento que monday no devolvió queda en blanco y se avisa en el resumen."""
    sub = subelemento(7001)
    sub["column_values"] = [c for c in sub["column_values"] if c["id"] != "s_area"]
    filas, resumen = filas_subelementos_desde_items([ticket(100, subelementos=[sub])], TABLA)
    assert filas[0][6] is None and resumen.columnas_ausentes["Area"] == 1


def test_texto_libre_del_subelemento_se_conserva_tal_cual():
    """Un nombre que empieza con "=" no se interpreta: se escribe como texto."""
    fila = filas_subelementos_desde_items([ticket(100, subelementos=[subelemento(7001, nombre="=SUMA(1,2)")])], TABLA)[0][0]
    assert fila[4] == "=SUMA(1,2)"


def test_los_avisos_no_llevan_valores():
    """Una fecha mal formada se escribe como texto y el aviso cuenta la columna sin copiar el valor."""
    filas, resumen = filas_subelementos_desde_items(
        [ticket(100, subelementos=[subelemento(7001, fecha="ayer por la tarde")])], TABLA)
    assert filas[0][9] == "ayer por la tarde"
    assert resumen.no_reconocidos == {"Fecha limite": 1}
    assert "ayer" not in " ".join(resumen.advertencias())


def test_una_columna_item_id_del_padre_usa_el_id_del_padre():
    """Si el texto de la columna item_id del ticket viene vacío, el respaldo es el ID del ticket, no el del subelemento."""
    esquema = esquema_desde_dict({
        "tablero_id": 1, "grupos": [{"hoja": "A", "grupo_id": "a", "hoja_subelementos": "S"}],
        "columnas": [{"encabezado": "Folio", "columna_id": "folio", "tipo": "numero", "clave": True}],
        "subelementos": {"tablero_id": 2, "columnas": [
            {"encabezado": "Folio", "origen": "padre_id", "tipo": "numero"},
            {"encabezado": "Folio del ticket", "origen": "padre_columna", "columna_id": "folio", "tipo": "numero"},
            {"encabezado": "ID", "origen": "id", "tipo": "numero", "clave": True}]},
    })
    padre = {"id": "500", "name": "T", "column_values": [cv("folio", "item_id", "")],
             "subitems": [{"id": "9", "name": "s", "column_values": []}]}
    assert filas_subelementos_desde_items([padre], esquema.subelementos)[0] == [[500, 500, 9]]


def test_un_subelemento_con_un_id_repetido_se_descarta_y_se_cuenta():
    """El ID es la clave de la pestaña: la primera aparición se conserva y las repeticiones se cuentan."""
    items = [ticket(100, subelementos=[subelemento(7001), subelemento(7002)]),
             ticket(101, subelementos=[subelemento(7001, nombre="repetido")])]
    filas, resumen = filas_subelementos_desde_items(items, TABLA)
    assert [f[3] for f in filas] == [7001, 7002]
    assert resumen.duplicados == 1 and "repetían" in " ".join(resumen.advertencias())


def test_una_columna_del_ticket_que_no_esta_en_su_pestana_llega_a_los_subelementos():
    """El VIN futuro: una columna del ticket pedida sólo para los subelementos se copia a cada fila."""
    datos = datos_esquema()
    datos["subelementos"]["columnas"].insert(3, {"encabezado": "VIN", "origen": "padre_columna", "columna_id": "vin"})
    esquema = esquema_desde_dict(datos)
    elemento = ticket(100, subelementos=[subelemento(7001)])
    elemento["column_values"].append(cv("vin", "text", "VIN-0001"))
    fila = filas_subelementos_desde_items([elemento], esquema.subelementos)[0][0]
    assert fila[:6] == [100, "Ticket", "P-1", "VIN-0001", 7001, "Subelemento"]
