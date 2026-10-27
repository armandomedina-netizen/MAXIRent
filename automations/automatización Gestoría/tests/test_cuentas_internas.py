from cuentas_internas import clasificar, compilar_patron, normalizar, nombres_por_revisar, senales_de_cuenta_interna

LISTA = {normalizar(n) for n in [
    "TRASLADO TRASLADO", "ENDEREZADO Y PINTURA", "GESTORIA", "GESTORIA GESTORIA", "HYP LP", "LEVANTAMIENTO DAÑOS LP",
    "OTROS", "RECOLECCION  LOG,LP RECOLECCION  LOG,LP", "RELEVOS", "SEMINUEVOS SEMINUEVOS", "T.CORRECTIVO LP",
    "TALLER EXTERNO TALLER EXTERNO", "TALLER FORANEO", "TALLER TALLER", "USO INTERNO", "HYP CP", "EXT. TALLER",
]}


def test_la_lista_manual_sigue_mandando():
    d = clasificar("  trasladO   TRASLADO ", LISTA)
    assert d.es_interna and d.motivo == "lista"


def test_la_regla_cubre_variantes_que_la_lista_no_tiene():
    for n in ["T.CORRECTIVO CP", "TALLER EXTERNO", "TALLER", "TRASLADO", "SEMINUEVOS", "TALLER MTO", "T.PREVENTIVO LP",
              "CARROCERIA EJEMPLO TALLER EXTERNO", "TALLER DE PRUEBA HYP EXT", "USO INTERNO ALMACEN", "PREVIA PREVIA",
              "HYP EXT HYP EXT", "PERDIDA TOTAL PERDIDA TOTAL"]:
        d = clasificar(n, LISTA)
        assert d.es_interna and d.motivo == "regla", n


def test_los_clientes_reales_no_se_marcan():
    for n in ["EMPRESA EJEMPLO SA DE CV", "LOGISTICA DEL NORTE SA DE CV", "HYPERION SA DE CV", "EXTRACTORES DEL GOLFO SA DE CV",
              "TRANSPORTES TO-GO SA DE CV", "MANTENIMIENTO INTEGRAL EJEMPLO", "TALLERES UNIDOS DEL CENTRO SA DE CV", "ANA PEREZ PEREZ"]:
        assert not clasificar(n, LISTA).es_interna, n


def test_nombres_vacios_nunca_son_internos():
    assert not clasificar(None, LISTA).es_interna and not clasificar("   ", LISTA).es_interna


def test_el_patron_se_toma_de_la_celda_y_uno_invalido_no_tumba():
    p = compilar_patron(r"^(MI CUENTA NUEVA)( |$)")
    assert clasificar("MI CUENTA NUEVA 2", set(), p).es_interna
    assert not clasificar("TALLER", set(), p).es_interna        # la celda reemplaza al patrón por omisión
    assert clasificar("TALLER", set(), compilar_patron("(")).es_interna     # expresión inválida -> patrón por omisión
    assert clasificar("TALLER", set(), compilar_patron("")).es_interna


def test_aviso_de_nombres_nuevos_que_parecen_cuenta_interna():
    assert senales_de_cuenta_interna("CAMBIO DE LLANTAS CAMBIO") == ["palabra repetida"]
    assert senales_de_cuenta_interna("REPOSICION") == ["nombre corto sin sufijo legal"]
    assert senales_de_cuenta_interna("EMPRESA EJEMPLO SA DE CV") == []
    tickets = [(1, "REPOSICION"), (2, "REPOSICION"), (3, "EMPRESA EJEMPLO SA DE CV"), (4, "TALLER TALLER")]
    avisos = nombres_por_revisar(tickets, LISTA, revisados=set())
    assert [(a.nombre, a.tickets, a.primer_folio) for a in avisos] == [("REPOSICION", 2, 1)]
    assert nombres_por_revisar(tickets, LISTA, revisados={"REPOSICION"}) == []
