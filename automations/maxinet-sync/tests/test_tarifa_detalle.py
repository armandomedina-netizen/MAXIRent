"""Lectura de TARIFA DETALLE (copia del Query): de ahí salen la lista de clientes LP y el historial de rentas."""
import pytest

import maxinet_sync as m

ENCABEZADO = [""] * 21
for indice, texto in m.ENCABEZADOS_TARIFA_DETALLE.items():
    ENCABEZADO[indice] = texto


def _fila(placa, cliente, ejecutivo="KAM"):
    fila = [""] * 21
    fila[m.IDX_RAD_PLACA] = placa
    fila[m.IDX_RAD_CLIENTE] = cliente
    fila[m.IDX_RAD_EJECUTIVO] = ejecutivo
    return fila


class _Pestana:
    def __init__(self, filas):
        self.filas = filas

    def get(self, rango, value_render_option=None):
        return self.filas


class _Libro:
    def __init__(self, nombre, filas):
        self.nombre, self.filas = nombre, filas

    def worksheet(self, nombre):
        assert nombre == self.nombre, f"se pidió '{nombre}' y la hoja se llama '{self.nombre}'"
        return _Pestana(self.filas)

    def get_worksheet_by_id(self, gid):
        return _Pestana(self.filas)

    def worksheets(self):
        return []


@pytest.fixture
def libro(monkeypatch):
    """Reemplaza las credenciales y gspread por un libro falso con TARIFA DETALLE."""
    monkeypatch.setenv("GOOGLE_CREDS_PATH", "x")
    monkeypatch.setenv("SPREADSHEET_ID_QUERY", "y")
    monkeypatch.delenv("WORKSHEET_TARIFA_DETALLE", raising=False)
    monkeypatch.setattr(m.service_account.Credentials, "from_service_account_file",
                        staticmethod(lambda *a, **k: object()))

    def preparar(filas, nombre="TARIFA DETALLE"):
        libro_falso = _Libro(nombre, filas)

        class Cliente:
            def open_by_key(self, clave):
                return libro_falso

        monkeypatch.setattr(m.gspread, "authorize", lambda credenciales: Cliente())
        return libro_falso

    return preparar


def test_devuelve_las_filas_de_datos_sin_el_encabezado(libro):
    libro([ENCABEZADO, _fila("AAA", "CLIENTE UNO"), _fila("BBB", "CLIENTE DOS")])
    filas = m._leer_tarifa_detalle()
    assert [f[m.IDX_RAD_PLACA] for f in filas] == ["AAA", "BBB"]


def test_si_mueven_una_columna_se_detiene_con_un_mensaje_claro(libro):
    encabezado = list(ENCABEZADO)
    encabezado[m.IDX_RAD_CLIENTE] = "OTRA COSA"
    libro([encabezado, _fila("AAA", "CLIENTE UNO")])
    with pytest.raises(RuntimeError) as error:
        m._leer_tarifa_detalle()
    assert "CLIENTES" in str(error.value) and "OTRA COSA" in str(error.value)


def test_clientes_lp_en_mayusculas_y_sin_vacios(libro):
    libro([ENCABEZADO, _fila("AAA", " cliente uno "), _fila("BBB", ""), _fila("CCC", "Cliente Dos")])
    assert m._obtener_clientes_rentas_lp() == {"CLIENTE UNO", "CLIENTE DOS"}


def test_el_secret_opcional_cambia_la_pestana(libro, monkeypatch):
    libro([ENCABEZADO, _fila("AAA", "X")], nombre="OTRO NOMBRE")
    monkeypatch.setenv("WORKSHEET_TARIFA_DETALLE", "OTRO NOMBRE")
    assert len(m._leer_tarifa_detalle()) == 1
    monkeypatch.setenv("WORKSHEET_TARIFA_DETALLE", "123456")  # por gid
    assert len(m._leer_tarifa_detalle()) == 1
