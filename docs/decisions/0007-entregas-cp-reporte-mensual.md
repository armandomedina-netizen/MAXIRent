# ADR 0007: ENTREGAS del Tablero CP desde el reporte "Entregas Diarias mensual CP"

- Estado: aceptada; la regla de agregar sólo filas nuevas fue sustituida el 2026-10-22 (ver "Revisión 2026-10-22")
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

- Rango: del primer día del mes de "ayer" a ayer (hora CDMX). El horario de disparo está en `docs/automatizaciones.md`.
- ~~Una fila es nueva si su (Fecha, Hr.Entrega) es posterior al último registro, o igual y no está ya en el Sheet. Las filas ya pegadas nunca se modifican.~~ Sustituida el 2026-10-22: el mes en curso se refresca completo (ver abajo).
- Si Maxinet cambia el ancho (distinto de 16 o 18) o las columnas dejan de cuadrar, la corrida se detiene sin escribir. Las descargas reintentan con espera creciente.
- Se valida al final que no haya Reservas repetidas.
- Los IDs que empiezan con `$` se escriben como texto, como en Clientes Nuevos (ver ADR 0002, punto 2).

## Decisiones confirmadas (2026-10-16)

1. ~~**Entregas rezagadas:** se sigue la estructura de Nuvia. Una entrega anterior al último registro no se agrega ni se inserta; se avisa en el log.~~ Sustituida el 2026-10-22 (ver abajo). Lo que se mantiene: las diferencias frente al archivo de Nuvia que se explican por un corte más reciente de Maxinet (estatus, gasolinas, No. Rentas, placa) son correctas y esperadas.
2. **IDs:** los identificadores clave (`# Cliente` y `Reserva`) que empiezan con `$` se escriben como texto para no perder el ID por el formato de moneda. Los IDs sin prefijo (ej. `10133`) se escriben como los tiene Nuvia (número), para que sigan coincidiendo con el XLOOKUP de la columna NOMINA contra "Clientes Frecuentes Activos 35".

## Pendientes y limitaciones

1. **IDs con `$` frente a NOMINA.** En el archivo de Nuvia 619 `# Cliente` quedaron como número por el formato de moneda. La columna NOMINA hace XLOOKUP de `# Cliente` contra "Clientes Frecuentes Activos 35"; un ID `$` escrito como texto podría no coincidir con el mismo ID dañado en esa pestaña y caer en el valor por defecto "CO". Afecta a unas decenas de filas. Se resuelve de raíz guardando también como texto los IDs de esa pestaña.
2. **Formato de moneda en celdas dañadas.** Al alinear con Nuvia se copiaron los valores, no el formato de moneda de sus celdas con ID convertido a número.
3. **Entregas con cambio de fecha o de ID en Maxinet.** En la comparación de enero a octubre, 23 entregas de Maxinet no estaban en el archivo de Nuvia y 22 del archivo de Nuvia ya no aparecen en Maxinet; la mayoría son cambios de placa o ID, no entregas perdidas.

## Revisión 2026-10-22: refresco del mes en curso

### Qué falló

El diseño de sólo agregar dejaba congelada la foto del momento en que cada fila se pegó. Una entrega se registra como `ON HIRE` y, días después, Maxinet la pasa a `RETURNED`, `CHECKED IN`, etc., pero el Sheet nunca se enteraba. Al comparar octubre contra Maxinet había 723 filas `ON HIRE` en el Sheet frente a 257 reales, y 1,091 recepciones frente a 1,568. Los indicadores del Tablero que dependen del estatus y de la gasolina de recepción quedaban subestimados. Las entregas que Maxinet publicaba con retraso (anteriores al último registro) tampoco entraban nunca.

Nuvia resuelve esto pegando de nuevo el mes en curso; los meses cerrados quedan congelados. La automatización hace lo mismo.

### Decisión

- Cada corrida descarga el mes en curso (del día 1 a ayer) y **reescribe ese bloque completo** en la pestaña, desde la primera fila cuya fecha sea del mes hasta el final. Los meses anteriores no se tocan.
- Durante los primeros 3 días del mes (`DIAS_MES_ANTERIOR`) también se refresca el mes anterior, porque Maxinet todavía cierra estatus de entregas de fin de mes. Cada mes se consulta con su propio rango para que Cumpleaños siga igual que en Nuvia.
- Las filas del bloque se ordenan por (Fecha, Hr.Entrega) con orden estable. Las entregas rezagadas dentro del mes ya entran en su lugar; las que desaparecen de Maxinet se retiran del bloque.
- Las fórmulas Q:X y los formatos no se sobrescriben: sólo se completan en las filas nuevas al final del bloque.
- **Salvaguarda:** si el bloque actual tiene 30 o más filas y Maxinet devuelve menos del 80%, la corrida se detiene sin escribir (respuesta incompleta, no un mes que de verdad se encogió). `FORZAR=1` la omite para un caso legítimo.
- El log informa altas, bajas, estatus cambiados y la distribución de `ON HIRE` antes y después, de modo que cada corrida deja trazabilidad de lo que movió. `DRY_RUN=1` calcula todo sin escribir.

### Aplicación y verificación

La primera corrida real reescribió `A21938:P23762` (1,825 filas, igual a las de Maxinet): 18 altas, 7 bajas, 674 estatus actualizados, `ON HIRE` de 723 a 256 y 1,569 recepciones. Una segunda corrida inmediata no movió nada (0 altas, 0 bajas, 0 estatus). Las fórmulas y formatos de Q:X se conservaron, sin Reservas repetidas. Antes de escribir se guardó un respaldo del bloque anterior.

Hay pruebas automáticas (`automations/maxinet-entregas-cp/tests`, corren en el workflow `Pruebas`) para los bloques de fechas en cambios de mes y de año, la validación del ancho, el refresco con altas, bajas y estatus, el encogimiento y crecimiento del bloque, la salvaguarda del 80%, `DRY_RUN` y los IDs con `$`.

### Consecuencias

- Una corrida reescribe unas 1,800 filas en lugar de agregar unas decenas. Es una sola escritura de la hoja, dentro de la cuota de la API.
- Si alguien edita a mano una celda A:P del mes en curso, la siguiente corrida la sobrescribe con lo de Maxinet. Las fórmulas Q:X no se ven afectadas.
- Clientes Nuevos y Clientes Potenciales conservan el comportamiento de sólo agregar. Si presentan el mismo desfase de estatus, se evaluará aplicar el mismo patrón en una decisión aparte.
