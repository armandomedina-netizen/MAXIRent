# ADR 0025: Órdenes de mantenimiento por ingreso a taller, actualizadas por Id en un archivo propio

Fecha: 2026-11-03

## Contexto

Se pidió una base de datos de las órdenes de mantenimiento LP en un archivo de Google Sheets propio (distinto de la Base LP copia), con las 59 columnas del reporte `lp-mtto-ordenes.php` de Maxinet (todas menos los tres botones, incluidos los datos de contacto), filtrada por **Fecha Ingreso Taller**, del 1 de enero al día de la consulta. El archivo ya trae esos datos hasta el 3 de noviembre, así que la corrida diaria no debe recargarlos: sólo revisar si cambió el estado de alguna orden y agregar las que ingresaron a taller desde la última vez. Horario: una vez al día, alrededor de las 8:45.

Ya existe `maxinet-mtto-ordenes` (ADR 0017), que lee el mismo reporte, pero con otro propósito: reescribe una pestaña de la Base LP copia con el mes corriente y las órdenes abiertas, sin datos de contacto, y las cerradas de meses anteriores salen de ella. No sirve de base de datos del año, así que esta automatización es aparte y no la modifica.

## Hallazgos de Maxinet (2026-11-03)

- `POST json/lp-mtto-ordenes.php` con `Criterio=INGRESO`, `Desde` y `Hasta` entrega las 62 celdas del reporte. Del 1 de enero a hoy son 6,187 órdenes (una sola consulta de unos 10 segundos), con Id únicos y todas con fecha de ingreso; la de hoy ya aparece.
- `Estatus` debe ir con valor, pero con `INGRESO` devuelve exactamente las mismas órdenes con `1` que con `0`.
- El filtro por ingreso deja fuera las órdenes que todavía no entran a taller (hoy, 92 de las 240 abiertas: citas por aprobar y órdenes en revisión). Entran a la hoja el día que ingresan.
- 41 celdas de fecha del año (Fecha Promesa, Fecha Cita, Fecha Prop.Cita, Fecha Entrega Cliente) traen años tecleados mal (0026, 2206, 3026...). Ver abajo cómo las guarda el archivo y cómo se igualan.

## Hallazgos del archivo real (2026-11-04)

La pestaña de órdenes tiene 6,178 órdenes y el encabezado idéntico; el archivo trae otra pestaña ajena, así que `WORKSHEET_MTTO_TALLER` es obligatorio. La primera comparación contra Maxinet marcó 2,577 filas como distintas (42%) y la salvaguarda de cambio masivo detuvo la corrida sin escribir. Casi todo era forma, no dato:

- **Texto**: el archivo guarda los textos de una línea (modelo, nombres, taller) con los espacios repetidos colapsados, y los de varias líneas (diagnóstico, comentarios) con salto `\n` en lugar del `\r\n` de Maxinet.
- **Teléfonos**: donde no hay teléfono Maxinet manda `0000000000` y Sheets lo guardó como el número 0.
- **Fechas con año de dos dígitos**: Sheets leyó `0026-07-15` como 2026-07-15; los demás años raros (2206, 3026, 0206) quedaron como fecha real con ese año, no como texto.
- **Costos dañados**: 21 celdas de costo y monto traían un número de serie en lugar del importe, porque Sheets leyó `2931.03` como marzo del año 2931 en la carga anterior (importes con centavos entre .01 y .12). Las 21 coinciden exactamente con esa lectura. La corrida las corrige.

Con esos criterios la comparación queda en movimiento real: 156 órdenes con cambios (121 con un día más de taller, 39 con otro estatus, cierres, diagnósticos y costos) y 39 nuevas.

## Decisión

Una automatización nueva, `automations/maxinet-mtto-taller`, con su propio workflow (`maxinet-mtto-taller.yml`) y sus propios secrets. En cada corrida:

