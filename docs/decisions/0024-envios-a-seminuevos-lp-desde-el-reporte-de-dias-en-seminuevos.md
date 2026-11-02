# ADR 0024: Envíos a seminuevos LP desde el reporte de días en seminuevos de Maxinet

Fecha: 2026-11-02

## Contexto

La pestaña `ENVIOS SEMINUEVOS` de la Base LP copia ("Copia de BASE LP_AUTOMATIZADO") tenía los datos del reporte `reporte-dias-seminuevos.php` de Maxinet, pero ningún proceso la actualizaba: su última fecha de ingreso a seminuevos es del 2026-09-08. Se pidió automatizarla, con la regla de reemplazar los datos de la hoja por lo que muestra Maxinet, una vez al día y ligada a las demás automatizaciones de la mañana.

La hoja tiene 28 columnas con los nombres del reporte (A:AB) y dos columnas derivadas, `MES` y `AÑO` (AC:AD, fórmulas sobre la fecha de ingreso a seminuevos). La pestaña `GRAFICO` de la misma Base cuenta con `COUNTIFS` sobre esas columnas y sobre `BSite` (mes, año y sucursal), incluyendo años anteriores.

## Decisión

Una automatización propia, `automations/maxinet-seminuevos-lp`, con su workflow y sin tocar `maxinet-sync`.

**Cómo se extrae.** Un solo `POST includes/flota/reporte-dias-sn.php` con el campo `Estatus`, que es el mismo que usa el DataTable de la página; el botón "Excel" de la página sólo exporta lo que ese POST ya trajo (se genera en el navegador), así que no hay archivo que descargar ni navegador que manejar. Es la opción de menor costo: una consulta HTTP de unos 520 KB. Maxinet tarda unos 90 segundos en responder; la corrida completa, unos dos minutos y medio.

**Qué filtro.** `Estatus=2` (TODAS), no `1` (ACTIVAS):

| Estatus | Filas (2026-11-02) | Contenido |
|---|---|---|
| 1 ACTIVAS | 102 | Sólo las unidades que siguen en flota |
| 0 OFF_FLEET | 1,183 | Las vendidas, con 41 placas repetidas (filas idénticas) |
| 2 TODAS | 1,242 | ACTIVAS más OFF_FLEET, una fila por placa |

La hoja guarda el historial de unidades vendidas (1,058 de 1,199 filas eran `OFF_FLEET` en la última foto) y `GRAFICO` lo cuenta por mes y año. Reemplazar con ACTIVAS habría borrado ese historial y llevado a cero las cuentas de años anteriores. TODAS es también lo que ya contenía la hoja: coincide con ella placa por placa (1,189 placas comunes; Gasto SN, Recup. y Total, iguales en todas), sin repetidos.

**Cómo se escribe.** Las columnas A:AB se reemplazan completas en cada corrida (`A2:AB{n}`, `RAW`), en el orden de la vista de Maxinet (`BOOKED_ON` descendente, las unidades sin fecha al final), que es el orden que ya tenía la hoja: no hay `append`, así que no hay duplicados ni datos viejos. Una unidad que Maxinet deja de listar sale de la hoja (el 2026-11-02 fueron 10 que habían regresado a flota sin venta). Se escribe primero y se limpia lo que sobra después, nunca al revés. El encabezado no se reescribe: se verifica que sea el esperado.

Tipos como los tenía la hoja: fechas como número de serie, días como entero, importes como decimal y el resto como texto sin espacios sobrantes; vacío donde Maxinet no trae dato. Las columnas `MES` y `AÑO` no se tocan: si la tabla crece, se extienden hacia abajo con la fórmula de la última fila que la tiene; si se acorta, se limpian las filas que sobran. El formato de la fila 2 se copia al resto de las filas con datos (la hoja lo tenía por columna, pero sin formato en parte de la última fila, y las filas nuevas lo necesitan). Esa copia usa `copyPaste`, así que la automatización instala `filtros_sheets.instalar()` (ADR 0022): un filtro activo en la hoja no la detiene.

La hora de actualización queda en `AF1:AF2`, con una columna libre de por medio a la derecha de `MES` y `AÑO`, igual que en las otras pestañas de la Base.

**Salvaguardas** (`FORZAR=1` las omite): la corrida se detiene sin escribir si el reporte cambia de ancho o una columna no tiene la forma esperada (fecha, entero o importe; placa), si una placa viene repetida, si la pestaña no existe (no se crea: tiene formato propio y la usa `GRAFICO`) o tiene otro encabezado, si Maxinet no trae ninguna unidad, o si trae menos del 80% de las filas que ya estaban en la hoja (con 30 o más). Al terminar se comprueba que no haya placas repetidas y que `MES` y `AÑO` tengan fórmula en la última fila. `DRY_RUN=1` descarga y compara sin escribir. Los logs sólo llevan conteos.

**Horario.** Una vez al día. El Vigilante la lanza a las 8:30, junto con Órdenes Mtto y Expedientes LP, y reintenta hasta 3 veces si falla; el resumen de las 8:45 la incluye. El reloj de GitHub (`30 14 * * *`, 8:30 hora de Ciudad de México) queda de respaldo si el Vigilante no corre: a veces llega con horas de retraso, y esa corrida tardía sólo repite el reemplazo, que es idempotente.

## Consecuencias

- Si `GRAFICO` o el tablero se alimentan de la hoja, ahora ven datos del día en lugar de los de septiembre.
- Cambia el conjunto de placas respecto de la última carga manual: entran las unidades enviadas desde entonces y salen las que Maxinet ya no lista (regresaron a flota). Es el efecto buscado de reemplazar por lo que muestra Maxinet.
- Si Maxinet cambia el reporte (ancho, orden o forma de las columnas), la corrida se detiene sin escribir y el error dice qué cambió; hay que ajustar `COLUMNAS` en el código.
- `MES` y `AÑO` salen de la fórmula que ya tiene la hoja: una unidad sin fecha de ingreso a seminuevos (hoy, 9 recién asignadas) muestra el mes y el año de la fecha cero de Sheets, que no coinciden con ningún mes de `GRAFICO`. Cambiar esa fórmula para que quede vacía en ese caso es una decisión de quien mantiene la hoja.
- No hay cobertura de la guardia de actualización (que revisa las pestañas del Tablero CP); la ventana del Vigilante avisa si la corrida no tuvo éxito.
