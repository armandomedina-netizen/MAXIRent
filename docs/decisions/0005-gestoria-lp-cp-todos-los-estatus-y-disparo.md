# 0005 - Gestoría LP & CP: todos los estatus, trampas del Sheet y disparo desde Apps Script

Fecha: 2026-10-12

## Contexto

`automations/automatización Gestoría/gestoria_lp_cp_sync.py` (workflow `gestoria-lp-cp-sync.yml`) mantiene la pestaña `GESTORIA CP - LP` de la copia automatizada de `GESTORIA CP&LP`. La auditoría del 2026-10-12 contra Maxinet y contra el original de Nuvia encontró: 13 de 13 corridas programadas exitosas, cero desajustes de estatus, sin duplicados, pero tickets faltantes. La automatización pedía sólo `Estatus=ABIERTO`; los tickets de VERIFICACIÓN o TRÁMITES que se abren y se cierran en menos de un minuto nunca aparecen como abiertos en una corrida, así que nunca entraban (faltaban 1629, 1638 a 1640, 1642 y 1644; el original de Nuvia sí los tiene). Además la columna AI "Cerrado" quedaba vacía en las filas que la automatización cerraba por ausencia.

## Decisión

1. Se piden todos los tickets (`Estatus` vacío, el botón "Ver Todo" de Maxinet). Se agrega todo folio que falte, con su estatus real; se cierra lo que Maxinet muestra CERRADO o ya no muestra; y la columna AI se llena con `estatus_created_at` cuando está vacía (nunca se sobrescribe). No se reabre una fila CERRADO que Maxinet muestre ABIERTO: sólo se avisa con el conteo, porque esa regla no se acordó.
2. Guardia: si Maxinet devuelve menos de la mitad de los folios que tiene el Sheet, la corrida aborta sin escribir (con cierre por ausencia, una respuesta vacía cerraría casi todo).
3. `--dry-run` informa qué cambiaría sin escribir.
4. El folio 871 (SINIESTRO de diciembre de 2025, con cargo adicional 4067 FINALIZADO, sin duplicados) faltaba también en el original. Se agrega como cualquier otro: es un ticket real y omitirlo dejaba un siniestro fuera de diciembre de 2025. Se avisa a Nuvia de que su original no lo tiene.
5. El disparo puntual vive en el proyecto de Apps Script `Vigilante_Maxinet` (no se versiona: contiene el correo del equipo), que ya tiene un disparador independiente por reporte (ADR 0003). `ejecutarGestoria` sigue el mismo patrón que `ejecutarQuerySync` y `ejecutarBalance`: `workflow_dispatch` cada hora (minuto 57) de lunes a sábado de 8:30 a 19:00 (hora CDMX) y aviso por correo (máximo uno cada 3 horas) si la última corrida exitosa tiene más de 3 horas dentro del horario. Antes de este cambio esa función sólo vigilaba (cada 6 horas, tolerancia de 26 horas) y la corrida dependía del cron de GitHub. El workflow gana `concurrency` y `timeout-minutes: 15`; su cron queda como respaldo (8:45, 12:45 y 16:45 CDMX). Un primer borrador de este disparo como archivo propio (`apps-script/disparador.gs`) se descartó: repetía las funciones de apoyo del Vigilante y su `ejecutarGestoria` chocaba con la existente.
6. Fórmulas de `2026` (B:H): las fórmulas `XLOOKUP` por fila hay que arrastrarlas hacia abajo cuando el derrame de la columna A crece. Sin eso, el folio aparece sin fecha, tipo, placa ni cliente: el 2026-10-12 los folios 1630 a 1654 estaban así (las fórmulas terminaban en la fila 1290 y el derrame en la 1310). `mantener_formulas_historico()` las extiende hasta el último folio del derrame más 50 filas de holgura, copiando el formato de la fila plantilla (la fecha de B) y agregando filas a la hoja si hace falta. Sólo escribe en filas con B:H totalmente vacías y nunca escribe en la columna A. Si `A2` muestra un error de derrame no toca nada y avisa. Un fallo ahí se registra pero no marca como fallida la sincronización principal.

## Trampas del Sheet que no deben repetirse

- No usar `append_rows`: la hoja tiene `row_count` de unas 2961 filas por las columnas auxiliares AJ:AM arrastradas de antemano, y la API inserta debajo del último formato, no del último dato (el folio 1624 cayó en la fila 2961 en vez de la 1562 el 2026-09-28). Se calcula la fila (última fila con folio + 1) y se escribe con `update()`.
- La columna A de la pestaña `2026` no se escribe nunca: su `A2` es `=UNIQUE(FILTER('GESTORIA CP - LP'!A:A,'GESTORIA CP - LP'!AM:AM="OK"))` y B:H son `XLOOKUP` precargados por fila. Un valor fijo en A bloquea el derrame y toda la fórmula queda en `#REF!` (incidente del 2026-09-28, sin pérdida de datos). Una fila nueva aparece ahí sola en cuanto su fecha de evento es de 2025 o 2026.

## Consecuencias

- Las filas nuevas con estatus CERRADO entran al final del Sheet, no en su lugar por folio; el equipo ordena por fecha del evento.
- La primera corrida llena de una sola vez la fecha de cierre de las filas ya cerradas (534 en la auditoría).
- Si el token de GitHub del Apps Script vence, el correo avisa y el cron de respaldo mantiene tres corridas al día.
- Si se vuelve a ejecutar `crearDisparadores` del Vigilante, debe llevar `everyHours(1).nearMinute(57)` para `ejecutarGestoria`; con `everyHours(6)` el disparo horario se revertiría sin avisar.
