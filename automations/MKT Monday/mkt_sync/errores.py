"""Errores propios de la sincronización; el punto de entrada los muestra sin traza y sale con código 1."""


class ErrorMKT(RuntimeError):
    """Error esperado de la sincronización, con un mensaje pensado para quien la opera."""


class ErrorConfig(ErrorMKT):
    """La configuración o las variables de entorno faltan o son inválidas."""


class ErrorMonday(ErrorMKT):
    """monday rechazó la petición o no respondió bien tras los reintentos."""


class ErrorHoja(ErrorMKT):
    """La hoja de Google no tiene lo esperado o no se puede leer o escribir."""
