import datetime as dt

import pytest

import cierre_diario as c
from tests.fakes import FotosFalsas, HojaFalsa, LibroFalso

D20, D21, D22, D23 = (dt.date(2026, 10, d) for d in (20, 21, 22, 23))
SERIE = {d: c.a_serie(d) for d in (D20, D21, D22, D23)}
CF = "=COUNTIFS('FLOTA CP'!$J:$J,\"EN RENTA CLIENTE CP\",'FLOTA CP'!$E:$E,{col}$2)"


def col_cerrada(col, d, v):
    """Columna congelada: constantes en las filas 4-6 y 8 (subtotal), SUM en la 3 y porcentaje en la 9."""
    return [f"=TEXT({col}2, \"ddd\")", SERIE[d], f"=SUM({col}4:{col}6)", v[0], v[1], v[2], "", v[3], f"=IFERROR({col}4/{col}3,0)"]


def col_viva(col, d):
    return [f"=TEXT({col}2, \"ddd\")", SERIE[d], f"=SUM({col}4:{col}6)", CF.format(col=col), CF.format(col=col), CF.format(col=col),
            "", f"=SUM({col}4:{col}6)", f"=IFERROR({col}4/{col}3,0)"]


def col_vacia(col, d):
    return [f"=TEXT({col}2, \"ddd\")", SERIE[d]] + [""] * 7


# columnas: B = 20-oct (cerrada), C = 21-oct (viva), D = 22-oct (vacía), E = 23-oct (vacía)
def estado(vivas_hasta):
    base = {2: col_cerrada("B", D20, [300, 20, 4, 324])}
    if vivas_hasta == D21:
        base.update({3: col_viva("C", D21), 4: col_vacia("D", D22), 5: col_vacia("E", D23)})
    else:    # D22 ya es la viva
        base.update({3: col_cerrada("C", D21, [310, 21, 3, 334]), 4: col_viva("D", D22), 5: col_vacia("E", D23)})
    fechas = {2: D20, 3: D21, 4: D22, 5: D23}
    return base, fechas


# ---------------------------------------------------------------- utilidades
def test_letras_y_series():
    assert [c.letras(n) for n in (1, 26, 27, 52, 53, 660)] == ["A", "Z", "AA", "AZ", "BA", "YJ"]
    assert c.de_serie(c.a_serie(D22)) == D22 and c.a_serie(dt.date(2026, 10, 16)) == 46311


def test_parsear_fecha_texto_y_serie():
    assert c.parsear_fecha("2026-10-22") == D22
    assert c.parsear_fecha(c.a_serie(D22)) == D22
    assert c.parsear_fecha("") is None and c.parsear_fecha("Fecha") is None and c.parsear_fecha(5) is None


def test_fecha_de_datos_toma_la_mas_comun():
    valores = [["2026-10-22"]] * 1500 + [["2026-10-21"]] * 5 + [[""], []]
    assert c.fecha_de_datos(valores) == (D22, 1500)
    assert c.fecha_de_datos([[""], ["x"]]) == (None, 0)


def test_clasificar():
    assert c.clasificar(col_viva("C", D21)) == "viva"
    assert c.clasificar(col_cerrada("B", D20, [1, 2, 3, 4])) == "congelada"
    assert c.clasificar(col_vacia("D", D22)) == "vacia"


# ---------------------------------------------------------------- plan
def test_dia_nuevo_congela_la_viva_anterior_y_crea_la_del_dia():
    cols, fechas = estado(D21)
    foto = {D21: {4: 346, 5: 13, 6: 1, 8: 360}}
    p = c.planear(cols, fechas, D22, foto)
    assert p["errores"] == [] and p["col_dia"] == 4 and p["base"] == 2 and p["fuente"] == 3 and p["crear_viva"]
    assert p["filas_patron"] == [4, 5, 6, 8]                      # las constantes de la columna cerrada con fórmula en la viva
    assert p["congelar"] == [(3, {4: 346, 5: 13, 6: 1, 8: 360})]


