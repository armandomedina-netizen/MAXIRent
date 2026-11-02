# ADR 0020: Pestaña BITACORA CP del Tablero CP desde la bitácora de entregas y recolecciones de Maxinet

- Estado: aceptada
- Fecha: 2026-10-28

## Contexto

La bitácora de entregas y recolecciones de CP (`cp-bitacora-entregas-recolecciones.php`) lista cada servicio a domicilio, con su fecha y hora promesa, la real, el semáforo, el retraso y los motivos de retraso. Nuvia mantiene una copia pegada a mano (`Copia de BITACORA CP`, 837 filas de octubre, con cuatro columnas de fórmulas a la derecha). Nuestro Tablero CP copia tiene una pestaña `BITACORA CP` con los 41 encabezados y sin datos (antes se llamaba `ENTREGA A DOMICILIO`), que esta automatización alimenta.

## Hallazgos que fijan el diseño

- La tabla es un DataTable que consulta `json/entregasRecoleccionesBitacora.php` por POST con `Desde`, `Hasta` y `Sucursal` (vacío = todas). Los filtros actúan sobre la Fecha Prom. y `Hasta` es inclusive. El mes completo (~930 servicios) tarda ~1 minuto.
- La respuesta trae 38 columnas: una de acción en HTML ("Comentarios") y las 37 de datos, en el mismo orden que `A:AK` de la pestaña. Los importes llegan sin formato (`250.0000`) y varios textos traen espacios al final.
- Maxinet no entrega los servicios ordenados por fecha promesa. No hay un id por servicio; en octubre la pareja (Reserva, Tipo Serv.) es única, pero no se usa para descartar filas.
- `AL:AO` (AÑO, MES, Asesor móvil, PERIODO) son fórmulas, no datos de Maxinet. La pestaña no las traía; las de la copia de Nuvia son `YEAR`, `TEXT(...,"MMMM")`, el asesor móvil o "SIN ASESOR", y `TEXT(...,"MMMM YYYY")` sobre la fecha promesa.
- La cuenta de servicio ya es editora de la protección de la pestaña.

## Decisión

- **Rango:** del primer día del mes a ayer (hora CDMX), todas las sucursales. Si hoy es día 1, ayer cae en el mes anterior y el rango es ese mes completo. Durante los primeros 3 días del mes también se refresca el mes anterior. Es la misma regla de Entregas (ADR 0007) y de leads (ADR 0019).
- **Refresco del bloque del mes.** Cada corrida reemplaza, desde la primera fila con Fecha Prom. dentro del bloque hasta el final, las columnas `A:AK`, ordenado por (Fecha Prom., Hora Prom., Reserva, Tipo Serv.). Los estatus, las fechas y horas reales y los motivos de retraso cambian con los días, por eso se reescribe el mes completo. Los meses anteriores y la fila 1 no se tocan; los meses se acumulan, como lo supone la columna PERIODO. Si la pestaña tiene filas fuera de orden dentro del bloque, la corrida se detiene.
- **Fórmulas auxiliares.** Para las filas del bloque se escriben las cuatro fórmulas de la copia de Nuvia en `AL:AO`. Nunca se borran: si el bloque se acorta sólo se limpian los datos de `A:AK`.
- **Tipos como los deja Nuvia:** fechas como número entero y horas como fracción del día, con los formatos que ya usa la pestaña (`d/M/yyyy`, `h:mm:ss`, `yyyy-mm-dd`, moneda); costos y `Dif. Dias` como números; `# Cliente`, `Reserva` y `Código Postal` como número cuando son sólo dígitos; el resto como texto sin espacios sobrantes.
- **Escritura en modo RAW** para los datos (domicilios y comentarios los capturan personas; nada se interpreta como fórmula) y en tandas de 800 filas; sólo las fórmulas auxiliares van como `USER_ENTERED`.
- **Salvaguardas:** los 41 encabezados deben coincidir (un texto adicional a la derecha, como el enlace del reporte, se ignora); un ancho distinto, fechas u horas con otra forma o servicios sin fecha promesa detienen la corrida sin escribir; si Maxinet trae menos del 80% de las filas actuales del bloque (con 30 o más) también (`FORZAR=1` la omite); después de escribir se verifica el número de filas y el orden.
- **Privacidad:** el repositorio y sus logs son públicos, así que sólo se registran conteos y fechas, nunca nombres, domicilios ni comentarios. Las pruebas usan datos sintéticos.
- **Pestaña por gid:** `WORKSHEET_BITACORA_NAME` acepta nombre o gid y se recomienda el gid (ADR 0018). El archivo es el del Tablero CP (`SPREADSHEET_ID_TABLERO_CP`).
- **Horario:** 8:30 (cron de respaldo en GitHub; el disparo exacto va en el Vigilante de Apps Script).

## Fuera de alcance

La `Copia de BITACORA CP` de Nuvia es su referencia y no se toca. Los gráficos y tableros que lean esta pestaña, y la revisión en la guardia de actualización, se definen cuando ella termine sus ajustes.