1. Pide a Maxinet las órdenes con ingreso del 1 de enero del año a hoy (hora CDMX). La consulta es completa a propósito: es la única forma de enterarse de que una orden pasó a `CERRADO`, porque deja de aparecer en las abiertas.
2. Las compara por Id con la hoja. Cada celda se normaliza antes de comparar (fecha, hora, número o texto), de modo que una fecha guardada como texto, un teléfono guardado como número, espacios o saltos de línea repetidos, `0000000000` contra `0` o un error de coma flotante en una hora no cuentan como cambio.
3. Escribe sólo lo que cambió: actualiza en su lugar las filas distintas (columnas `A:BG` de esa fila, conservando tal cual las celdas que no cambiaron) y agrega al final las órdenes nuevas, ordenadas por Id. Todo con `RAW` y valores tipados (fechas y horas como número de serie, costos y días como número, el resto como texto en la forma que ya usa el archivo), para que Sheets no reinterprete placas, folios ni importes. Como una celda vacía no tiene formato y un número de serie se vería como `46330`, las fechas y horas de las órdenes nuevas, y las que una orden que ya estaba recibe por primera vez (al cerrarse, por ejemplo), llevan el formato que el archivo ya usa (`yyyy-mm-dd` y `h:mm`); costos, días y teléfonos van sin formato, como están.
4. No borra ni reordena filas. Una orden que Maxinet deje de mostrar conserva su última versión; el log sólo cuenta cuántas son.

**Ventana.** Empieza el 1 de enero, o antes si la hoja tiene alguna orden sin cerrar con ingreso anterior. Sin esa regla, al cambiar de año las órdenes que quedaron abiertas en diciembre se quedarían con el estatus viejo para siempre.

**Filas ajenas.** Una fila sin Id numérico (un total al pie, por ejemplo) no es una orden y cuenta como ocupada: las altas se agregan después de ella. Las columnas a la derecha de `BG` no se tocan, salvo `BI1:BI4`, donde queda la hora de la última corrida y la ventana, y sólo si esas celdas están vacías o ya son de esta automatización. La automatización no agrega columnas: el archivo real tiene exactamente las 59 columnas de datos, y la primera corrida real (2026-11-04) escribió los datos pero falló al intentar dejar esa hora, porque la API rechaza escribir fuera de la cuadrícula. Si la pestaña no tiene columnas libres a la derecha, ahora se omite la hora con un aviso en el log y la corrida sigue y valida; para verla, basta agregar columnas a la pestaña.

**Salvaguardas** (`FORZAR=1` omite las de volumen; las de estructura siempre aplican). La corrida se detiene sin escribir si:

- el reporte cambia de ancho o sus columnas no cuadran (Id, Fecha Alta, Fecha Ingreso Taller, placa);
- la hoja tiene otro encabezado (alguien movió o renombró columnas) o repite un Id: actualizar por Id sin saber cuál fila es la buena podría pisar la equivocada;
- Maxinet no trae ninguna orden, o le faltan más del 20% de las órdenes con ingreso en el rango que ya estaban en la hoja (con 30 o más): probable respuesta incompleta;
- más del 30% de las filas de la hoja saldrían cambiadas (con 200 o más): casi seguro es un cambio de formato en la hoja o en el reporte, no movimiento real;
- la columna Id de la hoja cambió entre la lectura y la escritura (alguien ordenó o insertó filas). Como se escribe por número de fila, no se arriesga a pisar otra orden; basta relanzar.

Después de escribir se vuelve a leer la columna Id y la corrida falla si alguna fila no quedó en su lugar o si hay Ids repetidos. `DRY_RUN=1` (en el workflow, la casilla `dry_run`) descarga y compara sin escribir. Los logs sólo llevan conteos y nombres de columnas: la tabla trae nombres, teléfonos y correos de clientes y no se registran.

**Pestaña y archivo.** El ID del archivo va en el secret `SPREADSHEET_ID_MTTO_TALLER`. La pestaña es `WORKSHEET_MTTO_TALLER` (nombre o gid, opcional si el archivo tiene una sola). La automatización nunca crea pestañas: si falta, falla. La cuenta de servicio debe ser editora del archivo.

**Horario.** Una vez al día. El reloj de GitHub queda a las 8:45 como respaldo, y la hora puntual la da una ventana del Vigilante (pendiente de agregar). Como el resumen matutino del Vigilante sale a las 8:45, conviene que la ventana sea unos minutos antes (8:40), para que el resumen ya la incluya como exitosa.

## Consecuencias

- Los datos de contacto de los clientes quedan en ese archivo por petición expresa; el repositorio sigue sin ningún dato: sólo nombres de secrets.
- Las 92 órdenes que aún no ingresan a taller no están en la hoja, y una orden cuyo ingreso se borre o se corrija a otro año queda con su última versión.
- La consulta es siempre completa (el año entero, ~6,200 órdenes y creciendo); a cambio la escritura es mínima. Si algún día la consulta se vuelve lenta, se puede acotar a las órdenes sin cerrar más una ventana de cierres recientes, con el riesgo de perder un cierre antiguo.
- La guardia de actualización (ADR 0015) todavía no cubre este archivo; agregarla es un cambio aparte.
