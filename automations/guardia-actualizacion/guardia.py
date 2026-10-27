"""
Guardia de actualización: segundo corte después del matutino.

Que un workflow termine en éxito no demuestra que la información se actualizó: el 26-oct la corrida
de las 8:18 de Clientes Nuevos terminó bien con 0 filas porque Maxinet aún no publicaba el reporte.
La guardia comprueba el resultado, no la corrida:

1. Para cada automatización del Tablero CP (Clientes Nuevos, Clientes Potenciales, Encuestas, Entregas,
   Frecuentes Activos y el cierre diario del Tablero) corre su modo DRY_RUN, que calcula qué le falta a
   la hoja frente a Maxinet sin escribir nada, y lee cuántas filas, columnas o semanas faltan.
2. Si falta algo, relanza el workflow de esa automatización (así se serializa con su grupo de
   concurrencia y nunca hay dos procesos agregando filas al mismo tiempo), espera a que termine y
   vuelve a comprobar.
3. Comprueba que los datos del día lleguen al Tablero (FLOTA CP trae la fecha de ayer) y que las
   pestañas clave del Tablero no tengan celdas con error.

Termina con código 1 si al final algo sigue sin actualizarse o no se pudo verificar: el Vigilante de
Apps Script lo avisa por correo. No escribe en las hojas por su cuenta y no registra datos de
clientes; sólo nombres, conteos y fechas.

Variables de entorno: las de las automatizaciones de CP (MAXINET_*, GOOGLE_CREDS_PATH,
SPREADSHEET_ID_CLIENTES_NUEVOS, SPREADSHEET_ID_TABLERO_CP y los WORKSHEET_*), y GITHUB_TOKEN con permiso
actions:write más GITHUB_REPOSITORY para relanzar. Opcional: SIN_RELANZAR=1 (sólo verifica).
"""
import os
import re
import sys
import time
import logging
import subprocess
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("guardia_actualizacion")

RAIZ = Path(__file__).resolve().parents[1]
ZONA = ZoneInfo("America/Mexico_City")
TIMEOUT_SECO = 900
ESPERA_MAX_RELANZAR = 900
SONDEO_SEG = 15
PESTANAS_SIN_ERRORES = (
    "FLOTA CP", "UNIDADES CP", "UTILIZACION TODOS LOS GRUPO", "UTILIZACION POR GRUPO", "DETALLE", "GRAFICAS", "MKT",
    "Bitácora Entregas / Recolecciones CP", "ENTREGAS POR SUCURSAL", "INDICADOR DE GASOLINA",
    "CLIENTES NUEVOS & POTENCIAL", "Ticket Sac/Maxiemergencia", "POR ASESOR", "KADEX EJECUTIVOS",
)
ERROR_CELDA = re.compile(r"^#(REF!|N/A|VALUE!|NAME\?|ERROR!|DIV/0!)|^Please use")


# ---------------------------------------------------------------- lectura de la salida de las corridas en seco
def _termino_bien(salida: str) -> bool:
    return bool(re.search(r"completad[ao] con éxito", salida))


def pendientes_filas(salida: str):
    """Clientes Nuevos, Clientes Potenciales y Encuestas: filas que el DRY_RUN agregaría. None si no terminó bien."""
    if not _termino_bien(salida):
        return None
    return sum(int(n) for n in re.findall(r"se agregarían (\d+)", salida))


def pendientes_entregas(salida: str):
    """Entregas: altas más bajas del bloque del mes. Los estatus cambiados no cuentan: cambian durante el día."""
    if not _termino_bien(salida):
        return None
    bloques = re.findall(r"altas (\d+), bajas (\d+)", salida)
    if not bloques:
        return None
    return sum(int(a) + int(b) for a, b in bloques)


def pendientes_frecuentes(salida: str):
    """Frecuentes Activos: 0 si la hoja ya refleja la semana más reciente de Maxinet, 1 si hay algo que reemplazar."""
    if not re.search(r"Revisión completada con éxito", salida):
        return None
    return 0 if "Sin cambios" in salida else 1


def leer_cierre(salida: str) -> dict:
    """Cierre diario del Tablero: fecha de los datos de FLOTA CP y acciones que quedarían pendientes."""
    m = re.search(r"Fecha de los datos de FLOTA CP: (\d{4}-\d{2}-\d{2})", salida)
    if not m or not re.search(r"Cierre diario (completado con éxito|con pendientes)", salida):
        return {}
    pendientes = (len(re.findall(r"crear columna viva: sí", salida)) + len(re.findall(r"columnas a congelar: \[", salida))
                  + len(re.findall(r"se rellenan \[", salida)) + len(re.findall(r" ERROR ", salida)))
    return {"fecha": dt.date.fromisoformat(m[1]), "pendientes": pendientes}


