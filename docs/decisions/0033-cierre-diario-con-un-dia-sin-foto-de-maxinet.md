# ADR 0033: Cierre diario del Tablero CP con un día sin foto en Maxinet

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

El domingo 22-nov-2026 el servidor de Maxinet rechazó conexiones (`Connection refused` en el login): está confirmado de las 4:59 a las 8:24 CDMX y a las 12:23 ya respondía (hubo fallos desde la 1:28, sin confirmar la causa). El jueves 19-nov por la noche hubo un corte más corto (de las 21:20 a las 21:45, aproximadamente). Todas las automatizaciones entran por el mismo servidor, así que el domingo fallaron 22 workflows (71 corridas fallidas ese día: cada ventana del Vigilante lo intentó 3 veces, con 5 minutos de por medio, y se rindió; el siguiente éxito llegó por el reloj de GitHub, a las 12:23 el de Query Sync y a las 14:41 el de Maxinet Sync). Los datos que dependen de la fecha se recuperaron solos, salvo uno: **Maxinet no generó la foto de flota del sábado 21-nov** (el reporte con `Desde` = `Hasta` = 2026-11-21 devuelve 0 filas; los días 19, 20, 22 y 23 sí tienen 1,704).

Esa foto faltante dejó en rojo, del 22 al 24-nov, el **cierre diario del Tablero CP** (35 corridas fallidas en 10 días y, en consecuencia, la Guardia de actualización): para cerrar el 20-nov y rellenar los días vacíos, el cierre reconstruye cada día desde el reporte de Maxinet; la reconstrucción de cada día estaba fuera del `try`, así que una excepción en el 21 (`El reporte de flota trae [] columnas y se esperaban 42`) abortaba las tres pestañas (`UNIDADES CP`/`REPORTE FLOTA CP`, `UTILIZACION TODOS LOS GRUPO` y `UTILIZACION POR GRUPO`) sin escribir nada, ni lo que sí se podía. Resultado visible: la columna viva del 20-nov quedó con fórmulas sobre una `FLOTA CP` que ya traía otro día (ceros) y las del 21, 22 y 23 sin cerrar.

Es el mismo hecho del 29-oct (la foto no se generó): entonces Sistemas la regeneró al día siguiente. Esta vez no hay quien la regenere de inmediato, y el cierre no debe depender de eso.

## Decisión

- **Una foto que Maxinet no tiene es un hueco, no un error.** `descargar_flota` distingue la respuesta vacía (`FotoNoDisponible`, subclase de `RuntimeError`) de un cambio de ancho. En `_recuperar_huecos` cada día se reconstruye por separado: el que no tiene foto se omite con la línea `SIN FOTO DE MAXINET: <fechas>` y los demás se rellenan, se congela la columna viva y se crea la del día. La pestaña no queda con error por eso. Si el día de comprobación (el último conocido) no tiene foto, sigue siendo un pendiente real: no hay con qué validar la reconstrucción.
- **El hueco omitido se sigue buscando.** `planear` ya no sólo cuenta los días vacíos posteriores a la última columna llena: también los que quedaron entre columnas llenas de los últimos 14 días (`VENTANA_HUECOS_DIAS`). Así, en cuanto Maxinet regenere la foto del 21-nov, el siguiente cierre la rellena sin intervención. Pasados 14 días el hueco deja de perseguirse (queda como historia, vacío, sin ceros).
- **La Guardia de actualización lo avisa, una vez por revisión, no el cierre.** `leer_cierre` reconoce la marca `SIN FOTO DE MAXINET`; esos días no cuentan como acciones de cierre (relanzar no los arregla, así que ya no relanza el cierre por ellos) pero dejan el punto `Cierre diario del Tablero` en `PENDIENTE` con el texto "pedir a Sistemas de Maxinet que la regeneren". El workflow del cierre queda en verde: antes cada una de sus corridas (cada hora, tras cada Maxinet Sync y las del Vigilante) fallaba con el mismo error y generaba un aviso por corrida.

## Verificación

- 95 pruebas del cierre (6 nuevas: un día sin foto no bloquea a los demás, sin ningún hueco con foto igual se congela y se crea la columna, el día de comprobación sin foto sigue siendo error, un hueco omitido sigue siéndolo con los días posteriores llenos, un hueco viejo ya no se persigue, respuesta vacía distinta de error de ancho) y 38 de la Guardia (3 nuevas); cada pieza se probó con mutación.
- Corrida en seco real (24-nov-2026, sin escribir) contra el Tablero CP y Maxinet: en las tres pestañas la reconstrucción del 20-nov coincide con lo conocido (32, 93 y 18 filas), se rellenaría el 22-nov, se avisa `SIN FOTO DE MAXINET: 2026-11-21` y el cierre termina con éxito (antes abortaba).

## Consecuencias

- Mientras Maxinet no regenere el 21-nov, las tres pestañas muestran ese día vacío (no cero) y la Guardia queda en `PENDIENTE` con la fecha. Hay que pedir a Sistemas de Maxinet que la regeneren; el siguiente cierre la llena sola.
- Las caídas del servidor de Maxinet siguen fuera de nuestro control. Qué se puede hacer para que una caída de horas no deje datos atrasados sin intervención (reintentos del Vigilante más allá de 3 intentos, aviso de caída y de recuperación, relanzado de lo pendiente cuando vuelve) queda como propuesta aparte: el Vigilante vive en Apps Script y no está versionado.