def test_corrida_repetida_del_mismo_dia_no_cambia_nada():
    cols, fechas = estado(D22)
    p = c.planear(cols, fechas, D22, {})
    assert p["errores"] == [] and not p["crear_viva"] and p["congelar"] == [] and p["filas_patron"] == [4, 5, 6, 8]


def test_sin_foto_no_congela_pero_si_crea_la_columna_del_dia():
    cols, fechas = estado(D21)
    p = c.planear(cols, fechas, D22, {})
    assert p["crear_viva"] and p["congelar"] == []
    assert any("no hay foto de cierre" in e for e in p["errores"])


def test_foto_incompleta_no_se_usa():
    cols, fechas = estado(D21)
    p = c.planear(cols, fechas, D22, {D21: {4: 346, 5: 13}})
    assert p["congelar"] == [] and any("no trae" in e for e in p["errores"])


def test_fecha_fuera_de_la_fila_de_fechas():
    cols, fechas = estado(D21)
    p = c.planear(cols, fechas, dt.date(2026, 12, 1), {})
    assert p["col_dia"] is None and p["errores"]


def test_columna_del_dia_congelada_no_se_toca():
    cols, fechas = estado(D22)
    cols[4] = col_cerrada("D", D22, [1, 2, 3, 4])
    p = c.planear(cols, fechas, D22, {})
    assert p["errores"] and not p["congelar"]


# ---------------------------------------------------------------- solicitudes
def test_orden_de_las_solicitudes():
    cols, fechas = estado(D21)
    p = c.planear(cols, fechas, D22, {D21: {4: 346, 5: 13, 6: 1, 8: 360}})
    reqs = c.solicitudes(7, p, filas_formato=9, ultima_formula=9)
    tipos = [("copyPaste", r["copyPaste"]["pasteType"]) if "copyPaste" in r else ("updateCells",) for r in reqs]
    assert tipos == [("copyPaste", "PASTE_FORMULA"), ("copyPaste", "PASTE_FORMAT"),
                     ("updateCells",), ("updateCells",), ("copyPaste", "PASTE_FORMAT")]
    f = reqs[0]["copyPaste"]                                      # fórmulas de C (índice 2) a D (índice 3), filas 3 a 9
    assert (f["source"]["startColumnIndex"], f["destination"]["startColumnIndex"]) == (2, 3)
    assert (f["source"]["startRowIndex"], f["source"]["endRowIndex"]) == (2, 9)
    tramos = [r["updateCells"] for r in reqs if "updateCells" in r]
    assert [(t["start"]["rowIndex"], len(t["rows"])) for t in tramos] == [(3, 3), (7, 1)]    # filas 4-6 y 8
    assert tramos[0]["rows"][1]["values"][0]["userEnteredValue"] == {"numberValue": 13}
    assert all(t["start"]["columnIndex"] == 2 for t in tramos)
    ult = reqs[-1]["copyPaste"]                                   # formato de la cerrada B hacia la que se congeló, C
    assert (ult["source"]["startColumnIndex"], ult["destination"]["startColumnIndex"]) == (1, 2)


def test_sin_cambios_no_hay_solicitudes():
    cols, fechas = estado(D22)
    p = c.planear(cols, fechas, D22, {})
    assert c.solicitudes(7, p, 9, 9) == []


# ---------------------------------------------------------------- flujo completo
def hoja_desde(cols, valores_viva, nombre="UNIDADES CP"):
    """Hoja falsa con la fila 2 de fechas y las columnas dadas (B=2...)."""
    filas = 9
    formulas = [[""] * 6 for _ in range(filas)]
    valores = [[""] * 6 for _ in range(filas)]
    for i, col in cols.items():
        for r, x in enumerate(col):
            formulas[r][i - 1] = x
            valores[r][i - 1] = x if not c.es_formula(x) else ""
    for i, vals in valores_viva.items():
        for r, v in vals.items():
            valores[r - 1][i - 1] = v
    return HojaFalsa(formulas, valores, nombre=nombre, row_count=filas, id=11)


