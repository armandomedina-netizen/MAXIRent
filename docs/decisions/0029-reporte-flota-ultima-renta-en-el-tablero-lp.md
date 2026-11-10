# ADR 0029: Reporte Flota Última Renta en el Tablero LP

- Estado: aceptada
- Fecha: 2026-11-10

## Contexto

Se pidió llevar al libro del Tablero LP, en la pestaña `Reporte Flota Ultima Renta`, el reporte **Flota Última Renta Cliente** de Maxinet (`reporte-flota-ultima-renta-cliente.php`): una fila por placa con su sucursal, el último cliente que la rentó (fechas, booking, estatus), los días desde esa renta y los días no disponibles con sus semáforos, el odómetro con su semáforo y los datos del vehículo. Son las 20 columnas de la tabla de la página, en su mismo orden. Se actualiza **una vez al día, a las 8:00**, reemplazando lo que hay con todo lo que entrega Maxinet.

La pestaña ya existía, armada por quien la pidió: solo con la fila de encabezados (`A1:T1`, los mismos 20 nombres), sin datos, filtros, formatos condicionales ni protecciones. El libro es el mismo que usa `maxinet-sync` (`SPREADSHEET_ID_SECUNDARIO`); no se agrega ningún secret obligatorio.

## Hallazgos de Maxinet (2026-11-10)

- La página llena su `DataTable` con una consulta `GET includes/flota/reporte-flota-ultima-renta.php` **sin parámetros** (el filtro de estatus que quedó en su código está comentado). Responde `{"data": [...]}` en unos 30 segundos y 350 KB.
- Cada fila trae exactamente las **20 celdas** de la tabla: a diferencia de otros reportes, no hay una primera celda con un botón.
- Hoy son 1,456 placas, sin repetidas. Fechas `YYYY-MM-DD` o vacías; `Dias desde Ult. Renta Cliente` y `Dias no disponibles` enteros (vacíos cuando no aplican: la mayoría); `Odómetro` como texto de dígitos (la página le pone el separador de miles al mostrarlo), vacío en unas 37 placas; los semáforos son `verde`, `amarillo`, `rojo` o `na`; `Estatus ult. renta Cliente` viene rellenado a ancho fijo (`ON HIRE     `). Las placas pueden empezar con `@` y los bookings con `#`.

## Decisión

Una automatización nueva, `maxinet-flota-ultima-renta` (`automations/maxinet-flota-ultima-renta`, workflow `maxinet-flota-ultima-renta.yml`), con el patrón de `maxinet-expedientes-lp` (ADR 0021): reescritura completa, sin `append`.

- **Llave: `Placa`.** Es única en el reporte. La corrida cuenta altas, bajas y cambios por placa y se detiene si una placa viene vacía o repetida. Se conserva el orden en que Maxinet entrega las filas.
- **Se escribe `A2:T{n}` con `RAW`, primero; después se limpia lo que sobre** (nunca al revés), así la hoja no queda vacía a media corrida. No se toca ninguna columna a la derecha de la `T`, salvo la hora de actualización en `V1:V2`, con una columna libre de por medio.
- **El encabezado de la fila 1 es de quien armó la hoja.** Si trae los 20 nombres no se toca (tampoco su formato ni la configuración de la hoja: no se congela ni se pinta); si está vacío se escribe; si es otro, la corrida se detiene sin escribir. La pestaña se crea si no existe.
- **Tipos.** Las tres fechas (`PUDate Ult. Renta Cliente`, `ReturnDate Ult. Renta Cliente`, `ReturnDate Ult. Renta`) van como número de serie con formato `yyyy-mm-dd`; los días y el `Odómetro` como entero (el odómetro con separador de miles). Todo lo demás, texto sin espacios de relleno. Así se pueden filtrar, ordenar y restar. Lo que no tenga la forma esperada (por ejemplo `0000-00-00`) se conserva como texto. Un `0` en los días es un dato, no un vacío.
- **Salvaguardas** (`FORZAR=1` omite sólo la del 80%): se detiene sin escribir si el ancho no es 20, si fechas, días u odómetro no tienen su forma en al menos el 90% de las filas con dato (columnas recorridas), si Maxinet no trae ninguna placa, o si trae menos del 80% de las que ya estaban en la hoja (con 30 o más). `DRY_RUN=1` descarga y compara sin escribir. Las llamadas a Google Sheets reintentan ante la cuota (429), porque el sync del tablero escribe mucho en este mismo libro alrededor de las 8:00.
- **Horario.** Una vez al día a las 8:00. El Vigilante la lanza en esa ventana, con hasta 3 reintentos, y el resumen de las 8:45 la incluye; el reloj de GitHub queda de respaldo (`0 14 * * *`, a veces con horas de retraso). La ventana de las 8:00 coincide con la del sync completo del Tablero LP: la cuota de lectura de Google la comparten, pero ambos reintentan ante el 429 y escriben pestañas distintas.
- **Datos personales.** La tabla trae nombres de clientes y placas; los logs sólo llevan conteos y las pruebas usan datos ficticios.

## Consecuencias

- Nadie debe escribir a mano dentro de `A2:T` de esa pestaña: se reemplaza en cada corrida. Las fórmulas o notas se agregan a la derecha de la `V`; una columna nueva en medio de la tabla (o un encabezado distinto) detiene la corrida a propósito.
- No hay colores en los semáforos: Maxinet los pinta en la página con `verde`, `amarillo`, `rojo` y gris; la hoja guarda el texto. Se pueden agregar como formato condicional aparte si se quieren.
- No hay cobertura de la guardia de actualización (es una pestaña del Tablero LP, no del Tablero CP); el aviso lo da el Vigilante si pasa mucho tiempo sin una corrida exitosa.
