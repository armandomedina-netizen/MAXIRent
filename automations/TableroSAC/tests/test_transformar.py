"""Pruebas del mapeo de columnas y de la limpieza de valores."""
import pytest

from datos_sac import ESQUEMA, cv, item, item_completo
from sac_sync.transformar import (MAX_CARACTERES_CELDA, ResumenLimpieza, a_numero, a_serial_duracion,
                                  a_serial_fecha, fila_desde_item, filas_desde_items, valor_crudo)


@pytest.mark.parametrize("texto, esperado", [
    ("98765432101", 98765432101),
    ("7", 7),
    ("-3", -3),
    ("0.0006944444", 0.0006944444),
    (" 12.5 ", 12.5),
    ("1,234.5", 1234.5),
    ("5.", 5.0),
])
def test_a_numero_convierte_enteros_y_decimales(texto, esperado):
    """Los enteros salen como int y los decimales como float."""
    resultado = a_numero(texto)
    assert resultado == esperado
    assert isinstance(resultado, int) == ("." not in texto and "," not in texto)


@pytest.mark.parametrize("texto", ["", "abc", "12abc", "1e5", "--3", "null", "1.2.3", "9" * 20])
def test_a_numero_rechaza_lo_que_no_es_un_numero_exacto(texto):
    """Un entero mayor que 2**53 perdería dígitos en Sheets, así que tampoco se convierte."""
    assert a_numero(texto) is None


def test_a_serial_fecha_coincide_con_lo_que_sheets_guardo():
    """Valores observados en las filas ya cargadas: la misma hora local que trae monday."""
    assert a_serial_fecha("2026-10-06 14:28") == pytest.approx(46301.60277777778)
    assert a_serial_fecha("2026-10-06 12:44") == pytest.approx(46301.53055555555)
    assert a_serial_fecha("2026-10-06 14:29") == pytest.approx(46301.603472222225)


def test_a_serial_fecha_sin_hora_es_un_entero():
    """Una fecha sin hora es el día entero, sin fracción."""
    assert a_serial_fecha("2026-10-06") == 46301
    assert isinstance(a_serial_fecha("2026-10-06"), int)


def test_a_serial_fecha_usa_la_epoca_de_sheets():
    """El día cero es 1899-12-30."""
    assert a_serial_fecha("1899-12-30") == 0
    assert a_serial_fecha("1900-01-01") == 2


@pytest.mark.parametrize("texto", ["", "2026-13-40", "2026-10-06 25:00", "06/10/2026", "2026-10-06 14", "hoy"])
def test_a_serial_fecha_rechaza_fechas_invalidas(texto):
    """Lo que no es una fecha válida no se convierte."""
    assert a_serial_fecha(texto) is None


def test_a_serial_fecha_acepta_segundos_y_separador_t():
    """La hora puede traer segundos y la fecha puede separarse con T."""
    assert a_serial_fecha("2026-10-06T14:28:30") == pytest.approx(46301 + (14 * 3600 + 28 * 60 + 30) / 86400)


def test_a_serial_duracion_coincide_con_lo_que_sheets_guardo():
    """Valores observados en las filas ya cargadas: la duración es la fracción de día."""
    assert a_serial_duracion("2:08:47") == pytest.approx(0.08943287037037037)
    assert a_serial_duracion("3:52:49") == pytest.approx(0.16167824074074075)


def test_a_serial_duracion_admite_horas_sin_tope():
    """Las horas pueden pasar de 24 y de 99."""
    assert a_serial_duracion("677:41:17") == pytest.approx(2439677 / 86400)
    assert a_serial_duracion("0:00:00") == 0


@pytest.mark.parametrize("texto", ["", "12:30", "1:75:00", "1:00:00, 2:00:00", "abc"])
def test_a_serial_duracion_rechaza_lo_que_no_es_una_duracion(texto):
    """Varios valores, minutos o segundos fuera de rango y texto libre no se convierten."""
    assert a_serial_duracion(texto) is None


def test_valor_crudo_usa_display_value_en_reflejos_relaciones_formulas_y_subelementos():
    """Esos cuatro tipos se leen de display_value aunque text venga vacío o nulo."""
    for tipo in ("mirror", "board_relation", "formula", "subtasks"):
        assert valor_crudo(cv("x", tipo, text=None, dv="valor")) == valor_crudo(cv("x", tipo, text="", dv="valor")) == "valor"


def test_valor_crudo_usa_text_en_el_resto_de_los_tipos():
    """Los demás tipos se leen de text."""
    assert valor_crudo(cv("x", "status", "Atendido")) == "Atendido"
    assert valor_crudo(cv("x", "dropdown", None)) is None


def test_valor_crudo_trata_el_texto_null_de_las_formulas_como_vacio():
    """monday devuelve "null" en las fórmulas vacías."""
    assert valor_crudo(cv("x", "formula", "", dv="null")) is None


