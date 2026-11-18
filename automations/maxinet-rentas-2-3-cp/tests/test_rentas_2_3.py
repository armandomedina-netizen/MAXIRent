import datetime as dt
import logging

import gspread
import pytest

import maxinet_rentas_2_3_cp as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_maxinet

I = m.IDX


def serie(texto):
    return m._serie(texto, "x")


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for v in ("FECHA_DESDE", "FECHA_HASTA", "DRY_RUN", "FORZAR", "WORKSHEET_RENTAS_2_3_NAME"):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------- estructura
def test_hay_18_columnas_y_la_hoja_termina_en_R():
    assert len(m.COLUMNAS) == 18 and m.ULTIMA_COL == "R"
    assert m.COLUMNAS[0] == "No. Cliente" and m.COLUMNAS[3] == "No.Evento" and m.COLUMNAS[-1] == "Email"
    assert (I["Fecha 2da renta"], I["Fecha 3ra renta"]) == (7, 10)


# ---------------------------------------------------------------- tipos
def test_fecha_a_numero_de_serie():
    assert m._serie("2026-11-03", "x") == float((dt.date(2026, 11, 3) - m.BASE_SERIAL).days)


def test_una_fecha_con_otra_forma_detiene_la_corrida_sin_citar_el_valor():
    with pytest.raises(RuntimeError) as e:
        m._serie("03/11/2026", "Fecha 2da renta")
    assert "Fecha 2da renta" in str(e.value) and "03/11" not in str(e.value)


def test_telefonos_numero_si_son_digitos_y_texto_si_no():
    assert m._telefono("8115169750") == 8115169750 and isinstance(m._telefono("8115169750"), int)
    assert m._telefono("0123456789") == "0123456789"
    assert m._telefono("81-1516-9750") == "81-1516-9750"
    assert m._telefono("1234567890123456") == "1234567890123456"          # más de 15 dígitos


def test_los_enteros_invalidos_detienen_la_corrida():
    with pytest.raises(RuntimeError):
        m._entero("dos", "No.Rentas")


# ---------------------------------------------------------------- normalizar
def test_normaliza_tipos_y_recorta_espacios():
    f = m.normalizar_filas([fila_maxinet(" #1 ", 3, "2026-04-02", "2026-11-14", Email=" A@B.COM ", TelNo="", MobileNo="2222011202")])[0]
    assert len(f) == 18
    assert f[I["No. Cliente"]] == "#1" and f[I["Email"]] == "A@B.COM"
    assert f[I["No.Rentas"]] == 3 and f[I["No.Evento"]] == 3
    assert f[I["Fecha 3ra renta"]] == serie("2026-11-14") and f[I["Fecha 1ra renta"]] == serie("2025-03-15")
    assert f[I["MobileNo"]] == 2222011202 and f[I["TelNo"]] == ""


def test_la_fecha_vacia_queda_vacia():
    f = m.normalizar_filas([fila_maxinet("#1", 2, "2026-11-03", "")])[0]
    assert f[I["Fecha 3ra renta"]] == ""


def test_ordena_por_fecha_del_evento_evento_y_cliente():
    filas = m.normalizar_filas([
        fila_maxinet("#9", 3, "2025-01-01", "2026-11-05"),      # evento 3: cuenta con su fecha 3ra
        fila_maxinet("#2", 2, "2026-11-04"),
        fila_maxinet("#1", 2, "2026-11-05"),
        fila_maxinet("#1", 3, "2026-11-05", "2026-11-05"),
    ])
    assert [(f[I["No. Cliente"]], f[I["No.Evento"]]) for f in filas] == [("#2", 2), ("#1", 2), ("#1", 3), ("#9", 3)]


def test_un_mismo_cliente_puede_salir_con_evento_2_y_3():
    filas = m.normalizar_filas([fila_maxinet("#1", 2, "2026-11-10"), fila_maxinet("#1", 3, "2026-11-10", "2026-11-11")])
    assert len(filas) == 2


def test_quita_eventos_repetidos(caplog):
    with caplog.at_level(logging.WARNING):
        filas = m.normalizar_filas([fila_maxinet("#1", 2, "2026-11-10"), fila_maxinet("#1", 2, "2026-11-10")])
    assert len(filas) == 1 and "repitió 1 eventos" in caplog.text


def test_un_ancho_distinto_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_maxinet("#1", 2, "2026-11-10") + ["nueva"]])


def test_un_evento_distinto_de_2_y_3_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="No.Evento"):
        m.normalizar_filas([fila_maxinet("#1", 4, "2026-11-10")])


