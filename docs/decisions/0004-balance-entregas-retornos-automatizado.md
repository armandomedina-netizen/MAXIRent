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
- `SOLICITUDES ENTREGAS / RECOLECCIONES` y `PRONÓSTICO ENTREGAS` del original no forman parte del skill (ambas se automatizaron después; ver las secciones del 6-oct y del 9-oct).

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

Comparación con el original (6-oct, mismas horas de corrida salvo lo indicado) más abajo.

## Alineación con el archivo de Nuvia del 9-oct

- **SOLICITUDES con fechas futuras.** Nuvia pega también las solicitudes ya programadas (`Fecha Rec.` posterior a hoy). La descarga de traslados llega ahora hasta hoy + `SOLICITUDES_DIAS_FUTUROS` (variable del repositorio, 7 por omisión; no hay fecha fija en el código). `ONHIRE` y `RETORNOS` siguen hasta hoy. Con 7 días entran los 71 folios de su pegado más los creados después; con hasta = hoy faltaban 9, y 3 filas de `RETORNOS` se quedaban sin `STATUS MAXINET`. Con `criterio=fecha_entrega_recoleccion`, Maxinet filtra las entregas por `Fecha Rec.` y las recolecciones por `Fecha Ent.`.
- **`PRONÓSTICO ENTREGAS`** (nueva en su archivo). El script la crea junto a `SOLICITUDES` si falta, con sus fórmulas `A1`, `F1`, `A3` y `F3` idénticas. `A3` y `F3` usan `QUERY(FILTER(...))` y agrupan por cliente, grupo y `Fecha Rec.` las entregas nuevas y las recolecciones de hoy a hoy + 7 que no estén en `TRASLADO CANCELADO`. `C1` y `H1` suman hasta la fila 1000, como dicen los textos de `A1` y `F1`; en el original suman `C3:C9` y `H3:H35`. Cada corrida repone esas celdas si alguien las cambia y nunca escribe dentro del derrame.
- **Fechas guardadas como texto.** La causa estaba en la copia, no en Maxinet: `ONHIRE` y `RETORNOS` tenían "tablas" de Sheets (el original no las tiene) con tipos de columna del diseño anterior. `PUDATE`, `RETURNDATE` y `DIAS` estaban como texto, `CLIENTE` como fecha y `DIAS` y `EFECTO 0` de `RETORNOS` como fecha. El tipo de columna se impone a cualquier formato, y la API acepta el cambio de formato sin aplicarlo. El script quita los tipos de columna (la tabla y sus datos se conservan; no se usa `deleteTable` porque la documentación no garantiza que respete los datos). Además aplica los formatos antes de escribir, porque un número escrito en una celda con formato de texto se guarda como texto. Queda `PUDATE`/`RETURNDATE` = `yyyy-mm-dd` y `DIAS` = número.
- **Formato condicional de `BALANCE`.** Una sola regla, la de Nuvia (>= 1 en naranja y negrita), sobre `A2:AG9` y `A11:AG18`. Son las mismas filas de ejecutivos que usa el script; Nuvia la tiene en `A2:AH4` y `A11:AH13` porque su `BALANCE` usa 3 filas por bloque. Antes estaba desfasada (`B3:AF10`, `B14:AF21`). El script la corrige si cambia.
- **Visibilidad.** El original oculta `en renta` y `EJECUTIVO`. En la copia están protegidas sólo para el dueño, así que la cuenta de servicio no puede ocultarlas; se ocultan a mano (ninguna se borra). `FLOTA ACTUAL` sigue oculta.
- **`STATUS EMTREGAS`** (sólo en la copia). Es una foto estática de solicitudes del 28-ago al 23-sep en el formato viejo de 42 columnas. Sin referencias en las fórmulas del libro, en este repositorio ni en su historial; tampoco desde las copias de QUERY ni del Tablero LP ni desde "PARA CIERRE DE MES 2026". No se borró; queda para que Armando confirme.
- **Dependencia encontrada.** La copia del Tablero LP (`GRAFICOS UTILIZACION!AD8`, `AE4`, `AE5` y `DETALLE BALANCE!A126`) importa con `IMPORTRANGE` rangos del BALANCE original de Nuvia que ya no existen en su estructura nueva (`SOLICITUDES ENTREGAS / RECOLECCIONES!A4:H43`, `BALANCE!A35:D43`). No se tocó; es trabajo del tablero.

Verificación (9-oct, dos corridas seguidas desde la rama, mismos conteos): 81 entregas, 74 retornos y 78 solicitudes (69 de entrega, 9 de recolección), 0 errores en `P:S`. `ONHIRE` 59/59 y `RETORNOS` 69/69 filas comunes iguales en `A:S`; la única diferencia es una devolución que Maxinet movió del 6 al 7-oct después del pegado de Nuvia. Las 22 entregas y 5 retornos extra de la copia son de días posteriores a su último pegado. `BALANCE` igual en los días que ambos cubren. `FLOTA MES ANTERIOR` idéntica (783). `PRONÓSTICO` igual al original (6 y 1 placas) y a un recálculo independiente; excluye 2 entregas canceladas.

Comparación del 6-oct: `ONHIRE` 59/59 y `RETORNOS` 69/69 filas idénticas en A:O, y `P:S` iguales en todas las filas; `FLOTA MES ANTERIOR` idéntica (783 placas); los valores del `BALANCE` coinciden por ejecutivo y día. En `SOLICITUDES` sólo difieren 3 celdas de formato de moneda (el pegado de Nuvia es inconsistente) y un folio que cambió en Maxinet después de su pegada.
