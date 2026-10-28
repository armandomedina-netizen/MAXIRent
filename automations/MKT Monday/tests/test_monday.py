import json

import pytest

from mkt_sync.config import Config
from mkt_sync.errores import ErrorMonday
from mkt_sync.monday import ClienteMonday, ids_por_etiqueta

CFG = Config(tablero_id=1, columna_estado="estado", etiqueta_califica="Califica", columna_tipo="tipo",
             tipos_incluidos=("Saliente",))
COLUMNAS = [
    {"id": "estado", "type": "status", "settings_str": json.dumps({"labels": {"0": "Nuevo", "1": "Califica", "5": ""}})},
    {"id": "tipo", "type": "status", "settings_str": json.dumps({"labels": {"0": "Entrante", "3": "Saliente"}})},
    {"id": "texto", "type": "text", "settings_str": "{}"},
]


class Resp:
    def __init__(self, status=200, cuerpo=None, headers=None):
        self.status_code, self._cuerpo, self.headers = status, cuerpo, headers or {}

    def json(self):
        return self._cuerpo


class SesionFalsa:
    """Sesión HTTP que entrega las respuestas en el orden dado y guarda lo que se le pidió."""

    def __init__(self, *respuestas):
        self.headers, self.respuestas, self.pedidos = {}, list(respuestas), []

    def post(self, url, json=None, timeout=None):
        self.pedidos.append(json)
        return self.respuestas.pop(0)


def cliente(*respuestas):
    sesion = SesionFalsa(*respuestas)
    return ClienteMonday("token", sesion=sesion, dormir=lambda s: None), sesion


def tablero(columnas=COLUMNAS):
    return Resp(cuerpo={"data": {"boards": [{"columns": columnas}]}})


def pagina(ids, cursor=None, primera=True):
    items = [{"id": i, "created_at": "2026-10-02T15:00:00Z", "column_values": []} for i in ids]
    cuerpo = {"items_page": {"cursor": cursor, "items": items}}
    return Resp(cuerpo={"data": {"boards": [cuerpo]} if primera else {"next_items_page": cuerpo["items_page"]}})


def test_ids_por_etiqueta_descarta_etiquetas_sin_nombre():
    assert ids_por_etiqueta(COLUMNAS[0]) == {"Nuevo": [0], "Califica": [1]}


def test_validar_devuelve_los_ids_del_tipo_incluido():
    c, _ = cliente(tablero())
    assert c.validar(CFG) == [3]


def test_validar_detecta_cambios_en_el_tablero():
    sin_tablero, _ = cliente(Resp(cuerpo={"data": {"boards": []}}))
    with pytest.raises(ErrorMonday, match="no ve el tablero"):
        sin_tablero.validar(CFG)
    sin_estado, _ = cliente(tablero([c for c in COLUMNAS if c["id"] != "estado"]))
    with pytest.raises(ErrorMonday, match="ya no existe"):
        sin_estado.validar(CFG)
    no_estatus, _ = cliente(tablero([COLUMNAS[0], {**COLUMNAS[1], "type": "text"}, COLUMNAS[2]]))
    with pytest.raises(ErrorMonday, match="ya no es una columna de estatus"):
        no_estatus.validar(CFG)
    otra_etiqueta, _ = cliente(tablero([{**COLUMNAS[0], "settings_str": json.dumps({"labels": {"0": "Nuevo"}})}, *COLUMNAS[1:]]))
    with pytest.raises(ErrorMonday, match="etiqueta de leads calificados"):
        otra_etiqueta.validar(CFG)
    otro_tipo, _ = cliente(tablero([COLUMNAS[0], {**COLUMNAS[1], "settings_str": json.dumps({"labels": {"0": "Entrante"}})}, COLUMNAS[2]]))
    with pytest.raises(ErrorMonday, match="1 de los tipos"):
        otro_tipo.validar(CFG)


def test_los_mensajes_de_validacion_no_nombran_columnas_ni_etiquetas():
    cfg = Config(tablero_id=1, columna_estado="zz_estado_77", etiqueta_califica="EtiquetaSecreta",
                 columna_tipo="zz_tipo_88", tipos_incluidos=("TipoSecreto",))
    columnas = [
        {"id": "zz_estado_77", "type": "status", "settings_str": json.dumps({"labels": {"1": "EtiquetaSecreta"}})},
        {"id": "zz_tipo_88", "type": "status", "settings_str": json.dumps({"labels": {"0": "Otro"}})},
    ]
    c, _ = cliente(tablero(columnas))
    with pytest.raises(ErrorMonday) as e:
        c.validar(cfg)
    assert not any(secreto in str(e.value) for secreto in ("zz_estado_77", "zz_tipo_88", "EtiquetaSecreta", "TipoSecreto"))


def test_leer_leads_pagina_y_descarta_duplicados():
    c, sesion = cliente(pagina(["1", "2"], "sig"), pagina(["2", "3"], None, primera=False))
    leads = c.leer_leads(CFG, [3])
    assert [lead["id"] for lead in leads] == ["1", "2", "3"]
    regla = sesion.pedidos[0]["variables"]["filtro"]["rules"][0]
    assert regla == {"column_id": "tipo", "compare_value": [3], "operator": "any_of"}
    assert sesion.pedidos[1]["variables"]["cursor"] == "sig"


def test_token_rechazado():
    c, _ = cliente(Resp(401))
    with pytest.raises(ErrorMonday, match="rechazó el token"):
        c.validar(CFG)


def test_reintenta_ante_429_y_errores_de_limite():
    limite = Resp(cuerpo={"errors": [{"message": "x", "extensions": {"code": "RATE_LIMIT_EXCEEDED", "retry_in_seconds": 2}}]})
    c, sesion = cliente(Resp(429, headers={"Retry-After": "1"}), limite, tablero())
    assert c.validar(CFG) == [3]
    assert len(sesion.pedidos) == 3


def test_error_graphql_no_se_reintenta():
    c, sesion = cliente(Resp(cuerpo={"errors": [{"message": "campo inválido", "extensions": {"code": "argumentLiteralsIncompatible"}}]}))
    with pytest.raises(ErrorMonday, match="campo inválido"):
        c.validar(CFG)
    assert len(sesion.pedidos) == 1


def test_se_rinde_tras_los_intentos_maximos():
    c, _ = cliente(*[Resp(503)] * 8)
    with pytest.raises(ErrorMonday, match="no respondió bien"):
        c.validar(CFG)
