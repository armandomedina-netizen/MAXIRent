# ADR 0007: ENTREGAS del Tablero CP desde el reporte "Entregas Diarias mensual CP"

- Estado: aceptada
- Fecha: 2026-10-15

## Contexto

La pestaña ENTREGAS del Sheet "Base" (copia de "h encuestas") se alimentaba de una tabla equivocada de Maxinet. El reporte correcto es `cp-reporte-entregas-diarias-mensual.php` (el mismo enlace que Nuvia lleva en el encabezado de la pestaña), cuyo endpoint es `json/entregasDiariasCPMensual.php` (`FechaDesde`, `FechaHasta`, `Sucursal`).

## Hallazgos que fijan el diseño

- La copia era un subconjunto exacto del archivo de Nuvia (misma tabla, sin filas de más), detenido el 28-sep. La alineación consistió en copiar sus columnas A:P (23,117 filas); Q:X son fórmulas y no se tocan.
- Nuvia conserva la foto del momento: No. Rentas, estatus, gasolinas y placa cambian después en Maxinet y el Sheet no se refresca. Por eso la automatización sólo agrega lo posterior al último registro.
- El Sheet está estrictamente ordenado por Fecha y Hr.Entrega (cero quiebres), así que lo nuevo se agrega siempre al final, en orden.
- **El campo Cumpleaños depende del rango de fechas de la consulta:** Maxinet sólo devuelve la fecha de nacimiento si el cumpleaños cae en el periodo consultado. Con el rango del 1 al 14 de octubre devuelve 63 valores, los mismos 63 de Nuvia; con enero a octubre, ~13,000. El rango del primer día del mes a ayer es, por tanto, obligatorio y no sólo una optimización.
- El reporte devuelve 18 columnas: las 16 de la pestaña más JOB Entrega y JOB Recepción, que se ignoran.

## Decisión

- Rango: del primer día del mes de "ayer" a ayer (hora CDMX). Corre a las 9:30 AM CDMX.
- Una fila es nueva si su (Fecha, Hr.Entrega) es posterior al último registro, o igual y no está ya en el Sheet. Las filas ya pegadas nunca se modifican.
- Si Maxinet cambia el ancho (distinto de 16 o 18) o las columnas dejan de cuadrar, la corrida se detiene sin escribir. Las descargas reintentan con espera creciente.
- Se valida al final que no haya Reservas repetidas.
- Los IDs que empiezan con `$` se escriben como texto, como en Clientes Nuevos (ver ADR 0002, punto 2).

## Pendientes y limitaciones

1. **Entregas rezagadas.** Una entrega registrada en Maxinet con fecha anterior al último registro del Sheet no se agrega (insertarla rompería el orden); se avisa en el log. En la comparación de enero a octubre, 23 entregas de Maxinet no estaban en el archivo de Nuvia y 22 del archivo de Nuvia ya no aparecen en Maxinet; la mayoría son cambios de placa o ID, no entregas perdidas. Decidir con Nuvia si se insertan.
2. **IDs con `$`.** En el archivo de Nuvia 619 `# Cliente` quedaron como número por el formato de moneda. La columna NOMINA hace XLOOKUP de `# Cliente` contra "Clientes Frecuentes Activos 35"; un ID `$` escrito como texto podría no coincidir con el mismo ID dañado en esa pestaña y caer en el valor por defecto "CO". Afecta a unas decenas de filas.
3. **Formato de moneda en celdas dañadas.** Al alinear con Nuvia se copiaron los valores, no el formato de moneda de sus celdas con ID convertido a número.
