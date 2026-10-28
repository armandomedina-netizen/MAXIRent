import datetime as dt
import logging
import os

import gspread
import pytest

import maxinet_bitacora_cp as m
from tests.fakes import HojaFalsa, dia, fila_hoja, fila_maxinet

I = m.IDX


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for v in ("FECHA_DESDE", "FECHA_HASTA", "DRY_RUN", "FORZAR", "WORKSHEET_BITACORA_NAME"):
        monkeypatch.delenv(v, raising=False)


# ---------------------------------------------------------------- estructura
def test_hay_37_columnas_de_datos_mas_4_de_formulas():
    assert len(m.COLUMNAS) == 37 and len(m.ENCABEZADOS) == 41 and m.ANCHO_MAXINET == 38
    assert (m.COL_PROMESA, m.ULTIMA_COL_DATOS, m.PRIMERA_COL_AUX, m.ULTIMA_COL) == ("B", "AK", "AL", "AO")
    assert m.IDX["Fecha Prom."] == 1 and m.IDX["Asesor móvil"] == 18 and m.IDX["Comentarios"] == 36


def test_las_formulas_son_las_de_la_copia_de_nuvia_y_cuadran_con_las_columnas():
    assert len(m.FORMULAS_AUX) == len(m.COLUMNAS_AUX) == 4
    assert [f.format(r=2) for f in m.FORMULAS_AUX] == [
        '=IF(B2="","", YEAR(B2))', '=IF(B2="","",TEXT(B2,"MMMM"))',
        '=IF(B2="","", IF(S2="","SIN ASESOR",S2))', '=IF(B2="","",TEXT(B2,"MMMM YYYY"))']
    assert m.ENCABEZADOS[m.COLUMNAS.index("Asesor móvil")] == "Asesor móvil"
    # B es Fecha Prom. y S es Asesor móvil: las fórmulas dependen de esas letras
    assert chr(65 + m.IDX["Fecha Prom."]) == "B" and chr(65 + m.IDX["Asesor móvil"]) == "S"


# ---------------------------------------------------------------- tipos
def test_fechas_y_horas():
    assert m._fecha("2026-10-01", "x") == dia("2026-10-01") and isinstance(m._fecha("2026-10-01", "x"), int)
    assert m._hora("06:00:00", "x") == 0.25 and m._hora("9:22", "x") == (9 * 3600 + 22 * 60) / 86400
    for malo in ("01/10/2026", "2026-10-01 08:00", ""):
        with pytest.raises(RuntimeError) as e:
            m._fecha(malo, "Fecha Real")
        assert "Fecha Real" in str(e.value) and "01/10" not in str(e.value)
    with pytest.raises(RuntimeError, match="Hora Real"):
        m._hora("8am", "Hora Real")


def test_importes_e_identificadores():
    assert m._numero("250.0000") == 250 and isinstance(m._numero("250.0000"), int)
    assert m._numero("229.93") == 229.93 and m._numero("$ 1,234.50") == 1234.5 and m._numero("-3") == -3
    assert m._numero("sin costo") == "sin costo"
    assert m._identificador("52950012") == 52950012
    assert m._identificador("#216490798") == "#216490798" and m._identificador("$34E46B1") == "$34E46B1"
    assert m._identificador("06000") == "06000" and m._identificador("1234567890123456") == "1234567890123456"


def test_normalizar_tipa_las_columnas_y_limpia_espacios():
    f = fila_maxinet("2026-10-05", "06:30:00", **{
        "Fecha Real": "2026-10-06", "Hora Real": "09:22:00", "Costo Rec.": "606.0000", "Uber": "229.93", "Dif. Dias": 33,
        "Cliente": "  CLIENTE PRUEBA ", "Placa": "ABC123D ", "# Cliente": "52950012", "Código Postal": "67174",
        "Cumpleaños": "1980-05-17", "Delivery Details": "CALLE 1\nCOL. X ", "Tiempo Trans.": "27 hs 12 min", "Asesor móvil": None})
    (r,) = m.normalizar_filas([f])
    assert len(r) == 37
    assert r[I["Fecha Prom."]] == dia("2026-10-05") and r[I["Hora Prom."]] == 6.5 / 24
    assert r[I["Fecha Real"]] == dia("2026-10-06") and r[I["Hora Real"]] == (9 * 3600 + 22 * 60) / 86400
    assert r[I["Fecha GPS"]] == "" and r[I["Hora GPS"]] == ""
    assert r[I["Costo Ent.Dom"]] == 250 and r[I["Costo Rec."]] == 606 and r[I["Uber"]] == 229.93 and r[I["Dif. Dias"]] == 33
    assert r[I["Cliente"]] == "CLIENTE PRUEBA" and r[I["Placa"]] == "ABC123D"
    assert r[I["# Cliente"]] == 52950012 and r[I["Código Postal"]] == 67174 and r[I["Reserva"]] == "#100000001"
    assert r[I["Cumpleaños"]] == dia("1980-05-17")
    assert r[I["Delivery Details"]] == "CALLE 1\nCOL. X"
    assert r[I["Tiempo Trans."]] == "27 hs 12 min" and r[I["Asesor móvil"]] == ""


