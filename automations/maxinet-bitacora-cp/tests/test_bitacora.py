import datetime as dt
import logging

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
def test_hay_38_columnas_de_datos_mas_4_de_formulas():
    assert len(m.COLUMNAS) == 38 and len(m.ENCABEZADOS) == 42 and m.ANCHO_MAXINET == 39
    assert (m.COL_PROMESA, m.ULTIMA_COL_DATOS, m.PRIMERA_COL_AUX, m.ULTIMA_COL) == ("B", "AL", "AM", "AP")
    assert m.IDX["Fecha Prom."] == 1 and m.IDX["Asesor móvil"] == 18 and m.IDX["Comentarios"] == 36
    assert m.IDX["Fecha Justificación"] == 37 and m.COLUMNAS[-1] == "Fecha Justificación"
    assert m.IDX["Justificación retraso"] == 34                      # la columna AI


def test_las_formulas_son_las_de_la_copia_de_nuvia_y_cuadran_con_las_columnas():
    assert len(m.FORMULAS_AUX) == len(m.COLUMNAS_AUX) == 4
    assert [f.format(r=2) for f in m.FORMULAS_AUX] == [
        '=IF(B2="","", YEAR(B2))', '=IF(B2="","",TEXT(B2,"MMMM"))',
        '=IF(B2="","", IF(S2="","SIN ASESOR",S2))', '=IF(B2="","",TEXT(B2,"MMMM YYYY"))']
    assert chr(65 + m.IDX["Fecha Prom."]) == "B" and chr(65 + m.IDX["Asesor móvil"]) == "S"
    assert chr(65 + m.IDX["Estatus"]) == "K"


def test_la_pestana_por_defecto_es_la_del_mes_corriente():
    assert m.PESTANA_POR_DEFECTO == "BITACORA CP Mes Corriente"


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


def test_fecha_justificacion_pasa_a_fecha_y_hora():
    assert m._fecha_hora("2026-10-15 09:12:03", "x") == dia("2026-10-15") + (9 * 3600 + 12 * 60 + 3) / 86400
    assert m._fecha_hora("2026-10-15 9:12", "x") == dia("2026-10-15") + (9 * 3600 + 12 * 60) / 86400
    for malo in ("15/10/2026 09:12", "2026-10-15", ""):
        with pytest.raises(RuntimeError, match="Fecha Justificación"):
            m._fecha_hora(malo, "Fecha Justificación")


def test_importes_e_identificadores():
    assert m._numero("250.0000") == 250 and isinstance(m._numero("250.0000"), int)
    assert m._numero("229.93") == 229.93 and m._numero("$ 1,234.50") == 1234.5 and m._numero("-3") == -3
    assert m._numero("sin costo") == "sin costo"
    assert m._identificador("52950012") == 52950012
    assert m._identificador("#216490798") == "#216490798" and m._identificador("$34E46B1") == "$34E46B1"
    assert m._identificador("06000") == "06000" and m._identificador("1234567890123456") == "1234567890123456"


def test_normalizar_tipa_las_columnas_y_limpia_espacios():
    f = fila_maxinet("2026-11-05", "06:30:00", **{
        "Fecha Real": "2026-11-06", "Hora Real": "09:22:00", "Costo Rec.": "606.0000", "Uber": "229.93", "Dif. Dias": 33,
        "Cliente": "  CLIENTE PRUEBA ", "Placa": "ABC123D ", "# Cliente": "52950012", "Código Postal": "67174",
        "Cumpleaños": "1980-05-17", "Delivery Details": "CALLE 1\nCOL. X ", "Tiempo Trans.": "27 hs 12 min", "Asesor móvil": None,
        "Fecha Justificación": "2026-11-07 10:30:15"})
    (r,) = m.normalizar_filas([f])
    assert len(r) == 38
    assert r[I["Fecha Prom."]] == dia("2026-11-05") and r[I["Hora Prom."]] == 6.5 / 24
    assert r[I["Fecha Real"]] == dia("2026-11-06") and r[I["Hora Real"]] == (9 * 3600 + 22 * 60) / 86400
    assert r[I["Fecha GPS"]] == "" and r[I["Hora GPS"]] == ""
    assert r[I["Costo Ent.Dom"]] == 250 and r[I["Costo Rec."]] == 606 and r[I["Uber"]] == 229.93 and r[I["Dif. Dias"]] == 33
    assert r[I["Cliente"]] == "CLIENTE PRUEBA" and r[I["Placa"]] == "ABC123D"
    assert r[I["# Cliente"]] == 52950012 and r[I["Código Postal"]] == 67174 and r[I["Reserva"]] == "#100000001"
    assert r[I["Cumpleaños"]] == dia("1980-05-17") and r[I["Delivery Details"]] == "CALLE 1\nCOL. X"
    assert r[I["Tiempo Trans."]] == "27 hs 12 min" and r[I["Asesor móvil"]] == ""
    assert r[I["Fecha Justificación"]] == dia("2026-11-07") + (10 * 3600 + 30 * 60 + 15) / 86400


