"""Registro de ejecución. Los logs de GitHub Actions de un repositorio público los ve cualquiera,
así que sólo se imprimen conteos y se enmascaran los secretos conocidos (token, ID del Sheet, ID
del tablero) por si el mensaje de error de una librería los trae.
"""
from __future__ import annotations

import logging
import sys


class FiltroSecretos(logging.Filter):
    """Filtro de logging que reemplaza por *** los secretos que aparezcan en los mensajes."""

    def __init__(self, secretos=()):
        """Registra los secretos iniciales."""
        super().__init__()
        self._secretos: list[str] = []
        for s in secretos:
            self.agregar(s)

    def agregar(self, secreto) -> None:
        """Suma un secreto a la lista; los valores de menos de 6 caracteres se ignoran para no
        enmascarar texto común."""
        secreto = str(secreto or "").strip()
        if len(secreto) >= 6 and secreto not in self._secretos:
            self._secretos.append(secreto)

    def enmascarar(self, texto: str) -> str:
        """Reemplaza cada secreto conocido por ***."""
        for secreto in self._secretos:
            texto = texto.replace(secreto, "***")
        return texto

    def filter(self, record: logging.LogRecord) -> bool:
        """Deja el mensaje ya formateado y enmascarado en el registro."""
        record.msg = self.enmascarar(record.getMessage())
        record.args = ()
        return True


def configurar_registro(secretos=()) -> FiltroSecretos:
    """Envía el log a stdout con marca de tiempo y devuelve el filtro, para sumarle secretos después."""
    filtro = FiltroSecretos(secretos)
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    manejador.addFilter(filtro)
    raiz = logging.getLogger()
    raiz.handlers[:] = [manejador]
    raiz.setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return filtro
