import datetime as dt
import logging

import gspread
import pytest

import maxinet_mkt_leads_cp as m
from tests.fakes import HojaFalsa, fila_hoja, fila_maxinet, serie

I = m.IDX


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for v in ("FECHA_DESDE", "FECHA_HASTA", "DRY_RUN", "FORZAR", "WORKSHEET_MKT_NAME"):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------- estructura
def test_hay_40_columnas_y_la_hoja_termina_en_AN():
    assert len(m.COLUMNAS) == 40 and m.ULTIMA_COL == "AN" and m.ANCHO_MAXINET == 42
    assert m.IDX["Fecha Registro"] == 8 and m.IDX["Comentarios"] == 39


# ---------------------------------------------------------------- tipos
def test_fechas_pasan_a_numero_de_serie_con_hora():
    assert m._serie("2026-10-01 07:13:54", "x") == (dt.date(2026, 10, 1) - m.BASE_SERIAL).days + (7 * 3600 + 13 * 60 + 54) / 86400
    assert m._serie("2026-10-01 08:38", "x") == (dt.date(2026, 10, 1) - m.BASE_SERIAL).days + (8 * 3600 + 38 * 60) / 86400
    assert m._serie("2026-10-01", "x") == (dt.date(2026, 10, 1) - m.BASE_SERIAL).days


def test_una_fecha_con_otra_forma_detiene_la_corrida_sin_citar_el_valor():
    with pytest.raises(RuntimeError) as e:
        m._serie("01/10/2026 7:13", "Fecha Registro")
    assert "Fecha Registro" in str(e.value) and "01/10" not in str(e.value)


def test_numeros_y_telefonos():
    assert m._numero("39660") == 39660 and isinstance(m._numero("39660"), int)
    assert m._numero("10784.4828") == 10784.4828
    assert m._numero("$ 1,234.50") == 1234.5
    assert m._numero("sucursal") == "sucursal"
    assert m._telefono("8114944334") == 8114944334
    assert m._telefono("p:+528114944334") == "p:+528114944334"
    assert m._telefono("0123456789") == "0123456789"            # un cero inicial se conserva como texto
    assert m._telefono("1234567890123456") == "1234567890123456"  # más de 15 dígitos pierde precisión como número


def test_normalizar_tipa_las_columnas_y_limpia_espacios():
    f = fila_maxinet("2026-10-05 10:00:00", 100, **{
        "Estatus Reserva": "CHECKED IN  ", "Subtotal renta": "39660", "Garantía": "30000", "Subtotal Prohire": "10784.4828",
        "Días Renta": "3", "Fecha cierre": "2026-10-06 12:30", "Teléfono": "p:+528100000000", "Comentarios": "  hola \n mundo ",
        "Reserva": "$34E46B1", "No.Cliente": "#51014854", "Semáforo": None})
    (r,) = m.normalizar_filas([f])
    assert len(r) == 40
    assert r[I["Estatus Reserva"]] == "CHECKED IN"
    assert r[I["Subtotal renta"]] == 39660 and r[I["Garantía"]] == 30000 and r[I["Subtotal Prohire"]] == 10784.4828
    assert r[I["Días Renta"]] == 3 and r[I["No.Intento"]] == 1
    assert r[I["Fecha Registro"]] == serie("2026-10-05 10:00:00") and r[I["Fecha cierre"]] == serie("2026-10-06 12:30")
    assert r[I["Teléfono"]] == "p:+528100000000"
    assert r[I["Comentarios"]] == "hola \n mundo"
    assert r[I["Reserva"]] == "$34E46B1" and r[I["No.Cliente"]] == "#51014854"      # ids: texto tal cual
    assert r[I["Semáforo"]] == "" and r[I["Fecha envío cotización"]] == ""


def test_ancho_distinto_detiene_la_corrida():
    f = fila_maxinet("2026-10-05 10:00:00", 1)
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([f + ["extra"]])


def test_lead_sin_fecha_de_registro_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="sin Fecha Registro"):
        m.normalizar_filas([fila_maxinet("", 1)])


