# 0032 - Clientes en abandono en el Tablero CP

Fecha: 2026-11-18

## Contexto

La pestaña `Clientes en abandono` del Tablero CP se llena con el reporte **Clientes - No. Rentas** de Corto Plazo
(`cp-reporte-clientes-norentas.php`). Se pidió automatizar su carga como las demás: mes corriente y todos los campos
que muestra la hoja, para poder relacionarla fácilmente con el resto del Tablero.

## Decisión

- **Fuente:** `POST includes/reportescp/clientes-norentas-data.php` (el que usa la tabla de la página) con `Desde` y
  `Hasta`. Devuelve las 18 columnas con el mismo nombre y orden que la tabla; `No.Rentas` y `Dias sin rentar` llegan como
  número y el resto como texto. Con las fechas por defecto de la página el total coincide con el que muestra la página.
- **Qué filtra `Desde`/`Hasta`:** la Fecha registro del cliente (Hasta inclusive).
- **Mes corriente:** del primer día del mes **al día de la consulta** (hora CDMX), como se pidió; los primeros 3 días del
  mes se refresca además el mes anterior completo. Se reemplaza el bloque desde la primera fila con Fecha registro dentro
  del rango y las filas anteriores no se tocan. Como los días sin rentar y la última renta cambian cada día, el mes se
  reescribe completo en cada corrida. Orden por (Fecha registro, No. Cliente).
- **Número de rentas:** por defecto sin filtro (todas, como la página sin casillas marcadas). `NO_RENTAS` (por ejemplo
  `1,2`; 4 = "4 o más") lo manda como `NoRentas[]` si más adelante se quiere acotar. Los demás filtros comentados de la
  página (sin rentar desde) no se usan.
- **Destino:** pestaña `Clientes en abandono` del Tablero CP copia (`SPREADSHEET_ID_TABLERO_CP`); ya existía con los 18
  encabezados. Se recomienda poner su gid en el secret `WORKSHEET_CLIENTES_ABANDONO_NAME` para que un cambio de nombre no la
  rompa. Si no existe, se crea con el formato de `BITACORA CP`.
- **Tipos:** fechas como fecha real (`yyyy-mm-dd`), No.Rentas y Dias sin rentar como números, teléfonos como número si son
  sólo dígitos, el resto como texto (`Sin rentar desde` es un rango en texto: "-30 DIAS", "30+ DIAS"); todo en modo RAW.
- **Salvaguardas:** ancho distinto de 18 columnas, fechas o números con otra forma, cliente sin Fecha registro,
  encabezados distintos, hoja desordenada o menos del 80% de las filas actuales del bloque detienen la corrida sin escribir
  (`FORZAR=1` sólo omite la última). Los logs sólo llevan conteos y fechas: nunca nombres, correos ni teléfonos.
- **Horario:** 8:35 (reloj de GitHub `35 14 * * *`), cinco minutos después de 2das y 3ras rentas para no juntar lecturas
  de Sheets; la ventana del Vigilante queda pendiente de agregar.

## Consecuencias

- Un cliente que se registra en un mes y se "abandona" después sólo se actualiza mientras su mes esté en curso (y los
  primeros 3 días del siguiente); los meses cerrados conservan los días sin rentar de su último cierre. Para recalcular un
  mes anterior se usa `FECHA_DESDE`/`FECHA_HASTA`.
- La Guardia de actualización revisa esta pestaña desde el 2026-11-26 (corre su DRY_RUN a las 10:30, relanza el workflow si el bloque del mes tendría clientes de más y vigila errores de celda).
