# ADR 0023: Leads recibidos y calificados de monday en la pestaña MKT del tablero LP

Fecha: 2026-10-28

## Contexto

La pestaña `MKT` del libro del tablero LP lleva, por mes, los leads recibidos (columna G) y los calificados (columna H). Esos dos números salían de una gráfica del reporte de leads del CRM de ventas en monday y se capturaban a mano.

La API pública de monday no entrega los datos de las gráficas de un tablero de control (solo permite crearlos), así que la gráfica no se puede leer directamente. Para reproducirla se leyeron los leads del tablero de origen y se probó qué filtro daba las cifras que ya estaban en la hoja:

- La gráfica no cuenta todos los leads del tablero, sino los de un tipo de lead. Con ese tipo, los recibidos coincidieron exactos con la hoja en cinco meses seguidos (mayo a septiembre de 2026), y el mes en curso coincidió con la gráfica el día de la prueba.
- Los calificados de los meses cerrados hoy son algo más altos que lo que quedó en la hoja, porque los leads siguen pasando a calificado después de que se capturó la fila.
- La columna que distingue el tipo de lead se usa desde mayo de 2026. Los meses anteriores no se pueden reproducir con esta regla y se dejan como estaban.

## Decisión

Una automatización nueva, `automations/MKT Monday`, con su propio workflow `mkt-monday.yml`, que cada día a las 9:00 (hora CDMX):

- Lee los leads del tipo configurado, con su fecha de creación y su estado.
- Cuenta los creados en el mes en curso (hora CDMX): el total va a la columna G y los que tienen la etiqueta de calificado van a la H.
- Localiza la fila del mes por la fecha de la columna F y escribe solo G y H de esa fila.

**Qué no hace.** No toca la columna de cierres ni ninguna fórmula (se detiene si G o H tienen una). No reescribe meses ya cerrados: el mes anterior se refresca solo durante los primeros 3 días del mes, y `--mes AAAA-MM` queda para correcciones puntuales. No baja a cero un total que ya tiene leads sin `--forzar`, porque un cero suele ser una lectura fallida.

**Configuración.** El tipo de lead, la etiqueta de calificado y los IDs de monday viven en un JSON fuera del repositorio (`private/` en local y el secret `MKT_MONDAY_CONFIG_JSON` en Actions), porque el repositorio es público. El ID del libro sale del secret `SPREADSHEET_ID_SECUNDARIO`. Si el criterio de la gráfica cambia, se cambia ese JSON sin tocar el código.

## Consecuencias

- Un mes se cierra con la corrida de las 9:00 del último día y se vuelve a refrescar en los primeros 3 días del mes siguiente, así que quedan incluidos los leads de sus últimos días y los que se calificaron después. Si la fila de uno de los dos periodos falla, el otro se escribe igual y la corrida termina con error.
- El reloj de GitHub no garantiza la hora: el 3-nov-2026 la corrida pedida a las 9:00 no había salido a las 9:30. Por eso el workflow se pide al :07 (el :00 es la hora con más disparos saltados) y se repite cada hora hasta las 12:07; como una corrida sin cambios no escribe nada, las repeticiones son inofensivas. La hora exacta de las 9:00 la da una ventana en el Vigilante, pendiente de agregar.
- Al empezar un año hay que agregar en la hoja las filas de los 12 meses; mientras no existan, el proceso se detiene sin escribir.
- El registro de Actions es público: no imprime cifras ni nombres de columnas o etiquetas.
