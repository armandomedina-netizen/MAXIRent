# TableroSAC

Sincroniza el tablero de tickets de SAC de monday con un Google Sheet: una pestaña por grupo del tablero, las mismas columnas en el mismo orden y los datos desde la fila 2. Un grupo puede tener además una pestaña con los subelementos de sus tickets. monday es de solo lectura.

Todo lo de este proyecto vive en esta carpeta (código, pruebas, esquema real y documentación). Lo único que queda fuera es el `.gitignore` del repositorio y el workflow `.github/workflows/tablero-sac.yml`, porque GitHub sólo lee los workflows de esa ruta.

## Qué hace una corrida

1. Comprueba en monday que existan los grupos y las columnas del esquema.
2. Por cada pestaña pedida: lee el grupo por GraphQL (páginas de 100, con cursor), arma las filas, verifica que la fila 1 sea la del esquema, agrega filas si no alcanzan, escribe de A2 hacia abajo en lotes, limpia lo que sobre y verifica que el número de filas coincida con el de monday. Si el grupo tiene pestaña de subelementos, la misma lectura trae también los subelementos de cada ticket y se hace lo mismo con esa pestaña.
3. Registra sólo conteos; ningún dato de clientes llega al log.

Una pestaña con error no detiene a las demás (tampoco la de subelementos a la de tickets, ni al revés); el código de salida es 1 si alguna falló. No toca encabezados, formatos (salvo repetir el de la última fila en las filas que agrega), pestañas ni otras pestañas del libro.

La sincronización periódica es de una sola pestaña (la que el esquema marca con `periodica`) y, si la tiene, la de sus subelementos. Esa pestaña es un reflejo del estado actual del grupo en monday: lo que sale del grupo desaparece de la pestaña en la siguiente corrida. Las demás pestañas del esquema sólo se sincronizan cuando se piden por nombre.

## Reglas de datos

| Origen en monday | Se escribe como |
|---|---|
| Reflejos, relaciones, fórmulas y subelementos | texto de `display_value`; el texto `null` de una fórmula vacía queda en blanco |
| Resto de columnas | texto de `text` |
| Columnas de tipo `numero` | número (entero o decimal) |
| Columnas de tipo `fecha` | número de serie de fecha, con hora si monday la trae |
| Columnas de tipo `duracion` | fracción de día; con varios valores separados por coma queda como texto |
| Cualquier otra | texto literal |

Las celdas se envían con tipo (`RAW`), sin que Sheets interprete nada: los ceros de un teléfono o un texto que empiece con `=`, `+` o `-` llegan como están en monday. Las fechas y duraciones se muestran con el formato que ya tienen las columnas de cada pestaña. Lo que no cuadra con su tipo se conserva como texto y se cuenta en el log.

## Configuración