def test_ancho_distinto_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_maxinet("2026-10-05") + ["extra"]])


def test_servicio_sin_fecha_prom_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="sin Fecha Prom"):
        m.normalizar_filas([fila_maxinet("")])


def test_orden_por_fecha_hora_reserva_y_tipo_y_no_se_descarta_nada(caplog):
    filas = [fila_maxinet("2026-10-02", "09:00:00", "#2"), fila_maxinet("2026-10-01", "10:00:00", "#9"),
             fila_maxinet("2026-10-01", "08:00:00", "#5", "COLLECT"), fila_maxinet("2026-10-01", "08:00:00", "#5", "DELIVER"),
             fila_maxinet("2026-10-01", "08:00:00", "#1")]
    with caplog.at_level(logging.WARNING):
        out = m.normalizar_filas(filas)
    assert [(r[I["Reserva"]], r[I["Tipo Serv."]]) for r in out] == [
        ("#1", "DELIVER"), ("#5", "COLLECT"), ("#5", "DELIVER"), ("#9", "DELIVER"), ("#2", "DELIVER")]
    assert caplog.text == ""                                            # sin repetidos no hay aviso
    with caplog.at_level(logging.WARNING):
        assert len(m.normalizar_filas([fila_maxinet("2026-10-01", reserva="#1"), fila_maxinet("2026-10-01", reserva="#1")])) == 2
    assert "misma Reserva y Tipo Serv." in caplog.text


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
def _nuevas(*promesas):
    return m.normalizar_filas([fila_maxinet(p, reserva=f"#{100 + i}") for i, p in enumerate(promesas)])


def test_hoja_vacia_escribe_desde_la_fila_2_datos_en_raw_y_formulas_por_fila():
    hoja = HojaFalsa()
    r = m.refrescar_bloque(hoja, _nuevas("2026-10-01", "2026-10-02"), "2026-10-01")
    assert r == {"antes": 0, "despues": 2, "nuevas": 2, "inicio": 2}
    (r1, v1, modo1), (r2, v2, modo2) = hoja.escrituras
    assert (r1, modo1) == ("A2:AK3", "RAW") and len(v1) == 2 and all(len(v) == 37 for v in v1)
    assert (r2, modo2) == ("AL2:AO3", "USER_ENTERED")
    assert v2[0] == ['=IF(B2="","", YEAR(B2))', '=IF(B2="","",TEXT(B2,"MMMM"))', '=IF(B2="","", IF(S2="","SIN ASESOR",S2))', '=IF(B2="","",TEXT(B2,"MMMM YYYY"))']
    assert v2[1][0] == '=IF(B3="","", YEAR(B3))' and "S3" in v2[1][2]
    assert hoja.limpiezas == []


def test_no_toca_las_filas_de_meses_anteriores_y_reemplaza_el_bloque():
    septiembre = [fila_hoja("2026-09-29", Cliente="SEPT"), fila_hoja("2026-09-30", Cliente="SEPT")]
    octubre_viejo = [fila_hoja("2026-10-01", Cliente="VIEJO")]
    hoja = HojaFalsa(septiembre + octubre_viejo)
    nuevas = m.normalizar_filas([fila_maxinet("2026-10-01", reserva="#1", Cliente="NUEVO1"), fila_maxinet("2026-10-02", reserva="#2")])
    r = m.refrescar_bloque(hoja, nuevas, "2026-10-01")
    assert r["inicio"] == 4 and r["antes"] == 1 and r["despues"] == 2 and r["nuevas"] == 1
    assert [f[I["Cliente"]] for f in hoja.filas[:2]] == ["SEPT", "SEPT"]
    assert hoja.filas[2][I["Cliente"]] == "NUEVO1" and len(hoja.filas) == 4
    assert [e[0] for e in hoja.escrituras] == ["A4:AK5", "AL4:AO5"]


