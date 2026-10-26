import datetime as dt

import pytest

import cierre_diario as c
import recuperar_dias as r
from tests.fakes import FotosFalsas, HojaFalsa, LibroFalso

D20, D21, D22, D23, D24 = (dt.date(2026, 10, d) for d in (20, 21, 22, 23, 24))
CF = "=COUNTIFS('FLOTA CP'!$J:$J,\"EN RENTA CLIENTE CP\",'FLOTA CP'!$C:$C,\"TO\",'FLOTA CP'!$E:$E,{col}$2)"


# ---------------------------------------------------------------- utilidades
def test_partir_argumentos_respeta_comillas_y_parentesis():
    assert r.partir_argumentos("A,\"x,y\",SUM(B1,B2),C") == ["A", '"x,y"', "SUM(B1,B2)", "C"]


def test_texto_compara_como_countifs():
    assert r.texto(" TO ") == "to" and r.texto(5.0) == "5" and r.texto(None) == "" and r.texto(2.5) == "2.5"


def test_letras_e_indice_son_inversos():
    assert [r.letras(n) for n in (1, 27, 53)] == ["A", "AA", "BA"] and r.indice("BA") == 53 and r.indice("YK") == 661


# ---------------------------------------------------------------- columnas de FLOTA CP de un día
def fila_cruda(fecha, placa, bsite, current, segmento):
    f = [""] * r.ANCHO_REPORTE
    f[0], f[2], f[3], f[4], f[5] = fecha, placa, bsite, current, segmento   # E, G, H, I, J
    return f


def test_armar_columnas_deriva_con_las_mismas_reglas_y_toma_lo_estatico_de_hoy():
    filas = [fila_cruda("2026-10-22", "AAA", "LT", "TO", "EN RENTA CLIENTE CP"),
             fila_cruda("2026-10-22", "BBB", "L", "L", "DISPONIBLE"),
             fila_cruda("2026-10-22", "CCC", "TO", "XX", "OTROS"),
             fila_cruda("2026-10-22", "DDD", "SS", "SO", "TALLER")]
    hoy = {"G": ["bbb", "AAA", "CCC"], "D": ["VAN", "HIACE", "SEDAN"], "AU": ["MAXIRENT", "SUBARRENDADA", "MAXIRENT"],
           "AT": ["OK", "OK", "NA"], "AW": ["CARGA", "PASAJEROS", "SEDAN"], "AX": ["P1", "P2"], "AY": ["", ""],
           "AZ": [10, 60], "BA": ["BA-Con dep", "Ba-Sin dep"]}
    cols = r.armar_columnas(filas, hoy)
    assert cols["C"] == ["TO", "NA", "TO", "NA"]                       # BSITE CP: LT y TO cuentan
    assert cols["B"] == ["PRESTAMO", "NA", "NA", "PRESTAMO"]           # CurrentSite TO o SO
    assert cols["A"] == ["OK", "NG", "OK", "OK"]                       # préstamo o BSite TO
    assert cols["AV"] == ["NA", "OK", "OK", "NA"]                      # Segmento DISPONIBLE u OTROS
    assert cols["D"] == ["HIACE", "VAN", "SEDAN", ""]                  # GRUPO por placa de hoy (sin importar mayúsculas); DDD no existe hoy
    assert cols["AU"][:2] == ["SUBARRENDADA", "MAXIRENT"] and cols["AW"][0] == "PASAJEROS"
    assert cols["BA"] == ["BA-Con dep", "Ba-Sin dep"] and cols["J"][1] == "DISPONIBLE" and cols["E"][0] == "2026-10-22"


@pytest.mark.parametrize("sede,bsite_cp", [("LT", "TO"), ("PE", "TO"), ("TO", "TO"), ("FU", "TO"), ("AR", "TO"), ("LF", "TO"),
                                           ("L", "NA"), ("SO", "NA"), ("", "NA")])
def test_bsite_cp_acepta_exactamente_las_sedes_de_la_formula(sede, bsite_cp):
    assert r.armar_columnas([fila_cruda("2026-10-22", "A", sede, "L", "X")], {})["C"] == [bsite_cp]


