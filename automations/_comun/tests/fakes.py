"""Cliente de Google Sheets simulado: un libro con hojas, filtros básicos y filas ocultas por filtro."""
import re

from gspread.exceptions import APIError


class RespuestaFalsa:
    def __init__(self, codigo, mensaje):
        self.status_code = codigo
        self.text = mensaje
        self._cuerpo = {"error": {"code": codigo, "message": mensaje, "status": "INVALID_ARGUMENT"}}

    def json(self):
        return self._cuerpo


def error_api(codigo, mensaje):
    return APIError(RespuestaFalsa(codigo, mensaje))


FILA_FILTRADA = "Invalid requests[0].copyPaste: This operation is not supported on a range with a filtered out row."


class ClienteFalso:
    """Imita lo que Google hace con un `copyPaste` cuyo ORIGEN tiene filas ocultas por un filtro (probado en la API real).

    `hojas`: {sheetId: {"titulo": str, "filtro": spec o None, "ocultas": set de filas base 0 que el filtro oculta}}.
    """

    def __init__(self, hojas):
        self.hojas = hojas
        self.llamadas = []               # peticiones recibidas por batch_update (lista de listas)
        self.consultas = []              # params de fetch_sheet_metadata
        self.fallar_en = None            # callable(peticiones) -> excepción | None, para forzar otros errores
        self._guardadas = {}             # filas que ocultaba el filtro al suspenderlo

    # --- API que usa filtros_sheets ---------------------------------------------------------
    def batch_update(self, id, body):
        peticiones = list(body["requests"])
        self.llamadas.append(peticiones)
        if self.fallar_en:
            e = self.fallar_en(peticiones)
            if e:
                raise e
        for p in peticiones:
            if "copyPaste" in p:
                o = p["copyPaste"]["source"]
                hoja = self.hojas[o["sheetId"]]
                if any(r in hoja["ocultas"] for r in range(o.get("startRowIndex", 0), o["endRowIndex"])):
                    raise error_api(400, FILA_FILTRADA)
            elif "clearBasicFilter" in p:
                hoja = self.hojas[p["clearBasicFilter"]["sheetId"]]
                self._guardadas[p["clearBasicFilter"]["sheetId"]] = set(hoja["ocultas"])
                hoja["filtro"], hoja["ocultas"] = None, set()
            elif "setBasicFilter" in p:
                f = p["setBasicFilter"]["filter"]
                sid = f["range"]["sheetId"]
                self.hojas[sid]["filtro"] = f
                self.hojas[sid]["ocultas"] = set(self._guardadas.get(sid, set()))
        return {"replies": [{} for _ in peticiones]}

    def fetch_sheet_metadata(self, id, params=None):
        self.consultas.append(params)
        if params.get("includeGridData"):
            m = re.fullmatch(r"'((?:[^']|'')*)'!A(\d+):A(\d+)", params["ranges"][0])
            titulo = m.group(1).replace("''", "'")
            desde, hasta = int(m.group(2)) - 1, int(m.group(3))
            hoja = next(h for h in self.hojas.values() if h["titulo"] == titulo)
            filas = [{"hiddenByFilter": True} if r in hoja["ocultas"] else {} for r in range(desde, hasta)]
            return {"sheets": [{"data": [{"startRow": desde, "rowMetadata": filas}]}]}
        return {"sheets": [{"properties": {"sheetId": sid, "title": h["titulo"]},
                            **({"basicFilter": h["filtro"]} if h["filtro"] else {})} for sid, h in self.hojas.items()]}


def hoja(titulo="DATOS", ocultas=(), con_filtro=True):
    spec = {"range": {"sheetId": 1, "startRowIndex": 0, "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 5},
            "filterSpecs": [{"columnIndex": 1, "filterCriteria": {"hiddenValues": ["B"]}}]}
    return {"titulo": titulo, "filtro": spec if con_filtro else None, "ocultas": set(ocultas)}


def copiar(hoja_id, fila_origen, destino=(20, 25), tipo="PASTE_FORMAT"):
    """copyPaste de una fila origen (base 1) a un tramo destino (base 0, [a, b))."""
    return {"copyPaste": {
        "source": {"sheetId": hoja_id, "startRowIndex": fila_origen - 1, "endRowIndex": fila_origen,
                   "startColumnIndex": 0, "endColumnIndex": 5},
        "destination": {"sheetId": hoja_id, "startRowIndex": destino[0], "endRowIndex": destino[1],
                        "startColumnIndex": 0, "endColumnIndex": 5},
        "pasteType": tipo}}
