import datetime as dt
import json

import pytest

import maxinet_mtto_taller as m
from tests.fakes import HojaFalsa, Libro, fila_hoja, fila_reporte

SERIE_5_OCT = (dt.date(2026, 10, 5) - dt.date(1899, 12, 30)).days


@pytest.fixture(autouse=True)
def limpiar_entorno(monkeypatch):
    for v in ("FECHA_DESDE", "FECHA_HASTA", "DRY_RUN", "FORZAR", "WORKSHEET_MTTO_TALLER"):
        monkeypatch.delenv(v, raising=False)


def _hoja_con(*filas_hoja, **kw):
    return HojaFalsa([m.ENCABEZADO] + [list(f) for f in filas_hoja], **kw)


def _filas(*ids, ingreso="2026-10-05", estatus="CERRADO"):
    return [fila_hoja(i, ingreso, estatus) for i in ids]


def _correr(hoja, nuevas, desde="2026-01-01", hasta="2026-11-03"):
    """Lo que hace main() entre leer la hoja y escribir, sin red."""
    existentes, ultima, vacia = m.leer_hoja(hoja)
    plan = m.planear(existentes, nuevas, desde, hasta)
    m.revisar_volumen(plan)
    m.escribir(hoja, hoja.spreadsheet, existentes, ultima, vacia, plan, desde, hasta)
    return plan


# ---------------------------------------------------------------- forma del reporte
def test_el_reporte_tiene_62_columnas_y_la_hoja_59_sin_botones():
    assert m.ANCHO_REPORTE == 62
    assert len(m.ENCABEZADO) == 59 and m.ENCABEZADO[0] == "Id" and m.ENCABEZADO[-1] == "IdApp"
    assert "" not in m.ENCABEZADO and "Nombre Contacto" in m.ENCABEZADO and "Correo" in m.ENCABEZADO
    assert m.ULT_COL == "BG" and m.COL_ESTADO == "BI"
    assert m.FECHAS | m.HORAS | m.NUMEROS <= set(m.ENCABEZADO)


def test_el_encabezado_coincide_con_la_lista_de_columnas_pedida():
    pedidas = ("Id,Tipo ticket,Estatus,Tipo Servicio,Sub Tipo,No.Placa,PUSite,# Reserva,# Cliente,Nombre Cliente,Grupo,"
               "Marca,Modelo,Km.Actual,Ciudad,Taller,Fecha Alta,Hora Alta,Fecha Prop.Cita,Hora Prop.Cita,Fecha Cita,"
               "Hora Cita,Fecha Ingreso Taller,Dias Cte. Entr. Taller,Hora Ingreso Taller,Fecha Promesa,Hora Promesa,"
               "Fecha Diagnóstico,Hora Diagnóstico,Fecha T.Terminado,Hora T.Terminado,Fecha Entrega Cliente,Dias Taller,"
               "Hora Entrega Cliente,Fecha Cierre,Hora Cierre,Fecha Reingreso,Hora Reingreso,Motivo Reingreso,Facturado,"
               "Pagado,Costo Total,Cobro cliente,Monto cliente,Costo Real,Comentarios Cliente,Diagnóstico,"
               "Se ha realizado la afinación de esta unidad?,CANTIDAD LLANTAS,Responsable Alta,Nombre Contacto,"
               "Tel. Contacto,Cel. Contacto,Correo,PUDate,ReturnDate,Asesor,Origen,IdApp").split(",")
    assert m.ENCABEZADO == pedidas


# ---------------------------------------------------------------- ventana
@pytest.mark.parametrize("hoy,esperado", [
    (dt.date(2026, 11, 3), ("2026-01-01", "2026-11-03")),
    (dt.date(2026, 1, 1), ("2026-01-01", "2026-01-01")),
    (dt.date(2027, 1, 4), ("2027-01-01", "2027-01-04")),
])
def test_ventana_es_del_primero_de_enero_a_hoy(hoy, esperado):
    assert m.ventana(hoy) == esperado


