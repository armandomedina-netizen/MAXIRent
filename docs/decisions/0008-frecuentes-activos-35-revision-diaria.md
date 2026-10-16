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

- Cada corrida consulta la semana más reciente del selector, la compara con la pestaña y, si hay cualquier cambio (altas, bajas, asesor, tipo, semanas), reemplaza el bloque A:AH con la información actual de Maxinet. Sin cambios no escribe. El log resume altas, bajas y celdas distintas por columna. Corre a las 9:45 AM CDMX.
- Las columnas se leen de la tabla de la página. Si aparece "Sem 25" (y siguientes) se inserta la columna antes de "Comentario" y se escribe su encabezado; las columnas manuales se recorren a la derecha (probado y revertido sobre la copia). Si Maxinet quita o renombra columnas, la corrida se detiene sin escribir.
- Se conservan los comentarios manuales por No. Cliente, la fórmula TIPO (se completa en todas las filas con datos) y el enlace del encabezado.
- Si el reporte trae menos de la mitad de las filas actuales, la corrida se detiene (probable respuesta incompleta).
- Los No. Cliente con `$` se escriben como texto; los numéricos sin prefijo, como número, igual que en ENTREGAS. Con esto el XLOOKUP de NOMINA compara texto con texto en los IDs `$`.

## Pendientes

1. **Confirmar con Nuvia que la pestaña debe reflejar la semana más reciente.** Hoy su archivo tiene la semana 189; la copia automatizada tendrá la 192 y avanzará sola. La columna NOMINA de ENTREGAS cambiará respecto a su archivo (más clientes cambian de CO a CF o al revés).
2. **Comentarios de clientes que salen del reporte** se retiran con ellos (se registra cuántos). Decidir si deben archivarse.
3. **"Sem 1" es la semana actual:** al cambiar de semana, todas las columnas Sem se recorren; es el comportamiento del reporte, no un error.
