"""Las cinco automatizaciones de la Base CP encuentran su pestaña por gid o por nombre (sin red)."""
import importlib.util
from pathlib import Path

import gspread
import pytest

RAIZ = Path(__file__).resolve().parents[2]
# (carpeta, módulo, variable con el nombre o gid de la pestaña)
AUTOMATIZACIONES = (
    ("maxinet-clientes-nuevos-cp", "maxinet_clientes_nuevos_cp", "WORKSHEET_CLIENTES_NUEVOS_NAME"),
    ("maxinet-clientes-potenciales-cp", "maxinet_clientes_potenciales_cp", "WORKSHEET_CLIENTES_POTENCIALES_NAME"),
    ("maxinet-encuestas-cp", "maxinet_encuestas_cp", "WORKSHEET_ENCUESTAS_NAME"),
    ("maxinet-entregas-cp", "maxinet_entregas_cp", "WORKSHEET_ENTREGAS_NAME"),
    ("maxinet-frecuentes-activos-cp", "maxinet_frecuentes_activos_cp", "WORKSHEET_FRECUENTES_NAME"),
)


def _cargar(carpeta, modulo):
    spec = importlib.util.spec_from_file_location(f"{modulo}__prueba", RAIZ / carpeta / f"{modulo}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Libro:
    """Libro de mentira con pestañas {gid: título}."""

    def __init__(self, pestanas):
        self.pestanas = pestanas
        self.pedidas = []

    def get_worksheet_by_id(self, gid):
        self.pedidas.append(("gid", gid))
        if gid not in self.pestanas:
            raise gspread.exceptions.WorksheetNotFound(str(gid))
        return ("hoja", gid)

    def worksheet(self, nombre):
        self.pedidas.append(("nombre", nombre))
        for gid, titulo in self.pestanas.items():
            if titulo == nombre:
                return ("hoja", gid)
        raise gspread.exceptions.WorksheetNotFound(nombre)

    def worksheets(self):
        return [type("W", (), {"title": t}) for t in self.pestanas.values()]


@pytest.fixture(params=AUTOMATIZACIONES, ids=[a[1] for a in AUTOMATIZACIONES])
def auto(request, monkeypatch):
    carpeta, modulo, variable = request.param
    m = _cargar(carpeta, modulo)
    libro = Libro({101: "BD ALGO", 202: "OTRA"})
    monkeypatch.setenv("GOOGLE_CREDS_PATH", "no-importa.json")
    monkeypatch.setenv("SPREADSHEET_ID_CLIENTES_NUEVOS", "libro-de-prueba")
    monkeypatch.setattr(m.service_account.Credentials, "from_service_account_file", lambda *a, **k: None)
    monkeypatch.setattr(m.gspread, "authorize", lambda creds: type("C", (), {"open_by_key": lambda self, k: libro})())
    return m, variable, libro, monkeypatch


def test_el_secret_con_un_gid_abre_la_pestana_por_id(auto):
    m, variable, libro, mp = auto
    mp.setenv(variable, " 101 ")
    assert m.conectar_sheet() == ("hoja", 101)
    assert libro.pedidas == [("gid", 101)]


def test_el_secret_con_un_nombre_sigue_funcionando(auto):
    m, variable, libro, mp = auto
    mp.setenv(variable, ' "BD ALGO" ')
    assert m.conectar_sheet() == ("hoja", 101)
    assert libro.pedidas == [("nombre", "BD ALGO")]


def test_sin_secret_usa_el_nombre_de_siempre(auto):
    m, variable, libro, mp = auto
    mp.delenv(variable, raising=False)
    with pytest.raises(gspread.exceptions.WorksheetNotFound):
        m.conectar_sheet()
    assert libro.pedidas[0][0] == "nombre"


def test_pestana_inexistente_dice_cuantas_hay_y_no_vuelca_los_nombres(auto):
    m, variable, libro, mp = auto
    mp.setenv(variable, "999")
    with pytest.raises(gspread.exceptions.WorksheetNotFound) as e:
        m.conectar_sheet()
    mensaje = str(e.value)
    assert "999" in mensaje and "2 pestañas" in mensaje and "gid" in mensaje
    assert "BD ALGO" not in mensaje and "OTRA" not in mensaje
