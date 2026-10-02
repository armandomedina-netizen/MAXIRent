# ADR 0003: Disparo puntual y vigilancia de los workflows de Maxinet

- Estado: aceptada (pendiente de configurar el reloj externo)
- Fecha: 2026-10-01

## Contexto

Los workflows de este repositorio dependen del evento `schedule` de GitHub Actions, que no garantiza la hora. Del 27 al 30 de septiembre de 2026 los crons se retrasaron entre 4 y 6 horas (por ejemplo, el sync del tablero LP programado a las 15:00 UTC corrió a las 21:01 UTC el 28 de septiembre). `maxinet-query-sync.yml` además debe correr al menos una vez por hora sin depender de una computadora encendida.

## Decisión

1. El disparo puntual lo hace un Google Apps Script en la cuenta corporativa, con un disparador horario que llama a `workflow_dispatch` (los disparos por API arrancan en segundos). No agrega ningún proveedor nuevo.
2. El mismo script revisa la edad de la última corrida exitosa de cada workflow vigilado y envía un correo si se pasa de su tolerancia. Ese vigilante no usa Claude ni consume cuota de uso.
3. Query Sync: se dispara cada hora (es idempotente: reemplaza el bloque de datos y re-extiende fórmulas). El cron de GitHub (`7 * * * *`) queda como respaldo; el grupo `concurrency` serializa ambos disparos.
4. Workflows diarios (p. ej. el tablero LP): se dispara una sola vez al día a su hora, y sólo si no existe ya una corrida de esa ventana. Si el workflow tiene modos distintos según `github.event.schedule`, el modo debe poder pedirse también por `workflow_dispatch` (input). Los `schedule` de esos workflows sólo se retiran después de comprobar el disparo externo, para que un cron tardío no sobrescriba una captura hecha a la hora correcta.
5. Claude Cowork no se usa como reloj ni como vigilante: sus tareas sólo corren con la app abierta y cada ejecución consume una sesión completa con su contexto base.

## Seguridad

- El reloj sólo guarda un token fine-grained de GitHub limitado a este repositorio con permiso *Actions: Read and write*, con caducidad y revocable. No puede leer Secrets, modificar código ni hacer push.
- Los datos de Maxinet y de Sheets no pasan por el reloj; las credenciales siguen únicamente en los Secrets del repositorio.
- El token nunca se versiona ni se comparte por chat; vive en las propiedades del script.
- Este repositorio es público: los logs de Actions son visibles para cualquier usuario de GitHub, por lo que los scripts no imprimen placas, reservas ni nombres de clientes (sólo conteos).

## Consecuencias

- Costo: $0 (repositorio público; aun siendo privado caben en los minutos gratuitos) y sin consumo de Claude.
- Si el token caduca o se revoca, el disparo externo falla (Apps Script avisa por correo) y queda el cron de GitHub; hay que renovarlo antes de la fecha de caducidad.
- GitHub desactiva los workflows programados tras 60 días sin actividad en un repositorio público; el aviso por antigüedad de la última corrida exitosa lo detecta.

## Tablero LP (`maxinet-sync.yml`): auditoría y cambios (2026-10-01)

Se auditó cada paso de `main()` y `main_proyeccion_mtto()` para saber si una segunda corrida el mismo día es segura (el disparo externo y el cron de GitHub pueden coincidir).

| Paso | Idempotente | Por qué |
|---|---|---|
| `avanzar_columna_formulas`, `avanzar_columna_grupo_autos` | Sí | Si la columna destino ya tiene contenido, avisan y no hacen nada. |
| `actualizar_vor_cliente` | Sí | Reescribe los conteos de una fecha ya cerrada con los mismos valores. |
| `actualizar_periodo_resumen`, `extender_formulas_resumen`, `actualizar_tablas` | Sí | Se recalculan desde las fechas y el día de hoy; sólo se extiende lo que falta. |
| `avanzar_formula_dia_duracion_rentas`, `avanzar_activas_duracion_rentas` | Sí | Sólo tocan filas/meses que no corresponden; si ya están al día, regresan. |
| `actualizar_sheet` | Sí (resultado) | Limpia y reescribe el bloque con la foto más reciente. |
| Proyección de Mantenimientos | No (corregido) | Sobrescribía `D{hoy}`: un cron tardío pisaba la captura de las 9:10 (el 30-sep se escribió 6.63 % a las 14:00 hora CDMX). |
| Dos corridas simultáneas | No (corregido) | Las salvaguardas revisan y luego actúan, sin candado. |

Cambios:

- `maxinet_sync.py`: la captura de Proyección ya no sobrescribe un valor existente (`--forzar-mtto` para reescribirlo a propósito); todas las fechas "de hoy" usan `America/Mexico_City` en vez de la del servidor (UTC), para que una corrida tardía no avance las columnas un día de más.
- `maxinet-sync.yml`: `workflow_dispatch` acepta `modo` (`completo` | `solo_proyeccion_mtto`); `concurrency` serializa las corridas del mismo modo sin cancelar (grupos distintos por modo, porque GitHub conserva una sola corrida pendiente por grupo); `timeout-minutes: 20`. Los `schedule` se mantienen.

Riesgo mientras convivan el cron de GitHub y el disparo externo: un cron tardío dispara un segundo sync completo (no-op por las salvaguardas de arriba) y una segunda captura de Proyección (se conserva la primera). Los `schedule` se retiran hasta comprobar el disparo externo al menos 3 días seguidos.

### Incidente del calendario de UTILIZACION V3 y UTI. GRUPO DE AUTOS V1 (2026-10-02)

- Causa: ambas hojas tienen una columna por día y su calendario terminaba el 30-sep. El 2-oct no existía la columna del 1-oct y `_encontrar_columna_por_fecha` comparaba el texto "1-oct" (se repite en 2025 y 2026), así que escogió la del 2025 y VOR Cliente se escribió sobre el histórico de otro año (4 celdas, ya restauradas desde el original). Además, la hoja de datos ya tenía la foto del 1-oct y la columna viva del 30-sep quedó en ceros; se rellenó desde el original.
- Corrección: la búsqueda compara ahora el número de serie de la fecha (único); si la fecha continúa el calendario, éste se extiende solo hasta fin de mes (`_extender_columnas_calendario`, mismo formato que la última columna); en cualquier otro caso la corrida falla en vez de escribir en otra fecha.
- Lección: una salvaguarda "si la columna ya tiene contenido, no avanzar" evitó daños mayores, pero VOR Cliente no la tiene; por eso importa que la búsqueda falle fuerte.

### Disparo del tablero LP desde el Apps Script (2026-10-02)

Un solo proyecto de Apps Script, pero un disparador independiente por reporte (`ejecutarQuerySync`, `ejecutarTableroLP`, `ejecutarGestoria`) en lugar de un único `ejecutar` que lo hace todo en un ciclo: un error o un retraso en uno no afecta a los demás.

- **Tablero LP** (el más importante; debe quedar actualizado antes de las 9:30, hora CDMX): disparador cada 5 minutos que sale de inmediato fuera de 8:55–20:00. Dos ventanas: 9:00 `completo` y 9:10 `solo_proyeccion_mtto`. Cada una se dispara si no hay ya una corrida (en cola, en curso o exitosa, incluido un cron tardío de GitHub), se reintenta hasta 3 veces si falla y, si a las 9:30 no hay corrida exitosa, avisa por correo. La ventana se identifica por la etiqueta del `run-name` del workflow.
- **Query Sync:** cada hora, pero sólo en horario laboral (constantes `HORARIO_QUERY`); fuera de ese horario no se dispara ni se vigila.
- Los `schedule` de GitHub se retiran de `maxinet-sync.yml` cuando el disparo externo funcione 3 días seguidos.

### Corrección: Proyección de Mantenimientos toma el histórico de Maxinet (2026-10-02)

- Sustituye lo dicho antes sobre "no sobrescribir la captura de las 9:10": el % de cada día ya no es una foto de la tabla en vivo (cambia durante el día y coincidía en 27 de 31 días con el original). Maxinet guarda su propio histórico (`charMttosVencidos.php`, la gráfica "% Vencimiento y Meta") y de ahí copia Nuvia: coincide en 31 de 31. Por eso la hora exacta de la corrida ya no afecta el valor.
- Cada corrida llena en D los días cerrados (hasta ayer) que estén vacíos, sin pisar lo ya escrito; la fila de hoy se llena al día siguiente, cuando Maxinet la publica. `--forzar-mtto` reescribe los últimos 45 días. J1:J2 ("UNIDADES EN RENTA" y "VENCIDOS") se actualizan con la tabla en vivo y su falla no detiene lo demás. Las consultas a Maxinet de esta sección reintentan si se corta la conexión.
- **Principio:** el archivo de Nuvia sirve sólo para comparar y reconciliar; ningún proceso del repositorio lo lee ni depende de él. Cuando el tablero propio pase a ser el principal debe mostrar la información correcta con sus propias fuentes (Maxinet).
