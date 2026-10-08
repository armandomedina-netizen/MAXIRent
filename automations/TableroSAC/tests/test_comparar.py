"""Pruebas de la comparación entre las filas de monday y las de la pestaña."""
from datos_sac import ESQUEMA, INDICE_FOLIO
from sac_sync.comparar import comparar, formatear_comparacion
from sac_sync.config import esquema_desde_dict


def fila(folio, nombre="n", estado="Atendido", **cambios):
    """Una fila de 11 columnas del esquema de pruebas; `cambios` reemplaza celdas por su posición (c0, c2...)."""
    celdas = [nombre, estado, "0123", folio, 0.5, "https://x.test", 46301.5, None, 0.25, None, "Pestana A"]
    for clave, valor in cambios.items():
        celdas[int(clave[1:])] = valor
    return celdas


def test_filas_iguales_coinciden():
    """Sin diferencias, la comparación coincide y las filas no tienen pareja pendiente."""
    r = comparar([fila(1), fila(2)], [fila(1), fila(2)], ESQUEMA)
    assert r.coincide and r.comunes == 2 and r.mismo_orden


def test_celdas_vacias_y_none_son_la_misma_celda():
    """Una celda en blanco de la hoja ("") equivale al None de monday."""
    r = comparar([fila(1, c7=None)], [fila(1, c7="")], ESQUEMA)
    assert r.coincide


def test_cuenta_las_celdas_distintas_por_columna_con_su_fila_de_ejemplo():
    """Reporta cuántas celdas difieren en cada columna y en qué filas de la pestaña (la 2 es la primera de datos)."""
    r = comparar([fila(1), fila(2, estado="Resuelto")], [fila(1), fila(2)], ESQUEMA)
    assert list(r.diferencias) == ["Estado"]
    assert r.diferencias["Estado"].valor == 1
    assert r.diferencias["Estado"].filas == [3]
    assert not r.coincide


def test_numeros_se_comparan_con_tolerancia_de_punto_flotante():
    """Dos números que difieren en el último decimal son iguales; los que difieren de verdad no."""
    assert comparar([fila(1, c6=46301.60277777778)], [fila(1, c6=46301.602777777776)], ESQUEMA).coincide
    assert not comparar([fila(1, c6=46301.5)], [fila(1, c6=46301.6)], ESQUEMA).coincide


def test_mismo_contenido_con_distinto_tipo_se_cuenta_aparte():
    """El texto "123" contra el número 123 es una diferencia de tipo, no de valor."""
    r = comparar([fila(1, c2="123")], [fila(1, c2=123)], ESQUEMA)
    assert r.diferencias["Telefono"].tipo == 1 and r.diferencias["Telefono"].valor == 0


def test_filas_sin_pareja_en_cada_lado():
    """Las filas se emparejan por la columna clave; las que sobran de cada lado se cuentan."""
    r = comparar([fila(1), fila(2), fila(3)], [fila(2), fila(9)], ESQUEMA)
    assert (r.comunes, r.solo_monday, r.solo_hoja) == (1, 2, 1)


def test_el_orden_distinto_se_detecta():
    """Con las mismas filas en otro orden, la comparación lo marca."""
    r = comparar([fila(1), fila(2)], [fila(2), fila(1)], ESQUEMA)
    assert r.coincide and r.mismo_orden is False


def test_claves_repetidas_en_la_pestana_no_cuentan_como_filas_sin_pareja():
    """Una fila repetida de la pestaña se informa aparte y no se empareja dos veces."""
    r = comparar([fila(1)], [fila(1), fila(1)], ESQUEMA)
    assert r.claves_repetidas == 1 and r.solo_hoja == 0 and r.comunes == 1


def test_filas_completamente_vacias_de_la_pestana_se_ignoran():
    """Las filas en blanco entre datos no cuentan como filas de la pestaña."""
    r = comparar([fila(1)], [[None] * 11, fila(1)], ESQUEMA)
    assert r.filas_hoja == 1 and r.solo_hoja == 0


def test_sin_columna_clave_se_compara_por_posicion():
    """Si el esquema no tiene clave, la fila N de monday se compara con la fila N de la pestaña."""
    sin_clave = esquema_desde_dict({
        "tablero_id": 1, "grupos": [{"hoja": "H", "grupo_id": "g"}],
        "columnas": [{"encabezado": "A", "columna_id": "a"}, {"encabezado": "B", "columna_id": "b"}],
    })
    r = comparar([["x", "1"], ["y", "2"]], [["x", "1"], ["z", "2"]], sin_clave)
    assert r.comunes == 2 and r.diferencias["A"].valor == 1 and r.diferencias["A"].filas == [3]


def test_el_informe_no_contiene_valores_de_las_celdas():
    """Las líneas del registro llevan conteos y encabezados, nunca el contenido de una celda."""
    secreto = "NOMBRE-DE-CLIENTE-SECRETO"
    r = comparar([fila(1, nombre=secreto)], [fila(1, nombre="otro")], ESQUEMA)
    texto = "\n".join(formatear_comparacion(r))
    assert secreto not in texto and "otro" not in texto
    assert "columna 'Nombre': 1 celdas distintas" in texto


def test_el_informe_de_filas_iguales_lo_dice():
    """Sin diferencias, el informe lo indica en una línea."""
    texto = "\n".join(formatear_comparacion(comparar([fila(1)], [fila(1)], ESQUEMA)))
    assert "coinciden en todas las columnas" in texto and "mismo orden: sí" in texto


def test_la_clave_del_esquema_de_pruebas_es_el_folio():
    """Las pruebas de alineación dependen de que la clave sea la cuarta columna."""
    assert ESQUEMA.indice_clave == INDICE_FOLIO