def test_la_ventana_retrocede_hasta_la_orden_sin_cerrar_mas_antigua():
    assert m.ventana(dt.date(2027, 1, 4), pendiente_desde="2026-12-18") == ("2026-12-18", "2027-01-04")
    assert m.ventana(dt.date(2026, 11, 3), pendiente_desde="2026-05-07") == ("2026-01-01", "2026-11-03")


def test_override_de_fechas(monkeypatch):
    monkeypatch.setenv("FECHA_DESDE", "2026-10-05")
    monkeypatch.setenv("FECHA_HASTA", "2026-10-20")
    assert m.ventana(dt.date(2026, 10, 27), pendiente_desde="2026-01-02") == ("2026-10-05", "2026-10-20")


def test_pendiente_desde_ignora_cerradas_y_toma_la_mas_antigua_abierta():
    hoja = _hoja_con(fila_hoja(1, "2026-02-01", "CERRADO"), fila_hoja(2, "2026-03-10", "EN TALLER"),
                     fila_hoja(3, "2026-04-01", "DIAGNOSTICO"), fila_hoja(4, "2026-01-05", "CITA RECHAZADA"))
    existentes, _, _ = m.leer_hoja(hoja)
    assert m.pendiente_desde(existentes) == "2026-03-10"
    todas_cerradas = _hoja_con(*_filas(1, 2))
    assert m.pendiente_desde(m.leer_hoja(todas_cerradas)[0]) is None


# ---------------------------------------------------------------- limpieza y tipos
def test_texto_quita_html_entidades_y_none():
    assert m._texto('<a class="x" href="y">Detalle</a>') == "Detalle"
    assert m._texto("A &amp; B&nbsp;") == "A & B"
    assert m._texto(None) == "" and m._texto("None") == "" and m._texto("  ") == ""


def test_normalizar_limpia_los_62_valores_y_el_estatus():
    fila = m.normalizar_filas([fila_reporte(25861, estatus="TRABAJO TERMINADO")])[0]
    assert len(fila) == 62 and fila[0] == "Detalle"
    assert fila[m.COLUMNAS_REPORTE.index("Estatus")] == "TRABAJO TERMINADO"      # sin el espacio inicial
    assert fila[m.COLUMNAS_REPORTE.index("Motivo Reingreso")] == ""            # 'None' -> vacío


def test_ancho_distinto_detiene_sin_escribir():
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte(1)[:61]])
    with pytest.raises(RuntimeError, match="cambió el ancho"):
        m.normalizar_filas([fila_reporte(1) + ["x"]])


@pytest.mark.parametrize("campo,valor", [("Id", "abc"), ("Fecha Alta", "05/10/2026"),
                                         ("Fecha Ingreso Taller", "None"), ("No.Placa", "None")])
def test_columnas_que_no_cuadran_detienen_sin_escribir(campo, valor):
    with pytest.raises(RuntimeError, match="no cuadran"):
        m.normalizar_filas([fila_reporte(1, **{campo: valor})])


def test_fechas_horas_y_numeros_se_tipan():
    assert m._valor("Fecha Alta", "2026-10-05") == SERIE_5_OCT
    assert m._valor("Hora Alta", "09:28") == pytest.approx((9 * 60 + 28) / 1440)
    assert m._valor("Id", "25861") == 25861 and isinstance(m._valor("Id", "25861"), int)
    assert m._valor("Costo Total", "3665.60") == 3665.6
    assert m._valor("Costo Total", "1,234.50") == 1234.5
    assert m._valor("Dias Taller", "0.5") == 0.5


@pytest.mark.parametrize("nombre,texto", [
    ("Fecha Promesa", "0026-07-15"), ("Fecha Cita", "2026-02-30"), ("Hora Alta", "25:99"), ("Costo Total", "N/A"),
    ("# Reserva", "#217079644"), ("Tel. Contacto", "8113279900"), ("Motivo Reingreso", "=SUM(A1)"), ("No.Placa", "1E5"),
])
def test_lo_que_no_tiene_la_forma_esperada_queda_como_texto(nombre, texto):
    assert m._valor(nombre, texto) == texto and isinstance(m._valor(nombre, texto), str)