# ---------------------------------------------------------------- qué se revisa
@dataclass(frozen=True)
class Revision:
    nombre: str
    directorio: str
    script: str
    workflow: str
    leer: object          # función salida -> pendientes (int) o None si no se pudo verificar


REVISIONES = (
    Revision("Clientes Nuevos", "maxinet-clientes-nuevos-cp", "maxinet_clientes_nuevos_cp.py", "maxinet-clientes-nuevos-cp.yml", pendientes_filas),
    Revision("Clientes Potenciales", "maxinet-clientes-potenciales-cp", "maxinet_clientes_potenciales_cp.py", "maxinet-clientes-potenciales-cp.yml", pendientes_filas),
    Revision("Encuestas", "maxinet-encuestas-cp", "maxinet_encuestas_cp.py", "maxinet-encuestas-cp.yml", pendientes_filas),
    Revision("Entregas", "maxinet-entregas-cp", "maxinet_entregas_cp.py", "maxinet-entregas-cp.yml", pendientes_entregas),
    Revision("Frecuentes Activos", "maxinet-frecuentes-activos-cp", "maxinet_frecuentes_activos_cp.py", "maxinet-frecuentes-activos-cp.yml", pendientes_frecuentes),
)
CIERRE = Revision("Cierre diario del Tablero", "tablero-cp-cierre-diario", "cierre_diario.py", "tablero-cp-cierre-diario.yml", None)


@dataclass
class Resultado:
    nombre: str
    estado: str           # ok | recuperado | pendiente | sin datos | no verificado
    detalle: str = ""

    @property
    def bien(self) -> bool:
        return self.estado in ("ok", "recuperado")


# ---------------------------------------------------------------- ejecución real
def ejecutar_en_seco(rev: Revision) -> tuple:
    """(código, salida) de la corrida en seco de la automatización; no escribe en ninguna hoja."""
    try:
        r = subprocess.run([sys.executable, rev.script], cwd=RAIZ / rev.directorio, capture_output=True, text=True,
                           env={**os.environ, "DRY_RUN": "1"}, timeout=TIMEOUT_SECO)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, ""