1. Entorno (Python 3.12 o superior):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```

2. Variables: copiar `.env.example` a `.env` y llenar `MONDAY_TOKEN`, `GOOGLE_CREDS_PATH` (JSON de la cuenta de servicio, fuera de cualquier carpeta de git) y `SPREADSHEET_ID_SAC`. `.env` lo ignora git.

3. Esquema: copiar `schema.example.json` a `private/monday-sac-schema.json` y poner los IDs reales del tablero, de los grupos y de las columnas (se obtienen con `get_board_info`). El repositorio es público y `AGENTS.md` prohíbe versionar esos IDs, por eso `private/` lo ignora git. En GitHub Actions el mismo JSON va en el secret `MONDAY_SAC_SCHEMA_JSON`.

4. Permisos: el Sheet compartido como editor con el correo de la cuenta de servicio y, si alguna pestaña está protegida, la cuenta incluida en la protección.

El esquema describe cada pestaña con `hoja`, `grupo_id`, `periodica` (opcional; marca la que entra en `--periodicas`) y `hoja_subelementos` (opcional; la pestaña de los subelementos de ese grupo), y cada columna del Sheet con `encabezado`, `origen` (`columna`, `nombre`, `grupo`, `id`, `creado` o `en_marcha`), `columna_id`, `tipo` (`texto`, `numero`, `fecha`, `duracion`) y `clave` (la columna que identifica la fila al comparar). La sección opcional `subelementos` trae el tablero de subelementos y las columnas de su pestaña, con los orígenes adicionales `padre_id`, `padre_nombre` y `padre_columna` (datos del ticket que se copian a cada fila).

## Subelementos

Cada ticket puede tener subelementos en un tablero propio (los que miden el proceso por área). Se vuelcan en una pestaña aparte, en formato largo: una fila por subelemento, con el identificador del ticket en la primera columna para relacionarla con la pestaña de tickets (relación de uno a muchos, como la usaría un BI). Un ticket sin subelementos no genera filas, y si el ticket sale del grupo sus subelementos también salen de la pestaña.

La pestaña la crea una persona, una sola vez, con los encabezados del esquema: el sincronizador no crea pestañas ni cambia su estructura. Mientras no exista, o si sus encabezados no coinciden, falla sólo esa pestaña y los tickets se sincronizan igual. Los pasos de activación, el efecto de cada error y cómo agregar una columna del ticket (por ejemplo el VIN) están en [docs/subelementos.md](docs/subelementos.md).

## Uso

```bash
python monday_sac_sync.py --listar
python monday_sac_sync.py --hoja "NOMBRE DE LA PESTAÑA" --dry-run --comparar
python monday_sac_sync.py --hoja "NOMBRE DE LA PESTAÑA"
python monday_sac_sync.py --periodicas
python monday_sac_sync.py --todas
```

| Opción | Efecto |
|---|---|
| `--periodicas` / `--todas` / `--hoja NOMBRE` / `--listar` | elige las pestañas marcadas como periódicas, todas las del esquema, las nombradas (sin distinguir mayúsculas ni acentos) o sólo lista las del esquema; la pestaña de subelementos se sincroniza con su grupo, así que nombrarla elige el grupo completo |
| `--dry-run` | lee monday y revisa la pestaña, pero no escribe; sin credenciales de Google sólo cuenta lo de monday |
| `--comparar` | cuenta las celdas distintas por columna contra lo que ya hay en la pestaña (sin imprimir valores) |
| `--aceptar-vacio` | permite vaciar una pestaña con más de 20 filas cuando monday devuelve 0 elementos |
| `--depurar` | muestra el traceback de los errores (puede incluir datos; sólo para uso local) |

La API de monday se consulta con la versión `2026-07`; `MONDAY_API_VERSION` la cambia.

## Programación

La pestaña periódica, con la de sus subelementos, se actualiza de lunes a viernes a las 7, 9, 11, 13, 15 y 17 h, y el sábado a las 7, 9, 11, 13 y 14 h (hora CDMX): disparo exacto desde Apps Script y un cron de GitHub como seguro. El horario, los archivos y los pasos de activación están en [docs/programacion.md](docs/programacion.md).

## Pruebas

```bash
python -m pytest tests -q
```

Cubren el mapeo de columnas y la limpieza de valores, la lectura de subelementos y su pestaña, la paginación y los reintentos de monday, la escritura por lotes, la idempotencia, el dry-run, las protecciones, que el log no lleve datos ni secretos y que el horario cumpla el requisito de frecuencia. Usan datos sintéticos y no requieren red.

## Archivos

| Archivo | Contenido |
|---|---|
| `monday_sac_sync.py` | punto de entrada |
| `sac_sync/config.py` | carga y validación del esquema |
| `sac_sync/monday.py` | consultas GraphQL, paginación y reintentos |
| `sac_sync/transformar.py` | limpieza de valores y armado de filas |
| `sac_sync/hojas.py` | lectura y escritura en Google Sheets |
| `sac_sync/comparar.py` | comparación contra lo que ya hay en la pestaña |
| `sac_sync/sincronizar.py` | orquestación por pestaña |
| `sac_sync/registro.py`, `sac_sync/cli.py` | log con secretos enmascarados y línea de comandos |
| `docs/decisiones.md` | decisiones de diseño y pendientes |
| `docs/programacion.md` | horario aprobado, disparadores y pasos de activación |
| `docs/subelementos.md` | pestaña de subelementos: estructura, activación, errores y cómo agregar columnas |
| `apps-script/disparador.gs` | disparador exacto de Apps Script con la tabla de horas |
