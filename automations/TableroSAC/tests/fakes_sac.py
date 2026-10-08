"""Dobles de prueba: respuestas HTTP de monday y pestañas de Google Sheets en memoria."""
import re

from gspread.exceptions import WorksheetNotFound

_RANGO = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")


def _col_a_numero(letras: str) -> int:
    """Convierte las letras de una columna (A, AJ...) a su número."""
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - 64)
    return n


def _parsear_rango(rango: str) -> tuple[int, int, int, int]:
    """Convierte 'A2:AJ10' en (fila inicial, columna inicial, fila final, columna final)."""
    c1, r1, c2, r2 = _RANGO.match(rango).groups()
    return int(r1), _col_a_numero(c1), int(r2), _col_a_numero(c2)


class FakeRespuesta:
    """Respuesta HTTP mínima, con la interfaz de requests que usa el cliente."""

    def __init__(self, estado=200, cuerpo=None, cabeceras=None):
        """Guarda el código de estado, el cuerpo JSON (None simula un cuerpo que no es JSON) y las cabeceras."""
        self.status_code = estado
        self._cuerpo = cuerpo
        self.headers = cabeceras or {}

    def json(self):
        """Devuelve el cuerpo o lanza ValueError como lo haría requests."""
        if self._cuerpo is None:
            raise ValueError("sin JSON")
        return self._cuerpo


class FakeSesion:
    """Sesión de requests que entrega respuestas programadas (o lanza excepciones) y guarda las peticiones."""

    def __init__(self, respuestas):
        """Recibe la cola de respuestas o excepciones que devolverá en orden."""
        self.headers = {}
        self.respuestas = list(respuestas)
        self.peticiones = []

    def post(self, url, json=None, timeout=None):
        """Registra la petición y devuelve (o lanza) la siguiente respuesta programada."""
        self.peticiones.append({"url": url, "json": json})
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


class FakeMonday:
    """Cliente de monday que devuelve elementos fijos por grupo y registra las lecturas."""

    def __init__(self, items_por_grupo):
        """Recibe un diccionario grupo_id -> lista de elementos."""
        self.items_por_grupo = items_por_grupo
        self.lecturas = []

    def leer_grupo(self, grupo_id, ids_columnas):
        """Devuelve los elementos del grupo."""
        self.lecturas.append(grupo_id)
        return self.items_por_grupo[grupo_id]


class FakeLibroHoja:
    """Libro de la pestaña: guarda las solicitudes de batch_update."""

    def __init__(self):
        """Empieza sin solicitudes."""
        self.solicitudes = []

    def batch_update(self, cuerpo):
        """Registra el cuerpo de la solicitud."""
        self.solicitudes.append(cuerpo)


class FakeHoja:
    """Pestaña en memoria con la parte de la interfaz de gspread que usa el código; registra las llamadas."""

    def __init__(self, title="Pestana A", row_count=1000, col_count=11, encabezados=None, filas=None):
        """Carga los encabezados en la fila 1 y las filas de datos desde la 2."""
        self.title = title
        self.id = 777
        self.row_count = row_count
        self.col_count = col_count
        self.spreadsheet = FakeLibroHoja()
        self.celdas = {}
        self.llamadas = []
        for j, valor in enumerate(encabezados or [], start=1):
            self.celdas[(1, j)] = valor
        for i, fila in enumerate(filas or [], start=2):
            for j, valor in enumerate(fila, start=1):
                if valor is not None and valor != "":
                    self.celdas[(i, j)] = valor

    def nombres_de_llamadas(self):
        """Lista con el nombre de cada llamada registrada, en orden."""
        return [llamada[0] for llamada in self.llamadas]

    def row_values(self, fila):
        """Valores de una fila hasta su última celda con contenido."""
        columnas = [c for (r, c) in self.celdas if r == fila]
        if not columnas:
            return []
        return ["" if self.celdas.get((fila, c)) is None else self.celdas[(fila, c)]
                for c in range(1, max(columnas) + 1)]

    def col_values(self, columna):
        """Valores de una columna, como texto, hasta su última celda con contenido."""
        filas = [r for (r, c) in self.celdas if c == columna]
        if not filas:
            return []
        return ["" if (r, columna) not in self.celdas else str(self.celdas[(r, columna)])
                for r in range(1, max(filas) + 1)]

    def get(self, rango, value_render_option=None):
        """Valores de un rango sin las celdas ni las filas finales vacías, como los entrega la API."""
        self.llamadas.append(("get", rango, value_render_option))
        r1, c1, r2, c2 = _parsear_rango(rango)
        filas = []
        for r in range(r1, min(r2, self.row_count) + 1):
            fila = [self.celdas.get((r, c)) for c in range(c1, c2 + 1)]
            while fila and fila[-1] is None:
                fila.pop()
            filas.append(fila)
        while filas and not filas[-1]:
            filas.pop()
        return filas

    def update(self, values=None, range_name=None, value_input_option=None):
        """Escribe los valores desde el inicio del rango; una cadena vacía deja la celda en blanco."""
        self.llamadas.append(("update", range_name, value_input_option, len(values)))
        r1, c1, _, _ = _parsear_rango(range_name)
        for i, fila in enumerate(values):
            for j, valor in enumerate(fila):
                if valor == "":
                    self.celdas.pop((r1 + i, c1 + j), None)
                else:
                    self.celdas[(r1 + i, c1 + j)] = valor

    def batch_clear(self, rangos):
        """Borra los valores de cada rango."""
        self.llamadas.append(("batch_clear", tuple(rangos)))
        for rango in rangos:
            r1, c1, r2, c2 = _parsear_rango(rango)
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    self.celdas.pop((r, c), None)

    def add_rows(self, cantidad):
        """Suma filas a la capacidad de la pestaña."""
        self.llamadas.append(("add_rows", cantidad))
        self.row_count += cantidad


class FakeLibro:
    """Libro de Google Sheets con las pestañas que se le den."""

    def __init__(self, hojas):
        """Recibe las pestañas (FakeHoja) y las indexa por título."""
        self._hojas = {h.title: h for h in hojas}

    def worksheet(self, nombre):
        """Devuelve la pestaña o lanza WorksheetNotFound como gspread."""
        if nombre not in self._hojas:
            raise WorksheetNotFound(nombre)
        return self._hojas[nombre]
