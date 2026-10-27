import datetime as dt
import json

import pytest

import radar as r

T0 = dt.datetime(2026, 10, 27, 12, 0, tzinfo=dt.timezone.utc)


def meta(id, titulo, cols=10, hidden=False, charts=(), prot=0, merges=0, cf=0, filtro=False, frozen=(0, 0)):
    return {"properties": {"sheetId": id, "title": titulo, "hidden": hidden,
                           "gridProperties": {"columnCount": cols, "frozenRowCount": frozen[0], "frozenColumnCount": frozen[1]}},
            "charts": [{"spec": {"title": t}} for t in charts], "protectedRanges": [{}] * prot, "merges": [{}] * merges,
            "conditionalFormats": [{}] * cf, **({"basicFilter": {"range": {}}} if filtro else {})}


def huella(id=1, titulo="UNIDADES CP", matriz=None, **kw):
    return r.huella_hoja(meta(id, titulo, **kw), matriz or [["ASESOR", "CF"], [], [], ["x", "=SUM(A1:A5)"]])


# ---------------------------------------------------------------- patrones y huella
def test_patron_generaliza_las_referencias_de_celda():
    assert r.patron("=SUM(YJ4:YJ6)") == r.patron("=SUM(YK4:YK6)") == "=SUM(REF:REF)"
    assert r.patron("=COUNTIFS('FLOTA CP'!$J:$J,\"EN RENTA\",'FLOTA CP'!$E:$E,YJ$2)") == r.patron("=COUNTIFS('FLOTA CP'!$J:$J,\"EN RENTA\",'FLOTA CP'!$E:$E,YK$2)")
    assert r.patron("=SUM(A1:A5)") != r.patron("=AVERAGE(A1:A5)")


def test_el_mismo_calculo_en_otra_columna_no_cambia_la_huella():
    a = huella(matriz=[["x"], [], [], ["", "=SUM(B4:B6)"]])
    b = huella(matriz=[["x"], [], [], ["", "", "=SUM(C4:C6)"]])
    assert a["fm"] == b["fm"]


def test_la_huella_no_cuenta_filas_ni_datos():
    a = huella(matriz=[["A"], [], [], ["dato 1"], ["dato 2"]])
    b = huella(matriz=[["A"], [], [], ["dato 1"], ["dato 2"], ["dato 3"], ["dato 4"]])
    assert a == b


# ---------------------------------------------------------------- comparación
def test_sin_cambios():
    h = {"1": huella(1), "2": huella(2, "FLOTA CP")}
    assert r.comparar(h, json.loads(json.dumps(h))) == []


def test_renombre_pestana_nueva_y_eliminada_se_distinguen_por_identificador():
    base = {"1": huella(1, "UNIDADES CP"), "2": huella(2, "MENU PRINCIPAL"), "3": huella(3, "DETALLE")}
    actual = {"1": huella(1, "REPORTE FLOTA CP"), "3": huella(3, "DETALLE"), "4": huella(4, "NUEVA", cols=7)}
    c = {(nombre, tipo): det for _, nombre, tipo, det in r.comparar(base, actual)}
    assert c[("REPORTE FLOTA CP", "renombrada")] == "antes 'UNIDADES CP'"
    assert ("MENU PRINCIPAL", "pestaña eliminada") in c and c[("NUEVA", "pestaña nueva")] == "7 columnas"
    assert len(c) == 3                                                   # DETALLE no cambió


@pytest.mark.parametrize("cambio,tipo", [
    ({"cols": 12}, "columnas"), ({"hidden": True}, "oculta"), ({"charts": ("A",)}, "gráficas"), ({"prot": 2}, "protecciones"),
    ({"merges": 1}, "celdas combinadas"), ({"cf": 3}, "formatos condicionales"), ({"filtro": True}, "filtro"),
    ({"frozen": (1, 0)}, "filas o columnas congeladas"),
])
def test_cada_tipo_de_cambio_se_detecta(cambio, tipo):
    tipos = [t for _, _, t, _ in r.comparar({"1": huella(1)}, {"1": huella(1, **cambio)})]
    assert tipos == [tipo]


def test_encabezados_distintos_dicen_que_celda_cambio():
    a = huella(matriz=[["ASESOR", "CF", "CO"], [], []])
    b = huella(matriz=[["ASESOR", "CF", "CX", "NUEVA"], [], []])
    (_, _, tipo, det), = r.comparar({"1": a}, {"1": b})
    assert tipo == "encabezados" and "C1: 'CO' -> 'CX'" in det and "D1: '' -> 'NUEVA'" in det


def test_formulas_con_otro_patron_se_detectan():
    a = huella(matriz=[["x"], [], [], ["=SUM(A1:A5)"]])
    b = huella(matriz=[["x"], [], [], ["=AVERAGE(A1:A5)"]])
    assert [t for _, _, t, _ in r.comparar({"1": a}, {"1": b})] == ["fórmulas"]


# ---------------------------------------------------------------- estados
BASE = {"1": huella(1)}
CAMBIADA = {"1": huella(1, cols=12)}
OTRA = {"1": huella(1, cols=14)}


def test_sin_cambios_limpia_el_estado():
    e, c = r.evaluar({"estado": "en curso", "hash": "x", "desde": T0.isoformat()}, BASE, BASE, T0)
    assert e["estado"] == "sin cambios" and c == []


def test_primer_cambio_queda_en_curso_y_registra_desde_cuando():
    e, c = r.evaluar({}, BASE, CAMBIADA, T0)
    assert e["estado"] == "en curso" and e["desde"] == T0.isoformat() and len(c) == 1


