# 0004 - BALANCE de Entregas / Retornos LP automatizado

Fecha: 2026-10-05

## Contexto

Nuvia armaba el BALANCE a mano con un proceso que documentó en el skill `balance-entregas-retornos-lp`: pegar en `ONHIRE` y `RETORNOS` el reporte LP > Entregas / Retornos de Maxinet (Tipo ENTREGAS y RETORNOS, del día 1 del mes a hoy), pegar en `REPORTE MAXINET` el reporte de solicitudes de traslado (Entregas y debajo Recolecciones) y extender tres fórmulas (`P:R`). Su archivo ya usa ese formato nuevo (A:O del reporte más P:R); la copia automatizada seguía en el formato de septiembre.

## Decisión

`automations/maxinet-balance/maxinet_balance.py` (workflow `maxinet-balance.yml`) hace ese proceso con `requests`, sin navegador:

- `POST includes/reportesLP/reporte-entregas-retornos.php` (Desde, Hasta, Tipo) para `ONHIRE` y `RETORNOS`.
- `POST includes/traslados/lp-traslados-solicitudes.php` con `criterio=fecha_entrega_recoleccion` y `tipoSolicitud=entregas|recolecciones` para `REPORTE MAXINET` (el parámetro `Estatus` no filtra con ese criterio).
- Escribe A2:O (valores con tipo: fechas y enteros reales), extiende `P:R` con las fórmulas del skill (la `Q` lleva el cuarto argumento `""` para que una placa que no estaba en la flota anterior quede como POSIBLE ENTREGA y no como `#N/A`) y limpia lo que sobre sólo después de escribir.
- `FLOTA MES ANTERIOR` se rota sola: la pestaña oculta `FLOTA ACTUAL` guarda la flota ON HIRE de la última corrida (placa y cliente de la línea RENT de la pestaña `QUERY` de la copia de CLIENTES ACTIVOS) y al cambiar de mes pasa a `FLOTA MES ANTERIOR`. Para octubre se sembró una vez con la del original.
- Al cambiar de mes, las pestañas del mes que cierra se guardan como valores en pestañas ocultas (`RETORNOS 2026-09`...), porque Nuvia empieza de cero cada mes.
- Si Maxinet no regresa entregas ni retornos después del día 1, no se sobrescribe nada.

## Verificación contra el archivo de Nuvia (5-oct)

Las 52 filas de su `ONHIRE` y las 57 de su `RETORNOS` (1 y 2 de octubre) salen idénticas en A:O; los 10 folios de su `REPORTE MAXINET` también. En `ONHIRE`, `P` coincide en las 52 filas y `Q`/`R` en 49; las otras 3 son el caso del `#N/A` que el skill corrige.

## Pendiente

- El `BALANCE` de Nuvia sigue con fórmulas que leen las columnas del formato viejo (`RETORNOS!P/M/H`, `ONHIRE!G/Q/R`) y hoy da ceros. No se tocó la pestaña `BALANCE` de la copia hasta que ella defina el mapeo; en particular falta saber qué columna de ejecutivo usa (`EJECUTIVO` o `EJECUTIVO PROHIRE`: ninguna reproduce por sí sola el BALANCE de septiembre).
- Ejecutivo: `EJECUTIVO` viene de Maxinet y `EJECUTIVO PROHIRE` de la app ProHire; los dos llegan en el mismo reporte. En octubre `EJECUTIVO` viene vacío en 12 de 57 entregas y 17 de 65 retornos, `EJECUTIVO PROHIRE` nunca; Armando se inclina por `EJECUTIVO PROHIRE`. Los ejecutivos `JESUS LIMON`, `MARCO ELIZONDO` y `GABRIEL HERNANDEZ` no están en la lista fija de 7 del `BALANCE`.
- `SOLICITUDES ENTREGAS / RECOLECCIONES` y `PRONÓSTICO ENTREGAS` del original no forman parte del skill y no se automatizan todavía.

## Estado del despliegue (2026-10-05)

- Secret `SPREADSHEET_ID_BALANCE` creado y permiso en `RETORNOS` concedido. Dos corridas seguidas en GitHub terminaron en éxito con los mismos conteos (58 entregas, 65 retornos, 20 solicitudes de traslado, 0 errores en P:R): no duplica.
- Disparo: respaldo con cron (`17 14-23,0 * * *`) y disparo puntual desde el Apps Script con una función y un disparador propios (`ejecutarBalance`, lunes a sábado de 8:30 a 19:00), independiente del Query Sync y del tablero LP.