def test_ancho_distinto_detiene_la_corrida_y_el_reporte_viejo_de_37_columnas_tambien():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_maxinet("2026-11-05") + ["extra"]])
    viejo = fila_maxinet("2026-11-05")[:-1]                                  # 1 acción + 37 datos, como antes del 9-nov
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([viejo])


def test_servicio_sin_fecha_prom_detiene_la_corrida():
    with pytest.raises(RuntimeError, match="sin Fecha Prom"):
        m.normalizar_filas([fila_maxinet("")])


def test_orden_por_fecha_hora_reserva_y_tipo_y_no_se_descarta_nada(caplog):
    filas = [fila_maxinet("2026-11-02", "09:00:00", "#2"), fila_maxinet("2026-11-01", "10:00:00", "#9"),
             fila_maxinet("2026-11-01", "08:00:00", "#5", "COLLECT"), fila_maxinet("2026-11-01", "08:00:00", "#5", "DELIVER"),
             fila_maxinet("2026-11-01", "08:00:00", "#1")]
    with caplog.at_level(logging.WARNING):
        out = m.normalizar_filas(filas)
    assert [(r[I["Reserva"]], r[I["Tipo Serv."]]) for r in out] == [
        ("#1", "DELIVER"), ("#5", "COLLECT"), ("#5", "DELIVER"), ("#9", "DELIVER"), ("#2", "DELIVER")]
    assert caplog.text == ""
    with caplog.at_level(logging.WARNING):
        assert len(m.normalizar_filas([fila_maxinet("2026-11-01", reserva="#1"), fila_maxinet("2026-11-01", reserva="#1")])) == 2
    assert "misma Reserva y Tipo Serv." in caplog.text