@pytest.mark.parametrize("sede,prestamo", [("LF", "PRESTAMO"), ("LT", "PRESTAMO"), ("FU", "PRESTAMO"), ("SO", "PRESTAMO"),
                                           ("TO", "PRESTAMO"), ("PE", "NA"), ("AR", "NA"), ("L", "NA")])
def test_prestamo_acepta_exactamente_las_sedes_de_la_formula(sede, prestamo):
    assert r.armar_columnas([fila_cruda("2026-10-22", "A", "L", sede, "X")], {})["B"] == [prestamo]


@pytest.mark.parametrize("segmento,ok", [("DISPONIBLE", "OK"), ("otros", "OK"), (" Disponible ", "OK"), ("TALLER", "NA"), ("", "NA")])
def test_disponibles_de_prestamos_solo_con_disponible_u_otros(segmento, ok):
    assert r.armar_columnas([fila_cruda("2026-10-22", "A", "L", "L", segmento)], {})["AV"] == [ok]


# ---------------------------------------------------------------- evaluador de fórmulas
FLOTA = {"E": ["2026-10-22"] * 5, "J": ["EN RENTA CLIENTE CP"] * 4 + ["TALLER"], "C": ["TO", "TO", "NA", "TO", "TO"],
         "D": ["HIACE", "VAN", "HIACE", "VAN", "HIACE"], "BA": ["BA-Con dep", "Ba-Sin dep", "Ba-Sin dep"]}


def ev(formulas, etiquetas=None, fecha=D22, filas=None):
    return r.evaluar(formulas, "YK", etiquetas or {}, fecha, FLOTA, filas or sorted(formulas))


def test_countifs_con_texto_fecha_y_etiqueta():
    f = {4: CF.format(col="YK"),
         5: "=COUNTIFS('FLOTA CP'!$D:$D,$A5,'FLOTA CP'!$J:$J,\"en renta cliente cp\",'FLOTA CP'!$E:$E,YK$2)"}
    assert ev(f, {5: "hiace"}) == {4: 3, 5: 2}                          # sin distinguir mayúsculas
    assert ev({4: CF.format(col="YK")}, fecha=D23) == {4: 0}            # otra fecha: no hay filas de ese día


def test_countifs_de_una_sola_columna_lateral():
    assert ev({27: "=COUNTIFS('FLOTA CP'!$BA:$BA,$A$27)"}, {27: "Ba-Sin dep"}) == {27: 2}


def test_sum_con_rangos_referencias_y_filas_calculadas():
    f = {4: CF.format(col="YK"), 5: CF.format(col="YK"), 6: "=SUM(YK4:YK5)", 7: "=SUM(YK6,YK4)"}
    assert ev(f) == {4: 3, 5: 3, 6: 6, 7: 9}


def test_formulas_no_soportadas_se_rechazan_en_vez_de_inventar_un_valor():
    for f, et in [("=IFERROR(YK4/YK3,0)", {}), ("=COUNTIFS('FLOTA CP'!$J:$J,\">1\")", {}),
                  ("=COUNTIFS('FLOTA CP'!$J:$K,\"x\")", {}), ("=COUNTIFS('FLOTA CP'!$D:$D,$A9)", {9: ""}),
                  ("=COUNTIFS('FLOTA CP'!$D:$D,\"HI*\")", {}), ("=COUNTIFS('FLOTA CP'!$ZZ:$ZZ,\"x\")", {})]:
        with pytest.raises(r.FormulaNoSoportada):
            ev({4: f}, et)


# ---------------------------------------------------------------- plan con días sin columna
def col_cerrada(col, d, v):
    return [f"=TEXT({col}2, \"ddd\")", c.a_serie(d), f"=SUM({col}4:{col}5)", v[0], v[1], "", "", "", f"=IFERROR({col}4/{col}3,0)"]


def col_viva(col, d):
    return [f"=TEXT({col}2, \"ddd\")", c.a_serie(d), f"=SUM({col}4:{col}5)", CF.format(col=col), CF.format(col=col), "", "", "",
            f"=IFERROR({col}4/{col}3,0)"]


