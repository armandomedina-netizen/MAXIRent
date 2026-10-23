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
- **Sin depender de la hora:** el cierre es idempotente y no importa a qué hora corra. El Vigilante (Apps Script, fuera del repositorio) lo dispara a las 8:25, después del sync que cambia la fecha de `FLOTA CP`; el cron del workflow, cada hora al :27, es el seguro aunque GitHub lo retrase.
- **Protecciones:** no guarda una foto con valores no numéricos o en cero; no congela una columna sin foto (avisa y termina con código 1, pero sí crea la columna del día para que los datos nuevos se vean); no toca una columna del día que ya esté congelada; reintenta con espera ante 429 y errores 5xx, porque la cuota de lecturas por minuto se comparte con las demás automatizaciones.
- **Registro:** sólo fechas, nombres de pestañas y conteos; ningún dato de clientes.

## Verificación

- 19 pruebas automáticas con hojas simuladas (`automations/tablero-cp-cierre-diario/tests`, en el workflow `Pruebas`): día nuevo, corrida repetida, falta de foto o foto incompleta, fecha ausente, columna del día congelada, orden de las solicitudes a Sheets, no guardar fotos en cero y los reintentos.
- Contra el Tablero real, el 2026-10-23: corrida real (creó `_CIERRE_DIARIO` y guardó las fotos del 22 de octubre: 32, 93 y 18 filas, las mismas que se congelaron a mano), segunda corrida sin duplicados y simulación en seco de los datos del 23 de octubre (`FECHA_DATOS` con `DRY_RUN`), que crea la columna `YL`/`QN`/`YL` y congela la del 22 con su foto.

## Consecuencias

- La pestaña oculta `_CIERRE_DIARIO` no existe en el archivo de Nuvia; es la única diferencia de estructura y no la ve nadie que no la muestre.
- Los encabezados de fecha (fila 2) y la tabla de fechas de `DETALLE` se siguen extendiendo a mano cada mes. Si falta la fecha del día, el script lo avisa (código 1) y no escribe en esa pestaña.
- Si `FLOTA CP` salta un día (un sync que no corre), la columna de ese día queda vacía; el script congela la última viva y deja vivo el día nuevo, sin inventar datos.
- Los datos que `FLOTA CP` toma de la Base LP copia se actualizan por la mañana (8:00 y 8:10). Mientras el Vigilante no tenga el disparo de las 8:25, el cierre ocurre con el cron del workflow, que puede llegar varias horas tarde, y la columna del día nuevo aparecerá después.

## Cómo revertir

Desactivar el workflow en GitHub. La pestaña `_CIERRE_DIARIO` se puede borrar sin efecto en el resto del libro; las columnas ya cerradas son valores y no se pierden.