def test_orden_por_fecha_registro_e_id_y_sin_repetidos():
    filas = [fila_maxinet("2026-10-02 09:00:00", 12), fila_maxinet("2026-10-01 09:00:00", 20),
             fila_maxinet("2026-10-02 09:00:00", 11), fila_maxinet("2026-10-01 09:00:00", 20, Nombre="OTRO")]
    out = m.normalizar_filas(filas)
    assert [r[I["Fecha Registro"]] for r in out] == [serie("2026-10-01 09:00:00"), serie("2026-10-02 09:00:00"), serie("2026-10-02 09:00:00")]
    assert [r[I["Nombre"]] for r in out] == ["NOMBRE PRUEBA"] * 3                 # el repetido (id 20) se descartó
    # mismo instante: manda el id
    assert m.normalizar_filas([fila_maxinet("2026-10-02 09:00:00", 12, Nombre="B"), fila_maxinet("2026-10-02 09:00:00", 11, Nombre="A")])[0][I["Nombre"]] == "A"


def test_id_del_lead_en_las_tres_formas_del_enlace():
    assert m.id_lead('<a href="#" title="Detalle" class="muestraDtail" attrId="16907" >Detalle</a>') == 16907
    assert m.id_lead('<a href="cp-atiende-lead.php?id=16908" title="Contactar" >Contactar</a>') == 16908
    assert m.id_lead('<a href="cp-cierre-lead.php?id=16909" title="Editar" >Editar</a>') == 16909
    assert m.id_lead("") is None and m.id_lead(None) is None


