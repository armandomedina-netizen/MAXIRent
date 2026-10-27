# ADR 0015: La Gestoría automatizada deja de depender del original y documenta de dónde sale cada dato

- Estado: aceptada; el denominador del índice y los repuntes que tocan archivos de Nuvia esperan decisión (ver Pendiente)
- Fecha: 2026-10-27

## Contexto

El 22 de octubre Nuvia renombró su archivo `GESTORIA CP&LP` a "GESTORIA CP&LP ELIMINAR" y lo dejó con tres pestañas (ÍNDICE SINIESTRALIDAD, BDATOS y `respaldo`). Entre el 22 y el 23 de octubre también desaparecieron de nuestra copia las pestañas GESTORIA, RESUMEN y `2026`. Consecuencias que se encontraron al revisar los 21 libros que ve la cuenta de servicio:

- El sync registraba un `ERROR` cada hora ("No se pudieron mantener las fórmulas de la pestaña histórico") porque buscaba `2026`. El workflow terminaba en verde y nadie lo veía.
- Solo tres fórmulas leían el original y las tres daban `#REF!` ("Cannot find range or sheet for imported range"): `LP - TABLERO!SINIESTROS!D18` y `A19` (leían `RESUMEN!I1:P37` y `R1:S47`) y `RADIOGRAFIA CLIENTES!'REPORTE DE TICKETS / GESTORIA'!A1` (leía `'2026'!A:H`).
- Los efectos eran silenciosos: en `SINIESTROS` la calificación de las 34 filas salía "Sobresaliente" (la columna del índice quedaba vacía y vacío es menor que 1%), el gráfico quedaba sin datos, y en `RADIOGRAFIA CLIENTES` el bloque de tickets (86 fórmulas) quedaba vacío porque las envolturas `IFERROR` escondían el error.
- Nuestra cadena (Maxinet, sync, `GESTORIA CP - LP`, BDATOS, ÍNDICE, TABLERO LP) no tiene ninguna referencia al original, así que borrarlo no rompe nada de lo nuestro.
- Nada dentro del libro decía de dónde salía cada dato, cuándo se sincronizó por última vez ni qué era manual.

## Decisión

### 1. Retirar el paso de la pestaña `2026` del sync

Se eliminan `mantener_formulas_historico`, `conectar_hoja_historico` y la variable `WORKSHEET_HISTORICO_NAME`. La pestaña `2026` original era una columna de derrame con fórmulas `XLOOKUP` por fila que había que arrastrar a mano; no se recrea con ese diseño.

### 2. Pestaña `2026` nueva, de una sola fórmula, para `RADIOGRAFIA CLIENTES`

`RADIOGRAFIA CLIENTES` (libro de Nuvia, editado por Luis Hernández el 22 de octubre; enlazado desde el menú de LP - TABLERO) solo usa de esa pestaña la columna B (fecha), la C (tipo) y la E (cliente); la J (agrupación) y la I (mes) las calcula ella. La nueva `2026` de nuestra copia es una única fórmula de derrame en `A2` sobre BDATOS con las mismas ocho columnas (Folio, Fecha del Evento, Tipo, Placa, Cliente, Sucursal, Site, BSite), solo Largo Plazo y solo 2026, ordenada por fecha. Con eso quien mantiene `RADIOGRAFIA CLIENTES` solo tiene que cambiar el archivo en `A1` de su pestaña oculta `REPORTE DE TICKETS / GESTORIA`; el rango `'2026'!A:H` queda igual. No se tocó su libro.

El alcance (LP y 2026) se eligió porque su tablero tiene 17 filas de meses y las columnas auxiliares llegan a la fila 1000: la `2026` anterior de nuestra copia (CP y LP de 2025 y 2026, unas 1,370 filas y 22 meses) desbordaba ese espacio.

### 3. Pestañas de apoyo y sello de la última corrida

Se agregan al libro de Gestoría (el sync las llena; si faltan, las omite con un aviso):

