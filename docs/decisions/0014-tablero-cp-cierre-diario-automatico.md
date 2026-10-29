# ADR 0014: Cierre diario automático de las columnas por día del Tablero CP

- Estado: aceptada (autorizada por Armando el 2026-10-23)
- Fecha: 2026-10-23

## Contexto

El ADR 0013 documenta que las columnas por día de `UNIDADES CP`, `UTILIZACION TODOS LOS GRUPO` y `UTILIZACION POR GRUPO` dependen de un cierre manual: la columna "viva" cuenta vehículos de `FLOTA CP` con la fecha de ese día, y cuando `FLOTA CP` avanza al día siguiente esa columna se vuelve cero y hay que congelarla y pasar las fórmulas a la columna nueva. En nuestra copia nadie lo hacía, y por eso el Tablero se desfasaba cada día.

## Decisión

Un script (`automations/tablero-cp-cierre-diario`) y un workflow (`tablero-cp-cierre-diario.yml`) hacen el cierre.

- **Fecha de los datos:** la que traen la mayoría de las filas de `FLOTA CP`. Si hay menos de 1,000 filas con esa fecha, los datos aún no cargaron y no se hace nada (termina con código 1).
- **Columna del día:** la de esa fecha en la fila 2 de cada pestaña. Si ya tiene las fórmulas vivas, no cambia nada.
- **Día nuevo:** se copian las fórmulas y el formato de la columna viva anterior a la columna del día, y la anterior se congela con los valores de su "foto de cierre". Las filas que se congelan son las que están como constante en la columna cerrada inmediata anterior, el mismo criterio con el que cierra Nuvia.
- **Foto de cierre:** cada corrida guarda los valores de la columna viva del día en la pestaña oculta `_CIERRE_DIARIO` del propio Tablero (una fila por fecha y pestaña, con un JSON fila-valor; se conservan 14 días). La última foto del día es la final. Se eligió esto porque, una vez que `FLOTA CP` cambia de fecha, la fórmula de la columna anterior ya devuelve ceros: congelar a partir de la fórmula, y no de la foto, escribiría ceros si la corrida llega tarde.
- **Sin depender de la hora:** el cierre es idempotente y no importa a qué hora corra. El Vigilante (Apps Script, fuera del repositorio) lo dispara a las 8:00 (hasta el 2026-10-29 era a las 8:25; ver la revisión de esa fecha); el cron del workflow, cada hora al :27, es el seguro aunque GitHub lo retrase.
- **Espera matutina (2026-10-29):** entre las 7:55 y las 9:30 (hora CDMX), si `FLOTA CP` todavía trae un día anterior a ayer, el cierre espera hasta 25 minutos (lee cada 30 segundos; `ESPERAR_DATOS_MIN` lo cambia o lo desactiva) a que el sync de las 8:00 la cargue, y cierra en cuanto cambia la fecha. Si se agota el tiempo termina con código 1 (el Vigilante reintenta y avisa). Con `DRY_RUN` o fuera de ese horario no espera.
- **Días sin columna:** si el cierre no corrió uno o más días (una caída, o un fin de semana antes de que existiera), el script reconstruye esos días en lugar de dejarlos vacíos. Maxinet devuelve el reporte de flota de cualquier fecha (el mismo endpoint del sync con `Desde` y `Hasta` iguales), y con él se arman las columnas de `FLOTA CP` de ese día: las crudas vienen del reporte, las derivadas por fila (`TODO LO DISPONIBLE`, `PRESTAMOS`, `BSITE CP`, `DISPONIBLES DE PRESTAMOS`) se calculan con las mismas reglas de las fórmulas de la hoja, y las que no cambian entre días (`GRUPO`, `STATUS DISPONIBLE`, `UNIDADES`, `3 grupos`) y la tabla lateral `AX:BA` se toman de la hoja de hoy. Con esas columnas se evalúan las fórmulas `COUNTIFS` y `SUM` de la columna viva (`recuperar_dias.py`) y se escriben como valores, con las mismas filas y el mismo formato que usa el cierre normal. No usa ningún archivo de Nuvia.
- **Comprobación antes de rellenar:** el script reconstruye con ese mismo código un día que ya se conoce (la foto de cierre de la última columna llena, o la columna viva del día) y exige que coincida exactamente en todas las filas. Si algo difiere, o una fórmula no es de un tipo soportado, no rellena nada y avisa (código 1). Las fórmulas con operadores, comodines u otras funciones se rechazan en lugar de aproximarse.
- **Pestañas por identificador (2026-10-27):** Nuvia empezó a ajustar nuestro Tablero y renombró `UNIDADES CP` como `REPORTE FLOTA CP` (y `DETALLE` como `GRAFICOS`), lo que hizo fallar el cierre, que buscaba la pestaña por nombre. Ahora el cierre guarda el identificador de cada pestaña que maneja (`UNIDADES CP`, las dos `UTILIZACION` y `FLOTA CP`) en la pestaña oculta `_CIERRE_DIARIO`, la primera vez que la encuentra por nombre, y después la busca sólo por identificador: un renombre no lo rompe. Si la pestaña se borra, falla con un mensaje claro. Los nombres "de siempre" se siguen usando en los registros y en las fotos.
- **Protecciones:** no guarda una foto con valores no numéricos o en cero; no congela una columna sin foto (avisa y termina con código 1, pero sí crea la columna del día para que los datos nuevos se vean); no toca una columna del día que ya esté congelada; reintenta con espera ante 429 y errores 5xx, porque la cuota de lecturas por minuto se comparte con las demás automatizaciones.
- **Registro:** sólo fechas, nombres de pestañas y conteos; ningún dato de clientes.