# ---------------------------------------------------------------- rango de fechas
def _hoy(monkeypatch, fecha):
    class Reloj(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(fecha.year, fecha.month, fecha.day, 8, 0, tzinfo=tz)
    monkeypatch.setattr(m.dt, "datetime", Reloj)


def test_rango_normal_es_del_primero_del_mes_a_ayer(monkeypatch):
    _hoy(monkeypatch, dt.date(2026, 10, 28))
    assert m.bloques_a_refrescar() == [("2026-10-01", "2026-10-27")]


def test_el_dia_uno_el_rango_es_el_mes_anterior_completo(monkeypatch):
    _hoy(monkeypatch, dt.date(2026, 11, 1))
    assert m.bloques_a_refrescar() == [("2026-10-01", "2026-10-31")]


def test_los_primeros_tres_dias_se_refresca_tambien_el_mes_anterior(monkeypatch):
    _hoy(monkeypatch, dt.date(2026, 11, 3))
    assert m.bloques_a_refrescar() == [("2026-10-01", "2026-10-31"), ("2026-11-01", "2026-11-02")]
    _hoy(monkeypatch, dt.date(2026, 11, 5))
    assert m.bloques_a_refrescar() == [("2026-11-01", "2026-11-04")]


def test_fechas_manuales(monkeypatch):
    monkeypatch.setenv("FECHA_DESDE", "2026-09-01")
    monkeypatch.setenv("FECHA_HASTA", "2026-09-30")
    assert m.bloques_a_refrescar() == [("2026-09-01", "2026-09-30")]


# ---------------------------------------------------------------- refresco del bloque
def _nuevas(*registros):
    return m.normalizar_filas([fila_maxinet(r, 100 + i) for i, r in enumerate(registros)])


def test_hoja_vacia_escribe_desde_la_fila_2_en_modo_raw():
    hoja = HojaFalsa()
    r = m.refrescar_bloque(hoja, _nuevas("2026-10-01 08:00:00", "2026-10-02 09:00:00"), "2026-10-01")
    assert r == {"antes": 0, "despues": 2, "nuevas": 2, "inicio": 2}
    (rango, valores, modo), = hoja.escrituras
    assert rango == "A2:AN3" and modo == "RAW" and len(valores) == 2 and all(len(v) == 40 for v in valores)
    assert hoja.limpiezas == []


def test_no_toca_las_filas_de_meses_anteriores_y_reemplaza_el_bloque():
    septiembre = [fila_hoja("2026-09-29 10:00:00", Nombre="SEPT"), fila_hoja("2026-09-30 23:00:00", Nombre="SEPT")]
    octubre_viejo = [fila_hoja("2026-10-01 08:00:00", Nombre="VIEJO", Estatus="")]
    hoja = HojaFalsa(septiembre + octubre_viejo)
    nuevas = m.normalizar_filas([fila_maxinet("2026-10-01 08:00:00", 1, Estatus="SI CALIFICA"),
                                 fila_maxinet("2026-10-02 08:00:00", 2)])
    r = m.refrescar_bloque(hoja, nuevas, "2026-10-01")
    assert r["inicio"] == 4 and r["antes"] == 1 and r["despues"] == 2 and r["nuevas"] == 1
    assert [f[I["Nombre"]] for f in hoja.filas[:2]] == ["SEPT", "SEPT"]
    assert hoja.filas[2][I["Estatus"]] == "SI CALIFICA" and len(hoja.filas) == 4
    assert hoja.escrituras[0][0] == "A4:AN5"


def test_un_lead_de_las_00_00_del_primer_dia_es_parte_del_bloque():
    hoja = HojaFalsa([fila_hoja("2026-09-30 23:59:59", Nombre="SEPT"), fila_hoja("2026-10-01 00:00:00", Nombre="VIEJO")])
    r = m.refrescar_bloque(hoja, m.normalizar_filas([fila_maxinet("2026-10-01 00:00:00", 1, Nombre="NUEVO")]), "2026-10-01")
    assert r["inicio"] == 3 and r["antes"] == 1
    assert [f[I["Nombre"]] for f in hoja.filas] == ["SEPT", "NUEVO"]


def test_si_el_bloque_queda_mas_corto_se_limpia_lo_que_sobra():
    viejas = [fila_hoja(f"2026-10-0{d} 08:00:00") for d in (1, 2, 3, 4)]
    hoja = HojaFalsa(viejas)
    m.refrescar_bloque(hoja, _nuevas("2026-10-01 08:00:00", "2026-10-02 08:00:00"), "2026-10-01")
    assert hoja.limpiezas == ["A4:AN5"]
    assert all(c == "" for c in hoja.filas[2] + hoja.filas[3])


def test_salvaguarda_del_80_por_ciento(monkeypatch):
    viejas = [fila_hoja("2026-10-01 08:00:00") for _ in range(40)]
    hoja = HojaFalsa(viejas)
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar_bloque(hoja, _nuevas(*["2026-10-01 08:00:00"] * 10), "2026-10-01")
    assert hoja.escrituras == []
    monkeypatch.setenv("FORZAR", "1")
    m.refrescar_bloque(hoja, _nuevas(*["2026-10-01 08:00:00"] * 10), "2026-10-01")
    assert len(hoja.escrituras) == 1


def test_dry_run_no_escribe_nada(caplog):
    hoja = HojaFalsa()
    import os
    os.environ["DRY_RUN"] = "1"
    try:
        with caplog.at_level(logging.INFO):
            m.refrescar_bloque(hoja, _nuevas("2026-10-01 08:00:00"), "2026-10-01")
    finally:
        del os.environ["DRY_RUN"]
    assert hoja.escrituras == [] and hoja.spreadsheet.peticiones == [] and hoja.filas == []
    assert "DRY_RUN: se reescribirían A2:AN2 (1 filas)" in caplog.text


def test_encabezados_distintos_detienen_la_corrida_sin_escribir():
    enc = list(m.COLUMNAS)
    enc[6], enc[7] = enc[7], enc[6]
    hoja = HojaFalsa(encabezados=enc)
    with pytest.raises(RuntimeError, match="encabezados.*difieren las columnas \\[7, 8\\]"):
        m.refrescar_bloque(hoja, _nuevas("2026-10-01 08:00:00"), "2026-10-01")
    assert hoja.escrituras == []


def test_hoja_desordenada_detiene_la_corrida():
    hoja = HojaFalsa([fila_hoja("2026-10-03 08:00:00"), fila_hoja("2026-09-20 08:00:00")])
    with pytest.raises(RuntimeError, match="no está ordenada"):
        m.refrescar_bloque(hoja, _nuevas("2026-10-01 08:00:00"), "2026-10-01")
    assert hoja.escrituras == []


def test_escribe_en_tandas_y_agrega_filas_si_faltan(monkeypatch):
    monkeypatch.setattr(m, "FILAS_POR_ESCRITURA", 2)
    hoja = HojaFalsa()
    hoja.row_count = 3
    m.refrescar_bloque(hoja, _nuevas(*[f"2026-10-0{d} 08:00:00" for d in (1, 2, 3, 4, 5)]), "2026-10-01")
    assert [e[0] for e in hoja.escrituras] == ["A2:AN3", "A4:AN5", "A6:AN6"]
    assert hoja.filas_agregadas == [203] and len(hoja.filas) == 5


def test_da_formato_de_fecha_a_las_seis_columnas():
    hoja = HojaFalsa()
    m.refrescar_bloque(hoja, _nuevas("2026-10-01 08:00:00"), "2026-10-01")
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones]
    formatos = {p["range"]["startColumnIndex"]: p["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] for p in pedidos}
    assert formatos == {8: "yyyy-mm-dd h:mm:ss", 9: "yyyy-mm-dd h:mm:ss", 10: "yyyy-mm-dd h:mm:ss", 12: "yyyy-mm-dd h:mm:ss",
                        30: "yyyy-mm-dd h:mm", 33: "yyyy-mm-dd h:mm"}
    assert all(p["range"]["startRowIndex"] == 1 and p["range"]["endRowIndex"] == 2 for p in pedidos)


def test_un_texto_que_parece_formula_se_escribe_tal_cual_y_en_raw():
    hoja = HojaFalsa()
    filas = m.normalizar_filas([fila_maxinet("2026-10-01 08:00:00", 1, Comentarios='=HYPERLINK("http://x","y")')])
    m.refrescar_bloque(hoja, filas, "2026-10-01")
    rango, valores, modo = hoja.escrituras[0]
    assert modo == "RAW" and valores[0][I["Comentarios"]] == '=HYPERLINK("http://x","y")'


def test_validar_orden():
    hoja = HojaFalsa([fila_hoja("2026-10-01 08:00:00"), fila_hoja("2026-10-02 08:00:00")])
    m.validar_orden(hoja, 2, 2)
    with pytest.raises(RuntimeError, match="se esperaban 3"):
        m.validar_orden(hoja, 2, 3)
    hoja.filas.reverse()
    with pytest.raises(RuntimeError, match="orden ascendente"):
        m.validar_orden(hoja, 2, 2)


# ---------------------------------------------------------------- pestaña por gid o nombre
class LibroFalso:
    def __init__(self, pestanas):
        self.pestanas = pestanas

    def get_worksheet_by_id(self, gid):
        if gid not in self.pestanas:
            raise gspread.exceptions.WorksheetNotFound(str(gid))
        return ("hoja", gid)

    def worksheet(self, nombre):
        for gid, t in self.pestanas.items():
            if t == nombre:
                return ("hoja", gid)
        raise gspread.exceptions.WorksheetNotFound(nombre)

    def worksheets(self):
        return list(self.pestanas)


def test_resolver_pestana_por_gid_por_nombre_y_sin_volcar_nombres():
    libro = LibroFalso({101: "MKT SECRETA", 202: "OTRA"})
    assert m.resolver_pestana(libro, " 101 ") == ("hoja", 101)
    assert m.resolver_pestana(libro, "MKT SECRETA") == ("hoja", 101)
    with pytest.raises(gspread.exceptions.WorksheetNotFound) as e:
        m.resolver_pestana(libro, "999")
    assert "2 pestañas" in str(e.value) and "SECRETA" not in str(e.value)


# ---------------------------------------------------------------- corrida completa y privacidad
def test_la_corrida_no_registra_datos_de_clientes(monkeypatch, caplog):
    hoja = HojaFalsa()
    filas = [fila_maxinet("2026-10-01 08:00:00", 1, Nombre="MARIA SECRETA", Email="maria.secreta@ejemplo.com",
                          Teléfono="8111112222", Comentarios="NOTA PRIVADA")]
    monkeypatch.setattr(m, "bloques_a_refrescar", lambda: [("2026-10-01", "2026-10-27")])
    monkeypatch.setattr(m, "descargar_leads", lambda d, h: m.normalizar_filas(filas))
    monkeypatch.setattr(m, "conectar_sheet", lambda: hoja)
    with caplog.at_level(logging.DEBUG):
        m.main()
    texto = caplog.text
    assert "completada con éxito (bloque de 1 leads desde 2026-10-01)" in texto and "Validación OK" in texto
    for secreto in ("SECRETA", "maria", "8111112222", "NOTA PRIVADA"):
        assert secreto not in texto
    assert hoja.filas[0][I["Nombre"]] == "MARIA SECRETA"


def test_un_error_sale_con_codigo_1_y_sin_escribir(monkeypatch):
    hoja = HojaFalsa(encabezados=["otra", "cosa"])
    monkeypatch.setattr(m, "bloques_a_refrescar", lambda: [("2026-10-01", "2026-10-27")])
    monkeypatch.setattr(m, "descargar_leads", lambda d, h: _nuevas("2026-10-01 08:00:00"))
    monkeypatch.setattr(m, "conectar_sheet", lambda: hoja)
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 1 and hoja.escrituras == []
