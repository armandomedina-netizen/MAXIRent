# 0005 - Gestoría LP & CP: todos los estatus, trampas del Sheet y disparo desde Apps Script

Fecha: 2026-10-12

## Contexto

`automations/automatización Gestoría/gestoria_lp_cp_sync.py` (workflow `gestoria-lp-cp-sync.yml`) mantiene la pestaña `GESTORIA CP - LP` de la copia automatizada de `GESTORIA CP&LP`. La auditoría del 2026-10-12 contra Maxinet y contra el original de Nuvia encontró: 13 de 13 corridas programadas exitosas, cero desajustes de estatus, sin duplicados, pero tickets faltantes. La automatización pedía sólo `Estatus=ABIERTO`; los tickets de VERIFICACIÓN o TRÁMITES que se abren y se cierran en menos de un minuto nunca aparecen como abiertos en una corrida, así que nunca entraban (faltaban 1629, 1638 a 1640, 1642 y 1644; el original de Nuvia sí los tiene). Además la columna AI "Cerrado" quedaba vacía en las filas que la automatización cerraba por ausencia.

## Decisión

1. Se piden todos los tickets (`Estatus` vacío, el botón "Ver Todo" de Maxinet). Se agrega todo folio que falte, con su estatus real; se cierra lo que Maxinet muestra CERRADO o ya no muestra; y la columna AI se llena con `estatus_created_at` cuando está vacía (nunca se sobrescribe). No se reabre una fila CERRADO que Maxinet muestre ABIERTO: sólo se avisa con el conteo, porque esa regla no se acordó.
2. Guardia: si Maxinet devuelve menos de la mitad de los folios que tiene el Sheet, la corrida aborta sin escribir (con cierre por ausencia, una respuesta vacía cerraría casi todo).
3. `--dry-run` informa qué cambiaría sin escribir.
4. El folio 871 (SINIESTRO de diciembre de 2025, con cargo adicional 4067 FINALIZADO, sin duplicados) faltaba también en el original. Se agrega como cualquier otro: es un ticket real y omitirlo dejaba un siniestro fuera de diciembre de 2025. Se avisa a Nuvia de que su original no lo tiene.
5. El disparo puntual vive en el proyecto de Apps Script `Vigilante_Maxinet` (no se versiona: contiene el correo del equipo), que ya tiene un disparador independiente por reporte (ADR 0003). `ejecutarGestoria` sigue el mismo patrón que `ejecutarQuerySync` y `ejecutarBalance`: `workflow_dispatch` cada hora (minuto 57) de lunes a sábado de 8:30 a 19:00 (hora CDMX) y aviso por correo (máximo uno cada 3 horas) si la última corrida exitosa tiene más de 3 horas dentro del horario. Antes de este cambio esa función sólo vigilaba (cada 6 horas, tolerancia de 26 horas) y la corrida dependía del cron de GitHub. El workflow gana `concurrency` y `timeout-minutes: 15`; su cron queda como respaldo (8:45, 12:45 y 16:45 CDMX). Un primer borrador de este disparo como archivo propio (`apps-script/disparador.gs`) se descartó: repetía las funciones de apoyo del Vigilante y su `ejecutarGestoria` chocaba con la existente.
6. Fórmulas de `2026` (B:H): las fórmulas `XLOOKUP` por fila hay que arrastrarlas hacia abajo cuando el derrame de la columna A crece. Sin eso, el folio aparece sin fecha, tipo, placa ni cliente: el 2026-10-12 los folios 1630 a 1654 estaban así (las fórmulas terminaban en la fila 1290 y el derrame en la 1310). `mantener_formulas_historico()` las extiende hasta el último folio del derrame más 50 filas de holgura, copiando el formato de la fila plantilla (la fecha de B) y agregando filas a la hoja si hace falta. Sólo escribe en filas con B:H totalmente vacías y nunca escribe en la columna A. Si `A2` muestra un error de derrame no toca nada y avisa. Un fallo ahí se registra pero no marca como fallida la sincronización principal.
7. Refresco de campos de análisis en filas ya cargadas (2026-10-20): la fecha del evento, el tipo, el cliente, la sucursal, Site, BSite y PUSite se corrigen con lo que diga Maxinet hoy (`CAMPOS_REFRESCABLES`). Maxinet los reclasifica o corrige después de que la fila entra al Sheet y las pestañas `GESTORIA`, `ÍNDICE SINIESTRALIDAD`, `RESUMEN` y `2026` cuentan con ellos; la comparación del 2026-10-20 encontró 69 folios con otra Sucursal, 2 fechas corregidas por Maxinet (folios 1385 y 1435, que quedaron con el mes equivocado) y 405 folios antiguos sin Site ni BSite. Reglas: sólo se escribe cuando Maxinet trae un valor (jamás se borra una celda porque venga vacío: en 742 folios antiguos la sucursal sólo existe en el Sheet), una fecha con año fuera de 2020 a año actual más uno se ignora y se avisa (Maxinet trae `6/2/0026` en el folio 1503) y un campo que cambiaría en más de la mitad de las filas (con al menos 50 comparadas) se omite y se avisa, porque indicaría que Maxinet cambió de formato. Los demás campos (días, cargo adicional, factura, conductor) siguen sin actualizarse. Maxinet manda `&amp;` en algunos textos; la descarga los convierte a `&` para que un cliente no quede en dos variantes.
8. Reparación única de 233 filas heredadas del clon (2026-10-20): desde el folio 1343 (junio de 2026) las columnas `AC:AI` estaban corridas una columna a la derecha porque el original recibe pegada la columna "Alerta Siniestro" de Maxinet, que este Sheet excluye por regla; el efecto era que `AH` traía el municipio y `AI` la fecha de creación en lugar de la de cierre. Se reescribieron `AC:AI` de esas filas con los datos de Maxinet (en 68 se reemplazó un texto de "Alerta Siniestro", que sigue en Maxinet y en un respaldo local). Las filas que agrega la automatización siempre estuvieron alineadas.