def col_vacia(col, d):
    return [f"=TEXT({col}2, \"ddd\")", c.a_serie(d)] + [""] * 7


def estado_hueco(dia_vivo_es_el_ultimo):
    """B=20 cerrada, C=21 viva, D=22 y E=23 vacías, F=24 (día de los datos): vacía o ya viva."""
    cols = {2: col_cerrada("B", D20, [100, 20]), 3: col_viva("C", D21), 4: col_vacia("D", D22), 5: col_vacia("E", D23)}
    cols[6] = col_viva("F", D24) if dia_vivo_es_el_ultimo else col_vacia("F", D24)
    fechas = {2: D20, 3: D21, 4: D22, 5: D23, 6: D24}
    return cols, fechas


def test_el_plan_detecta_los_dias_sin_columna():
    cols, fechas = estado_hueco(False)
    p = c.planear(cols, fechas, D24, {D21: {4: 110, 5: 21}})
    assert p["huecos"] == [4, 5] and p["col_ref"] == 3 and p["crear_viva"] and p["fuente"] == 3 and p["congelar"]


def test_sin_huecos_cuando_el_cierre_corre_a_diario():
    cols = {2: col_cerrada("B", D20, [100, 20]), 3: col_cerrada("C", D21, [110, 21]), 4: col_viva("D", D22),
            5: col_vacia("E", D23)}
    fechas = {2: D20, 3: D21, 4: D22, 5: D23}
    assert c.planear(cols, fechas, D23, {D22: {4: 1, 5: 2}})["huecos"] == []
    assert c.planear(cols, fechas, D22, {})["huecos"] == []


def test_orden_de_las_solicitudes_con_huecos():
    cols, fechas = estado_hueco(False)
    p = c.planear(cols, fechas, D24, {D21: {4: 110, 5: 21}})
    reqs = c.solicitudes(7, p, 9, 9, rellenar=[(4, {4: 90, 5: 18}), (5, {4: 95, 5: 19})])
    tipos = [r_["copyPaste"]["pasteType"] if "copyPaste" in r_ else "valores" for r_ in reqs]
    assert tipos == ["PASTE_FORMULA", "PASTE_FORMAT",                    # la columna del día
                     "PASTE_FORMULA", "valores", "PASTE_FORMAT",         # hueco 22
                     "PASTE_FORMULA", "valores", "PASTE_FORMAT",         # hueco 23
                     "valores", "PASTE_FORMAT"]                          # al final se congela la viva anterior
    destinos = [r_["copyPaste"]["destination"]["startColumnIndex"] for r_ in reqs if "copyPaste" in r_]
    assert destinos == [5, 5, 3, 3, 4, 4, 2]                             # F, F, D, D, E, E, C


# ---------------------------------------------------------------- flujo completo con huecos
class RecuperadorFalso:
    def __init__(self, resultados, falla=False):
        self.resultados, self.falla, self.llamadas = resultados, falla, []

    def evaluar(self, formulas, letra, etiquetas, fecha, filas):
        self.llamadas.append((fecha, letra))
        if self.falla:
            raise r.FormulaNoSoportada("x")
        return {f: self.resultados[fecha][f] for f in filas}


def hoja_hueco(vivo_en_el_ultimo):
    cols, fechas = estado_hueco(vivo_en_el_ultimo)
    filas = 9
    formulas = [[""] * 7 for _ in range(filas)]
    valores = [[""] * 7 for _ in range(filas)]
    for i, col in cols.items():
        for n, x in enumerate(col):
            formulas[n][i - 1] = x
            valores[n][i - 1] = x if not c.es_formula(x) else ""
    for n in (4, 5):                                                    # etiquetas de la columna A
        valores[n - 1][0] = f"fila {n}"
    return HojaFalsa(formulas, valores, nombre="UNIDADES CP", row_count=filas, id=11), valores


