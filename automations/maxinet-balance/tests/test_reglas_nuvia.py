"""Reglas de Nuvia del 30-oct en ONHIRE, RETORNOS y BALANCE (sin red ni Sheets reales)."""
import maxinet_balance as mb
from tests.fakes import HojaFalsa, LibroFalso

# Fórmulas tal como están en el archivo de Nuvia (fila 2): las del 2026-10-30 y la de P2 con la regla de reemplazo.
NUVIA_ONHIRE_P2_30_OCT = "=MAP(A2:A,C2:C,M2:M,LAMBDA(cli,res,pla,IF(pla=\"\",\"\",IFERROR(INDEX(SORT(FILTER(HSTACK('SOLICITUDES ENTREGAS / RECOLECCIONES'!$C$2:$C,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E),LEFT('SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E,7)=\"ENTREGA\",(('SOLICITUDES ENTREGAS / RECOLECCIONES'!$M$2:$M=pla)+('SOLICITUDES ENTREGAS / RECOLECCIONES'!$O$2:$O=pla))>0,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$J$2:$J=cli),1,FALSE),1,2),IFERROR(INDEX(SORT(FILTER(HSTACK('SOLICITUDES ENTREGAS / RECOLECCIONES'!$C$2:$C,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E),LEFT('SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E,7)=\"ENTREGA\",'SOLICITUDES ENTREGAS / RECOLECCIONES'!$I$2:$I=res),1,FALSE),1,2),\"\")))))"
# Con la regla de reemplazo (CAMBIO -> NUEVO), tal como está en su archivo.
NUVIA_ONHIRE_P2 = "=MAP(A2:A,C2:C,M2:M,LAMBDA(cli,res,pla,IF(pla=\"\",\"\",LET(sFec,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$C$2:$C,sEst,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$H$2:$H,sTip,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E,sRes,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$I$2:$I,sCli,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$J$2:$J,sPla,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$M$2:$M,sRem,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$O$2:$O,vacio,HSTACK(\"\",\"\",\"\",\"\"),porPlaca,IFERROR(CHOOSEROWS(SORT(FILTER(HSTACK(sFec,sTip,sRes,sRem),LEFT(sTip,7)=\"ENTREGA\",((sPla=pla)+(sRem=pla))>0,sCli=cli),1,FALSE),1),vacio),mejor,IF(INDEX(porPlaca,1,2)=\"\",IFERROR(CHOOSEROWS(SORT(FILTER(HSTACK(sFec,sTip,sRes,sRem),LEFT(sTip,7)=\"ENTREGA\",sRes=res),1,FALSE),1),vacio),porPlaca),tipoSol,INDEX(mejor,1,2),IF(tipoSol=\"\",\"\",IF(AND(tipoSol=\"ENTREGA (CAMBIO)\",UPPER(INDEX(mejor,1,4))=UPPER(pla),COUNTIFS(sRes,INDEX(mejor,1,3),sTip,\"ENTREGA (NUEVO)\",sEst,\"<>TRASLADO CANCELADO\")>0,COUNTIF('FLOTA MES ANTERIOR'!$K:$K,INDEX(mejor,1,3))=0),\"ENTREGA (NUEVO)\",tipoSol))))))"
NUVIA_ONHIRE_R2 = "=ARRAYFORMULA(IF(M2:M=\"\",\"\",IF(COUNTIFS('FLOTA MES ANTERIOR'!$C:$C,M2:M,'FLOTA MES ANTERIOR'!$L:$L,A2:A)+COUNTIFS('FLOTA MES ANTERIOR'!$C:$C,M2:M,'FLOTA MES ANTERIOR'!$J:$J,B2:B)>0,\"CAMBIO DE RESERVA\",IF(P2:P=\"\",\"SIN SOLICITUD\",P2:P))))"
NUVIA_RETORNOS_P2 = "=IF(M2=\"\",\"\",IFERROR(INDEX(SORT(FILTER({'SOLICITUDES ENTREGAS / RECOLECCIONES'!$C$2:$C,'SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E},'SOLICITUDES ENTREGAS / RECOLECCIONES'!$E$2:$E=\"RECOLECCION\",(('SOLICITUDES ENTREGAS / RECOLECCIONES'!$I$2:$I=C2)+(('SOLICITUDES ENTREGAS / RECOLECCIONES'!$M$2:$M=M2)*('SOLICITUDES ENTREGAS / RECOLECCIONES'!$J$2:$J=A2)))>0),1,FALSE),1,2),\"\"))"
NUVIA_RETORNOS_R2 = "=ARRAYFORMULA(IF(M2:M=\"\",\"\",IF((P2:P<>\"\")*((COUNTIFS(ONHIRE!$M:$M,M2:M,ONHIRE!$A:$A,A2:A,ONHIRE!$C:$C,\"<>\"&C2:C)+COUNTIFS(ONHIRE!$C:$C,C2:C,ONHIRE!$M:$M,\"<>\"&M2:M))=0),\"RECOLECCION\",IF(COUNTIFS('FLOTA MES ANTERIOR'!$C:$C,M2:M,'FLOTA MES ANTERIOR'!$L:$L,A2:A)+COUNTIFS('FLOTA MES ANTERIOR'!$C:$C,M2:M,'FLOTA MES ANTERIOR'!$J:$J,B2:B)>0,\"CAMBIO DE RESERVA\",IF(P2:P=\"\",\"SIN SOLICITUD\",\"CAMBIO DE RESERVA\")))))"


