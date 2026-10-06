# 0004 - BALANCE de Entregas / Retornos LP automatizado

Fecha: 2026-10-05

## Contexto

Nuvia armaba el BALANCE a mano con un proceso que documentó en el skill `balance-entregas-retornos-lp`: pegar en `ONHIRE` y `RETORNOS` el reporte LP > Entregas / Retornos de Maxinet (Tipo ENTREGAS y RETORNOS, del día 1 del mes a hoy), pegar en `SOLICITUDES ENTREGAS / RECOLECCIONES` el reporte de solicitudes de traslado (Entregas y debajo Recolecciones) y extender tres fórmulas (`P:R`). Su archivo ya usa ese formato nuevo (A:O del reporte más P:R); la copia automatizada seguía en el formato de septiembre.

## Decisión

`automations/maxinet-balance/maxinet_balance.py` (workflow `maxinet-balance.yml`) hace ese proceso con `requests`, sin navegador:

- `POST includes/reportesLP/reporte-entregas-retornos.php` (Desde, Hasta, Tipo) para `ONHIRE` y `RETORNOS`.
- `POST includes/traslados/lp-traslados-solicitudes.php` con `criterio=fecha_entrega_recoleccion` y `tipoSolicitud=entregas|recolecciones` para `SOLICITUDES ENTREGAS / RECOLECCIONES` (el parámetro `Estatus` no filtra con ese criterio).
- Escribe A2:O (valores con tipo: fechas y enteros reales), extiende `P:R` con las fórmulas del skill (la `Q` lleva el cuarto argumento `""` para que una placa que no estaba en la flota anterior quede como POSIBLE ENTREGA y no como `#N/A`) y limpia lo que sobre sólo después de escribir.
- `FLOTA MES ANTERIOR` se rota sola: la pestaña oculta `FLOTA ACTUAL` guarda la flota ON HIRE de la última corrida (placa y cliente de la línea RENT de la pestaña `QUERY` de la copia de CLIENTES ACTIVOS) y al cambiar de mes pasa a `FLOTA MES ANTERIOR`. Para octubre se sembró una vez con la del original.
- Al cambiar de mes, las pestañas del mes que cierra se guardan como valores en pestañas ocultas (`RETORNOS 2026-09`...), porque Nuvia empieza de cero cada mes.
- Si Maxinet no regresa entregas ni retornos después del día 1, no se sobrescribe nada.

## Verificación contra el archivo de Nuvia (5-oct)

Las 52 filas de su `ONHIRE` y las 57 de su `RETORNOS` (1 y 2 de octubre) salen idénticas en A:O; los 10 folios de su `SOLICITUDES ENTREGAS / RECOLECCIONES` también. En `ONHIRE`, `P` coincide en las 52 filas y `Q`/`R` en 49; las otras 3 son el caso del `#N/A` que el skill corrige.

## Pendiente

- El `BALANCE` de Nuvia sigue con fórmulas que leen las columnas del formato viejo (`RETORNOS!P/M/H`, `ONHIRE!G/Q/R`) y hoy da ceros. No se tocó la pestaña `BALANCE` de la copia hasta que ella defina el mapeo; en particular falta saber qué columna de ejecutivo usa (`EJECUTIVO` o `EJECUTIVO PROHIRE`: ninguna reproduce por sí sola el BALANCE de septiembre).
- Ejecutivo (resuelto 2026-10-05): Nuvia confirmó que el ejecutivo del `BALANCE` sale de la columna `H` (`EJECUTIVO KAM`) de la pestaña `EJECUTIVOS` del libro DATA EJECUTIVOS DE CUENTAS, que la pestaña `EJECUTIVO` del BALANCE importa; no sale de `EJECUTIVO` (Maxinet) ni de `EJECUTIVO PROHIRE` del reporte. Se busca por cliente (`B`). Con esa búsqueda las 122 filas de octubre y las 144 de septiembre caen en uno de los 7 ejecutivos del `BALANCE`. El script agrega la columna `S` (`EJECUTIVO KAM`) en `ONHIRE` y `RETORNOS`; no está en el skill. Las fórmulas de la pestaña `BALANCE` de la copia se reconectaron el 5-oct (434 fórmulas, respaldo previo; permiso de edición concedido): `RETORNOS!H` en lugar de `P`, `RETORNOS!S` en lugar de `M`, `RETORNOS!F` en lugar de `H`; `ONHIRE!P` en lugar de `Q`, `ONHIRE!S` en lugar de `R`, `ONHIRE!E` en lugar de `G`.
- `SOLICITUDES ENTREGAS / RECOLECCIONES` y `PRONÓSTICO ENTREGAS` del original no forman parte del skill y no se automatizan todavía.

