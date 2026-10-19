# ADR 0009: ENCUESTAS (Base) desde el reporte de encuestas de satisfacción de Maxinet

- Estado: aceptada
- Fecha: 2026-10-19

## Contexto

La pestaña ENCUESTAS de la Base (copia de "h encuestas") se alimenta del reporte `mk-reporte-encuestas-satisfaccion-cp.php` (el enlace está en el encabezado de la pestaña). Estaba atrasada: la copia llegaba al 28-sep y el archivo de Nuvia al 18-oct. Las pestañas "ENCUESTAS 2026 V1", "ENCUESTAS POR SUCURSAL" y "ENCUESTAS POR AREAS RESPONSABLES" del Tablero leen los archivos originales de Nuvia por IMPORTRANGE, no esta pestaña.

## Hallazgos que fijan el diseño

- Endpoint: `includes/encuestasCP/esatisfaccion2026_data.php` (`Desde`, `Hasta`, `criterio=FechaRespuesta`, `NoCliente` vacío). Responde en ~2 s. La lista viene bajo la clave `data_ui` (no `data`).
- Cada fila trae una columna de acciones al inicio (lupa de detalle) y dos celdas con HTML (el nombre del cliente va dentro de un enlace). Los encabezados salen de la tabla de la página.
- Las 24 columnas del reporte son las de la hoja (C:Z). Las columnas A (PERIODO) y B (RECLASIFICACION) son fórmulas.
- Clave única: (Fecha resp., Reserva). La Reserva sola se repite alguna vez, y hay encuestas distintas del mismo cliente, placa y día.
- La hoja de Nuvia va ordenada por Fecha resp. ascendente y, dentro de cada día, en el mismo orden en que las entrega Maxinet (108 de 108 días).
- Algunos IDs con `$` quedaron dañados en el archivo de Nuvia por el formato de moneda (ver ADR 0002 y 0007).

## Decisión

- Filtro: el mes corriente (primer día del mes a hoy, hora CDMX; los primeros 3 días del mes incluye también el mes anterior). Corre a las 9:30 AM CDMX.
- Las columnas se relacionan por nombre: se requieren las 24, se ignoran las columnas nuevas que agregue Maxinet (se avisa en el log), el orden de Maxinet no importa, y si falta alguna o las columnas de la hoja dejan de ser contiguas la corrida se detiene sin escribir.
- Sólo se agrega lo que falta, en el orden descrito. Las encuestas ya pegadas no se modifican. Las que llegan con fecha anterior al último registro se agregan al final y se avisa en el log.
- Para las reservas con `$` se usa además (Fecha resp., Placa, Cliente) para reconocer registros ya presentes con el ID dañado; no se usa para las demás.
- Los IDs con `$` se escriben como texto. Se agregan filas a la hoja si hacen falta y se copian las fórmulas de A:B y el formato de C:Z.
- El texto se conserva como lo entrega Maxinet, incluidos los saltos de línea; en el archivo de Nuvia (que pega desde la página web) los saltos de línea se vuelven espacios.

## Resultado de la recuperación (2026-10-19)

Se agregaron 160 encuestas del 29-sep al 19-oct (`C923:Z1082`). El mes corriente tiene 142 encuestas, la misma cifra que muestra Maxinet. Frente al archivo de Nuvia: mismas encuestas por día (salvo las 5 de hoy, que ella aún no pega), mismo orden y mismos tipos de dato. Las diferencias son 7 comentarios con salto de línea, 5 valores de "Enc. Respondidas" de filas anteriores al 29-sep que Nuvia actualizó después, y 1 ID con `$` dañado en su archivo.

## Pendientes

1. Decidir si los saltos de línea de los comentarios deben convertirse en espacios, como queda en el archivo de Nuvia.
2. Decidir si el Tablero copia debe leer esta pestaña en lugar de los archivos originales de Nuvia.
3. El Sheet guarda la foto del momento: columnas como "Enc. Respondidas" (acumulado por cliente) se actualizan después en Maxinet y Nuvia las refresca de forma manual en filas anteriores.
