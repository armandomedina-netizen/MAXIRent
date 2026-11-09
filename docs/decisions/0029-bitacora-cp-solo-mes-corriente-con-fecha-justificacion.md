# ADR 0029: Bitácora CP con sólo el mes en curso y la columna Fecha Justificación

- Estado: aceptada (sustituye en parte al ADR 0020)
- Fecha: 2026-11-09

## Contexto

Maxinet agregó una columna al final del reporte de bitácora de entregas y recolecciones, **Fecha Justificación**. Además, Operaciones pidió que la hoja contenga únicamente el mes en curso (el 9 de noviembre, del 1 al 9) y que se eliminen los meses anteriores. Para desarrollar el cambio sin tocar la pestaña `BITACORA CP`, se creó en el Tablero CP copia la pestaña `BITACORA CP Mes Corriente`.

El detonante de los cambios de información es la columna AI, **Justificación retraso**: cuando un servicio con retraso recibe una justificación, cambian los datos que la acompañan.

## Hallazgos (medidos en datos reales)

- La respuesta del endpoint pasó de 38 a **39 columnas** (una de acción en HTML y 38 de datos). La última es Fecha Justificación, con forma `AAAA-MM-DD HH:MM:SS`.
- Un servicio con valor en AI aparece con: Semáforo en verde, **Estatus Serv. (columna I) en "EN TIEMPO"** y con Motivo retraso, Responsable justificación y Fecha Justificación llenos. La columna K "Estatus" (estado de la reserva: CHECKED IN, RETURNED, ON HIRE…) **no cambia** con la justificación. Maxinet aplica estos cambios; la automatización sólo los copia y los valida.
- Una justificación puede capturarse días después (por ejemplo el 5 de noviembre para un servicio de octubre), así que el mes completo se reescribe en cada corrida.
- Desde/Hasta filtran por Fecha Prom.

## Decisión

- **Rango:** del día 1 del mes en curso a **hoy** (hora CDMX). `FECHA_DESDE` y `FECHA_HASTA` lo sustituyen para pruebas.
- **Reemplazo del mes:** cada corrida reescribe desde la fila 2 las columnas de datos `A:AL` (38) ordenadas por (Fecha Prom., Hora Prom., Reserva, Tipo Serv.) y limpia lo que sobre debajo; así desaparecen los meses anteriores el primer día del mes sin ningún paso aparte. Las fórmulas auxiliares `AM:AP` (AÑO, MES, Asesor móvil, PERIODO) se escriben para las filas nuevas y nunca se borran. Este punto sustituye a la regla del ADR 0020 de acumular los meses y de refrescar el mes anterior los primeros 3 días.
- **Encabezados:** deben coincidir las 42 columnas (38 de Maxinet + 4 auxiliares); un texto adicional a la derecha de la fila 1 se ignora.
- **Fecha Justificación** se guarda como fecha y hora con formato `yyyy-mm-dd h:mm:ss`.
- **Validación de justificaciones (AI):** después de la descarga se revisa cada servicio justificado: Estatus Serv. en "EN TIEMPO", semáforo en verde y Motivo, Responsable y Fecha Justificación llenos (y, a la inversa, que no haya datos de justificación sin valor en AI); lo que no cuadre se registra como advertencia con conteos, sin detener la corrida (el origen es Maxinet).
- **Salvaguardas:** si Maxinet trae menos del 80% de las filas del mes actual en la pestaña (con 30 o más), o responde vacío cuando ya hay filas del mes, la corrida se detiene sin escribir (`FORZAR=1` la omite). Los datos se escriben en `RAW` en tandas de 800 filas; sólo las fórmulas auxiliares van como `USER_ENTERED`.
- **Privacidad:** igual que el ADR 0020, los logs sólo llevan conteos y fechas.
- **Pestaña:** `WORKSHEET_BITACORA_NAME` acepta nombre o gid; si no existe el secret, se usa `BITACORA CP Mes Corriente`. La pestaña `BITACORA CP` anterior deja de actualizarse.
- **Guardia de actualización:** como Hasta es hoy, la corrida en seco vería filas nuevas todos los días. La guardia compara hasta **ayer** dentro del mismo mes (el día 1, ese mismo día) y fija `FORZAR=1` para que la regla del 80% no dé falsas alarmas al inicio del mes. `BITACORA CP Mes Corriente` es ahora pestaña crítica y `BITACORA CP` sólo opcional.

## Consecuencias

- A las 8:30 el reporte de hoy es parcial: el día en curso trae sólo lo que ya existe. Si Operaciones necesita el día actualizado más tarde se puede agregar otra ventana en el Vigilante.
- Las gráficas o fórmulas que dependan de meses anteriores en esta pestaña dejan de tenerlos; el historial queda en `BITACORA CP`.
