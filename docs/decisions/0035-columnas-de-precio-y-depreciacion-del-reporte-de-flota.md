# ADR 0035: Columnas de precio y depreciación del reporte de flota

Fecha: 2026-11-27

## Contexto

El 26-nov-2026 Maxinet agregó siete columnas al final del reporte de flota (`reporte-flota-general.php`), después de `Meses uso`: **Precio Compra, MOI (sin iva), Precio caja, Total MOI, Dep. Mensual, Dep. Acumulada y Remanente ajustado 14%** (49 columnas; el endpoint trae además la de acciones, 50 valores por fila). El cambio aplica a cualquier fecha consultada, también a las fotos de días pasados.

El candado de ancho hizo lo que debe (no escribir columnas corridas) y falló, sin escribir nada, en:

- `Maxinet Sync` (modo completo): `El reporte de flota trae [49] columnas y el script espera 42`. Fallaron la corrida de las 8:00 del 27-nov (y sus reintentos) y la del 26-nov a las 16:41 (la de las 8:05 de ese día aún pasó); el modo `proyeccion-mtto` no usa este reporte y siguió en verde.
- `Tablero CP Cierre Diario` (`recuperar_dias.py`, mismo candado), que reconstruye días desde el reporte.

## Decisión

1. **Se acepta el ancho de 49 columnas** y se sigue exigiendo exactamente ese ancho (42 o 50 siguen siendo "cambió la estructura"), por la misma razón del ADR 0027: una columna insertada a la mitad correría el bloque sin avisar.
2. **Ninguna de las siete va en el bloque `B:AP`** (a su derecha están las fórmulas del dueño de la hoja, y la tabla lateral de resumen ocupa de `AU` en adelante, así que no hay espacio contiguo a `Meses uso`). Se suman a `COLUMNAS_FUERA_DE_BLOQUE`: cada una se escribe en la columna de la base `RESERVAS CP&LP` cuyo encabezado de la fila 1 se llama igual, como número, alineada con el bloque. Dónde se colocan las columnas lo decide quien mantiene la hoja; el sync las sigue por encabezado.
3. **Cada columna fuera del bloque es independiente.** `actualizar_columnas_fuera_del_bloque` ya no se detiene en la primera que no puede escribir: una sin encabezado, con fórmulas o dentro de `A:AP` se omite y las demás se escriben; al final, un solo error las nombra a todas (anotación de la corrida, el sync no se detiene). Mientras la base no tenga los encabezados, el sync queda al día con el bloque y `Meses uso`, y avisa de las siete pendientes.
4. **`recuperar_dias.py` acepta los 49 valores** y sigue usando los 41 primeros (`E:AS` de `FLOTA CP`); las nuevas no se importan para no caer sobre las columnas estáticas (`AT` en adelante).
5. **`FLOTA LP` y `FLOTA CP` no cambian**: importan `A:AT` y `A:AR` de la base, y ninguna letra existente se mueve.

## Verificación

- Pruebas: 95 del sync y 96 del cierre diario; tres mutantes (volver a detener en la primera columna sin encabezado, quitar una columna nueva, escribir texto en lugar de número) fallan las pruebas nuevas.
- Descarga real (foto del 26-nov, 1,703 filas x 49 columnas) validada con el código nuevo, y paso de columnas contra la base real con las escrituras bloqueadas: se escribiría `AT` y se avisan las siete pendientes.

## Consecuencias

- Hasta que se agreguen los siete encabezados en la base, las columnas nuevas no se llenan (el reporte sigue al día en lo demás). Con el encabezado, la siguiente corrida las llena sola.
- Si Maxinet vuelve a agregar columnas, el procedimiento sigue siendo el de `docs/automatizaciones.md`.