# ---------------------------------------------------------------- rango de fechas: el mes corriente hasta hoy
def _hoy(monkeypatch, fecha):
    class Reloj(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(fecha.year, fecha.month, fecha.day, 8, 0, tzinfo=tz)
    monkeypatch.setattr(m.dt, "datetime", Reloj)


def test_el_rango_es_del_primero_del_mes_a_hoy(monkeypatch):
    _hoy(monkeypatch, dt.date(2026, 11, 9))
    assert m.rango_del_mes() == ("2026-11-01", "2026-11-09")


def test_el_dia_uno_el_rango_es_solo_ese_dia_y_no_el_mes_anterior(monkeypatch):
    _hoy(monkeypatch, dt.date(2026, 11, 1))
    assert m.rango_del_mes() == ("2026-11-01", "2026-11-01")
    _hoy(monkeypatch, dt.date(2026, 12, 31))
    assert m.rango_del_mes() == ("2026-12-01", "2026-12-31")


def test_fechas_manuales(monkeypatch):
    monkeypatch.setenv("FECHA_DESDE", "2026-09-01")
    monkeypatch.setenv("FECHA_HASTA", "2026-09-30")
    assert m.rango_del_mes() == ("2026-09-01", "2026-09-30")
    monkeypatch.delenv("FECHA_DESDE")
    assert m.rango_del_mes() == ("2026-09-01", "2026-09-30")


# ---------------------------------------------------------------- reemplazo del mes
def _nuevas(*promesas):
    return m.normalizar_filas([fila_maxinet(p, reserva=f"#{100 + i}") for i, p in enumerate(promesas)])


def test_hoja_vacia_escribe_desde_la_fila_2_datos_en_raw_y_formulas_por_fila():
    hoja = HojaFalsa()
    r = m.reemplazar_mes(hoja, _nuevas("2026-11-01", "2026-11-02"), "2026-11-01")
    assert r == {"antes": 0, "despues": 2, "nuevas": 2, "inicio": 2, "anteriores": 0}
    (r1, v1, modo1), (r2, v2, modo2) = hoja.escrituras
    assert (r1, modo1) == ("A2:AL3", "RAW") and len(v1) == 2 and all(len(v) == 38 for v in v1)
    assert (r2, modo2) == ("AM2:AP3", "USER_ENTERED")
    assert v2[0] == ['=IF(B2="","", YEAR(B2))', '=IF(B2="","",TEXT(B2,"MMMM"))', '=IF(B2="","", IF(S2="","SIN ASESOR",S2))', '=IF(B2="","",TEXT(B2,"MMMM YYYY"))']
    assert v2[1][0] == '=IF(B3="","", YEAR(B3))' and "S3" in v2[1][2]
    assert hoja.limpiezas == []


def test_elimina_las_filas_de_meses_anteriores_y_deja_solo_el_mes_corriente():
    octubre = [fila_hoja("2026-10-29", Cliente="OCT"), fila_hoja("2026-10-31", Cliente="OCT")]
    noviembre_viejo = [fila_hoja("2026-11-01", Cliente="VIEJO")]
    hoja = HojaFalsa(octubre + noviembre_viejo)
    nuevas = m.normalizar_filas([fila_maxinet("2026-11-01", reserva="#1", Cliente="NUEVO1"), fila_maxinet("2026-11-02", reserva="#2")])
    r = m.reemplazar_mes(hoja, nuevas, "2026-11-01")
    assert r["antes"] == 1 and r["despues"] == 2 and r["nuevas"] == 1 and r["anteriores"] == 2 and r["inicio"] == 2
    assert [f[I["Cliente"]] for f in hoja.filas[:2]] == ["NUEVO1", "CLIENTE PRUEBA"]
    assert hoja.escrituras[0][0] == "A2:AL3"
    assert hoja.limpiezas == ["A4:AL4"]                                   # sobraba una fila (eran 3, quedan 2)
    assert all(c == "" for c in hoja.filas[2][:38])
    assert all(f[I["Cliente"]] != "OCT" for f in hoja.filas if f[I["Cliente"]])


def test_al_cambiar_de_mes_la_pestana_queda_solo_con_el_mes_nuevo_sin_activar_la_salvaguarda():
    octubre = [fila_hoja("2026-10-15", Cliente="OCT") for _ in range(100)]
    hoja = HojaFalsa(octubre)
    r = m.reemplazar_mes(hoja, _nuevas("2026-11-01", "2026-11-01"), "2026-11-01")      # 2 contra 100 de octubre
    assert r["antes"] == 0 and r["anteriores"] == 100 and r["despues"] == 2
    assert hoja.limpiezas == ["A4:AL101"] and all(c == "" for f in hoja.filas[2:] for c in f[:38])


def test_las_formulas_auxiliares_nunca_se_borran():
    viejas = [fila_hoja(f"2026-11-0{d}") for d in (1, 2, 3, 4)]
    for i, f in enumerate(viejas):
        f[38:] = [f"=F{i}", "=g", "=h", "=i"]
    hoja = HojaFalsa(viejas)
    m.reemplazar_mes(hoja, _nuevas("2026-11-01", "2026-11-02"), "2026-11-01")
    assert hoja.limpiezas == ["A4:AL5"]
    assert all(c == "" for c in hoja.filas[2][:38] + hoja.filas[3][:38])
    assert hoja.filas[2][38:] == ["=F2", "=g", "=h", "=i"] and hoja.filas[3][38:] == ["=F3", "=g", "=h", "=i"]


def test_un_servicio_prometido_el_primer_dia_es_del_mes_corriente():
    hoja = HojaFalsa([fila_hoja("2026-10-31", Cliente="OCT"), fila_hoja("2026-11-01", Cliente="VIEJO")])
    r = m.reemplazar_mes(hoja, m.normalizar_filas([fila_maxinet("2026-11-01", Cliente="NUEVO")]), "2026-11-01")
    assert r["antes"] == 1 and r["anteriores"] == 1
    assert [f[I["Cliente"]] for f in hoja.filas[:1]] == ["NUEVO"] and all(c == "" for c in hoja.filas[1][:38])


def test_la_hoja_no_tiene_que_estar_ordenada_para_limpiar_meses_anteriores():
    hoja = HojaFalsa([fila_hoja("2026-11-03"), fila_hoja("2026-10-20"), fila_hoja("2026-11-01")])
    r = m.reemplazar_mes(hoja, _nuevas("2026-11-01", "2026-11-03"), "2026-11-01")
    assert r["antes"] == 2 and r["anteriores"] == 1 and hoja.limpiezas == ["A4:AL4"]


def test_salvaguarda_del_80_por_ciento_solo_cuenta_las_filas_del_mes(monkeypatch):
    hoja = HojaFalsa([fila_hoja("2026-11-01") for _ in range(40)])
    with pytest.raises(RuntimeError, match="menos del 80%"):
        m.reemplazar_mes(hoja, _nuevas(*["2026-11-01"] * 10), "2026-11-01")
    assert hoja.escrituras == []
    monkeypatch.setenv("FORZAR", "1")
    m.reemplazar_mes(hoja, _nuevas(*["2026-11-01"] * 10), "2026-11-01")
    assert len(hoja.escrituras) == 2


def test_una_respuesta_vacia_no_borra_el_mes_que_ya_esta_en_la_pestana(monkeypatch):
    hoja = HojaFalsa([fila_hoja("2026-11-01")])
    with pytest.raises(RuntimeError, match="no trae servicios del mes"):
        m.reemplazar_mes(hoja, [], "2026-11-01")
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_sin_servicios_del_mes_todavia_se_eliminan_los_meses_anteriores():
    hoja = HojaFalsa([fila_hoja("2026-10-30"), fila_hoja("2026-10-31")])
    r = m.reemplazar_mes(hoja, [], "2026-11-01")
    assert r["despues"] == 0 and r["anteriores"] == 2 and hoja.escrituras == [] and hoja.limpiezas == ["A2:AL3"]
    assert m.reemplazar_mes(HojaFalsa(), [], "2026-11-01")["anteriores"] == 0


def test_dry_run_no_escribe_nada(monkeypatch, caplog):
    hoja = HojaFalsa([fila_hoja("2026-10-31")])
    monkeypatch.setenv("DRY_RUN", "1")
    with caplog.at_level(logging.INFO):
        m.reemplazar_mes(hoja, _nuevas("2026-11-01"), "2026-11-01")
    assert hoja.escrituras == [] and hoja.limpiezas == [] and hoja.spreadsheet.peticiones == []
    assert "DRY_RUN: la pestaña quedaría con 1 filas del mes en A2:AL2 y 1 filas de meses anteriores eliminadas" in caplog.text
    assert "Bloque desde 2026-11-01: filas 0 -> 1 | nuevas 1" in caplog.text          # formato que lee la guardia


@pytest.mark.parametrize("cambio", ["intercambiar", "falta_aux", "otro_nombre", "falta_fecha_justificacion", "faltan_aux_y_fecha"])
def test_encabezados_distintos_detienen_la_corrida_sin_escribir(cambio):
    enc = list(m.ENCABEZADOS)
    if cambio == "intercambiar":
        enc[6], enc[7] = enc[7], enc[6]
    elif cambio == "falta_aux":
        enc = enc[:-1]
    elif cambio == "otro_nombre":
        enc[39] = "MES2"
    elif cambio == "falta_fecha_justificacion":
        enc.remove("Fecha Justificación")                                    # el encabezado de 41 columnas, antes del 9-nov
    else:
        enc = enc[:37]
    hoja = HojaFalsa(encabezados=enc)
    with pytest.raises(RuntimeError, match="encabezados"):
        m.reemplazar_mes(hoja, _nuevas("2026-11-01"), "2026-11-01")
    assert hoja.escrituras == [] and hoja.limpiezas == []


def test_un_texto_extra_a_la_derecha_de_la_fila_1_no_estorba():
    hoja = HojaFalsa(encabezados=list(m.ENCABEZADOS) + ["http://origen-del-reporte"])
    m.reemplazar_mes(hoja, _nuevas("2026-11-01"), "2026-11-01")
    assert len(hoja.escrituras) == 2


def test_escribe_en_tandas_y_agrega_filas_si_faltan(monkeypatch):
    monkeypatch.setattr(m, "FILAS_POR_ESCRITURA", 2)
    hoja = HojaFalsa()
    hoja.row_count = 3
    m.reemplazar_mes(hoja, _nuevas(*[f"2026-11-0{d}" for d in (1, 2, 3, 4, 5)]), "2026-11-01")
    assert [e[0] for e in hoja.escrituras] == ["A2:AL3", "AM2:AP3", "A4:AL5", "AM4:AP5", "A6:AL6", "AM6:AP6"]
    assert hoja.filas_agregadas == [203] and len(hoja.filas) == 5


def test_da_formato_a_fechas_horas_importes_y_fecha_justificacion():
    hoja = HojaFalsa()
    m.reemplazar_mes(hoja, _nuevas("2026-11-01"), "2026-11-01")
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones]
    formatos = {p["range"]["startColumnIndex"]: (p["cell"]["userEnteredFormat"]["numberFormat"]["type"],
                                                 p["cell"]["userEnteredFormat"]["numberFormat"]["pattern"]) for p in pedidos}
    assert formatos == {1: ("DATE", "d/M/yyyy"), 3: ("DATE", "d/M/yyyy"), 5: ("DATE", "yyyy-mm-dd"), 21: ("DATE", "yyyy-mm-dd"),
                        2: ("TIME", "h:mm:ss"), 4: ("TIME", "h:mm:ss"), 6: ("TIME", "h:mm:ss"),
                        23: ("CURRENCY", '"$"#,##0.00'), 24: ("CURRENCY", '"$"#,##0.00'), 25: ("CURRENCY", '"$"#,##0.00'),
                        37: ("DATE_TIME", "yyyy-mm-dd h:mm:ss")}
    assert all(p["range"]["startRowIndex"] == 1 and p["range"]["endRowIndex"] == 2 for p in pedidos)


