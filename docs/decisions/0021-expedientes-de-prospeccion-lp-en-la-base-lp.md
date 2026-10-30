# ADR 0021: Expedientes de prospección LP en la Base LP copia (copia fiel de la tabla)

Fecha: 2026-10-30

## Contexto

La página `lp-prospeccion-expedientes.php` de Maxinet lista los expedientes de prospección de largo plazo con la validación de cada área (CXC, mantenimiento, postventa, comercial y gerencia) y los datos del cliente. Se pidió llevar esa tabla completa a la Base LP copia ("Copia de BASE LP_AUTOMATIZADO") y mantenerla al día, sin filtros: la tabla tal como viene en Maxinet.

## Decisión

Una pestaña nueva, `EXPEDIENTES LP`, con su propia automatización (`automations/maxinet-expedientes-lp`) y su propio workflow, sin tocar `maxinet-sync`.

**Qué se copia.** La tabla con los valores por defecto del filtro de la página, que es lo que Maxinet muestra al abrirla: `Criterio=ESTATUS`, `Estatus=1` ("Pendientes") y sin fechas (348 expedientes al 2026-10-30). Se pide a `POST includes/prospeccion/expedientesData.php`; con parámetros vacíos el servidor responde `{"data": ""}`, así que los cinco campos del filtro deben ir siempre. Cada fila trae 32 celdas HTML: el botón "Ver Expediente" (se descarta) y las 31 columnas pedidas, con los nombres del reporte y en su orden, incluidos los datos de contacto.

Los expedientes "Cerrados" (`Estatus=0`) sólo salen con un rango de fechas y no están en esa vista (243 entre 2020 y hoy); no se incluyen. Un expediente que deja de estar pendiente sale de la hoja en la corrida siguiente.

**Cómo se escribe.** La pestaña se reescribe completa en cada corrida, en el orden en que Maxinet entrega las filas: no hay `append`, así que no hay duplicados ni datos viejos. Se escribe primero y se limpia lo que sobra después. `Folio` va como número y las fechas con hora (validaciones de cada área y fecha de la presentación) como número de serie con su formato, de modo que se ven igual que en Maxinet y se pueden filtrar y restar; todo lo demás se copia como texto, sin interpretarlo, con `value_input_option=RAW` (los folios de Prohire, los teléfonos y los plazos mezclan números y texto). Una fecha inválida como `0000-00-00` se conserva como texto. **`Fecha Facturación` no es una fecha** en Maxinet (trae el número de día de facturación) y se deja tal cual.

**Salvaguardas** (`FORZAR=1` las omite): la corrida se detiene sin escribir si la tabla cambia de ancho o sus columnas no cuadran (Folio, Fecha Registro), si un Folio viene repetido, si la hoja tiene otro encabezado (alguien movió columnas), si Maxinet no trae ningún expediente, o si trae menos del 80% de los que ya estaban en la hoja (con 30 o más). `DRY_RUN=1` descarga y compara sin crear ni escribir nada. La columna `AG` (fuera de los datos) muestra la hora de la última actualización. Las llamadas a Google Sheets reintentan ante la cuota (429), porque el sync del tablero escribe mucho en la misma Base alrededor de las 8:00.

**Datos personales.** La tabla trae nombres, correos y teléfonos de prospectos y de contactos de compras; se copian porque se pidieron como columnas de la hoja. Los logs sólo llevan conteos y las pruebas usan datos ficticios.

**Horario.** A las 8:30, 9:30 y 10:30 (reloj de GitHub): de las 8:30 a las 10:30 como máximo, por decisión de quien pidió la hoja. La consulta tarda unos 3 segundos y la corrida completa unos 20. El reloj de GitHub a veces llega con horas de retraso; si se necesita que las corridas caigan en esa franja con puntualidad, hace falta una ventana en el Vigilante (cambio aparte).

## Consecuencias

- La pestaña se crea sola en la primera corrida (por eso el secret `WORKSHEET_EXPEDIENTES_LP` es opcional y sólo acepta el nombre).
- No hay ventana en el Vigilante ni cobertura de la guardia de actualización: agregarlas es un cambio aparte.
- Para conservar también los cerrados habría que pedir `Estatus=0` con un rango de fechas y unirlos a la tabla; no se hizo porque la vista pedida es la activa.