## Estado del despliegue (2026-10-05)

- Secret `SPREADSHEET_ID_BALANCE` creado y permiso en `RETORNOS` concedido. Dos corridas seguidas en GitHub terminaron en éxito con los mismos conteos (58 entregas, 65 retornos, 20 solicitudes de traslado, 0 errores en P:R): no duplica.
- Disparo: respaldo con cron (`17 14-23,0 * * *`) y disparo puntual desde el Apps Script con una función y un disparador propios (`ejecutarBalance`, lunes a sábado de 8:30 a 19:00), independiente del Query Sync y del tablero LP.
- `B2` de la pestaña `BALANCE` (día 1 del mes que usan todas sus fórmulas) lo pone el script cada corrida; Nuvia lo cambia a mano cada mes. Verificado con octubre: 58 entradas (`SI APLICA`) y 4 salidas (`ENTREGA (NUEVO)`), iguales al cálculo directo sobre `RETORNOS` y `ONHIRE`, sin errores.

## Cambio de Nuvia del 6-oct y realineación

Nuvia reestructuró su archivo el 6-oct y la copia se realineó el mismo día:

- La pestaña `REPORTE MAXINET` ya no existe en su archivo: el reporte de traslados vive en `SOLICITUDES ENTREGAS / RECOLECCIONES` (43 columnas, Entregas y debajo Recolecciones) y `P` de `ONHIRE`/`RETORNOS` lee de ahí.
- `R` quedó distinto en cada pestaña (`ONHIRE` vacía si no hay flota anterior; `RETORNOS` vacía si no hay placa) y `S` se llama `EJECUTIVO REAL`: `=IF(M2="","",XLOOKUP(B2,EJECUTIVO!B:B,EJECUTIVO!H:H,"SIN ASIGNACIÓN"))`.
- `BALANCE` cambió de lógica: ya no cuenta por `SI APLICA`. Bloque de entregas: `COUNTIFS(ONHIRE!S, ejecutivo, ONHIRE!E, día, ONHIRE!P, "ENTREGA (NUEVO)")`; bloque de retornos: `COUNTIFS(RETORNOS!S, ejecutivo, RETORNOS!F, día, RETORNOS!P, "RECOLECCION")`. La lista de ejecutivos sale de `UNIQUE` sobre la columna `S` y `C1` es el día 1 del mes. El script reconstruye la pestaña con esa estructura y rellena 8 filas por bloque con un `IF` sobre la columna `A` (con criterio vacío un `COUNTIFS` contaría celdas en blanco).
- Al reconstruir una pestaña el script también separa celdas combinadas y borra formatos del diseño anterior: una fila combinada vieja se tragaba las escrituras de un folio y un formato de fecha mostraba un folio como fecha.

Comparación con el original (6-oct, mismas horas de corrida salvo lo indicado): `ONHIRE` 59/59 y `RETORNOS` 69/69 filas idénticas en A:O, y `P:S` iguales en todas las filas; `FLOTA MES ANTERIOR` idéntica (783 placas); los valores del `BALANCE` coinciden por ejecutivo y día. En `SOLICITUDES` sólo difieren 3 celdas de formato de moneda (el pegado de Nuvia es inconsistente) y un folio que cambió en Maxinet después de su pegada.