def test_un_texto_que_parece_formula_se_escribe_tal_cual_y_en_raw():
    hoja = HojaFalsa()
    filas = m.normalizar_filas([fila_maxinet("2026-11-01", **{"Delivery Details": '=HYPERLINK("http://x","y")', "Tiempo Trans.": "-43 min"})])
    m.reemplazar_mes(hoja, filas, "2026-11-01")
    rango, valores, modo = hoja.escrituras[0]
    assert modo == "RAW" and valores[0][I["Delivery Details"]] == '=HYPERLINK("http://x","y")' and valores[0][I["Tiempo Trans."]] == "-43 min"


def test_validar_orden():
    hoja = HojaFalsa([fila_hoja("2026-11-01"), fila_hoja("2026-11-02")])
    m.validar_orden(hoja, 2, 2)
    with pytest.raises(RuntimeError, match="se esperaban 3"):
        m.validar_orden(hoja, 2, 3)
    hoja.filas.reverse()
    with pytest.raises(RuntimeError, match="orden ascendente"):
        m.validar_orden(hoja, 2, 2)


# ---------------------------------------------------------------- justificaciones (columna AI)
def _just(**campos):
    base = {"Justificación retraso": "Se justificó", "Estatus Serv.": "EN TIEMPO", "Semáforo": "verde", "Motivo retraso": "Cliente no disponible",
            "Responsable justificación": "alguien.interno", "Fecha Justificación": "2026-11-05 10:00:00"}
    base.update(campos)
    return m.normalizar_filas([fila_maxinet("2026-11-04", **base)])[0]