def _fila_reporte(i):
    """Una fila del reporte de Maxinet (15 columnas) con placa, cliente y reserva distintos."""
    return [f"#{100 + i}", f"CLIENTE {i}", f"#{200 + i}", "ON HIRE", "2026-10-0%d" % (i % 9 + 1), "2026-12-31", "30", "SI APLICA",
            "EJEC", "", "", "EJEC", f"PLACA{i}", "GRUPO", "MODELO"]


def _libro(hoja_nombre):
    libro = LibroFalso()
    hoja = libro.add_worksheet(hoja_nombre, 1000, 20)
    for j, h in enumerate(mb.ENCABEZADO_ER, 1):
        hoja.celdas[(1, j)] = h
    return libro, hoja


def test_las_formulas_son_identicas_a_las_de_nuvia():
    assert mb.FORMULA_P_ONHIRE == NUVIA_ONHIRE_P2
    assert mb.FORMULA_R_ONHIRE == NUVIA_ONHIRE_R2
    assert mb.FORMULA_R_RETORNOS == NUVIA_RETORNOS_R2
    assert mb._con_fila(mb.FORMULA_P_RETORNOS, 2) == NUVIA_RETORNOS_P2


def test_con_fila_conserva_las_llaves_de_matriz():
    f = mb._con_fila(mb.FORMULA_P_RETORNOS, 7)
    assert "M7" in f and "C7" in f and "A7" in f and "{r}" not in f
    assert "FILTER({" in f


def test_onhire_deja_P_y_R_como_una_sola_formula_matricial():
    libro, hoja = _libro("ONHIRE")
    mb.cargar_entregas_retornos(libro, "ONHIRE", [_fila_reporte(i) for i in range(3)])
    assert hoja.celda("P2") == mb.FORMULA_P_ONHIRE and hoja.celda("R2") == mb.FORMULA_R_ONHIRE
    assert hoja.celda("P3") == "" and hoja.celda("R3") == "" and hoja.celda("P4") == ""
    # Q y S sí van por fila, con la fila correcta
    assert "M3" in hoja.celda("Q3") and "B4" in hoja.celda("S4")


def test_retornos_P_va_por_fila_y_R_es_matricial():
    libro, hoja = _libro("RETORNOS")
    mb.cargar_entregas_retornos(libro, "RETORNOS", [_fila_reporte(i) for i in range(3)])
    assert hoja.celda("R2") == mb.FORMULA_R_RETORNOS and hoja.celda("R3") == ""
    assert "M2" in hoja.celda("P2") and "M4" in hoja.celda("P4")
    assert "M3" in hoja.celda("Q3")


def test_migra_las_formulas_por_fila_del_diseno_anterior():
    libro, hoja = _libro("ONHIRE")
    for r in range(2, 6):                                   # diseño anterior: P:S por fila
        hoja.poner(f"P{r}", f"=XLOOKUP(C{r},viejo)")
        hoja.poner(f"R{r}", f'=IF(Q{r}="","","POSIBLE ENTREGA")')
    mb.cargar_entregas_retornos(libro, "ONHIRE", [_fila_reporte(i) for i in range(3)])
    assert hoja.celda("P2") == mb.FORMULA_P_ONHIRE and hoja.celda("R2") == mb.FORMULA_R_ONHIRE
    # nada debajo: cualquier valor ahí bloquearía el derrame
    assert all(hoja.celda(f"{c}{r}") == "" for c in "PR" for r in range(3, 8))


def test_segunda_corrida_no_reescribe_las_formulas_matriciales():
    libro, hoja = _libro("ONHIRE")
    filas = [_fila_reporte(i) for i in range(3)]
    mb.cargar_entregas_retornos(libro, "ONHIRE", filas)
    hoja.escrituras.clear()
    mb.cargar_entregas_retornos(libro, "ONHIRE", filas)
    assert "P2" not in hoja.escrituras and "R2" not in hoja.escrituras
    assert not any(e.startswith("clear:P") or e.startswith("clear:R") for e in hoja.escrituras)