- **FUENTES:** sello de la última sincronización (hora, tickets en Maxinet, folios en la hoja, resultado de la corrida, alertas y nombres por revisar), cuatro comprobaciones por fórmula (estructura de BDATOS, conexión con TABLERO LP, conexión con TABLERO CP y sucursales faltantes) y la tabla de procedencia: de dónde sale cada bloque, cómo se actualiza y qué sigue siendo manual, más las reglas de conteo.
- **ALERTAS DE DATOS:** datos dudosos del reporte de Maxinet, recalculados en cada corrida: año de dos dígitos, año fuera de rango, evento posterior a la creación del ticket, evento más de dos años anterior a su creación, sucursal vacía desde el folio 1500 y posibles duplicados de tipos que cuentan en el índice (misma placa, reserva, fecha y tipo capturados con menos de diez minutos de diferencia). No corrige nada: quien captura corrige en Maxinet.
- **REVISAR NOMBRES:** ver el punto siguiente.

El código vive en `hojas_apoyo.py` y `anomalias.py`, con pruebas (`automations/automatización Gestoría/tests`, ya en el workflow `Pruebas`).

### 4. Automatizar la lista manual `NO SON CLIENTES`

Ningún atributo de Maxinet separa las cuentas internas (traslados, talleres, uso interno...) de los clientes: el giro no sirve (las dos clases comparten el mismo giro en la mayoría de los tickets), y árboles de decisión validados por cliente dieron decenas de falsos positivos. Lo único que las distingue es el nombre. Se adoptó:

- Una celda de patrón (`ÍNDICE SINIESTRALIDAD!B2`, con rótulo en `B1` y protección suave) con prefijos y sufijos de cuentas internas. `BDATOS!B2` marca NO cliente si el nombre está en la lista **o** lo cubre el patrón, salvo que una persona lo haya confirmado como CLIENTE en `REVISAR NOMBRES`. La fórmula tolera un patrón vacío o inválido (el patrón deja de aplicar en lugar de marcar todo como NO).
- El sync lee el patrón de esa misma celda y llena `REVISAR NOMBRES` con los nombres sin confirmar que (a) parecen una cuenta interna y todavía cuentan como cliente, o (b) cubre solo el patrón (para que un cliente real con un nombre parecido no salga del índice en silencio). Una persona marca ESTADO = INTERNA (el nombre se agrega solo a la lista, nunca se borra nada) o CLIENTE.
- En la primera corrida los nombres que ya existían se siembran como CLIENTE ("línea base") para no inundar la pestaña.
- Se quitaron dos nombres repetidos de la lista.

Verificado antes de aplicar: la fórmula nueva da exactamente la misma clasificación que la anterior sobre los 1,651 folios (182 NO, 1,469 SI, 0 diferencias) y el ÍNDICE no cambió; con un patrón de prueba que cubría a un cliente real subió a 248 NO y volvió a 182 al marcarlo CLIENTE. Limitaciones: el patrón no elimina del todo lo manual (confirmar nombres nuevos), y si Maxinet agrega un campo de tipo de cliente al reporte esta pieza se retira.

### 5. TABLERO LP: correcciones de fuentes que no cambian cifras correctas

- `RESUMEN AFECTACIONES!F6:F17` sumaba por igualdad exacta el mes de la fuente, y dos filas de la fuente dicen "Mayo " con un espacio final: mayo salía en $711,456 y es $1,081,963 (faltaban $370,507). Ahora es `SUMIFS(...,E6&"*")`; los demás meses no cambian.
- 216 fórmulas de `FLOTA POR GRUPO` y 2 de `REPORTE DE FLOTA` (SL10 y SL12) leían pestañas que ya no existen (`BD PLACAS`, `LISTA VEHICULOS FOTO`) y valían 0. Se demostró que 0 es el valor correcto (la suma de los grupos coincide con el total de `REPORTE DE FLOTA` en los 86 días afectados) y se pasaron a valor.
- Pestaña temporal `_AUTORIZAR` con una prueba de `IMPORTRANGE` hacia nuestro TABLERO CP: sirve para autorizar la conexión una vez y después repuntar `TABLAS!BR2` (que hoy lee `CP - TABLERO` de Nuvia, con valores idénticos a los de nuestro TABLERO CP) sin dejar en blanco el índice CP del dashboard mientras tanto. Se borra al terminar.