def test_si_el_bloque_queda_mas_corto_se_borran_datos_sobrantes_pero_no_las_formulas():
    viejas = [fila_hoja(f"2026-10-0{d}") for d in (1, 2, 3, 4)]
    for i, f in enumerate(viejas):
        f[37:] = [f"=F{i}", "=g", "=h", "=i"]              # fórmulas que ya había en AL:AO
    hoja = HojaFalsa(viejas)
    m.refrescar_bloque(hoja, _nuevas("2026-10-01", "2026-10-02"), "2026-10-01")
    assert hoja.limpiezas == ["A4:AK5"]
    assert all(c == "" for c in hoja.filas[2][:37] + hoja.filas[3][:37])
    assert hoja.filas[2][37:] == ["=F2", "=g", "=h", "=i"] and hoja.filas[3][37:] == ["=F3", "=g", "=h", "=i"]


def test_un_servicio_prometido_el_primer_dia_es_parte_del_bloque():
    hoja = HojaFalsa([fila_hoja("2026-09-30", Cliente="SEPT"), fila_hoja("2026-10-01", Cliente="VIEJO")])
    r = m.refrescar_bloque(hoja, m.normalizar_filas([fila_maxinet("2026-10-01", Cliente="NUEVO")]), "2026-10-01")
    assert r["inicio"] == 3 and r["antes"] == 1
    assert [f[I["Cliente"]] for f in hoja.filas] == ["SEPT", "NUEVO"]


def test_salvaguarda_del_80_por_ciento(monkeypatch):
    hoja = HojaFalsa([fila_hoja("2026-10-01") for _ in range(40)])
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.refrescar_bloque(hoja, _nuevas(*["2026-10-01"] * 10), "2026-10-01")
    assert hoja.escrituras == []
    monkeypatch.setenv("FORZAR", "1")
    m.refrescar_bloque(hoja, _nuevas(*["2026-10-01"] * 10), "2026-10-01")
    assert len(hoja.escrituras) == 2


def test_dry_run_no_escribe_nada(monkeypatch, caplog):
    hoja = HojaFalsa()
    monkeypatch.setenv("DRY_RUN", "1")
    with caplog.at_level(logging.INFO):
        m.refrescar_bloque(hoja, _nuevas("2026-10-01"), "2026-10-01")
    assert hoja.escrituras == [] and hoja.spreadsheet.peticiones == [] and hoja.filas == []
    assert "DRY_RUN: se reescribirían A2:AK2 (1 filas)" in caplog.text


@pytest.mark.parametrize("cambio", ["intercambiar", "falta_aux", "otro_nombre"])
def test_encabezados_distintos_detienen_la_corrida_sin_escribir(cambio):
    enc = list(m.ENCABEZADOS)
    if cambio == "intercambiar":
        enc[6], enc[7] = enc[7], enc[6]
    elif cambio == "falta_aux":
        enc = enc[:-1]
    else:
        enc[38] = "MES2"
    hoja = HojaFalsa(encabezados=enc)
    with pytest.raises(RuntimeError, match="encabezados"):
        m.refrescar_bloque(hoja, _nuevas("2026-10-01"), "2026-10-01")
    assert hoja.escrituras == []


def test_un_texto_extra_a_la_derecha_de_la_fila_1_no_estorba():
    hoja = HojaFalsa(encabezados=list(m.ENCABEZADOS) + ["http://origen-del-reporte"])
    m.refrescar_bloque(hoja, _nuevas("2026-10-01"), "2026-10-01")
    assert len(hoja.escrituras) == 2


def test_hoja_desordenada_detiene_la_corrida():
    hoja = HojaFalsa([fila_hoja("2026-10-03"), fila_hoja("2026-09-20")])
    with pytest.raises(RuntimeError, match="no está ordenada"):
        m.refrescar_bloque(hoja, _nuevas("2026-10-01"), "2026-10-01")
    assert hoja.escrituras == []