def test_la_fila_de_la_hoja_incluye_los_datos_de_contacto_pedidos():
    fila = fila_hoja(25861, "2026-10-05", "EN TALLER", "TEX769B")
    assert len(fila) == 59
    assert fila[m.COL_ID] == 25861 and fila[m.COL_INGRESO] == SERIE_5_OCT
    assert fila[m.ENCABEZADO.index("Correo")] == "privado@example.com"
    assert fila[m.ENCABEZADO.index("Tel. Contacto")] == "8100000000"


# ---------------------------------------------------------------- comparación (misma orden, mismo dato)
@pytest.mark.parametrize("nombre,en_hoja,de_maxinet", [
    ("Fecha Ingreso Taller", "2026-10-05", SERIE_5_OCT),                   # fecha guardada como texto
    ("Fecha Ingreso Taller", float(SERIE_5_OCT), SERIE_5_OCT),
    ("Hora Alta", "09:28", (9 * 60 + 28) / 1440),                          # hora como texto
    ("Hora Alta", 0.3944444444444, (9 * 60 + 28) / 1440),                  # error de coma flotante de Sheets
    ("Tel. Contacto", 8113279900, "8113279900"),                           # teléfono guardado como número
    ("Estatus", " EN TALLER ", "EN TALLER"),
    ("Costo Total", "3,665.60", 3665.6),
    ("Costo Total", 3665.6, 3665.6),
    ("Motivo Reingreso", None, ""),
])
def test_canonico_no_cuenta_diferencias_de_formato_como_cambios(nombre, en_hoja, de_maxinet):
    assert m.canonico(nombre, en_hoja) == m.canonico(nombre, de_maxinet)


@pytest.mark.parametrize("nombre,en_hoja,de_maxinet", [
    ("Estatus", "EN TALLER", "TRABAJO TERMINADO"),
    ("Fecha Cierre", "", SERIE_5_OCT),
    ("Costo Total", 3665.6, 3700.0),
    ("Hora Alta", "09:28", (9 * 60 + 29) / 1440),
])
def test_canonico_si_distingue_cambios_reales(nombre, en_hoja, de_maxinet):
    assert m.canonico(nombre, en_hoja) != m.canonico(nombre, de_maxinet)


# ---------------------------------------------------------------- actualizar por Id
def test_primera_carga_en_una_pestana_vacia_escribe_encabezado_y_todas_las_ordenes():
    hoja = HojaFalsa([])
    plan = _correr(hoja, _filas(3, 1, 2))
    assert (len(plan["altas"]), len(plan["cambios"])) == (3, 0)
    assert hoja.celdas[0][:len(m.ENCABEZADO)] == m.ENCABEZADO
    assert [f[m.COL_ID] for f in hoja.celdas[1:4]] == [1, 2, 3]            # altas ordenadas por Id


def test_sin_cambios_no_hay_nada_que_escribir():
    hoja = _hoja_con(*_filas(1, 2, 3))
    existentes, _, _ = m.leer_hoja(hoja)
    plan = m.planear(existentes, _filas(1, 2, 3), "2026-01-01", "2026-11-03")
    assert (plan["iguales"], plan["cambios"], plan["altas"]) == (3, [], [])


def test_actualiza_en_su_lugar_solo_las_filas_que_cambiaron_y_agrega_las_nuevas_al_final():
    hoja = _hoja_con(fila_hoja(10, estatus="EN TALLER"), *_filas(11, 12), fila_hoja(13, estatus="DIAGNOSTICO"))
    nuevas = [fila_hoja(10, estatus="CERRADO"), fila_hoja(11), fila_hoja(12), fila_hoja(13, estatus="EN TALLER"),
              fila_hoja(20), fila_hoja(21)]
    plan = _correr(hoja, nuevas)
    assert [n for n, _ in plan["cambios"]] == [2, 5]                       # filas de las órdenes 10 y 13
    assert [f[m.COL_ID] for f in plan["altas"]] == [20, 21]
    assert [f[m.COL_ID] for f in hoja.celdas[1:7]] == [10, 11, 12, 13, 20, 21]
    assert hoja.celdas[1][m.COL_ESTATUS] == "CERRADO" and hoja.celdas[4][m.COL_ESTATUS] == "EN TALLER"
    rangos = [r for r, _ in hoja.escrituras]
    assert "A2:BG2" in rangos and "A5:BG5" in rangos and "A6:BG7" in rangos
    assert "A3:BG3" not in rangos and "A4:BG4" not in rangos               # las filas iguales no se tocan