def test_un_evento_sin_su_fecha_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="sin la fecha"):
        m.normalizar_filas([fila_maxinet("#1", 3, "2026-04-02", "")])


def test_sin_filas_devuelve_lista_vacia():
    assert m.normalizar_filas([]) == []


# ---------------------------------------------------------------- bloques de fechas
def _fijar_hoy(monkeypatch, fecha):
    class FalsoDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime.combine(fecha, dt.time(8, 30), tzinfo=tz)
    monkeypatch.setattr(m.dt, "datetime", FalsoDT)


def test_bloque_normal_del_primero_de_mes_a_ayer(monkeypatch):
    _fijar_hoy(monkeypatch, dt.date(2026, 11, 18))
    assert m.bloques_a_refrescar() == [("2026-11-01", "2026-11-17")]


def test_primeros_tres_dias_incluyen_el_mes_anterior(monkeypatch):
    _fijar_hoy(monkeypatch, dt.date(2026, 11, 4))                  # ayer = 3
    assert m.bloques_a_refrescar() == [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-03")]


def test_dia_uno_refresca_el_mes_anterior_completo(monkeypatch):
    _fijar_hoy(monkeypatch, dt.date(2026, 12, 1))
    assert m.bloques_a_refrescar() == [("2026-11-01", "2026-11-30")]


def test_fechas_manuales_fijan_un_solo_bloque(monkeypatch):
    monkeypatch.setenv("FECHA_DESDE", "2026-01-01")
    monkeypatch.setenv("FECHA_HASTA", "2026-11-17")
    assert m.bloques_a_refrescar() == [("2026-01-01", "2026-11-17")]


# ---------------------------------------------------------------- descarga
class RespuestaFalsa:
    def __init__(self, cuerpo):
        self.content = cuerpo.encode("utf-8")


class SesionFalsa:
    def __init__(self, cuerpo):
        self.cuerpo, self.llamadas = cuerpo, []

    def post(self, url, data=None, timeout=None):
        self.llamadas.append((url, data))
        return RespuestaFalsa(self.cuerpo)


def test_descarga_pide_ambas_rentas_sin_filtro_de_registro(monkeypatch):
    import json
    monkeypatch.setenv("MAXINET_BASE_URL", "http://ejemplo.test/maxinetv2/")
    ses = SesionFalsa(json.dumps({"data": [fila_maxinet("#1", 2, "2026-11-10")]}))
    filas = m.descargar_rentas(ses, "2026-11-01", "2026-11-17")
    url, datos = ses.llamadas[0]
    assert url == "http://ejemplo.test/maxinetv2/includes/reportescp/clientes-2-3-data-v2.php"
    assert datos == {"Desde": "2026-11-01", "Hasta": "2026-11-17", "f_registro": "0", "tiporenta": "0"}
    assert len(filas) == 1


def test_una_respuesta_sin_data_detiene_la_corrida(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://ejemplo.test/maxinetv2")
    with pytest.raises(RuntimeError, match="lista 'data'"):
        m.descargar_rentas(SesionFalsa('{"error": 1}'), "2026-11-01", "2026-11-17")


# ---------------------------------------------------------------- refrescar el bloque
def _bloque(*especificaciones):
    return m.normalizar_filas([fila_maxinet(c, e, f2, f3) for c, e, f2, f3 in especificaciones])


OCT = [("#1", 2, "2026-10-05", ""), ("#2", 3, "2025-01-01", "2026-10-20")]


def test_hoja_vacia_escribe_el_bloque_desde_la_fila_2():
    hoja = HojaFalsa()
    nuevas = _bloque(("#3", 2, "2026-11-02", ""), ("#4", 3, "2025-05-30", "2026-11-03"))
    r = m.refrescar_bloque(hoja, nuevas, "2026-11-01")
    assert (r["antes"], r["despues"], r["inicio"]) == (0, 2, 2)
    assert hoja.escrituras[0][0] == "A2:R3" and hoja.filas == nuevas


def test_reemplaza_el_mes_sin_tocar_los_meses_cerrados():
    previos = _bloque(*OCT)
    hoja = HojaFalsa(previos + _bloque(("#7", 2, "2026-11-01", "")))
    nuevas = _bloque(("#7", 2, "2026-11-01", ""), ("#8", 2, "2026-11-02", ""))
    r = m.refrescar_bloque(hoja, nuevas, "2026-11-01")
    assert r["inicio"] == 4 and r["antes"] == 1 and r["nuevas"] == 1
    assert hoja.filas[:2] == previos and hoja.filas[2:] == nuevas
    assert hoja.escrituras[0][0] == "A4:R5"


def test_es_idempotente():
    hoja = HojaFalsa(_bloque(*OCT))
    nuevas = _bloque(("#7", 2, "2026-11-01", ""), ("#8", 3, "2025-01-01", "2026-11-02"))
    m.refrescar_bloque(hoja, nuevas, "2026-11-01")
    despues_1 = [list(f) for f in hoja.filas]
    m.refrescar_bloque(hoja, nuevas, "2026-11-01")
    assert hoja.filas == despues_1 and hoja.limpiezas == []


def test_si_el_bloque_queda_mas_corto_limpia_lo_que_sobra():
    hoja = HojaFalsa(_bloque(("#7", 2, "2026-11-01", ""), ("#8", 2, "2026-11-02", ""), ("#9", 2, "2026-11-03", "")))
    m.refrescar_bloque(hoja, _bloque(("#7", 2, "2026-11-01", "")), "2026-11-01")
    assert hoja.limpiezas == ["A3:R4"]


def test_el_evento_3_se_ubica_por_la_fecha_de_su_3ra_renta():
    # su 2da renta es de octubre pero el evento es de noviembre: pertenece al bloque de noviembre
    hoja = HojaFalsa(_bloque(("#1", 2, "2026-10-05", ""), ("#2", 3, "2026-10-10", "2026-11-02")))
    r = m.refrescar_bloque(hoja, _bloque(("#2", 3, "2026-10-10", "2026-11-02"), ("#5", 2, "2026-11-03", "")), "2026-11-01")
    assert r["inicio"] == 3 and r["antes"] == 1 and len(hoja.filas) == 3


def test_salvaguarda_del_80_por_ciento():
    hoja = HojaFalsa(_bloque(*[(f"#{i}", 2, "2026-11-02", "") for i in range(40)]))
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar_bloque(hoja, _bloque(*[(f"#{i}", 2, "2026-11-02", "") for i in range(10)]), "2026-11-01")
    assert hoja.escrituras == []


def test_forzar_omite_la_salvaguarda(monkeypatch):
    monkeypatch.setenv("FORZAR", "1")
    hoja = HojaFalsa(_bloque(*[(f"#{i}", 2, "2026-11-02", "") for i in range(40)]))
    m.refrescar_bloque(hoja, _bloque(("#1", 2, "2026-11-02", "")), "2026-11-01")
    assert hoja.escrituras


def test_encabezados_distintos_detienen_la_corrida_sin_escribir():
    hoja = HojaFalsa(encabezados=m.COLUMNAS[:-1] + ["Correo"])
    with pytest.raises(RuntimeError, match="encabezados"):
        m.refrescar_bloque(hoja, _bloque(("#1", 2, "2026-11-02", "")), "2026-11-01")
    assert hoja.escrituras == []


def test_una_hoja_desordenada_detiene_la_corrida():
    hoja = HojaFalsa(_bloque(("#1", 2, "2026-11-05", ""), ("#2", 2, "2026-10-02", "")))
    hoja.filas.sort(key=lambda f: -f[I["Fecha 2da renta"]])        # noviembre primero y octubre después
    with pytest.raises(RuntimeError, match="no está ordenada"):
        m.refrescar_bloque(hoja, _bloque(("#3", 2, "2026-11-06", "")), "2026-11-01")
    assert hoja.escrituras == []


def test_dry_run_no_escribe(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    hoja = HojaFalsa()
    r = m.refrescar_bloque(hoja, _bloque(("#1", 2, "2026-11-02", "")), "2026-11-01")
    assert r["despues"] == 1 and hoja.escrituras == [] and hoja.spreadsheet.peticiones == []


def test_sin_filas_de_maxinet_no_escribe_nada():
    hoja = HojaFalsa(_bloque(*OCT))
    m.refrescar_bloque(hoja, [], "2026-11-01")
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_da_formato_de_fecha_a_las_tres_columnas_de_fecha():
    hoja = HojaFalsa()
    m.refrescar_bloque(hoja, _bloque(("#1", 2, "2026-11-02", "")), "2026-11-01")
    cols = sorted(p["repeatCell"]["range"]["startColumnIndex"] for p in hoja.spreadsheet.peticiones)
    assert cols == [4, 7, 10]
    assert all(p["repeatCell"]["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] == "yyyy-mm-dd"
               for p in hoja.spreadsheet.peticiones)


def test_escribe_en_tandas_cuando_hay_muchas_filas(monkeypatch):
    monkeypatch.setattr(m, "FILAS_POR_ESCRITURA", 2)
    hoja = HojaFalsa()
    m.refrescar_bloque(hoja, _bloque(*[(f"#{i}", 2, "2026-11-02", "") for i in range(5)]), "2026-11-01")
    assert [e[0] for e in hoja.escrituras] == ["A2:R3", "A4:R5", "A6:R6"]


def test_validar_bloque_detecta_filas_fuera_de_orden():
    hoja = HojaFalsa(_bloque(("#1", 2, "2026-11-05", ""), ("#2", 2, "2026-11-06", "")))
    m.validar_bloque(hoja, 2, 2)
    hoja.filas.reverse()
    with pytest.raises(RuntimeError, match="orden"):
        m.validar_bloque(hoja, 2, 2)


# ---------------------------------------------------------------- pestaña
class LibroFalso:
    def __init__(self, existentes=()):
        self.hojas = {n: object() for n in existentes}
        self.creadas = []

    def worksheet(self, nombre):
        if nombre not in self.hojas:
            raise gspread.exceptions.WorksheetNotFound(nombre)
        return self.hojas[nombre]

    def get_worksheet_by_id(self, gid):
        raise gspread.exceptions.WorksheetNotFound(str(gid))

    def worksheets(self):
        return list(self.hojas.values())

    def add_worksheet(self, title, rows, cols):
        hoja = HojaCreada()
        self.creadas.append((title, rows, cols, hoja))
        self.hojas[title] = hoja
        return hoja


class HojaCreada:
    id = 99

    def __init__(self):
        self.llamadas = []
        self.spreadsheet = Libro()

    def update(self, range_name, values, value_input_option=None):
        self.llamadas.append(("update", range_name, values, value_input_option))

    def freeze(self, rows):
        self.llamadas.append(("freeze", rows))

    def format(self, rango, formato):
        self.llamadas.append(("format", rango))


def test_si_la_pestana_no_existe_se_crea_con_los_encabezados():
    libro = LibroFalso()
    hoja = m.resolver_pestana(libro, "2DAS Y 3RAS RENTAS")
    assert libro.creadas[0][:3] == ("2DAS Y 3RAS RENTAS", 2000, 18)
    assert ("update", "A1:R1", [m.COLUMNAS], "RAW") in hoja.llamadas
    assert hoja.spreadsheet.peticiones                              # el formato se aplica al crearla


def test_el_formato_de_la_hoja_sigue_el_de_las_demas_de_la_base():
    hoja = HojaCreada()
    m.dar_formato_hoja(hoja)
    pedidos = hoja.spreadsheet.peticiones
    props = next(p["updateSheetProperties"] for p in pedidos if "updateSheetProperties" in p)
    assert props["properties"]["tabColor"] == {"blue": 1}
    assert props["properties"]["gridProperties"] == {"frozenRowCount": 1, "hideGridlines": True}
    enc = next(p["repeatCell"] for p in pedidos if "repeatCell" in p and p["repeatCell"]["range"].get("endRowIndex") == 1)
    assert enc["cell"]["userEnteredFormat"]["textFormat"]["bold"] and enc["cell"]["userEnteredFormat"]["horizontalAlignment"] == "CENTER"
    anchos = [p["updateDimensionProperties"] for p in pedidos if "updateDimensionProperties" in p]
    assert len(anchos) == 18 and anchos[1]["properties"]["pixelSize"] == 300
    fechas = sorted(p["repeatCell"]["range"]["startColumnIndex"] for p in pedidos
                    if "repeatCell" in p and "numberFormat" in p["repeatCell"]["cell"]["userEnteredFormat"])
    assert fechas == [4, 7, 10]


def test_si_la_pestana_existe_no_se_crea_otra():
    libro = LibroFalso(["2DAS Y 3RAS RENTAS"])
    m.resolver_pestana(libro, "2DAS Y 3RAS RENTAS")
    assert libro.creadas == []


def test_dry_run_no_crea_la_pestana(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    libro = LibroFalso()
    assert m.resolver_pestana(libro, "2DAS Y 3RAS RENTAS") is None and libro.creadas == []


def test_un_gid_que_no_existe_falla_sin_crear_nada():
    libro = LibroFalso()
    with pytest.raises(gspread.exceptions.WorksheetNotFound, match="actualiza el gid"):
        m.resolver_pestana(libro, "123456")
    assert libro.creadas == []


def test_nombre_de_pestana_por_defecto_y_por_secret(monkeypatch):
    assert m._nombre_pestana() == "2DAS Y 3RAS RENTAS"
    monkeypatch.setenv("WORKSHEET_RENTAS_2_3_NAME", ' "Otra" ')
    assert m._nombre_pestana() == "Otra"
