"""Pruebas del enmascarado de secretos en el registro."""
import logging

from sac_sync.registro import FiltroSecretos


def registro(mensaje, *args):
    """Un LogRecord con el mensaje y los argumentos dados."""
    return logging.LogRecord("prueba", logging.INFO, __file__, 1, mensaje, args, None)


def test_enmascara_los_secretos_en_el_mensaje_ya_formateado():
    """Los secretos que llegan por los argumentos del mensaje también se enmascaran."""
    filtro = FiltroSecretos(["token-de-prueba-123", "1_ID-DEL-SHEET_abc"])
    r = registro("fallo con %s en %s", "token-de-prueba-123", "https://sheets/1_ID-DEL-SHEET_abc/values")
    assert filtro.filter(r) is True
    assert r.getMessage() == "fallo con *** en https://sheets/***/values"


def test_ignora_secretos_cortos_o_vacios():
    """Un valor de menos de 6 caracteres enmascararía texto común, así que no se registra."""
    filtro = FiltroSecretos(["abc", "", None])
    r = registro("abc sigue igual")
    filtro.filter(r)
    assert r.getMessage() == "abc sigue igual"


def test_agregar_un_secreto_despues_de_crear_el_filtro():
    """El ID del tablero se conoce hasta cargar el esquema y se suma al filtro ya instalado."""
    filtro = FiltroSecretos()
    filtro.agregar(1000000002)
    r = registro("tablero 1000000002 no existe")
    filtro.filter(r)
    assert r.getMessage() == "tablero *** no existe"
