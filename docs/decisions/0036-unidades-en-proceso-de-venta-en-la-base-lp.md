# ADR 0036: Unidades en proceso de venta en la Base LP

Fecha: 2026-11-27

## Contexto

El reporte **Unidades en Proceso de Venta** (venta de seminuevos, `Unidades-Venta.php`) se consultaba a mano. La Base LP copia (`BASE LP_AUTOMATIZADO`) ya tenía una pestaña con ese nombre, vacía salvo una nota en `A1` y la URL del reporte en `A2`, como destino para cargarlo de forma automática.

La página carga una tabla DataTable desde `POST json/unidades-venta-all.php` con un filtro de estatus (Abierto 1, Propuesta 10, Cerrado 0, Rechazo 11, Todo 2). Cada fila trae 47 celdas: el botón "Detalle", una columna oculta y vacía, y las 45 columnas de la tabla. El 26-nov-2026 Maxinet le agregó las columnas de MOI, precio de caja y depreciación (las mismas del reporte de flota, ADR 0035).

## Decisión

1. **Se carga el estatus Abierto (151 unidades el 27-nov).** El estatus Propuesta (41) es un subconjunto de Abierto: son las mismas filas, así que pedir los dos duplicaría. `ESTATUS_UNIDADES_VENTA` (variable del repositorio, opcional) permite otro o varios, separados por coma; se desduplica por `Id`.
2. **Reemplazo completo en cada corrida**, una vez al día a las 8:00 (misma ventana del Proyector, ADR 0030): una unidad que se vende, se da de baja o cambia de estatus sale o se actualiza. La llave es el `Id` del reporte, no la placa (una placa puede volver a venderse).
3. **Las 45 columnas, `A:AS`, tal como la página**, tipadas: fechas como número de serie (`yyyy-mm-dd`); precios, MOI y depreciación como número con formato de moneda (varios llegan como texto `$ 208,000.00`); kilómetros, % de utilización, año, meses de uso e `Id` como número; el resto como texto con `RAW` (el `# Cliente` `#4799998`, el RFC y las placas nunca se interpretan). "Estatus A" llega con una etiqueta de color: se guarda el texto visible.
4. **Mismo esquema de seguridad que el Proyector**: el encabezado de la fila 1 es de quien armó la hoja (si coincide con los 45 nombres no se toca; si está vacío se escribe; si es otro, la corrida se detiene sin escribir); la pestaña no se crea; se detiene sin escribir si cambia el ancho, si las columnas dejan de cuadrar, si un `Id` viene vacío o repetido o si Maxinet trae menos del 80% de lo que hay en la hoja (`FORZAR=1` omite sólo esa última); se escribe primero y se limpia lo que sobra después; la hora de la última actualización va dos columnas a la derecha de los datos (`AU`).
5. **No se envía el `Puesto_Id` que la página manda**: el servidor responde lo mismo sin él (se probó con vacío y con otros valores), y es un dato fijo de la página que depende del puesto de quien la abre, no del reporte.

## Verificación

- 73 pruebas; siete mutantes (sin desduplicar por Id, signo negativo ignorado, prefijo de columnas, formato de moneda, umbral de la salvaguarda, orden de escritura y limpieza, estatus por omisión) fallan las pruebas.
- Descarga real: 151 unidades x 45 columnas, 0 valores que se queden como texto en columnas numéricas o de fecha. Primera carga el 27-nov-2026 9:55: 151 unidades en `A2:AS152`; la segunda corrida no encuentra altas, bajas ni cambios.
- Antes de la primera carga se respaldó la pestaña (`private/backups`), se retiró la nota de `A1:A2` y la URL de origen se conservó en `AU4:AU5`. Al encabezado se le dio el estilo de la hoja principal de la Base y se congeló la fila 1 (una sola vez; la automatización no toca el encabezado).

## Consecuencias

- La corrida de las 8:00 la lanza el Vigilante (ventana agregada al archivo; falta pegarlo en Apps Script) y el reloj de GitHub de respaldo.
- Si Maxinet agrega o quita columnas, la corrida falla sin escribir con el ancho en el mensaje; el procedimiento es el de `docs/automatizaciones.md` (ajustar `ENCABEZADO`, el encabezado de la pestaña y el ancho).