def test_escribe_en_tandas_y_agrega_filas_si_faltan(monkeypatch):
    monkeypatch.setattr(m, "FILAS_POR_ESCRITURA", 2)
    hoja = HojaFalsa()
    hoja.row_count = 3
    m.refrescar_bloque(hoja, _nuevas(*[f"2026-10-0{d}" for d in (1, 2, 3, 4, 5)]), "2026-10-01")
    assert [e[0] for e in hoja.escrituras] == ["A2:AK3", "AL2:AO3", "A4:AK5", "AL4:AO5", "A6:AK6", "AL6:AO6"]
    assert hoja.filas_agregadas == [203] and len(hoja.filas) == 5


def test_da_formato_a_fechas_horas_e_importes():
    hoja = HojaFalsa()
    m.refrescar_bloque(hoja, _nuevas("2026-10-01"), "2026-10-01")
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones]
    formatos = {p["range"]["startColumnIndex"]: (p["cell"]["userEnteredFormat"]["numberFormat"]["type"],
                                                 p["cell"]["userEnteredFormat"]["numberFormat"]["pattern"]) for p in pedidos}
    assert formatos == {1: ("DATE", "d/M/yyyy"), 3: ("DATE", "d/M/yyyy"), 5: ("DATE", "yyyy-mm-dd"), 21: ("DATE", "yyyy-mm-dd"),
                        2: ("TIME", "h:mm:ss"), 4: ("TIME", "h:mm:ss"), 6: ("TIME", "h:mm:ss"),
                        23: ("CURRENCY", '"$"#,##0.00'), 24: ("CURRENCY", '"$"#,##0.00'), 25: ("CURRENCY", '"$"#,##0.00')}
    assert all(p["range"]["startRowIndex"] == 1 and p["range"]["endRowIndex"] == 2 for p in pedidos)


def test_un_texto_que_parece_formula_se_escribe_tal_cual_y_en_raw():
    hoja = HojaFalsa()
    filas = m.normalizar_filas([fila_maxinet("2026-10-01", **{"Delivery Details": '=HYPERLINK("http://x","y")', "Tiempo Trans.": "-43 min"})])
    m.refrescar_bloque(hoja, filas, "2026-10-01")
    rango, valores, modo = hoja.escrituras[0]
    assert modo == "RAW" and valores[0][I["Delivery Details"]] == '=HYPERLINK("http://x","y")' and valores[0][I["Tiempo Trans."]] == "-43 min"


def test_validar_orden():
    hoja = HojaFalsa([fila_hoja("2026-10-01"), fila_hoja("2026-10-02")])
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
    libro = LibroFalso({101: "BITACORA SECRETA", 202: "OTRA"})
    assert m.resolver_pestana(libro, " 101 ") == ("hoja", 101)
    assert m.resolver_pestana(libro, "BITACORA SECRETA") == ("hoja", 101)
    with pytest.raises(gspread.exceptions.WorksheetNotFound) as e:
        m.resolver_pestana(libro, "999")
    assert "2 pestañas" in str(e.value) and "SECRETA" not in str(e.value)


# ---------------------------------------------------------------- corrida completa y privacidad
def test_la_corrida_no_registra_datos_de_clientes(monkeypatch, caplog):
    hoja = HojaFalsa()
    filas = [fila_maxinet("2026-10-01", Cliente="MARIA SECRETA", **{"Delivery Details": "CALLE PRIVADA 123", "Comentarios": "NOTA PRIVADA"})]
    monkeypatch.setattr(m, "bloques_a_refrescar", lambda: [("2026-10-01", "2026-10-27")])
    monkeypatch.setattr(m, "descargar_bitacora", lambda d, h: m.normalizar_filas(filas))
    monkeypatch.setattr(m, "conectar_sheet", lambda: hoja)
    with caplog.at_level(logging.DEBUG):
        m.main()
    texto = caplog.text
    assert "completada con éxito (bloque de 1 servicios desde 2026-10-01)" in texto and "Validación OK" in texto
    for secreto in ("SECRETA", "PRIVADA", "CALLE"):
        assert secreto not in texto
    assert hoja.filas[0][I["Cliente"]] == "MARIA SECRETA"


def test_un_error_sale_con_codigo_1_y_sin_escribir(monkeypatch):
    hoja = HojaFalsa(encabezados=["otra", "cosa"])
    monkeypatch.setattr(m, "bloques_a_refrescar", lambda: [("2026-10-01", "2026-10-27")])
    monkeypatch.setattr(m, "descargar_bitacora", lambda d, h: _nuevas("2026-10-01"))
    monkeypatch.setattr(m, "conectar_sheet", lambda: hoja)
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 1 and hoja.escrituras == []
