# ADR 0030: Proyector de Mantenimientos en la Base LP

- Estado: aceptada
- Fecha: 2026-11-10

## Contexto

Se pidió llevar a la Base LP copia ("BASE LP_AUTOMATIZADO"), a la pestaña `Proyección de Mantenimientos(DATA)`, toda la tabla del **Proyector de Mantenimientos** de Maxinet (`lp-mtto-proyector-mtto.php`): una fila por placa con su grupo, cliente, estatus de la orden de mantenimiento, kilometrajes, % de vencimiento y fechas del último y del próximo mantenimiento. Se actualiza **una vez al día, a las 8:00**, reemplazando lo que hay con todo lo que entrega Maxinet, porque un mantenimiento puede desaparecer del proyector y los tiempos de vencimiento cambian cada día.

La pestaña ya existía, armada por quien la pidió, junto a `Proyección de Mantenimientos` (la hoja de análisis con la historia diaria del % de vencimiento, fórmulas `UNIQUE` y `AVERAGEIFS`, que no se toca). Pero la fila 1 de `(DATA)` traía los **20 encabezados de otro reporte** (Flota Última Renta, ADR 0029) y no los de esta tabla: la lista de columnas del pedido era la de la automatización anterior. La tabla pegada en el pedido y la que carga Maxinet tienen **15 columnas**; esas son las que se escriben. El libro es el mismo que usa `maxinet-sync` (`SPREADSHEET_ID`); no se agrega ningún secret obligatorio.

## Hallazgos de Maxinet (2026-11-10)

- La página llena su `DataTable` con una consulta `GET includes/mttoLP/lp-mtto-proyeccionmtto-data.php` **sin parámetros** (los filtros de fecha de la página sólo alimentan la gráfica). Responde `{"dataReservas": [...]}` en unos 5 segundos y 180 KB.
- Cada fila trae **16 celdas**: las 15 columnas de la tabla y una última, **oculta** en la página (`visible: false`), que es un código numérico (`0`, `2` o `3`) con el que la página pinta de color `Fecha Prox. Mtto` (`2` rojo: el próximo mantenimiento ya venció; `3` gris: sin mantenimiento previo; `0` amarillo: vigente). Se deduce de las propias fechas, así que no se copia a la hoja.
- Hoy son 814 placas, sin repetidas, ordenadas por `FECHA RENTA`. `ESTATUS` está vacío en 794 y en las otras 20 viene como un **enlace HTML a la orden** (`<a href="lp-mtto-DetailOrden.php?Id=...">CITA APROBADA</a>`; los valores son `POR CITAR`, `CITA APROBADA` y `EN TALLER`). `Fecha Sig. Mtto` **mezcla** textos de semáforo (`MAYOR A 1 MES`, `VENCIDO`, `KMS EN 0`) con fechas cuando falta menos de un mes; el nombre del cliente y algunas placas traen espacios de relleno. En 38 unidades no hay mantenimiento previo y `Fecha Ult.Mtto` y `Fecha Prox. Mtto` vienen vacías. `ULTIMA UBICACION` es hoy `SIN ASIGNACION DE ESTADO` en todas. Los kilómetros y el % llegan como texto con dos decimales (`55194.00`); la página les pone el separador de miles al mostrarlos.

## Decisión

Una automatización nueva, `maxinet-mtto-proyector` (`automations/maxinet-mtto-proyector`, workflow `maxinet-mtto-proyector.yml`), con el patrón de `maxinet-flota-ultima-renta` (ADR 0029): reescritura completa, sin `append`.