def test_una_orden_que_maxinet_ya_no_muestra_conserva_su_ultima_version():
    hoja = _hoja_con(*_filas(1, 2, 3))
    plan = _correr(hoja, _filas(1, 3))
    assert plan["fuera_de_maxinet"] == 1 and plan["cambios"] == [] and plan["altas"] == []
    assert [f[m.COL_ID] for f in hoja.celdas[1:4]] == [1, 2, 3]


def test_no_toca_columnas_a_la_derecha_de_los_datos():
    fila_con_extra = list(fila_hoja(1, estatus="EN TALLER")) + ["", "", "FORMULA"]    # BH vacía, BI vacía, BJ
    hoja = _hoja_con(fila_con_extra)
    _correr(hoja, [fila_hoja(1, estatus="CERRADO")])
    assert hoja.celdas[1][m.COL_ESTATUS] == "CERRADO" and hoja.celdas[1][len(m.ENCABEZADO) + 2] == "FORMULA"


def test_una_fila_ajena_al_pie_no_es_orden_ni_se_pisa_al_agregar():
    hoja = _hoja_con(*_filas(1, 2), ["TOTAL", "", ""])
    existentes, ultima, _ = m.leer_hoja(hoja)
    assert sorted(existentes) == [1, 2] and ultima == 4                    # la fila del total cuenta como ocupada
    _correr(hoja, _filas(1, 2, 3))
    assert hoja.celdas[3][0] == "TOTAL" and hoja.celdas[4][m.COL_ID] == 3


def test_amplia_la_hoja_si_las_filas_no_caben():
    hoja = _hoja_con(*_filas(1))
    hoja.row_count = 2
    _correr(hoja, _filas(1, 2, 3, 4))
    assert hoja.filas_agregadas > 0 and hoja.row_count >= 5


def test_da_formato_de_fecha_hora_y_costo_solo_a_las_filas_nuevas():
    hoja = _hoja_con(*_filas(1))
    _correr(hoja, _filas(1, 2, 3))
    pedidos = [p["repeatCell"] for p in hoja.spreadsheet.peticiones if "repeatCell" in p]
    tipos = [p["cell"]["userEnteredFormat"]["numberFormat"]["type"] for p in pedidos]
    assert tipos.count("DATE") == len(m.FECHAS) and tipos.count("TIME") == len(m.HORAS) and tipos.count("NUMBER") == 3
    assert {(p["range"]["startRowIndex"], p["range"]["endRowIndex"]) for p in pedidos} == {(2, 4)}   # filas 3 y 4


def test_deja_la_hora_de_actualizacion_en_la_columna_bi_sin_pisar_contenido_ajeno():
    hoja = _hoja_con(*_filas(1))
    _correr(hoja, _filas(1, 2))
    rango, valores = hoja.escrituras[-1]
    assert rango == "BI1:BI4" and valores[0] == [m.MARCA_ACTUALIZADO] and valores[3] == ["2026-01-01 a 2026-11-03"]
    ajena = _hoja_con(*_filas(1))
    ajena.celdas[0] += ["", "MI NOTA"]                                    # BH vacía y BI ocupada
    _correr(ajena, _filas(1, 2))
    assert not any(r.startswith("BI") for r, _ in ajena.escrituras)


def test_la_hora_de_actualizacion_tampoco_pisa_las_celdas_de_abajo():
    hoja = _hoja_con(list(fila_hoja(1)) + ["", "", ""], list(fila_hoja(2)) + ["", "FORMULA"])   # BI3 ocupada
    _correr(hoja, _filas(1, 2, 3))
    assert hoja.celdas[2][len(m.ENCABEZADO) + 1] == "FORMULA"
    assert not any(r.startswith("BI") for r, _ in hoja.escrituras)


