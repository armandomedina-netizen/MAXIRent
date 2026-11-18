# 0031 - 2das y 3ras rentas en la Base CP

Fecha: 2026-11-18

## Contexto

Maxinet tiene el reporte **2da - 3ra renta** de Corto Plazo (`cp-reporte-2-3-rentas.php`). El tablero de 2das y 3ras
rentas 2026 se alimenta hoy con un CSV que se sube a mano (los meses de 2026 más el reporte de Maxinet de noviembre),
y se pidió automatizar la carga del reporte con las mismas reglas de las demás automatizaciones: mes corriente,
actualización diaria y ventana de las 8:30.

## Decisión

- **Fuente:** `POST includes/reportescp/clientes-2-3-data-v2.php` (el que usa la tabla de la página) con `Desde`, `Hasta`,
  `f_registro=0` y `tiporenta=0` (Ambas). Entrega las 18 columnas con el mismo nombre y orden que la tabla y una fila por
  evento: un cliente con su 2da y su 3ra renta en el mismo mes sale dos veces (No.Evento 2 y 3).
- **Qué filtra `Desde`/`Hasta`:** la fecha del evento, es decir la Fecha 2da renta en las filas de evento 2 y la Fecha 3ra
  renta en las de evento 3. Con `tiporenta=0` el resultado es exactamente la unión de `2` y `3`, y coincide con el total
  que muestra la página.
- **Filtro de clientes registrados:** se deja sin filtro (`f_registro=0`), como se pidió; se revisará cuando se defina
  el criterio con el tablero.
- **Destino:** pestaña `2DAS Y 3RAS RENTAS` del libro Base CP (el de `SPREADSHEET_ID_CLIENTES_NUEVOS`). Si no existe, la
  automatización la crea con los 18 encabezados; los siguientes encabezados se verifican en cada corrida.
- **Mes corriente:** de la misma forma que MKT Leads, se reemplaza el bloque del mes (del primer día a ayer, hora CDMX) y
  el mes anterior los primeros 3 días. El bloque se ubica por la **fecha del evento** (2da o 3ra según el No.Evento) y
  queda ordenado por (fecha del evento, No.Evento, No. Cliente). Los meses cerrados no se tocan.
- **Tipos:** fechas como fecha real (`yyyy-mm-dd`), No.Rentas y No.Evento como números, teléfonos como número si son sólo
  dígitos, el resto como texto; todo en modo RAW.
- **Salvaguardas:** ancho distinto de 18 columnas, No.Evento distinto de 2 y 3, fechas con otra forma, encabezados distintos,
  hoja desordenada o menos del 80% de las filas actuales del bloque detienen la corrida sin escribir (`FORZAR=1` sólo omite la
  última). Los logs sólo llevan conteos y fechas: nunca nombres, correos ni teléfonos.
- **Horario:** 8:30 (reloj de GitHub `30 14 * * *`); la ventana del Vigilante queda pendiente de agregar.

## Consecuencias

- Una carga inicial histórica (por ejemplo del 1 de enero) se puede hacer con `FECHA_DESDE`/`FECHA_HASTA`; la corrida
  diaria sólo mantiene el mes en curso.
- Si se define un filtro de antigüedad del cliente (`f_registro`), cambia una sola constante del módulo.
- La Guardia de actualización todavía no revisa esta pestaña.
