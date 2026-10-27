# ADR 0017: Órdenes de mantenimiento LP en la Base LP copia (mes corriente y abiertas)

Fecha: 2026-10-27

## Contexto

El reporte `lp-mtto-ordenes.php` de Maxinet lista las órdenes de mantenimiento (una fila por orden, 62 columnas). Se pidió llevarlo a la Base LP copia ("Copia de BASE LP_AUTOMATIZADO", la misma que alimenta el tablero LP) y mantenerlo al día, con prioridad en que la información sea la más reciente y en que la hoja no se llene.

Antes de construirlo se revisó si ese reporte podía alimentar la pestaña `ENVIOS SEMINUEVOS` de la misma base (1,199 filas, 28 columnas, todo constantes, sin una sola fórmula):

- Una fila por orden contra una fila por placa: las columnas no se corresponden.
- Gasto SN, Garantía, Recup., Total y Job no coinciden con ninguna suma de las órdenes (se probaron siete variantes sobre 11,834 órdenes de 2025 y 2026; ninguna coincidió en las filas con valor). Esos costos salen de otra fuente.
- Sólo 370 de las 1,199 placas de la hoja tienen alguna orden en 2025-2026, y el tipo de ticket `SM` (seminuevos) aparece en 94 órdenes de 43 placas, de las cuales 11 están en la hoja.

Por eso `ENVIOS SEMINUEVOS` no se toca. La Base LP original de Nuvia (pestañas `RESERVAS CP&LP`, `ONHIRE`, `ENVIOS SEMINUEVOS`, `GRAFICO` y `LINK`) tampoco tiene una pestaña de órdenes de mantenimiento, así que no hay nada que migrar ni contra qué comparar.

## Decisión

Una pestaña nueva, `ORDENES MTTO`, en la Base LP copia, con su propia automatización (`automations/maxinet-mtto-ordenes`) y su propio workflow, sin tocar `maxinet-sync`.

**Qué contiene.** Sólo el mes corriente más las órdenes que siguen abiertas, para que la hoja no crezca sin límite (hoy, 1,135 filas: 960 del mes y 175 abiertas de meses anteriores):

- Mes corriente: del día 1 a ayer (hora CDMX) por fecha de alta. Si hoy es día 1, "ayer" cae en el mes anterior y el rango es ese mes completo, para no dejar la hoja vacía.
- Órdenes abiertas de cualquier mes, para que su estatus esté al día aunque se hayan dado de alta antes. Sin esto, una orden abierta en septiembre se quedaría con el estatus viejo todo octubre.
- Al cambiar de mes, las órdenes cerradas o canceladas del mes anterior salen de la hoja. No queda otra copia de ese historial (ni en esta base ni en la original de Nuvia).

**Cómo se consulta.** `POST json/lp-mtto-ordenes.php` con los mismos campos del filtro de la página: `Criterio=ALTA` con `Desde` y `Hasta` para el mes, y `Criterio=ESTATUS` con `Estatus=1` para las abiertas. `Estatus` debe ir siempre con valor aunque el criterio sea por fecha (la página lo manda con el del selector deshabilitado); con `Estatus` vacío el servidor responde `{"data": ""}`. Cada fila trae 62 celdas HTML.

**Cómo se escribe.** La pestaña se reescribe completa en cada corrida con lo que entrega Maxinet, ordenada por Id: no hay `append`, así que no puede haber duplicados ni estatus viejos. Se escribe primero y se limpia lo que sobra después. Los valores van tipados con `value_input_option=RAW` (fechas y horas como número de serie, costos y días como número, el resto como texto) para que Sheets no reinterprete placas ni folios; lo que no tiene la forma esperada, por ejemplo una fecha con año 0026 tecleada mal (5 casos en octubre), se conserva como texto. La suma de `Costo Total` de la hoja coincide al centavo con la del reporte.

**Columnas.** Las 62 del reporte menos los 3 botones y los 4 datos personales de contacto (nombre, teléfono, celular y correo): quedan 55, con los nombres del reporte. Ninguna de las columnas de `ENVIOS SEMINUEVOS` los usa y no hay razón para copiar datos personales de clientes a la base. La columna `BE` (fuera de los datos) muestra la hora de la última actualización y la ventana.

**Salvaguardas** (`FORZAR=1` las omite): la corrida se detiene sin escribir si el reporte cambia de ancho o sus columnas no cuadran (Id, Fecha Alta, placa), si la hoja tiene otro encabezado (alguien movió columnas), si Maxinet no trae ninguna orden, o si trae menos del 80% de las órdenes de alta del rango o menos del 80% de las abiertas que ya estaban en la hoja (con 30 o más de cada una). Las dos comparaciones son sin estado y no se disparan en falso al cambiar de mes. `DRY_RUN=1` descarga y compara sin crear ni escribir nada. Los logs sólo llevan conteos; no se registran datos de las órdenes.

**Horario.** Ventana de las 8:30 en el Vigilante (pendiente de agregar: una línea en `MATUTINO.reportes`) y reloj de GitHub cada hora de 8:30 a 17:30, porque los estatus de las órdenes cambian durante el día y la prioridad es la información más reciente. Es una consulta de unos 20 segundos.

## Consecuencias

- La pestaña se crea sola en la primera corrida (por eso el secret `WORKSHEET_MTTO_ORDENES` es opcional y sólo acepta el nombre).
- La guardia de actualización todavía no la cubre: agregarla es un cambio aparte.
- Quien quiera conservar los meses cerrados necesita una pestaña congelada por mes; no se hizo porque no se pidió.