def test_un_servicio_justificado_cuadra_cuando_maxinet_lo_dejo_en_tiempo_y_verde(caplog):
    filas = [_just(), m.normalizar_filas([fila_maxinet("2026-11-04", **{"Estatus Serv.": "RETRASO", "Semáforo": "rojo"})])[0]]
    with caplog.at_level(logging.INFO):
        r = m.revisar_justificaciones(filas)
    assert r == {"justificadas": 1, "problemas": {}}
    assert "1 de 2 servicios justificados" in caplog.text and "no cuadran" not in caplog.text


@pytest.mark.parametrize("campos,problema", [
    ({"Estatus Serv.": "RETRASO"}, "Estatus Serv. distinto de EN TIEMPO"),
    ({"Semáforo": "rojo"}, "Semáforo distinto de verde"),
    ({"Motivo retraso": ""}, "sin Motivo retraso"),
    ({"Responsable justificación": ""}, "sin Responsable justificación"),
    ({"Fecha Justificación": ""}, "sin Fecha Justificación"),
])
def test_avisa_cuando_una_fila_justificada_no_quedo_como_debe(caplog, campos, problema):
    with caplog.at_level(logging.WARNING):
        r = m.revisar_justificaciones([_just(**campos)])
    assert r["problemas"] == {problema: 1} and problema in caplog.text