# ---------------------------------------------------------------- salvaguardas
def test_encabezado_distinto_detiene_sin_escribir():
    hoja = HojaFalsa([["Otra", "cosa"] + m.ENCABEZADO[2:], *_filas(1)])
    with pytest.raises(RuntimeError, match="encabezado distinto"):
        _correr(hoja, _filas(1))
    assert hoja.escrituras == []


def test_id_repetido_en_la_hoja_detiene_sin_escribir():
    hoja = _hoja_con(*_filas(1, 2, 2))
    with pytest.raises(RuntimeError, match="repite 1 Id"):
        _correr(hoja, _filas(1, 2, 3))
    assert hoja.escrituras == []


def test_salvaguarda_si_maxinet_trae_menos_del_80_por_ciento_de_lo_que_ya_esta():
    hoja = _hoja_con(*_filas(*range(1, 41)))
    with pytest.raises(RuntimeError, match="más del 20%"):
        _correr(hoja, _filas(*range(1, 31)))
    assert hoja.escrituras == []


def test_ordenes_de_otros_anios_en_la_hoja_no_cuentan_como_faltantes():
    hoja = _hoja_con(*_filas(*range(1, 41), ingreso="2025-06-01"))
    plan = _correr(hoja, _filas(*range(100, 110)), desde="2026-01-01")
    assert plan["ausentes"] == 0 and len(plan["altas"]) == 10


def test_forzar_omite_las_salvaguardas_de_volumen(monkeypatch):
    monkeypatch.setenv("FORZAR", "1")
    hoja = _hoja_con(*_filas(*range(1, 41)))
    plan = _correr(hoja, _filas(*range(1, 31)))
    assert plan["ausentes"] == 10 and plan["cambios"] == [] and plan["altas"] == []


def test_salvaguarda_de_cambio_masivo_de_filas():
    hoja = _hoja_con(*_filas(*range(1, 301)))
    nuevas = _filas(*range(1, 301), estatus="CANCELADO")                   # el 100% cambiaría
    with pytest.raises(RuntimeError, match="más del 30%"):
        _correr(hoja, nuevas)
    assert hoja.escrituras == []


def test_un_movimiento_normal_de_filas_no_dispara_el_cambio_masivo():
    hoja = _hoja_con(*_filas(*range(1, 301), estatus="EN TALLER"))
    nuevas = _filas(*range(1, 31), estatus="CERRADO") + _filas(*range(31, 301), estatus="EN TALLER")
    plan = _correr(hoja, nuevas)
    assert len(plan["cambios"]) == 30


def test_si_la_hoja_cambia_a_media_corrida_no_escribe():
    hoja = _hoja_con(*_filas(1, 2, 3))
    existentes, ultima, vacia = m.leer_hoja(hoja)
    plan = m.planear(existentes, [fila_hoja(1, estatus="EN TALLER"), *_filas(2, 3)], "2026-01-01", "2026-11-03")
    hoja.celdas.insert(1, list(fila_hoja(99)))                             # alguien insertó una fila arriba
    with pytest.raises(RuntimeError, match="cambió mientras se preparaba"):
        m.escribir(hoja, hoja.spreadsheet, existentes, ultima, vacia, plan, "2026-01-01", "2026-11-03")
    assert hoja.escrituras == []


def test_valida_la_columna_id_despues_de_escribir():
    hoja = _hoja_con(*_filas(1, 2))

    def estropear():                                                       # alguien ordena la hoja justo al escribir
        hoja.celdas[1], hoja.celdas[2] = hoja.celdas[2], hoja.celdas[1]
    hoja.alterar_antes_de_escribir = estropear
    with pytest.raises(RuntimeError, match="Validación fallida"):
        _correr(hoja, [fila_hoja(1, estatus="EN TALLER"), *_filas(2, 3)])