## Trampas del Sheet que no deben repetirse

- No usar `append_rows`: la hoja tiene `row_count` de unas 2961 filas por las columnas auxiliares AJ:AM arrastradas de antemano, y la API inserta debajo del último formato, no del último dato (el folio 1624 cayó en la fila 2961 en vez de la 1562 el 2026-09-28). Se calcula la fila (última fila con folio + 1) y se escribe con `update()`.
- La columna A de la pestaña `2026` no se escribe nunca: su `A2` es `=UNIQUE(FILTER('GESTORIA CP - LP'!A:A,'GESTORIA CP - LP'!AM:AM="OK"))` y B:H son `XLOOKUP` precargados por fila. Un valor fijo en A bloquea el derrame y toda la fórmula queda en `#REF!` (incidente del 2026-09-28, sin pérdida de datos). Una fila nueva aparece ahí sola en cuanto su fecha de evento es de 2025 o 2026.

## Consecuencias

- Las filas nuevas con estatus CERRADO entran al final del Sheet, no en su lugar por folio; el equipo ordena por fecha del evento.
- La primera corrida llena de una sola vez la fecha de cierre de las filas ya cerradas (534 en la auditoría).
- Si el token de GitHub del Apps Script vence, el correo avisa y el cron de respaldo mantiene tres corridas al día.
- Si se vuelve a ejecutar `crearDisparadores` del Vigilante, debe llevar `everyHours(1).nearMinute(57)` para `ejecutarGestoria`; con `everyHours(6)` el disparo horario se revertiría sin avisar.

## Alineación con el formato del original (2026-10-20)

Nuvia reorganizó `GESTORIA CP&LP`: la hoja `DATA` pasó a llamarse `RESUMEN` (mismo `sheetId`), `DATA GESTORIA` es la hoja de datos (la nuestra, `GESTORIA CP - LP`, tiene el mismo `sheetId`), apareció el tablero `GESTORIA`, el índice `ÍNDICE SINIESTRALIDAD` (antes `% SINIESTRALIDAD`) y `BDATOS`, y se eliminó `DESCARTAR`. La comparación previa mostró que las hojas de datos y `2026` ya eran idénticas en encabezados, formatos de número y las 7 reglas condicionales (sólo diferían el ancho de la columna AF y, por decisión propia, el contenido de `2026`).

### Decisiones