def test_valor_crudo_conserva_null_si_viene_en_un_texto_normal():
    """Sólo el display_value se interpreta; un texto escrito por una persona se copia tal cual."""
    assert valor_crudo(cv("x", "text", "null")) == "null"


def test_fila_respeta_el_orden_del_esquema_y_los_tipos():
    """Una celda por columna, en orden, con números, fechas y duraciones tipados y el resto como texto."""
    fila = fila_desde_item(item_completo(5001, nombre="Elemento de prueba", grupo="Pestana A"), ESQUEMA, ResumenLimpieza())
    assert fila == [
        "Elemento de prueba", "Atendido", "0123456789", 5001, 0.5, "https://ejemplo.test/x",
        pytest.approx(46301.60277777778), None, pytest.approx(0.08943287037037037), None, "Pestana A",
    ]
    assert len(fila) == len(ESQUEMA.columnas)


def test_telefono_con_ceros_y_numerico_se_conserva_como_texto():
    """Una columna de texto nunca se convierte en número, así que no pierde los ceros."""
    fila = fila_desde_item(item_completo(1, telefono="0012345"), ESQUEMA, ResumenLimpieza())
    assert fila[2] == "0012345"
    assert isinstance(fila[2], str)


@pytest.mark.parametrize("texto", ["=SUMA(1,2)", "+52 81 1234 5678", "-sin acento", "10/10", "TRUE", "'comilla"])
def test_texto_libre_que_sheets_reinterpretaria_se_copia_tal_cual(texto):
    """Los textos que parecen fórmula, número, fecha o booleano llegan idénticos."""
    fila = fila_desde_item(item_completo(1, estado=texto), ESQUEMA, ResumenLimpieza())
    assert fila[1] == texto


def test_formula_vacia_con_null_queda_en_blanco():
    """El "null" de una fórmula numérica vacía es una celda en blanco, no el texto."""
    it = item_completo(1)
    for columna in it["column_values"]:
        if columna["id"] == "dias":
            columna["display_value"] = "null"
    resumen = ResumenLimpieza()
    assert fila_desde_item(it, ESQUEMA, resumen)[4] is None
    assert not resumen.no_reconocidos


def test_folio_cae_al_id_del_elemento_si_el_texto_viene_vacio():
    """La columna de tipo item_id se respalda con el ID del elemento."""
    it = item_completo(777)
    for columna in it["column_values"]:
        if columna["id"] == "folio":
            columna["text"] = ""
    assert fila_desde_item(it, ESQUEMA, ResumenLimpieza())[3] == 777


def test_duracion_con_varios_valores_queda_como_texto_sin_contarse_como_error():
    """Varias duraciones separadas por coma se escriben como texto y no generan aviso."""
    it = item_completo(1)
    for columna in it["column_values"]:
        if columna["id"] == "areas":
            columna["display_value"] = "1:00:00, 2:30:00"
    resumen = ResumenLimpieza()
    assert fila_desde_item(it, ESQUEMA, resumen)[9] == "1:00:00, 2:30:00"
    assert not resumen.no_reconocidos


def test_valor_que_no_cuadra_con_su_tipo_se_conserva_y_se_cuenta():
    """Una fecha mal formada se escribe como texto y queda registrada en el resumen, sin su valor."""
    resumen = ResumenLimpieza()
    fila = fila_desde_item(item_completo(1, registro="ayer por la tarde"), ESQUEMA, resumen)
    assert fila[6] == "ayer por la tarde"
    assert resumen.no_reconocidos == {"Registro": 1}
    assert "ayer" not in " ".join(resumen.advertencias())


def test_columna_ausente_en_la_respuesta_queda_en_blanco_y_se_cuenta():
    """Si monday no devuelve una columna, la celda queda vacía y el resumen lo avisa."""
    it = item("1", "Elemento", "Pestana A", [cv("folio", "item_id", "1")])
    resumen = ResumenLimpieza()
    fila = fila_desde_item(it, ESQUEMA, resumen)
    assert fila[1] is None and fila[3] == 1
    assert resumen.columnas_ausentes["Estado"] == 1


def test_celda_demasiado_larga_se_recorta():
    """Google Sheets no admite más de 50,000 caracteres por celda."""
    resumen = ResumenLimpieza()
    fila = fila_desde_item(item_completo(1, estado="x" * (MAX_CARACTERES_CELDA + 10)), ESQUEMA, resumen)
    assert len(fila[1]) == MAX_CARACTERES_CELDA
    assert resumen.celdas_acotadas == 1


def test_filas_desde_items_cuenta_las_filas_y_conserva_el_orden():
    """Devuelve una fila por elemento, en el orden recibido."""
    filas, resumen = filas_desde_items([item_completo(3), item_completo(1), item_completo(2)], ESQUEMA)
    assert [f[3] for f in filas] == [3, 1, 2]
    assert resumen.filas == 3
