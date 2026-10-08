# Programación de la ejecución

Estado: horario aprobado el 7-oct-2026, pendiente de activar. Nada corre hasta que el workflow esté en la rama principal y existan los secrets.

## Requisito

- Entre una actualización y la siguiente pasan como máximo 2 horas.
- La información del día está en el Sheet antes de las 10:00 (hora CDMX).

## Horario (hora CDMX)

| Día | Corridas |
|---|---|
| Lunes a viernes | 7:00, 9:00, 11:00, 13:00, 15:00 y 17:00 (la última) |
| Sábado | 7:00, 9:00, 11:00, 13:00 y 14:00 (la última, de cierre) |
| Domingo | ninguna |

Cada corrida sincroniza sólo la pestaña periódica y tarda segundos. A las 10:00 la información tiene a lo más una hora, y la corrida de las 14:00 del sábado deja el estado de cierre.

## Dos disparos para el mismo horario

1. **Apps Script (principal).** `apps-script/disparador.gs` crea un disparador diario por cada hora de la tabla `HORARIO` y llama a `workflow_dispatch` con el token fine-grained de GitHub. Google lo ejecuta dentro de ±15 minutos de la hora; la función descarta los días y horas que no están en la tabla.
2. **Cron de GitHub (seguro).** El workflow corre cada hora a los 20 minutos: lunes a viernes de 7:20 a 17:20 y sábado de 7:20 a 14:20. Si el disparo exacto falla o se retrasa, el hueco máximo sigue siendo de 2 horas y antes de las 10:00 hay tres oportunidades más (7:20, 8:20 y 9:20).

Dos corridas cercanas no estorban: el workflow las encola (`concurrency`) y la sincronización es idempotente.

GitHub ejecuta los `schedule` cuando puede: se retrasan, sobre todo al inicio de cada hora, y con carga alta pueden saltarse. Por eso el cron es el seguro y el disparo exacto lo hace Apps Script, como en las demás automatizaciones del repositorio.

## Archivos

| Archivo | Contenido |
|---|---|
| `.github/workflows/tablero-sac.yml` | el workflow; queda fuera de esta carpeta porque GitHub sólo lee los workflows de esa ruta |
| `apps-script/disparador.gs` | disparador exacto con la tabla `HORARIO` |
| `tests/test_programacion.py` | comprueba que el cron y la tabla cumplen el requisito |

## Activación, en este orden

1. Crear los secrets del repositorio `MONDAY_TOKEN`, `SPREADSHEET_ID_SAC` y `MONDAY_SAC_SCHEMA_JSON` (el contenido de `private/monday-sac-schema.min.json`). `GOOGLE_CREDS_JSON` ya existe.
2. Mezclar la rama `monday-sac-sync` en `main`: los `schedule` y los `workflow_dispatch` sólo funcionan desde la rama principal.
3. Lanzar el workflow a mano (Actions, Tablero SAC, Run workflow) y revisar en el log los conteos de filas.
4. Crear un proyecto nuevo de Apps Script, aparte del que ya tiene otras automatizaciones, con una propiedad del script `GITHUB_TOKEN` cuyo valor sea el mismo token de GitHub que ya se usa. Pegar `disparador.gs`, ejecutar `probarDisparoTableroSac` para ver que GitHub recibe el disparo y después `crearDisparadoresTableroSac` una vez.

## Proyecto de Apps Script propio con el token existente

Un proyecto aparte no comparte nada con el que ya tiene otras automatizaciones: ni código, ni activadores (el límite de 20 es por proyecto), ni zona horaria. El token se reutiliza copiando su valor a la propiedad `GITHUB_TOKEN` del proyecto nuevo: el permiso `Actions` del token cubre cualquier workflow del repositorio y copiarlo no modifica el original.

La zona horaria del proyecto debe tener el mismo desfase que `TABLERO_SAC.ZONA` (`America/Mexico_City`). `America/Monterrey` sirve porque ambas son UTC-6 sin horario de verano. `crearDisparadoresTableroSac` lo verifica y se detiene con un error si no coincide.

El token queda compartido entre los dos proyectos: si vence, dejan de dispararse las automatizaciones de ambos, y el cron del workflow sigue corriendo cada hora como seguro.

## Cambiar el horario

Se edita la tabla `TABLERO_SAC.HORARIO` de `disparador.gs` y los dos `cron` del workflow; `tests/test_programacion.py` verifica que el requisito se siga cumpliendo.

## Desactivar

Deshabilitar el workflow en Actions o borrar los disparadores de Apps Script.
