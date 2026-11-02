# ADR 0019: Pestaña MKT de la Base CP desde el reporte de leads externos de Maxinet

- Estado: aceptada
- Fecha: 2026-10-28

## Contexto

Marketing revisa los leads externos (prospectos de la página web, 2chat, formularios de Facebook e Instagram y cotizaciones) en `mk-reporte-leads-externos.php`. Nuvia pega esa tabla a mano en su Tablero y acumula los meses (de marzo a octubre de 2026 hay ~12,000 filas). La Base CP copia ya tiene una pestaña `MKT` con los 40 encabezados y sin datos, que esta automatización alimenta.

## Hallazgos que fijan el diseño

- La tabla de la página es un DataTable que consulta `includes/comercialCP/cp-leads-externos.php` por POST con `Estatus` (2 = TODO), `Desde`, `Hasta` y `permisoEditaCerrado`. Los filtros actúan sobre la Fecha Registro y `Hasta` es inclusive. El mes completo (~2,000 leads) tarda unos 2 minutos.
- La respuesta trae 42 columnas: dos de acción en HTML (que llevan el id único del lead) y las 40 de la pestaña, en el mismo orden que los encabezados. Los importes llegan sin formato (`39660`, `10784.4828`) y `Estatus Reserva` trae espacios al final.
- Maxinet no entrega los leads ordenados por Fecha Registro. El id del lead es único y crece con el registro.
- El botón "Recargar" de la página llama a `importleads.php`, que escribe en Maxinet. Esta automatización nunca lo llama.

## Decisión

- **Rango:** del primer día del mes a ayer (hora CDMX), estatus TODO. Si hoy es día 1, ayer cae en el mes anterior y el rango es ese mes completo. Durante los primeros 3 días del mes también se refresca el mes anterior. Es la misma regla de Entregas (ADR 0007).
- **Refresco del bloque del mes.** Cada corrida reemplaza, desde la primera fila con Fecha Registro dentro del bloque hasta el final, las columnas A:AN, ordenado por (Fecha Registro, id). Los estatus, cierres y reservas cambian con los días, por eso se reescribe el mes completo y no sólo lo nuevo. Los meses anteriores y la fila 1 no se tocan. Si la pestaña tiene filas fuera de orden dentro del bloque, la corrida se detiene.
- **Tipos como los deja Nuvia:** fechas reales con hora (`yyyy-mm-dd h:mm:ss`; `Fecha cierre` y `Fecha envío cotización` sin segundos), `No.Intento`, `Días Renta`, subtotales y garantía como números, `Teléfono` como número si son sólo dígitos y el resto como texto sin espacios sobrantes. Los identificadores (`Reserva`, `No.Cliente`) se conservan como texto.
- **Escritura en modo RAW.** Los textos los capturan clientes y ejecutivos (nombre, comentarios); en modo RAW nada se interpreta como fórmula. Se escribe en tandas de 800 filas.
- **Salvaguardas:** los encabezados de la fila 1 deben coincidir con las 40 columnas; un ancho de reporte distinto, fechas con otra forma o leads sin fecha detienen la corrida sin escribir; si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más) también (`FORZAR=1` la omite); un lead repetido por id se conserva una sola vez; después de escribir se verifica el número de filas y el orden por fecha.
- **Privacidad:** el repositorio y sus logs son públicos, así que sólo se registran conteos y fechas, nunca nombres, correos, teléfonos ni comentarios. Las pruebas usan datos sintéticos.
- **Pestaña por gid:** `WORKSHEET_MKT_NAME` acepta nombre o gid y se recomienda el gid (ADR 0018).
- **Horario:** 8:20 (cron de respaldo en GitHub; el disparo exacto va en el Vigilante de Apps Script).

## Fuera de alcance

El Tablero CP todavía lee sus leads de su propia pestaña `Reporte Prospectos CP`; repuntarla a `MKT` de la Base, y la columna `Mes` y los clasificadores que Nuvia agrega a la derecha, se definen cuando ella termine sus ajustes. La guardia de actualización todavía no revisa esta automatización.