def test_si_maxinet_no_trae_ninguna_orden_la_corrida_falla_sin_escribir(monkeypatch):
    hoja = _hoja_con(*_filas(1, 2))
    libro = Libro([hoja])
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    monkeypatch.setattr(m, "conectar_libro", lambda: libro)
    monkeypatch.setattr(m, "login_maxinet", lambda: _SesionFalsa('{"data":""}'))
    with pytest.raises(SystemExit) as salida:
        m.main()
    assert salida.value.code == 1 and hoja.escrituras == [] and libro.peticiones == []


# ---------------------------------------------------------------- DRY_RUN y pestañas
def test_resolver_pestana_por_nombre_gid_o_unica(monkeypatch):
    a, b = HojaFalsa([], titulo="ORDENES", gid=5), HojaFalsa([], titulo="OTRA", gid=9)
    libro = Libro([a, b])
    with pytest.raises(RuntimeError, match="2 pestañas"):
        m.resolver_pestana(libro)
    monkeypatch.setenv("WORKSHEET_MTTO_TALLER", ' "OTRA" ')
    assert m.resolver_pestana(libro) is b
    monkeypatch.setenv("WORKSHEET_MTTO_TALLER", "5")
    assert m.resolver_pestana(libro) is a
    monkeypatch.setenv("WORKSHEET_MTTO_TALLER", "404")
    with pytest.raises(Exception, match="2 pestañas"):
        m.resolver_pestana(libro)
    monkeypatch.delenv("WORKSHEET_MTTO_TALLER")
    assert m.resolver_pestana(Libro([a])) is a


def test_dry_run_no_escribe_nada(monkeypatch):
    hoja = _hoja_con(*_filas(1))
    libro = Libro([hoja])
    cuerpo = json.dumps({"data": [fila_reporte(1, estatus="EN TALLER"), fila_reporte(2)]})
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    monkeypatch.setattr(m, "conectar_libro", lambda: libro)
    monkeypatch.setattr(m, "login_maxinet", lambda: _SesionFalsa(cuerpo))
    m.main()
    assert hoja.escrituras == [] and libro.peticiones == []


def test_corrida_completa_actualiza_y_agrega(monkeypatch):
    hoja = _hoja_con(fila_hoja(1, estatus="EN TALLER"))
    libro = Libro([hoja])
    cuerpo = json.dumps({"data": [fila_reporte(1, estatus="CERRADO"), fila_reporte(2)]})
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    monkeypatch.setattr(m, "conectar_libro", lambda: libro)
    monkeypatch.setattr(m, "login_maxinet", lambda: _SesionFalsa(cuerpo))
    m.main()
    assert hoja.celdas[1][m.COL_ESTATUS] == "CERRADO" and hoja.celdas[2][m.COL_ID] == 2


# ---------------------------------------------------------------- consulta a Maxinet
class _Resp:
    def __init__(self, cuerpo):
        self.content = ("﻿" + cuerpo).encode("utf-8")


class _SesionFalsa:
    def __init__(self, cuerpo):
        self.cuerpo, self.pedidos = cuerpo, []

    def post(self, url, data=None, timeout=None):
        self.pedidos.append((url, data))
        return _Resp(self.cuerpo)


def test_consultar_filtra_por_ingreso_y_manda_el_estatus_siempre(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor/maxinetv2/")
    s = _SesionFalsa(json.dumps({"data": [fila_reporte(1)]}))
    assert len(m.consultar(s, "INGRESO", "1", "2026-01-01", "2026-11-03")) == 1
    url, datos = s.pedidos[0]
    assert url == "http://servidor/maxinetv2/json/lp-mtto-ordenes.php"
    assert datos == {"Criterio": "INGRESO", "Estatus": "1", "Desde": "2026-01-01", "Hasta": "2026-11-03", "valueCriterio": ""}


def test_consultar_sin_filas_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    assert m.consultar(_SesionFalsa('{"data":""}'), "INGRESO") == []


def test_consultar_con_data_inesperado_falla(monkeypatch):
    monkeypatch.setenv("MAXINET_BASE_URL", "http://servidor")
    with pytest.raises(RuntimeError, match="inesperado"):
        m.consultar(_SesionFalsa('{"data":{"a":1}}'), "INGRESO")