## Verificación

- 58 pruebas automáticas con hojas simuladas (`automations/tablero-cp-cierre-diario/tests`, en el workflow `Pruebas`): día nuevo, corrida repetida, falta de foto o foto incompleta, fecha ausente, columna del día congelada, orden de las solicitudes a Sheets, no guardar fotos en cero y los reintentos.
- Contra el Tablero real, el 2026-10-23: corrida real (creó `_CIERRE_DIARIO` y guardó las fotos del 22 de octubre: 32, 93 y 18 filas, las mismas que se congelaron a mano), segunda corrida sin duplicados y simulación en seco de los datos del 23 de octubre (`FECHA_DATOS` con `DRY_RUN`), que crea la columna `YL`/`QN`/`YL` y congela la del 22 con su foto.

## Consecuencias

- La pestaña oculta `_CIERRE_DIARIO` no existe en el archivo de Nuvia; es la única diferencia de estructura y no la ve nadie que no la muestre.
- Los encabezados de fecha (fila 2) y la tabla de fechas de `DETALLE` se siguen extendiendo a mano cada mes. Si falta la fecha del día, el script lo avisa (código 1) y no escribe en esa pestaña.
- Si faltan días, se reconstruyen desde Maxinet con la comprobación descrita arriba. Es una aproximación: usa la clasificación de hoy para las columnas que no cambian entre días (por placa) y la tabla lateral de hoy; la comprobación sobre un día conocido lo acota, pero un cambio de grupo o de sede de una placa entre el día perdido y hoy no se vería. Hasta 8 días hacia atrás.
- Los datos que `FLOTA CP` toma de la Base LP copia se actualizan por la mañana (8:00 y 8:10). Mientras el Vigilante no tenga el disparo de la mañana, el cierre ocurre con el cron del workflow, que puede llegar varias horas tarde, y la columna del día nuevo aparecerá después.
- **Revisión 2026-10-29:** con el disparo de las 8:25, entre que el sync terminaba (8:08) y el cierre corría (8:28) pasaron unos 20 minutos en los que la columna viva del día anterior (27-oct) contaba contra una hoja que ya traía el 28 y mostraba ceros en `UTILIZACION TODOS LOS GRUPO` y las otras dos pestañas, aunque `FLOTA CP` ya estaba actualizada. No se perdió ningún dato (la foto del 27 estaba guardada y el cierre de las 8:28 la congeló), pero cualquiera que abriera el Tablero en ese lapso veía el día en ceros. Con la espera matutina y el disparo de las 8:00 el hueco se reduce al tiempo que tarda `FLOTA CP` en reflejar el sync (segundos).
- **Disparo al terminar el sync (2026-10-29):** para no depender de la hora del Vigilante ni del reloj de GitHub, el workflow del cierre también se dispara con `workflow_run` cuando termina con éxito `Maxinet Sync` (las corridas de las 8:00 y de las 8:10; cada una dispara un cierre idempotente). El Vigilante y el cron de cada hora quedan como respaldo. La guardia sigue relanzando el cierre por `workflow_dispatch` y sólo cuenta sus propias corridas.

## Cómo revertir

Desactivar el workflow en GitHub. La pestaña `_CIERRE_DIARIO` se puede borrar sin efecto en el resto del libro; las columnas ya cerradas son valores y no se pierden.

### Recuperación del 23 y 24 de octubre

El cierre no corrió el fin de semana del 23 al 25 de octubre (el cambio seguía sin integrarse). El 26 de octubre se reconstruyeron los dos días con esta recuperación: contra Maxinet, la reconstrucción del 22 (foto de cierre) y del 25 (columna viva) coincidió en las 143 filas de las tres pestañas, sin diferencias; los totales del 23 y del 24 (399 y 382 unidades CP en renta) son los que reporta Maxinet para esas fechas.