def test_si_la_estructura_sigue_cambiando_se_reinicia_la_espera():
    e1, _ = r.evaluar({}, BASE, CAMBIADA, T0)
    e2, _ = r.evaluar(e1, BASE, OTRA, T0 + dt.timedelta(minutes=90))
    assert e2["estado"] == "en curso" and e2["desde"] == (T0 + dt.timedelta(minutes=90)).isoformat()


def test_queda_estable_cuando_lleva_el_tiempo_de_calma_sin_moverse():
    e1, _ = r.evaluar({}, BASE, CAMBIADA, T0)
    assert r.evaluar(e1, BASE, CAMBIADA, T0 + dt.timedelta(minutes=59))[0]["estado"] == "en curso"
    assert r.evaluar(e1, BASE, CAMBIADA, T0 + dt.timedelta(minutes=60))[0]["estado"] == "estable"
    assert r.evaluar(e1, BASE, CAMBIADA, T0 + dt.timedelta(minutes=30), silencio_min=15)[0]["estado"] == "estable"


# ---------------------------------------------------------------- instantánea y almacén (con dobles)
class LibroFalso:
    def __init__(self, metas, matrices):
        self.metas, self.matrices, self.llamadas = metas, matrices, []

    def fetch_sheet_metadata(self, params=None):
        return {"sheets": self.metas}

    def values_batch_get(self, rangos, params=None):
        self.llamadas.append((rangos, params))
        return {"valueRanges": [{"values": self.matrices.get(r_, [])} for r_ in rangos]}


def test_instantanea_omite_las_ocultas_propias_y_pide_las_formulas():
    metas = [meta(1, "UNIDADES CP"), meta(2, "_RADAR", hidden=True), meta(3, "_CIERRE_DIARIO", hidden=True), meta(4, "Ticket Sac/Maxi")]
    libro = LibroFalso(metas, {})
    out = r.tomar_instantanea(libro)
    assert sorted(out) == ["1", "4"] and libro.llamadas[0][1] == {"valueRenderOption": "FORMULA"}
    assert libro.llamadas[0][0][0] == "'UNIDADES CP'!A1:BZ60"


def test_instantanea_escapa_las_comillas_del_nombre():
    assert r._rango("O'Brien") == "'O''Brien'!A1:BZ60"


class HojaRadarFalsa:
    def __init__(self, filas=()):
        self.filas, self.row_count, self.id, self.limpiado = [list(f) for f in filas], 400, 5, []

    def get_all_values(self):
        return [list(f) for f in self.filas]

    def update(self, range_name=None, values=None, value_input_option=None):
        self.filas = [list(f) for f in values]

    def batch_clear(self, rangos):
        self.limpiado += rangos

    def add_rows(self, n):
        self.row_count += n


class LibroConRadar:
    def __init__(self, hoja):
        self.hoja = hoja

    def worksheet(self, nombre):
        return self.hoja


def test_almacen_guarda_base_estado_e_informe_sin_perder_la_base():
    hoja = HojaRadarFalsa()
    a = r.Almacen(LibroConRadar(hoja)); a.cargar()
    base = {"1": huella(1)}
    a.guardar({"Tablero CP": base, "Base CP": {"9": huella(9, "ENTREGAS")}}, {"Tablero CP": {"estado": "sin cambios"}}, {"Tablero CP": ["línea"]})
    b = r.Almacen(LibroConRadar(hoja)); b.cargar()
    assert b.base("Tablero CP") == base and b.base("Base CP")["9"]["t"] == "ENTREGAS" and b.estado("Tablero CP") == {"estado": "sin cambios"}
    # una corrida normal no manda bases: la actual se conserva
    b.guardar({}, {"Tablero CP": {"estado": "en curso", "hash": "h", "desde": "d"}}, {"Tablero CP": ["otra"]})
    c = r.Almacen(LibroConRadar(hoja)); c.cargar()
    assert c.base("Tablero CP") == base and c.estado("Tablero CP")["estado"] == "en curso"


def test_almacen_limpia_las_filas_que_sobran_y_amplia_la_hoja():
    hoja = HojaRadarFalsa([["INFORME", "Tablero CP", f"l{i}", ""] for i in range(30)])
    a = r.Almacen(LibroConRadar(hoja)); a.cargar()
    a.guardar({}, {}, {"Tablero CP": ["una"]})
    assert hoja.limpiado == ["A2:D30"]
    hoja2 = HojaRadarFalsa(); hoja2.row_count = 3
    b = r.Almacen(LibroConRadar(hoja2)); b.cargar()
    b.guardar({"Tablero CP": {str(i): huella(i, f"T{i}") for i in range(10)}}, {}, {})
    assert hoja2.row_count > 3


def test_informe_incluye_el_impacto_por_el_nombre_anterior():
    base = {"1": huella(1, "UNIDADES CP")}
    cambios = [("1", "REPORTE FLOTA CP", "renombrada", "antes 'UNIDADES CP'")]
    lineas = r.informe("Tablero CP", {"estado": "estable", "desde": "2026-10-27T12:00:00"}, cambios, base)
    assert "estable" in lineas[0] and "cierre diario" in lineas[1] and "REPORTE FLOTA CP" in lineas[1]


def test_con_reintentos_ante_429(monkeypatch):
    import gspread

    class Resp:
        status_code = 429
        text = '{"error": {"code": 429, "message": "x", "status": "RESOURCE_EXHAUSTED"}}'

        def json(self):
            return {"error": {"code": 429, "message": "x", "status": "RESOURCE_EXHAUSTED"}}
    esperas, n = [], []
    monkeypatch.setattr(r.time, "sleep", lambda s: esperas.append(s))

    def fn():
        n.append(1)
        if len(n) < 3:
            raise gspread.exceptions.APIError(Resp())
        return "ok"
    assert r.con_reintentos(fn) == "ok" and esperas == [20, 40]