- **Llave: `PLACA`.** Es única en el reporte. La corrida cuenta altas, bajas y cambios por placa y se detiene si una placa viene vacía o repetida. Se conserva el orden en que Maxinet entrega las filas. Al comparar con lo que ya había en la hoja, `55194` (lo que devuelve Sheets) y `55194.0` (lo que se escribe) son el mismo valor: no cuentan como cambio.
- **Se escribe `A2:O{n}` con `RAW`, primero; después se limpia lo que sobre** (nunca al revés). No se toca ninguna columna a la derecha de la `O`, salvo la hora de actualización en `Q1:Q2`, con una columna libre de por medio.
- **La pestaña debe existir: la automatización no la crea.** `Proyección de Mantenimientos` y las fórmulas que se agreguen dependen de ese nombre; si alguien la renombra o la borra, es mejor que la corrida se detenga que dejar los datos en una pestaña nueva que nadie usa. El nombre se puede cambiar con `WORKSHEET_MTTO_PROYECTOR`.
- **El encabezado de la fila 1 es de quien armó la hoja.** Si trae los 15 nombres de la tabla no se toca (tampoco su formato ni la configuración de la hoja); si está vacío se escribe; si es otro (como los 20 de Flota Última Renta con que nació la pestaña), la corrida se detiene sin escribir. El cambio de esos encabezados se hace una sola vez, a mano, al integrar.
- **Tipos.** `FECHA RENTA`, `Fecha Ult.Mtto` y `Fecha Prox. Mtto` van como número de serie con formato `yyyy-mm-dd`. `Fecha Sig. Mtto` también, **cuando es una fecha**; los textos de semáforo se guardan como texto (la columna queda mixta, como en la página). Los kilómetros y el % de vencimiento van como número con el formato de la página (`#,##0.00`; `Km. de Regla` `#,##0`; `% Vencimiento` `0.00`, en puntos: `21.90` es 21.9 %). `ESTATUS` guarda el texto visible, sin el enlace. Todo lo demás, texto sin espacios de relleno. Lo que no tenga la forma esperada (por ejemplo `0000-00-00`) se conserva como texto.
- **Salvaguardas** (`FORZAR=1` omite sólo la del 80%): se detiene sin escribir si el ancho no es 16, si fechas, kilómetros o el código de color no tienen su forma en al menos el 90% de las filas con dato (columnas recorridas), si la respuesta ya no trae `dataReservas`, si Maxinet no trae ninguna placa, si la pestaña no existe o tiene otro encabezado, o si trae menos del 80% de las placas que ya estaban en la hoja (con 30 o más). `DRY_RUN=1` descarga y compara sin escribir. Las llamadas a Google Sheets reintentan ante la cuota (429), porque el sync de la base escribe mucho en este mismo libro alrededor de las 8:00.
- **Horario.** Una vez al día a las 8:00. El Vigilante la lanza en esa ventana, con hasta 3 reintentos, y el resumen de las 8:45 la incluye; el reloj de GitHub queda de respaldo (`0 14 * * *`, a veces con horas de retraso).
- **Datos personales.** La tabla trae nombres de clientes y placas; los logs sólo llevan conteos y las pruebas usan datos ficticios.

## Consecuencias

- Nadie debe escribir a mano dentro de `A2:O` de esa pestaña: se reemplaza en cada corrida. Las fórmulas o notas se agregan a la derecha de la `Q`; una columna nueva en medio de la tabla (o un encabezado distinto) detiene la corrida a propósito.
- La columna `Fecha Sig. Mtto` es mixta (fechas y textos): para filtrar por fecha o por semáforo conviene un filtro por condición o una columna auxiliar con `ISNUMBER`.
- No hay colores: Maxinet pinta `ESTATUS`, `Fecha Sig. Mtto` y `Fecha Prox. Mtto` en la página; la hoja guarda el dato. Se pueden agregar como formato condicional aparte (por ejemplo, `Fecha Prox. Mtto` menor a `HOY()` en rojo equivale al código `2`).
- Se pierde el número de la orden de mantenimiento que traía el enlace de `ESTATUS` (20 órdenes hoy). Si se necesita, es una columna más a la derecha de la tabla (`Id Orden`), a agregar en una automatización posterior.
- No hay cobertura de la guardia de actualización (es una pestaña de la Base LP, no del Tablero CP); el aviso lo da el Vigilante si pasa mucho tiempo sin una corrida exitosa.
