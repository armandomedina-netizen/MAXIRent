# ADR 0013: Columnas diarias del Tablero CP copia y actualización del 23 de octubre

- Estado: aceptada; el cierre diario automático se decidió el mismo día (ADR 0014)
- Fecha: 2026-10-23

## Contexto

El Tablero CP copia se veía atrasado: en `UNIDADES CP`, `UTILIZACION TODOS LOS GRUPO` y `UTILIZACION POR GRUPO` sólo había datos hasta el 19 de octubre, la columna del 20 mostraba ceros y `DETALLE` y `GRAFICAS` tenían 0.0% en los días recientes. `MKT` y `Bitácora Entregas / Recolecciones CP` mostraban `#DIV/0!` en el mes en curso.

## Hallazgos

1. **Las columnas diarias dependen de un cierre manual.** Esas tres pestañas tienen una columna por día. Nuvia deja una sola columna "viva" con fórmulas `COUNTIFS` sobre `FLOTA CP` que filtran por la fecha de los datos (`'FLOTA CP'!$E:$E` igual a la fecha del encabezado). Cuando cambia el día, congela a mano la columna anterior (constantes en las filas `COUNTIFS` y en los subtotales que ella decide; las sumas de totales y los porcentajes `IFERROR` quedan como fórmula) y mueve las fórmulas a la columna siguiente. Si la fecha de `FLOTA CP` ya no coincide con la del encabezado, la columna viva devuelve 0. Nuestra copia no tenía quién hiciera ese cierre.
2. **El bloque comercial de `DETALLE` dejó de extenderse el 16 de octubre, también en el original.** Las fórmulas `XLOOKUP` de las columnas `DJ:EA` (porcentajes comerciales por grupo, tomados de las filas 137 a 154 de `UTILIZACION TODOS LOS GRUPO`) llegaban sólo a la fila 444. El bloque operativo (`CN:DE`) sí llega a la fila 1000. La tabla "UTILIZACION POR GRUPO (COMERCIAL)" de `GRAFICAS` es una importación de ese bloque, por eso salía vacía del 17 en adelante en los dos libros.
3. **`GRAFICAS` no guarda datos propios.** Importa `DETALLE!EC1:FO45` y sus 16 gráficas leen `DETALLE`; su diseño y rangos ya coincidían con los del original.
4. **Las gráficas de otras pestañas venían del clon** y estaban entre una y cuatro filas más cortas que las del original (`MKT`, `ENTREGAS POR SUCURSAL`, `INDICADOR DE GASOLINA`, `Bitácora`, `Ticket Sac`, `CLIENTES NUEVOS & POTENCIAL`).
5. **`MKT` lee todo de `Reporte Prospectos CP` y `Bitácora` todo de `ENTREGA A DOMICILIO`.** Esas hojas, protegidas sin la cuenta de servicio como editora, seguían en la instantánea del 21 de octubre.

## Decisión y cambios aplicados

Todo se aplicó sólo en nuestro libro; el de Nuvia sólo se lee. Antes de escribir se respaldó lo anterior en `private/backups`, fuera del repositorio.

- **Columnas diarias:** la columna del 20 se copió tal cual de Nuvia; la del 21 se congeló con los valores que muestra el original; las fórmulas vivas quedaron en la columna del 22, que corresponde a los datos de nuestra `FLOTA CP` (un día adelante del original). Los datos de `FLOTA CP` salen de la Base LP copia, que se actualiza por la mañana.
- **`DETALLE`:** las fórmulas del bloque comercial se extendieron de la fila 445 a la 1000, igual que el bloque operativo. El original sigue sin ellas.
- **Gráficas:** se copió el diseño y los rangos de 20 gráficas desde el original. La API de Sheets no permite escribir `lineSmoothing` en gráficas que no son de línea, por lo que se omite ese campo, y no dejó escribir el mínimo del eje de una gráfica (`% TRASLADOS CONDONADOS`).
- **Hojas manuales:** una vez abiertas las protecciones, `Reporte Prospectos CP` y `ENTREGA A DOMICILIO` se copiaron del original (carga única, mismo criterio que el ADR 0012 punto 4). `TASA DE ENTREGAS` y `KADEX EJECUTIVOS` pasaron a leer de nuestra Base copia en lugar del `h encuestas` de Nuvia.

## Verificación

Comparación de valores mostrados celda por celda contra el original, en las 30 pestañas: las tres de columnas diarias, `MKT`, `Bitácora`, `Reporte Prospectos CP` y `ENTREGA A DOMICILIO` quedaron sin diferencias y sin errores. Las diferencias restantes son esperadas: `FLOTA CP` y `DISPONIBLE CON RESERVA` llevan un día más que el original; `DETALLE` y `GRAFICAS` tienen los días 17 a 22 del bloque comercial y el 22 de octubre, que el original no tiene; y los conteos de `KADEX EJECUTIVOS`, `NOMINA`, `INDICADOR DE GASOLINA` y `CRE` salen de nuestras pestañas automatizadas, que van adelante. En la Base copia las fórmulas y constantes de las pestañas manuales son idénticas a las del original salvo `MaxiEmergencia!F1`, que apunta a una hoja local a propósito.

## Pendiente

1. **Cierre diario automático.** Resuelto: ver el ADR 0014.
2. **`FACTURACION LP & CP!D12` (Base copia)** da `#REF!` hasta que alguien pulse "Permitir acceso" en esa celda (importación del Tablero LP). Google no permite autorizarlo por API.
3. **Siguen en archivos o hojas sin resolver:** `PROYECCIÓN DE VENTA $$` y `RESERVAS SIN FACTURAR` (archivo sin acceso para la cuenta de servicio), y `DISPONIBLE+TALLER` (640 errores también en el original, lee una hoja que ya no existe).
4. **Las hojas manuales copiadas son una instantánea del 23 de octubre.** Mientras Nuvia las capture en su archivo seguirán desfasándose; falta identificar el reporte de Maxinet que las alimenta o acordar un refresco periódico.

## Cómo revertir

Los respaldos de valores, fórmulas y especificaciones de gráficas están en `private/backups` (`tablero_cp_columnas_diarias_antes_*`, `tablero_DETALLE_DJ_EA_antes_*`, `tablero_cp_graficas_antes_*`, `tablero_cp_hojas_manuales_antes_*` y `tablero_cp_formulas_repunte_antes_*`). Para volver a leer el `h encuestas` de Nuvia en `TASA DE ENTREGAS` y `KADEX EJECUTIVOS` basta sustituir la clave de nuestra Base por la del original en su fórmula.
