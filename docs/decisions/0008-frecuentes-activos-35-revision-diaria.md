# ADR 0008: Clientes Frecuentes Activos 35 como revisión diaria contra Maxinet

- Estado: aceptada
- Fecha: 2026-10-16

## Contexto

La pestaña "Clientes Frecuentes Activos 35" de la Base se alimenta del reporte `cp-reporte-clientes-frecuentes-activos-v2.php` (endpoint `json/cp-frecuentes-activos-data-v2.php`, parámetro `Periodo` = id de la semana del selector). Es una foto completa de una semana, no un historial. La columna NOMINA de ENTREGAS hace XLOOKUP contra esta pestaña (`# Cliente` -> Tipo).

## Hallazgos

- El archivo de Nuvia contiene exactamente la semana 189 (2026-09-12): 780 de 780 clientes y el mismo orden; no se había actualizado con las semanas 190 a 192. La copia estaba más atrás todavía.
- El endpoint devuelve 36 columnas: una de acciones ("Editar") al inicio, 34 de datos (Sucursal ... Sem 24) y "Comentario" al final. La página lista además "Facturación 2 meses" comentada en el HTML; no se muestra ni viene en los datos.
- El reporte crece por semanas ("Sem 1 es la semana actual"). Cada consulta tarda ~100 s.
- En el Sheet, "Comentario" es manual (4 filas con valor) y no coincide con el "Comentario" de Maxinet (150 con valor en la semana 192). Al reemplazar el bloque los clientes cambian de fila, así que los comentarios se recolocan por No. Cliente.
- La fórmula de la columna TIPO terminaba en la fila 758 con un hueco, aunque había datos hasta la 781.

## Decisión

- **La copia muestra lo mismo que el archivo original (modo espejo, por defecto).** Cada corrida lee la pestaña del archivo original (sólo lectura), identifica qué semana de Maxinet contiene (mismos clientes y mismas columnas de semanas; el asesor, la sucursal y demás datos del cliente se ignoran para identificarla porque Maxinet los corrige después en todas las semanas) y carga esa misma semana. Primero revisa la semana anotada en la corrida anterior (una consulta de ~100 s); si el original se actualizó y ya no coincide, revisa en paralelo las 8 semanas más recientes y, si ninguna coincide, no escribe. La semana cargada se anota en una celda bajo el enlace del encabezado ("Semana cargada: 189 (2026-09-12)"). `MODO_SEMANA=ultima` carga la semana más reciente (para cuando la automatización sustituya al proceso manual) y `PERIODO=<id>` fija una semana.
- Cada corrida compara esa semana con la pestaña y, si hay cualquier cambio (altas, bajas, asesor, tipo, semanas), reemplaza el bloque A:AH con la información actual de Maxinet. Sin cambios no escribe. El log resume altas, bajas y celdas distintas por columna. Corre a las 9:45 AM CDMX.
- Las columnas se leen de la tabla de la página. Si aparece "Sem 25" (y siguientes) se inserta la columna antes de "Comentario" y se escribe su encabezado; las columnas manuales se recorren a la derecha (probado y revertido sobre la copia). Si Maxinet quita o renombra columnas, la corrida se detiene sin escribir.
- Se conservan los comentarios manuales por No. Cliente, la fórmula TIPO (se completa en todas las filas con datos) y el enlace del encabezado.
- Si el reporte trae menos de la mitad de las filas actuales, la corrida se detiene (probable respuesta incompleta).
- Los No. Cliente con `$` se escriben como texto; los numéricos sin prefijo, como número, igual que en ENTREGAS. Con esto el XLOOKUP de NOMINA compara texto con texto en los IDs `$`.

## Validación de la lógica contra el archivo de Nuvia (2026-10-16)

El armado se validó reconstruyendo con este mismo código la semana que tenía Nuvia y comparándola celda por celda:

- **Semana 189 (archivo actual de Nuvia):** mismas 780 filas, mismo orden y 26,504 de 26,520 celdas idénticas (99.94%). Todas las columnas `Sem 1..24`, No. Semanas Renta y Tipo CF coinciden. Las 16 celdas distintas (9 clientes) son Asesor y Tipo Persona vacíos en Nuvia y llenos hoy en Maxinet, y 2 Sucursal que cambiaron.
- **Semana 183 (la copia antes de actualizarla):** mismos 781 clientes y 756 de 781 filas idénticas; las 52 celdas distintas son del mismo tipo (Asesor 19, Tipo Persona 19, Sucursal 9, Cumpleaños 5).
- Esos datos de cliente cambian retroactivamente en Maxinet: las semanas 188, 190 y 192 muestran los mismos valores actuales, por lo que se corrigieron después del corte de Nuvia.
- Estructura: encabezados A1:AL1, fórmula TIPO, formatos de número, dimensiones, tipo de dato de cada celda (fecha, número, texto), ID `$` como texto y los 4 comentarios manuales coinciden. La única diferencia estructural es que la fórmula TIPO en Nuvia termina en la fila 758 y la copia la tiene en todas las filas.
- Cadencia de Nuvia: su pestaña pasó de la semana 183 (15-ago) a la 189 (12-sep), es decir, la refresca de forma irregular, aproximadamente una vez al mes y con la semana más reciente de ese momento. Eso respalda usar siempre la más reciente.
- La copia automatizada contiene exactamente la semana 192: una segunda corrida reporta "sin cambios". Por lo tanto, toda diferencia contra el archivo de Nuvia es la diferencia entre las semanas 189 y 192 de Maxinet.

## Pendientes

1. **Cambiar a `MODO_SEMANA=ultima`** cuando la automatización sustituya al proceso manual de Nuvia (ella actualiza la pestaña aproximadamente una vez al mes). Con ese modo la columna NOMINA de ENTREGAS cambiaría respecto a su archivo.
2. **Diferencias que quedan frente al archivo de Nuvia (semana 189):** 16 celdas (Asesor y Tipo Persona vacíos en su archivo y llenos en Maxinet, y 2 Sucursal corregidas) y la fórmula TIPO, que en su archivo falta en 24 filas. Se conservan los valores actuales de Maxinet; confirmar con Nuvia.
3. **Primera búsqueda lenta.** Cuando el original se actualiza, la búsqueda en paralelo de 8 semanas tardó ~8 minutos (cada consulta de Maxinet es pesada).
4. **Comentarios de clientes que salen del reporte** se retiran con ellos (se registra cuántos). Decidir si deben archivarse.
5. **Significado de las columnas Sem.** Maxinet indica que "Sem 1 es la semana actual", pero los datos de semanas consecutivas no se explican con un simple recorrido de columnas (se probó y no se sostuvo). Para el armado no importa, porque se copia lo que entrega Maxinet; sí importa si algún día se quiere interpretar la columna.