def test_cerrar_pestana_dia_nuevo_aplica_y_guarda_foto():
    cols, fechas = estado(D21)
    ws = hoja_desde(cols, {})
    libro = LibroFalso([ws])
    fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 346, 5: 13, 6: 1, 8: 360}})
    # después del batch, la columna D (22-oct) ya calcula con los datos del día
    original = libro.batch_update

    def aplicar(cuerpo):
        original(cuerpo)
        for r, v in {4: 375, 5: 14, 6: 3, 8: 392}.items():
            ws.valores[r - 1][3] = v
    libro.batch_update = aplicar
    ok = c.cerrar_pestana(libro, "UNIDADES CP", D22, fotos, dt.date(2026, 10, 23), dry_run=False)
    assert ok and len(libro.peticiones) == 5
    assert fotos.guardadas == [(D22, "UNIDADES CP", {4: 375, 5: 14, 6: 3, 8: 392})]


def test_cerrar_pestana_dry_run_no_escribe_ni_guarda():
    cols, fechas = estado(D21)
    ws = hoja_desde(cols, {})
    libro = LibroFalso([ws]); fotos = FotosFalsas({(D21, "UNIDADES CP"): {4: 1, 5: 2, 6: 3, 8: 6}})
    assert c.cerrar_pestana(libro, "UNIDADES CP", D22, fotos, dt.date(2026, 10, 23), dry_run=True)
    assert libro.peticiones == [] and fotos.guardadas == []


def test_cerrar_pestana_corrida_repetida_solo_actualiza_la_foto():
    cols, fechas = estado(D22)
    ws = hoja_desde(cols, {4: {4: 375, 5: 14, 6: 3, 8: 392}})
    libro = LibroFalso([ws]); fotos = FotosFalsas()
    assert c.cerrar_pestana(libro, "UNIDADES CP", D22, fotos, dt.date(2026, 10, 23), dry_run=False)
    assert libro.peticiones == [] and fotos.guardadas[0][2] == {4: 375, 5: 14, 6: 3, 8: 392}


def test_no_guarda_foto_con_ceros():
    cols, fechas = estado(D22)
    ws = hoja_desde(cols, {4: {4: 0, 5: 0, 6: 0, 8: 0}})
    libro = LibroFalso([ws]); fotos = FotosFalsas()
    c.cerrar_pestana(libro, "UNIDADES CP", D22, fotos, dt.date(2026, 10, 23), dry_run=False)
    assert fotos.guardadas == []


def test_sin_foto_devuelve_falso_y_aun_asi_crea_la_columna():
    cols, fechas = estado(D21)
    ws = hoja_desde(cols, {})
    libro = LibroFalso([ws]); fotos = FotosFalsas()
    ok = c.cerrar_pestana(libro, "UNIDADES CP", D22, fotos, dt.date(2026, 10, 23), dry_run=False)
    assert ok is False
    assert any("copyPaste" in r and r["copyPaste"]["pasteType"] == "PASTE_FORMULA" for r in libro.peticiones)
    assert not any("updateCells" in r for r in libro.peticiones)        # nada se congeló sin foto


# ---------------------------------------------------------------- reintentos ante 429
class _Resp:
    def __init__(self, codigo):
        self.status_code = codigo
        self.text = '{"error": {"code": %d, "message": "cuota", "status": "RESOURCE_EXHAUSTED"}}' % codigo

    def json(self):
        return {"error": {"code": self.status_code, "message": "cuota", "status": "RESOURCE_EXHAUSTED"}}


def test_reintentar_espera_y_vuelve_a_intentar_ante_429(monkeypatch):
    import gspread
    esperas = []
    monkeypatch.setattr(c.time, "sleep", lambda s: esperas.append(s))
    llamadas = []

    def fn():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise gspread.exceptions.APIError(_Resp(429))
        return "ok"
    assert c.reintentar(fn) == "ok" and esperas == [15, 30]


def test_reintentar_no_oculta_otros_errores(monkeypatch):
    import gspread
    monkeypatch.setattr(c.time, "sleep", lambda s: None)

    def fn():
        raise gspread.exceptions.APIError(_Resp(403))
    with pytest.raises(gspread.exceptions.APIError):
        c.reintentar(fn)