def test_una_corrida_sin_filas_no_borra_el_derrame():
    libro, hoja = _libro("ONHIRE")
    mb.cargar_entregas_retornos(libro, "ONHIRE", [_fila_reporte(i) for i in range(3)])
    mb.cargar_entregas_retornos(libro, "ONHIRE", [])          # p. ej. el día 1 antes de la primera entrega
    assert hoja.celda("P2") == mb.FORMULA_P_ONHIRE and hoja.celda("R2") == mb.FORMULA_R_ONHIRE
    assert hoja.celda("A2") == "" and hoja.celda("Q2") == "" and hoja.celda("S2") == ""


def test_el_balance_cuenta_por_la_columna_R():
    from datetime import date
    filas, columnas = mb._formulas_balance(date(2026, 11, 14))
    assert "ONHIRE!$R:$R" in filas[2][2] and "ONHIRE!$P:$P" not in filas[2][2]
    assert "RETORNOS!$R:$R" in filas[11][2] and "RETORNOS!$P:$P" not in filas[11][2]
    assert filas[1][2] == (date(2026, 11, 1) - mb.EPOCH_SHEETS).days     # C1 = día 1 del mes
    assert columnas == 33


def test_el_resumen_por_ejecutivo_empieza_en_la_fila_21():
    from datetime import date
    filas, _ = mb._formulas_balance(date(2026, 11, 1))
    assert filas[21][1:] == ["ENTREGAS", "RETORNOS"]
    assert filas[21][0].startswith("=UNIQUE(FILTER(A1:A18")
    assert "XLOOKUP($A22,$A$2:$A$9,$B$2:$B$9,0)" in filas[22][1]
    assert "XLOOKUP($A22,$A$11:$A$18,$B$11:$B$18,0)" in filas[22][2]
    assert max(k for k in filas if k > 21) == 21 + mb.BALANCE_FILAS_RESUMEN


# ---------------------------------------------------------------- regla de reemplazo (CAMBIO -> NUEVO) en ONHIRE!P2
def test_p2_ya_no_es_la_formula_del_30_oct():
    assert mb.FORMULA_P_ONHIRE != NUVIA_ONHIRE_P2_30_OCT
    assert mb.FORMULA_P_ONHIRE == NUVIA_ONHIRE_P2


def test_la_regla_de_reemplazo_pide_las_cuatro_condiciones():
    f = mb.FORMULA_P_ONHIRE
    assert 'tipoSol="ENTREGA (CAMBIO)"' in f                              # la solicitud encontrada es un cambio
    assert "UPPER(INDEX(mejor,1,4))=UPPER(pla)" in f                      # y esta placa es la de reemplazo (no la que falló)
    assert 'sTip,"ENTREGA (NUEVO)",sEst,"<>TRASLADO CANCELADO")>0' in f   # la reserva tiene una ENTREGA (NUEVO) no cancelada
    assert "'FLOTA MES ANTERIOR'!$K:$K,INDEX(mejor,1,3))=0" in f          # y no venía del mes anterior
    assert f.count('"ENTREGA (NUEVO)"') == 2                              # el valor convertido y el criterio de búsqueda


def test_r_y_retornos_no_cambian_con_la_regla_de_reemplazo():
    assert mb.FORMULA_R_ONHIRE == NUVIA_ONHIRE_R2
    assert mb.FORMULA_R_RETORNOS == NUVIA_RETORNOS_R2
    assert "reemplazo" not in mb.FORMULA_P_RETORNOS and "CAMBIO" not in mb.FORMULA_P_RETORNOS


def test_la_formula_del_30_oct_se_repone_con_la_regla_de_reemplazo_sin_tocar_lo_demas():
    libro, hoja = _libro("ONHIRE")
    hoja.poner("P2", NUVIA_ONHIRE_P2_30_OCT)                  # como está hoy el libro real
    hoja.poner("R2", mb.FORMULA_R_ONHIRE)
    mb.cargar_entregas_retornos(libro, "ONHIRE", [_fila_reporte(i) for i in range(3)])
    assert hoja.celda("P2") == mb.FORMULA_P_ONHIRE
    assert hoja.celda("R2") == mb.FORMULA_R_ONHIRE            # R2 ya era la correcta: no se reescribe
    assert "R2" not in hoja.escrituras
    assert all(hoja.celda(f"P{r}") == "" for r in range(3, 8))  # nada debajo: bloquearía el derrame


def test_con_la_regla_de_reemplazo_la_segunda_corrida_no_reescribe_p2():
    libro, hoja = _libro("ONHIRE")
    hoja.poner("P2", NUVIA_ONHIRE_P2_30_OCT)
    filas = [_fila_reporte(i) for i in range(3)]
    mb.cargar_entregas_retornos(libro, "ONHIRE", filas)
    hoja.escrituras.clear()
    mb.cargar_entregas_retornos(libro, "ONHIRE", filas)
    assert "P2" not in hoja.escrituras and not any(e.startswith("clear:P") for e in hoja.escrituras)