def relanzar_workflow(archivo: str) -> str:
    """Lanza el workflow por workflow_dispatch y espera su conclusión; success, failure, timeout o no disponible."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo or os.environ.get("SIN_RELANZAR"):
        return "no disponible"
    cab = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    desde = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=10)
    r = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/{archivo}/dispatches", headers=cab,
                      json={"ref": os.environ.get("GITHUB_REF_NAME") or "main"}, timeout=60)
    if r.status_code != 204:
        return f"no se pudo lanzar (HTTP {r.status_code})"
    limite = time.time() + ESPERA_MAX_RELANZAR
    while time.time() < limite:
        time.sleep(SONDEO_SEG)
        runs = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/{archivo}/runs",
                            params={"event": "workflow_dispatch", "per_page": 10}, headers=cab, timeout=60).json().get("workflow_runs", [])
        nuevas = [x for x in runs if dt.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00")) >= desde]
        if nuevas and nuevas[0]["status"] == "completed":
            return nuevas[0]["conclusion"] or "desconocida"
    return "timeout"


def con_reintentos(fn, *args, **kwargs):
    """Llama a Sheets y reintenta con espera creciente ante 429 (la cuota por minuto se comparte) o 5xx."""
    import gspread
    for n in range(6):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if getattr(e.response, "status_code", 0) in (429, 500, 502, 503) and n < 5:
                time.sleep(20 * (n + 1))
                continue
            raise


def contar_errores_tablero() -> dict:
    """Celdas con error por pestaña clave del Tablero CP, sólo las pestañas que tienen alguna."""
    import gspread
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_CREDS_PATH"], scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    libro = con_reintentos(gspread.authorize(creds).open_by_key, os.environ["SPREADSHEET_ID_TABLERO_CP"])
    con_error = {}
    for nombre in PESTANAS_SIN_ERRORES:
        valores = con_reintentos(con_reintentos(libro.worksheet, nombre).get_all_values)
        n = sum(1 for fila in valores for x in fila if ERROR_CELDA.match(x))
        if n:
            con_error[nombre] = n
        time.sleep(1.2)
    return con_error


# ---------------------------------------------------------------- lógica de la guardia (sin red: recibe ejecutor y relanzador)
def revisar(rev: Revision, ejecutar=ejecutar_en_seco, relanzar=relanzar_workflow) -> Resultado:
    codigo, salida = ejecutar(rev)
    antes = rev.leer(salida) if codigo == 0 else None
    if antes is None:
        return Resultado(rev.nombre, "no verificado", f"la corrida en seco no terminó bien (código {codigo})")
    if antes == 0:
        return Resultado(rev.nombre, "ok")
    conclusion = relanzar(rev.workflow)
    if conclusion != "success":
        return Resultado(rev.nombre, "pendiente", f"faltaban {antes}; el relanzado terminó como: {conclusion}")
    codigo, salida = ejecutar(rev)
    despues = rev.leer(salida) if codigo == 0 else None
    if despues == 0:
        return Resultado(rev.nombre, "recuperado", f"faltaban {antes}; se relanzó y quedó al día")
    return Resultado(rev.nombre, "pendiente", f"faltaban {antes}; tras relanzar aún falta: {despues}")


def revisar_tablero(ayer: dt.date, ejecutar=ejecutar_en_seco, relanzar=relanzar_workflow) -> list:
    """FLOTA CP con la fecha de ayer y cierre diario al día."""
    codigo, salida = ejecutar(CIERRE)
    estado = leer_cierre(salida)
    if not estado:
        return [Resultado(CIERRE.nombre, "no verificado", f"no se pudo leer la corrida en seco (código {codigo})")]
    if estado["fecha"] != ayer:
        return [Resultado("Datos del día en el Tablero", "sin datos", f"FLOTA CP trae {estado['fecha']} y se esperaba {ayer}"),
                Resultado(CIERRE.nombre, "no verificado", "no se revisa mientras FLOTA CP no tenga los datos del día")]
    out = [Resultado("Datos del día en el Tablero", "ok", f"FLOTA CP trae {ayer}")]
    if estado["pendientes"] == 0:
        return out + [Resultado(CIERRE.nombre, "ok")]
    conclusion = relanzar(CIERRE.workflow)
    codigo, salida = ejecutar(CIERRE)
    despues = leer_cierre(salida)
    if conclusion == "success" and despues and despues["pendientes"] == 0:
        return out + [Resultado(CIERRE.nombre, "recuperado", "tenía columnas por cerrar; se relanzó y quedó al día")]
    return out + [Resultado(CIERRE.nombre, "pendiente", f"relanzado: {conclusion}; pendientes: {despues.get('pendientes') if despues else '?'}")]


def revisar_errores(contar=contar_errores_tablero) -> Resultado:
    try:
        con_error = contar()
    except Exception as e:                                       # hoja renombrada, cuota o permisos
        return Resultado("Errores en el Tablero", "no verificado", f"{type(e).__name__}")
    if con_error:
        return Resultado("Errores en el Tablero", "pendiente", ", ".join(f"{k}: {v}" for k, v in con_error.items()))
    return Resultado("Errores en el Tablero", "ok", f"{len(PESTANAS_SIN_ERRORES)} pestañas sin celdas con error")


def resumen(resultados: list) -> str:
    marcas = {"ok": "OK         ", "recuperado": "RECUPERADO ", "pendiente": "PENDIENTE  ", "sin datos": "SIN DATOS  ", "no verificado": "NO VERIFICADO"}
    return "\n".join(f"{marcas[r.estado]} {r.nombre}" + (f" — {r.detalle}" if r.detalle else "") for r in resultados)


def main() -> int:
    ayer = dt.datetime.now(ZONA).date() - dt.timedelta(days=1)
    log.info("Guardia de actualización: se espera información hasta el %s", ayer)
    resultados = [revisar(r) for r in REVISIONES] + revisar_tablero(ayer) + [revisar_errores()]
    texto = resumen(resultados)
    log.info("Resultado:\n%s", texto)
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(f"### Guardia de actualización (datos hasta {ayer})\n\n```\n{texto}\n```\n")
    malos = [r for r in resultados if not r.bien]
    if malos:
        log.error("La guardia encontró %d punto(s) sin actualizar o sin verificar", len(malos))
        return 1
    log.info("Todo actualizado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
