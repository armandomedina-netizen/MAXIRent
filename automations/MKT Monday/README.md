# MKT Monday

Actualiza en la pestaña **MKT** del libro del tablero LP los **leads recibidos** (columna G) y los **leads calificados** (columna H) del mes en curso, a partir de los leads del CRM de ventas en monday.

## Qué hace

1. Lee de monday los leads del tipo configurado, con su fecha de creación y su estado.
2. Cuenta los creados en el mes en curso (hora de Ciudad de México): el total es *recibidos* y los que tienen la etiqueta de calificado son *calificados*.
3. Busca en la columna F de la hoja la fila de ese mes (la celda es una fecha; también acepta texto como `oct 2026`) y escribe solo G y H de esa fila.

No toca ninguna otra celda: la columna de cierres, las fórmulas y los meses anteriores quedan como están.

## Estructura

```
mkt_monday_sync.py      punto de entrada
mkt_sync/
  cli.py                argumentos, variables de entorno y flujo general
  config.py             lectura y validación de la configuración
  monday.py             cliente de lectura de monday (reintentos, paginación)
  conteo.py             conteo de recibidos y calificados por mes
  hoja.py               búsqueda de la fila del periodo y escritura en la hoja
  errores.py            errores esperados
tests/                  pruebas sin red
config.example.json     plantilla de la configuración
docs/decisiones.md      decisiones de diseño
```

## Configuración

El repositorio es público, así que los IDs y nombres reales de monday no se versionan. Viven en un JSON con la forma de `config.example.json`:

- **Local:** `private/mkt-monday-config.json` (la carpeta `private/` la ignora git) o la ruta de `MKT_MONDAY_CONFIG_PATH`.
- **GitHub Actions:** el secret `MKT_MONDAY_CONFIG_JSON`, con el mismo JSON en una sola línea.

Variables de entorno (en `.env` local, copiado de `.env.example`, o como secrets):

| Variable | Para qué |
| --- | --- |
| `MONDAY_TOKEN` | token de la API de monday, solo lectura |
| `GOOGLE_CREDS_PATH` | ruta al JSON de la cuenta de servicio (en Actions se escribe desde `GOOGLE_CREDS_JSON`) |
| `SPREADSHEET_ID_MKT` | ID del libro que contiene la pestaña MKT (en Actions viene del secret `SPREADSHEET_ID_SECUNDARIO`) |
| `MKT_MONDAY_CONFIG_JSON` | configuración en una línea (solo Actions) |

El libro debe estar compartido como editor con la cuenta de servicio.

## Uso

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python mkt_monday_sync.py --simular   # calcula y muestra, sin escribir
.venv\Scripts\python mkt_monday_sync.py             # actualiza el mes en curso
.venv\Scripts\python mkt_monday_sync.py --mes 2026-09
```

`--mes AAAA-MM` actualiza otro periodo; sin él se usa el mes en curso. `--forzar` permite escribir 0 recibidos sobre un total mayor que cero.

## Programación

`.github/workflows/mkt-monday.yml` corre todos los días a las 9:00 (hora CDMX) y se puede lanzar a mano desde la pestaña Actions. Secrets que usa: `MONDAY_TOKEN`, `GOOGLE_CREDS_JSON`, `SPREADSHEET_ID_SECUNDARIO` y `MKT_MONDAY_CONFIG_JSON`.

## Salvaguardas

- Valida la configuración contra el tablero real y se detiene si falta una columna o una etiqueta.
- Falla si la hoja no tiene la fila del mes o la tiene repetida.
- No sobrescribe una celda con fórmula.
- No baja a cero un total que ya tiene leads, porque suele ser una lectura fallida.
- Es idempotente: una segunda corrida sin cambios en monday no escribe nada.
- El registro de Actions es público, así que ahí no se imprimen cifras ni nombres de columnas o etiquetas.

## Mantenimiento

- Al empezar un año hay que agregar en la hoja las filas de los 12 meses; mientras no existan el script se detiene con un mensaje claro.
- Cada mes se actualiza solo mientras es el mes en curso. Si se necesita cerrar el mes anterior después del cambio de mes, se corre con `--mes`.

## Pruebas

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```