Los respaldos de lo reemplazado están en `private/backups` (fuera del repositorio).

## Pendiente

1. **Denominador del índice (decisión de Armando y Nuvia).** Hoy `TABLAS!BI` (LP) y `DETALLE!FS` (CP) toman el valor del **último día** del mes y el encabezado dice AVG. El histórico de Nuvia (`respaldo`, `TABLAS!BD:BF`, la tabla CP `DETALLE!GP:GR` y `OPERACIONES`) usa el **promedio diario**: coincide en 17 de 17 meses en CP y 30 de 33 en LP. Cambia el índice hasta 0.14 puntos en LP y 0.69 en CP (hasta 18.8% relativo); el dashboard `GESTORÍA` ya mezcla ambas definiciones (LP con último día y CP con promedio). Propuesta: promedio mensual en los dos; en CP basta repuntar `ÍNDICE SINIESTRALIDAD!I3` de `DETALLE!FQ:FS` a `DETALLE!GP3:GR200` (ya existe, es dinámica y tiene los mismos valores), y en LP cambiar `TABLAS!BI3:BI50`.
2. **Permiso de la copia.** El libro de Gestoría es legible por "cualquiera con el enlace" y contiene nombre, edad y estado civil de conductores; debe restringirse al dominio (lo cambia el dueño).
3. **Archivos de Nuvia, que solo ella o Luis cambian:** repuntar `RADIOGRAFIA CLIENTES!'REPORTE DE TICKETS / GESTORIA'!A1` a nuestra pestaña `2026`; decidir qué hacer con `LP - TABLERO!SINIESTROS` (la reemplazó el dashboard `GESTORÍA` de TABLERO LP; no tenía CORRALÓN evitado ni su índice, que hoy nadie calcula); confirmar que nadie más lee el original antes de borrarlo. `RADIOGRAFIA CLIENTES` también tiene `CLIENTES ACTIVOS (ESTADOS)` roto (`BASE LP` ya no tiene `UBICACIONES`) y ONHIRE con corte del 21 de octubre.
4. **Datos de Maxinet por corregir** (las alertas los señalan): fechas de los folios 1108, 1662, 1683 y 1503; posible duplicado 1646/1647; el 1108 y el 1683 mueven el índice si se confirman.
5. **Dashboard `GESTORÍA` de TABLERO LP:** los comparativos contra 2025 comparan un octubre parcial con un octubre completo; el comparativo CP promedia meses sin captura real (CP solo existe desde julio de 2025); `Z2` y las fórmulas del ÍNDICE esconden errores con `IFERROR`; y el ranking mezcla años en una columna. Cada corrección cambia cifras visibles y se aplicará después de acordar el criterio.
6. **Lo manual que sigue sin fuente:** `AFECTACIONES` (captura de otro libro), los archivos externos de PROXIMOS RETORNOS, PROXIMAS ENTREGAS, PAGOS CXC, TRASLADOS y Descuentos NC (la cuenta de servicio no los ve), `OPERACIONES!A3` (falta ubicar el reporte de mantenimiento de Maxinet) y la serie huérfana `SIN LOCSA` de `TABLAS!E`.

## Cómo revertir

Los respaldos están en `private/backups` (`gestoria_copia_antes_apoyo_*`, `tablero_lp_fuentes_antes_*`). Para volver a la clasificación anterior basta restaurar la fórmula original de `BDATOS!B2` (`=ARRAYFORMULA(IF(R2:R="","",IF(ISNUMBER(MATCH(TRIM(R2:R),TRIM('ÍNDICE SINIESTRALIDAD'!A:A),0)),"NO","SI")))`). Las pestañas de apoyo se pueden borrar sin efecto en el resto del libro; el sync las omite si no existen.