def test_cerrar_pestana_rellena_los_dias_y_congela_la_viva():
    ws, _ = hoja_hueco(False)
    libro = LibroFalso([ws])
    fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 110, 5: 21}})
    rec = RecuperadorFalso({D21: {4: 110, 5: 21}, D22: {4: 90, 5: 18}, D23: {4: 95, 5: 19}})
    ok = c.cerrar_pestana(libro, "UNIDADES CP", D24, fotos, dt.date(2026, 10, 25), dry_run=True, recuperador=rec)
    assert [f for f, _ in rec.llamadas] == [D21, D22, D23]              # primero la comprobación con el día conocido
    assert ok is True and libro.peticiones == [] and fotos.guardadas == []     # en seco: comprueba, calcula y no escribe nada


def test_cerrar_pestana_escribe_los_valores_reconstruidos():
    ws, valores = hoja_hueco(False)
    libro = LibroFalso([ws])
    fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 110, 5: 21}})
    rec = RecuperadorFalso({D21: {4: 110, 5: 21}, D22: {4: 90, 5: 18}, D23: {4: 95, 5: 19}})
    original = libro.batch_update

    def aplicar(cuerpo):
        original(cuerpo)
        for n, v in {4: 7, 5: 7}.items():
            ws.valores[n - 1][5] = v                                    # la columna F calcula con los datos del día
    libro.batch_update = aplicar
    c.cerrar_pestana(libro, "UNIDADES CP", D24, fotos, dt.date(2026, 10, 25), dry_run=False, recuperador=rec)
    celdas = [rq["updateCells"] for rq in libro.peticiones if "updateCells" in rq]
    por_columna = {}
    for t in celdas:
        por_columna.setdefault(t["start"]["columnIndex"], []).extend(
            x["values"][0]["userEnteredValue"]["numberValue"] for x in t["rows"])
    assert por_columna == {3: [90, 18], 4: [95, 19], 2: [110, 21]}      # días 22 y 23 reconstruidos; 21 congelado con su foto


def test_si_la_reconstruccion_no_coincide_no_se_rellena_nada():
    ws, _ = hoja_hueco(False)
    libro = LibroFalso([ws])
    fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 110, 5: 21}})
    rec = RecuperadorFalso({D21: {4: 111, 5: 21}, D22: {4: 90, 5: 18}, D23: {4: 95, 5: 19}})   # el día conocido sale distinto
    ok = c.cerrar_pestana(libro, "UNIDADES CP", D24, fotos, dt.date(2026, 10, 25), dry_run=False, recuperador=rec)
    assert ok is False
    cols_rellenadas = {rq["updateCells"]["start"]["columnIndex"] for rq in libro.peticiones if "updateCells" in rq}
    assert cols_rellenadas == {2}                                       # sólo se congeló la viva con su foto; los huecos no se tocaron


def test_sin_recuperador_avisa_y_no_inventa_datos():
    ws, _ = hoja_hueco(False)
    libro = LibroFalso([ws])
    fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 110, 5: 21}})
    ok = c.cerrar_pestana(libro, "UNIDADES CP", D24, fotos, dt.date(2026, 10, 25), dry_run=False, recuperador=None)
    assert ok is False
    assert {rq["updateCells"]["start"]["columnIndex"] for rq in libro.peticiones if "updateCells" in rq} == {2}


def test_una_formula_no_soportada_detiene_el_rellenado_sin_romper_el_cierre():
    ws, _ = hoja_hueco(False)
    libro = LibroFalso([ws])
    fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 110, 5: 21}})
    ok = c.cerrar_pestana(libro, "UNIDADES CP", D24, fotos, dt.date(2026, 10, 25), dry_run=False,
                          recuperador=RecuperadorFalso({}, falla=True))
    assert ok is False and any("copyPaste" in rq for rq in libro.peticiones)


def test_recuperador_cachea_y_carga_hoy_una_sola_vez():
    cargas, descargas = [], []
    rec = r.Recuperador(lambda: cargas.append(1) or {"G": []},
                        descargar=lambda f: descargas.append(f) or [fila_cruda(f.isoformat(), "AAA", "TO", "TO", "EN RENTA CLIENTE CP")])
    rec.flota(D22); rec.flota(D22); rec.flota(D23)
    assert len(cargas) == 1 and descargas == [D22, D23]