def test_avisa_de_datos_de_justificacion_sin_justificacion_retraso(caplog):
    fila = m.normalizar_filas([fila_maxinet("2026-11-04", **{"Motivo retraso": "Algo", "Justificación retraso": ""})])[0]
    with caplog.at_level(logging.WARNING):
        r = m.revisar_justificaciones([fila])
    assert r["problemas"] == {"datos de justificación sin Justificación retraso": 1}


def test_la_validacion_no_modifica_las_filas_ni_registra_texto_de_clientes(caplog):
    fila = _just(**{"Justificación retraso": "TEXTO PRIVADO DEL CLIENTE", "Estatus Serv.": "RETRASO"})
    copia = list(fila)
    with caplog.at_level(logging.DEBUG):
        m.revisar_justificaciones([fila])
    assert fila == copia and "PRIVADO" not in caplog.text and "alguien.interno" not in caplog.text


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
def _preparar(monkeypatch, hoja, filas, rango=("2026-11-01", "2026-11-09")):
    visto = {}
    monkeypatch.setattr(m, "rango_del_mes", lambda: rango)
    monkeypatch.setattr(m, "descargar_bitacora", lambda d, h: visto.update(rango=(d, h)) or m.normalizar_filas(filas))
    monkeypatch.setattr(m, "conectar_sheet", lambda: hoja)
    return visto


def test_la_corrida_pide_el_mes_corriente_hasta_hoy_y_no_registra_datos_de_clientes(monkeypatch, caplog):
    hoja = HojaFalsa([fila_hoja("2026-10-30")])
    filas = [fila_maxinet("2026-11-01", Cliente="MARIA SECRETA", **{"Delivery Details": "CALLE PRIVADA 123", "Comentarios": "NOTA PRIVADA"})]
    visto = _preparar(monkeypatch, hoja, filas)
    with caplog.at_level(logging.DEBUG):
        m.main()
    texto = caplog.text
    assert visto["rango"] == ("2026-11-01", "2026-11-09")
    assert "completada con éxito (bloque de 1 servicios desde 2026-11-01)" in texto and "Validación OK" in texto
    for secreto in ("SECRETA", "PRIVADA", "CALLE"):
        assert secreto not in texto
    assert hoja.filas[0][I["Cliente"]] == "MARIA SECRETA"
    assert all(c == "" for f in hoja.filas[1:] for c in f[:38])                      # el mes anterior ya no está


def test_la_corrida_avisa_de_las_justificaciones_que_no_cuadran(monkeypatch, caplog):
    hoja = HojaFalsa()
    filas = [fila_maxinet("2026-11-01", **{"Justificación retraso": "x", "Estatus Serv.": "RETRASO"})]
    _preparar(monkeypatch, hoja, filas)
    with caplog.at_level(logging.INFO):
        m.main()
    assert "Justificaciones que no cuadran" in caplog.text


def test_un_error_sale_con_codigo_1_y_sin_escribir(monkeypatch):
    hoja = HojaFalsa(encabezados=["otra", "cosa"])
    _preparar(monkeypatch, hoja, [fila_maxinet("2026-11-01")])
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 1 and hoja.escrituras == []