1. La copia queda con la misma estructura y orden que el original: `GESTORIA`, `ÍNDICE SINIESTRALIDAD`, `BDATOS`, `RESUMEN`, `GESTORIA CP - LP`, `2026`. Las tres pestañas nuevas y `RESUMEN` se trajeron con `copyTo` (formato, colores de pestaña, filas fijas, reglas, listas desplegables) y sus propiedades coinciden con las del original. La hoja de datos conserva su nombre `GESTORIA CP - LP` (la copia es CP y LP), por lo que las fórmulas apuntan a ese nombre en lugar de `DATA GESTORIA`.
2. Independencia: nada del libro lee archivos de Nuvia. `RESUMEN` importaba los promedios de rentas de `LP - TABLERO` y `CP - TABLERO` (los suyos); ahora lee `TABLAS!BC2:BF14` de nuestro `TABLERO LP` (misma tabla, 13 filas sin diferencias) y `DETALLE!CE1:CG13` de nuestra copia automatizada de `CP - TABLERO`. `ÍNDICE SINIESTRALIDAD` ya importaba de esos dos archivos nuestros. Un barrido de todas las fórmulas del libro no encontró ninguna liga a archivos de ella.
3. `BDATOS` deja de ser una pegada manual: `C1` es `=FILTER('GESTORIA CP - LP'!A1:AI,'GESTORIA CP - LP'!A1:A<>"")` y las columnas `A` (PERIODO) y `B` (CLIENTE, SI/NO según la lista de `ÍNDICE SINIESTRALIDAD!A:A`) conservan sus fórmulas. Todas las fórmulas de las pestañas nuevas sólo usan las columnas A, B, E, I, R y V, que coinciden con las del original aunque nuestra hoja no tenga la columna "Alerta Siniestro". La hoja tiene 5,000 filas (con unas 1,600 filas de datos y ~2 tickets diarios alcanza para años).
4. Se conserva en `RESUMEN!U:V` nuestro bloque de siniestros de corto plazo por cliente; el bloque de largo plazo es el del original (un `QUERY` en `R1`). `2026` no cambia (lista CP y LP de 2025 y 2026 con Site y BSite).

### Trampa del Sheet que no debe repetirse

Al copiar una pestaña a otro libro, las fórmulas que apuntan a hojas hermanas conservan el texto, pero la referencia queda sin enlazar y calcula 0 (`GESTORIA!B7` daba 0 con `BDATOS` llena). Hay que volver a escribir cada fórmula (basta con reescribir su mismo texto con `USER_ENTERED`) y sólo las celdas que son fórmulas: las celdas derramadas son valores y escribirlas bloquea el derrame. La cuenta de servicio no puede duplicar el libro completo para respaldarlo (cuota de Drive llena); el respaldo de la `DATA` anterior se guardó en un JSON local y la pestaña quedó oculta como `DATA (anterior)`, sin las dos fórmulas IMPORTRANGE.

### Verificación

- `RESUMEN!R1:T50` y `ÍNDICE SINIESTRALIDAD!A1:M60` coinciden celda por celda con el original; `GESTORIA` difiere en 11 celdas por datos distintos en ambas `BDATOS`, no por el formato (ver abajo).
- `RESUMEN!C49:C66` y el bloque `E17:G29` esperan el permiso "Permitir acceso" de la liga a la copia de `CP - TABLERO` (requiere navegador de escritorio).

### Diferencias de datos entre las dos `BDATOS`

Sobre 1,585 folios comunes: 69 con otra Sucursal (en 59 Maxinet la tiene vacía y Nuvia la completó a mano; en otros 8 Maxinet cambió después de que la fila entró a nuestra hoja), 17 con otro estatus (Maxinet coincide con la copia en los 17) y 2 con otra fecha de evento (folios 1385 y 1435, donde Maxinet coincide con el original y nuestra fila quedó con la fecha anterior). Como el script no actualiza filas existentes (decisión 1 de este ADR), esos valores no se refrescan solos.

### Cierre de la alineación (2026-10-20)

- `SINIESTROS` del `TABLERO LP` (`D18` y `A19`) leía por IMPORTRANGE la hoja `RESUMEN` de `GESTORIA CP&LP` de Nuvia (`I1:P37` y `R1:S47`); si ella la cambiaba o la borraba, la pestaña y su gráfico se rompían. Ahora leen las mismas celdas de nuestra `RESUMEN`, que se alimenta cada hora de Maxinet. La tabla mensual quedó idéntica (0 diferencias en `D18:K54`) y el ranking de clientes sólo cambió por los datos, que ahora siguen a Maxinet (por ejemplo, el folio 1343 pasó de LP a CP). La conexión entre ambos libros ya estaba autorizada. El sync de `maxinet_sync.py` sólo estira el gráfico de esa pestaña y no toca sus fórmulas.
- Se borró la pestaña oculta `DATA (anterior)` (la `DATA` previa, ya sin sus IMPORTRANGE); la copia queda con las mismas 6 pestañas y el mismo orden que el original. El respaldo de las fórmulas anteriores de `DATA` y de `SINIESTROS` quedó en archivos locales fuera del repositorio.
- El log avisa en cada corrida del folio 1503 (Maxinet trae la fecha `6/2/0026`); es esperado mientras Maxinet no la corrija, y la hoja conserva `6/2/2026`.
