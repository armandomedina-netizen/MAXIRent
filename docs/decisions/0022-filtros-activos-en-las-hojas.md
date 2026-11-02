# ADR 0022: Un filtro activo en una hoja no debe detener la actualización

Fecha: 2026-11-02

## Contexto

El 2-nov-2026 a las 8:05, Encuestas CP escribió las 6 encuestas nuevas y falló al copiar el formato y las fórmulas con `400: This operation is not supported on a range with a filtered out row`. Alguien tenía un filtro activo en la pestaña `ENCUESTAS` y la fila que se usa como modelo (la última del bloque) quedó oculta. Dos problemas encadenados:

1. La copia de formato y fórmulas (`copyPaste`) se rechaza.
2. El reintento de las 8:10 salió en verde porque ya no había encuestas nuevas: el paso de fórmulas y formato sólo corría al agregar filas, así que una corrida a medias no se reparaba sola y nadie se enteraba.

Se probó contra la API real de Google Sheets (pestaña temporal, ya eliminada) qué operaciones rechaza un filtro básico: **sólo `copyPaste` cuyo origen contiene una fila oculta por el filtro**. Un destino con filas filtradas, `repeatCell`, `insertDimension`, `updateCells` y la escritura de valores funcionan con el filtro puesto.

## Decisión

**Módulo común `automations/_comun/lib/filtros_sheets.py`.** Se instala una vez por proceso sobre `HTTPClient.batch_update` de gspread (`filtros_sheets.instalar()`), así cubre todas las llamadas existentes sin tocarlas una por una. No hace nada mientras Sheets acepte la petición. Cuando la rechaza por una fila filtrada:

1. **Etapa 1.** Si el origen es una sola fila, la copia se rehace con la fila **visible** más cercana hacia arriba, buscando sólo debajo del encabezado del filtro (el encabezado nunca se oculta pero no es un modelo válido). Las fórmulas se ajustan solas a la fila destino y el formato es el de una fila de datos igual de reciente. El filtro no se toca.
2. **Etapa 2.** Si no hay fila visible o el origen abarca varias filas, se suspende el filtro básico de esa hoja (`clearBasicFilter`), se ejecuta la petición y se restaura el mismo filtro (`setBasicFilter` con el rango, criterios y orden leídos antes) en un `finally`. Si la restauración fallara, se registra y se levanta un error para que la guardia lo vea.
3. Cualquier otro error (429, 5xx, otro 400) pasa sin cambios; y si la hoja no tiene filtro básico se relanza el error original.

Está instalado en las ocho automatizaciones que usan `copyPaste`: `maxinet-sync`, `maxinet-encuestas-cp`, `maxinet-entregas-cp`, `maxinet-clientes-potenciales-cp`, `maxinet-frecuentes-activos-cp`, `automatización Gestoría`, `tablero-cp-cierre-diario` y `TableroSAC`. Una prueba falla si una automatización nueva usa `copyPaste` sin instalarlo. Es un módulo compartido (no una copia por archivo) para que la regla viva en un solo lugar; cada script lo importa con una ruta relativa a `automations/_comun/lib`, que existe en cualquier ejecución del repositorio completo (GitHub Actions hace checkout de todo).

**Encuestas CP repara lo que quedó a medias.** En cada corrida, haya o no encuestas nuevas, revisa las últimas 60 filas con fecha; las que no tienen PERIODO o RECLASIFICACION reciben fórmulas y formato desde la fila completa más reciente. Con `DRY_RUN=1` sólo informa. El aviso de "fórmula copiada a N filas" ya sólo sale después de que Sheets aceptó la copia (antes salía antes y podía decir que había copiado algo que se rechazó).

## Consecuencias

- Un filtro puesto por una persona ya no detiene ninguna automatización. En la etapa 2 el filtro se libera un instante y vuelve igual; si alguien tiene la hoja abierta puede ver parpadear las filas. El log lo avisa (`Se suspendió el filtro…` / `Filtro restaurado…`) sin imprimir datos de las hojas.
- Si el filtro dejaba fuera de la vista filas que se escriben, esas filas se escriben igual (la escritura de valores nunca dependió del filtro); lo que el filtro oculte después lo decide el criterio de quien lo puso.
- Pendiente (no incluido): la misma revisión de filas recientes para Entregas, Clientes Potenciales y Frecuentes Activos, que tienen el mismo patrón "escribir y luego copiar fórmulas y formato" y nunca han fallado por esto; y revisar si la guardia debe avisar cuando una hoja tiene un filtro activo desde hace horas.
