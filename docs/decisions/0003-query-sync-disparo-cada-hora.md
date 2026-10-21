# ADR 0003: Disparo puntual y vigilancia de los workflows de Maxinet

- Estado: aceptada (pendiente de configurar el reloj externo)
- Fecha: 2026-10-01

## Contexto

Los workflows de este repositorio dependen del evento `schedule` de GitHub Actions, que no garantiza la hora. Del 27 al 30 de septiembre de 2026 los crons se retrasaron entre 4 y 6 horas (por ejemplo, el sync del tablero LP programado a las 15:00 UTC corrió a las 21:01 UTC el 28 de septiembre). `maxinet-query-sync.yml` además debe correr al menos una vez por hora sin depender de una computadora encendida.

## Decisión

1. El disparo puntual lo hace un Google Apps Script en la cuenta corporativa, con un disparador horario que llama a `workflow_dispatch` (los disparos por API arrancan en segundos). No agrega ningún proveedor nuevo.
2. El mismo script revisa la edad de la última corrida exitosa de cada workflow vigilado y envía un correo si se pasa de su tolerancia. Ese vigilante no usa Claude ni consume cuota de uso.
3. Query Sync: se dispara cada hora (es idempotente: reemplaza el bloque de datos y re-extiende fórmulas). El cron de GitHub (`7 * * * *`) queda como respaldo; el grupo `concurrency` serializa ambos disparos.
4. Workflows diarios (p. ej. el tablero LP): se dispara una sola vez al día a su hora, y sólo si no existe ya una corrida de esa ventana. Si el workflow tiene modos distintos según `github.event.schedule`, el modo debe poder pedirse también por `workflow_dispatch` (input). Los `schedule` de esos workflows sólo se retiran después de comprobar el disparo externo, para que un cron tardío no sobrescriba una captura hecha a la hora correcta.
5. Claude Cowork no se usa como reloj ni como vigilante: sus tareas sólo corren con la app abierta y cada ejecución consume una sesión completa con su contexto base.

## Seguridad

- El reloj sólo guarda un token fine-grained de GitHub limitado a este repositorio con permiso *Actions: Read and write*, con caducidad y revocable. No puede leer Secrets, modificar código ni hacer push.
- Los datos de Maxinet y de Sheets no pasan por el reloj; las credenciales siguen únicamente en los Secrets del repositorio.
- El token nunca se versiona ni se comparte por chat; vive en las propiedades del script.
- Este repositorio es público: los logs de Actions son visibles para cualquier usuario de GitHub, por lo que los scripts no imprimen placas, reservas ni nombres de clientes (sólo conteos).

## Consecuencias

- Costo: $0 (repositorio público; aun siendo privado caben en los minutos gratuitos) y sin consumo de Claude.
- Si el token caduca o se revoca, el disparo externo falla (Apps Script avisa por correo) y queda el cron de GitHub; hay que renovarlo antes de la fecha de caducidad.
- GitHub desactiva los workflows programados tras 60 días sin actividad en un repositorio público; el aviso por antigüedad de la última corrida exitosa lo detecta.

## Tablero LP (`maxinet-sync.yml`): auditoría y cambios (2026-10-01)

Se auditó cada paso de `main()` y `main_proyeccion_mtto()` para saber si una segunda corrida el mismo día es segura (el disparo externo y el cron de GitHub pueden coincidir).

| Paso | Idempotente | Por qué |
|---|---|---|
| `avanzar_columna_formulas`, `avanzar_columna_grupo_autos` | Sí | Si la columna destino ya tiene contenido, avisan y no hacen nada. |
| `actualizar_vor_cliente` | Sí | Reescribe los conteos de una fecha ya cerrada con los mismos valores. |
| `actualizar_periodo_resumen`, `extender_formulas_resumen`, `actualizar_tablas` | Sí | Se recalculan desde las fechas y el día de hoy; sólo se extiende lo que falta. |
| `avanzar_formula_dia_duracion_rentas`, `avanzar_activas_duracion_rentas` | Sí | Sólo tocan filas/meses que no corresponden; si ya están al día, regresan. |
| `actualizar_sheet` | Sí (resultado) | Limpia y reescribe el bloque con la foto más reciente. |
| Proyección de Mantenimientos | No (corregido) | Sobrescribía `D{hoy}`: un cron tardío pisaba la captura de las 9:10 (el 30-sep se escribió 6.63 % a las 14:00 hora CDMX). |
| Dos corridas simultáneas | No (corregido) | Las salvaguardas revisan y luego actúan, sin candado. |

Cambios:

- `maxinet_sync.py`: la captura de Proyección ya no sobrescribe un valor existente (`--forzar-mtto` para reescribirlo a propósito); todas las fechas "de hoy" usan `America/Mexico_City` en vez de la del servidor (UTC), para que una corrida tardía no avance las columnas un día de más.
- `maxinet-sync.yml`: `workflow_dispatch` acepta `modo` (`completo` | `solo_proyeccion_mtto`); `concurrency` serializa las corridas del mismo modo sin cancelar (grupos distintos por modo, porque GitHub conserva una sola corrida pendiente por grupo); `timeout-minutes: 20`. Los `schedule` se mantienen.

Riesgo mientras convivan el cron de GitHub y el disparo externo: un cron tardío dispara un segundo sync completo (no-op por las salvaguardas de arriba) y una segunda captura de Proyección (se conserva la primera). Los `schedule` se retiran hasta comprobar el disparo externo al menos 3 días seguidos.

### Incidente del calendario de UTILIZACION V3 y UTI. GRUPO DE AUTOS V1 (2026-10-02)

- Causa: ambas hojas tienen una columna por día y su calendario terminaba el 30-sep. El 2-oct no existía la columna del 1-oct y `_encontrar_columna_por_fecha` comparaba el texto "1-oct" (se repite en 2025 y 2026), así que escogió la del 2025 y VOR Cliente se escribió sobre el histórico de otro año (4 celdas, ya restauradas desde el original). Además, la hoja de datos ya tenía la foto del 1-oct y la columna viva del 30-sep quedó en ceros; se rellenó desde el original.
- Corrección: la búsqueda compara ahora el número de serie de la fecha (único); si la fecha continúa el calendario, éste se extiende solo hasta fin de mes (`_extender_columnas_calendario`, mismo formato que la última columna); en cualquier otro caso la corrida falla en vez de escribir en otra fecha.
- Lección: una salvaguarda "si la columna ya tiene contenido, no avanzar" evitó daños mayores, pero VOR Cliente no la tiene; por eso importa que la búsqueda falle fuerte.

### Disparo del tablero LP desde el Apps Script (2026-10-02)

Un solo proyecto de Apps Script, pero un disparador independiente por reporte (`ejecutarQuerySync`, `ejecutarTableroLP`, `ejecutarGestoria`) en lugar de un único `ejecutar` que lo hace todo en un ciclo: un error o un retraso en uno no afecta a los demás.

- **Tablero LP** (el más importante; debe quedar actualizado antes de las 9:30, hora CDMX): disparador cada 5 minutos que sale de inmediato fuera de 8:55–20:00. Dos ventanas: 9:00 `completo` y 9:10 `solo_proyeccion_mtto`. Cada una se dispara si no hay ya una corrida (en cola, en curso o exitosa, incluido un cron tardío de GitHub), se reintenta hasta 3 veces si falla y, si a las 9:30 no hay corrida exitosa, avisa por correo. La ventana se identifica por la etiqueta del `run-name` del workflow.
- **Query Sync:** cada hora, pero sólo en horario laboral (constantes `HORARIO_QUERY`); fuera de ese horario no se dispara ni se vigila.
- Los `schedule` de GitHub se retiran de `maxinet-sync.yml` cuando el disparo externo funcione 3 días seguidos.

### Corrección: Proyección de Mantenimientos toma el histórico de Maxinet (2026-10-02)

- Sustituye lo dicho antes sobre "no sobrescribir la captura de las 9:10": el % de cada día ya no es una foto de la tabla en vivo (cambia durante el día y coincidía en 27 de 31 días con el original). Maxinet guarda su propio histórico (`charMttosVencidos.php`, la gráfica "% Vencimiento y Meta") y de ahí copia Nuvia: coincide en 31 de 31. Por eso la hora exacta de la corrida ya no afecta el valor.
- Cada corrida llena en D los días cerrados (hasta ayer) que estén vacíos, sin pisar lo ya escrito; la fila de hoy se llena al día siguiente, cuando Maxinet la publica. `--forzar-mtto` reescribe los últimos 45 días. J1:J2 ("UNIDADES EN RENTA" y "VENCIDOS") se actualizan con la tabla en vivo y su falla no detiene lo demás. Las consultas a Maxinet de esta sección reintentan si se corta la conexión.
- **Principio:** el archivo de Nuvia sirve sólo para comparar y reconciliar; ningún proceso del repositorio lo lee ni depende de él. Cuando el tablero propio pase a ser el principal debe mostrar la información correcta con sus propias fuentes (Maxinet).

### Hojas de solo fórmulas del tablero LP (2026-10-02)

`mantener_formulas_tablero()` (en `maxinet_sync.py`, dentro del sync completo) mantiene las fórmulas por fila de las hojas que listan algo con una fórmula que se derrama (`UNIQUE`/`SORT`/`FILTER`): `UTILIZACION POR GRUPO`, `RESUMEN DE RENTAS ACTIVAS` y `PROXIMOS RETORNOS` (`BLOQUES_FORMULAS_TABLERO`). Cada corrida extiende las fórmulas hasta la última fila de la lista más una holgura (agrega filas a la hoja si hace falta, con formato), rellena huecos y avisa si hay errores en la guía o el bloque (por ejemplo un derrame bloqueado). Nunca borra ni sobrescribe contenido. Si una escritura no es posible (rango protegido) avisa y sigue: estas hojas son secundarias y no deben detener el sync. `RESUMEN AFECTACIONES!B2` (selector de mes) pasa solo al mes en curso cuando todavía muestra el anterior; si alguien eligió otro mes a propósito, se respeta.

Requisito: la cuenta de servicio debe ser editora de los rangos protegidos de esas hojas (`UTILIZACION POR GRUPO`, `PROXIMOS RETORNOS`, `RESUMEN DE RENTAS ACTIVAS`); hoy sólo están protegidas en la copia del tablero.

### Cuota de lecturas de Google Sheets (2026-10-02)

El 2-oct un sync completo falló con `429 Quota exceeded ... Read requests per minute per user`: esa cuota (60 lecturas por minuto) la comparten todos los procesos que usan la misma cuenta de servicio (este sync, el Query Sync, pruebas manuales). `maxinet_sync.py` instala reintentos sobre el cliente de gspread: un 429 se reintenta hasta 5 veces con espera creciente (20 s, 40 s, ...), y los 5xx sólo en lecturas, para no duplicar escrituras. Además el mantenimiento de fórmulas junta sus lecturas (`batch_get`) y abre el libro una sola vez.

### Gráficos del tablero y la base (2026-10-02)

Cada mes se estiraba a mano el rango de datos de cada gráfico de series de tiempo (por ejemplo `COMPORTAMIENTO DE CUENTAS` pasó de `A23:AF23` a `A23:AG23`). `mantener_graficos()` revisa los gráficos de `GRAFICOS_CRECIENTES`: toma el eje del gráfico y, si inmediatamente después de su último dato hay celdas con contenido sin huecos, extiende todos los rangos del gráfico hasta ahí (sólo agranda, se detiene en la primera celda vacía y no se sale de la cuadrícula de la hoja). `RESUMEN AFECTACIONES` termina en el último mes completo. Cada gráfico se actualiza por separado: si su hoja está protegida (la cuenta de servicio debe ser editora) avisa y sigue. La API devuelve `lineSmoothing` en gráficos de área o combinados pero lo rechaza al escribirlos, por eso se quita salvo en gráficos de línea.

Sólo se tocan los gráficos listados; los que se alimentan de tablas de tamaño fijo (por ejemplo los de envíos a seminuevos) no se estiran.

### Detalle de Duración rentas desde Maxinet (2026-10-05)

El detalle de devoluciones de `Duración rentas` se capturaba a mano a partir del `RETORNOS` del BALANCE, que pega el reporte LP > Entregas / Retornos de Maxinet (`reporte-entregas-retornos.php`, Tipo `RETORNOS`). Con el reporte más la lista de rentas activas (la copia del Query Sync) se arma lo mismo sin captura:

- Base de partida: el detalle de Nuvia (copia única del 5-oct, con respaldo previo). Desde ahí `actualizar_detalle_duracion_rentas()` (sync completo) agrega las devoluciones nuevas en orden de fecha de retorno y arriba del bloque ON HIRE. Es idempotente (una devolución se reconoce por placa+retorno o placa+PU) y sólo mira los 10 días anteriores a la última devolución cargada.
- Criterio v1: estatus `RETURNED`, efecto `SI APLICA` y que no sea la renovación del contrato del mismo cliente (la misma placa abre otro contrato con ese cliente el día de la devolución, +-1 día). Contra el detalle de Nuvia del 15-ago al 29-sep acierta 67 de 69; sobre todo 2026 el acuerdo baja (499 de 557), porque su captura histórica no sigue una regla única. El criterio exacto de Nuvia está pendiente de confirmar con ella.
- `EJECUTIVO`, `TARIFA` y `UNIFICADO` sólo existen mientras la renta está activa. La pestaña oculta `HISTORIAL ACTIVAS` guarda, por placa y fecha de recogida, los datos de cada renta activa en cada corrida (nunca borra). Si una devolución no está en el historial se busca la misma placa y cliente en el detalle; si tampoco, se agrega con esos campos vacíos y un aviso en el log.
- También se mantienen sin captura: las fórmulas por fila del bloque ON HIRE (hasta el final de la lista + 10 filas) y la fórmula `TIEMPO DE VIDA (RETORNOS)` del mes en curso. `MENSUAL` pasa a `=M*MIN(E,30)`, como en el archivo de Nuvia.
- Principio de independencia: ningún proceso lee el archivo de Nuvia; su versión sólo fue la base inicial.

### Reporte de flota de Maxinet con 41 columnas (2026-10-12)

El 9-oct Maxinet agregó `VIN` y `EntryDate` al final del reporte de flota (`reporte-flota-maxirent.php`, antes 39 columnas). El sync completo falló desde la tarde del 9-oct con `39 columns passed, passed data had 41 columns`, antes de tocar ninguna hoja, así que del 9 al 12 no se avanzaron las columnas diarias de `UTILIZACION V3` ni de `UTI. GRUPO DE AUTOS V1`.

- Script: `COLUMNAS` suma `VIN` y `EntryDate`, el rango de la base pasa de `B:AN` a `B:AP` (la base ya tenía las dos columnas insertadas en `AO` y `AP`, y el original de Nuvia igual) y, si el ancho vuelve a cambiar, el script se detiene con un mensaje claro antes de escribir. La descarga del reporte de flota reintenta si Maxinet corta la conexión.
- Tablero: Nuvia reestructuró `FLOTA LP` (importa `A:AS` de la base y los auxiliares `Placa`/`Entrie Data`/`Meses`/`Estatus` pasaron de `AR` a `AT`; `Entrie Data` ahora sale de `EntryDate` en vez de la tabla manual `Current Reg No`/`Entry Date`) y apuntó las fórmulas de `UTILIZACION V3` a `FLOTA LP!$AR:$AR` (`UNIDADES`, antes `AP`). Se hizo lo mismo en la copia: 2 columnas insertadas en `AR`, importación `A:AS`, `Entrie Data` por `EntryDate` y las filas 4, 5 y 22 de la columna viva leen `$AR`. Si no se cambian, esas filas leen `EntryDate` y todos los conteos salen en cero.
- Recuperación: Maxinet devuelve la foto de flota de cualquier fecha pasada (`Desde`=`Hasta`=fecha), así que los días 9, 10 y 11 de octubre se procesaron en orden con la foto de cada día. La columna del 8-oct, que se había congelado con ceros por las fórmulas viejas, se recalculó con la foto del 8-oct y se congeló otra vez. Resultado contra el archivo de Nuvia: cero diferencias del 8 al 9-oct en `UTILIZACION V3` y en `UTI. GRUPO DE AUTOS V1` del 8 al 11-oct; del 10 y 11-oct sólo difieren la fila 22 y la 43 (que la suma), porque la fórmula de la fila 22 de Nuvia todavía lee la columna `AP` (hoy `EntryDate`) y da 0.
- Límite de la recuperación: al reclasificar `OTROS` como cliente LP o CP, `leer_datos` usa la lista de `Rentas activas detalle` de hoy, no la del día recuperado.

### Fórmulas por fila del libro base (2026-10-12)

El mismo mantenimiento de las hojas de solo fórmulas se aplica ahora al libro base (`SPREADSHEET_ID`), después de revisar cada pestaña (lecturas de solo lectura, una por pestaña) y quedarse sólo con las que de verdad se quedaban cortas:

- `RESERVAS CP&LP!A` (GRUPO): fórmula por fila a la izquierda del bloque B:AN que el sync reescribe cada día. Terminaba en la fila 1705 y ya había reservaciones hasta la 1707 (más huecos después), así que esas filas salían sin GRUPO. `BLOQUES_FORMULAS_BASE` la mantiene con la columna B como guía y 40 filas de holgura; corre en el sync completo, después de `actualizar_sheet`.
- `Proyección de Mantenimientos!G` (promedio por periodo): F es un derrame de `UNIQUE(B:B)` y en la quincena en curso cada día es su propia fila, así que F gana unas 15 filas al empezar la quincena. G terminaba en la fila 33 con F ya en la 34. `BLOQUE_FORMULAS_PROYECCION_MTTO` la mantiene (guía F, holgura 20) al final de `actualizar_proyeccion_mantenimientos`, ya con PERIODO al día.
- Sin cambios: `ONHIRE` (las fórmulas llegan a la fila 1673 con datos hasta la 797), `UBICACIONES!J` (totales hasta la 1056 para 31 ubicaciones) y `GRAFICO` (tablas anuales fijas).
- Fuera de alcance, sin fuente automatizable conocida: los datos de `UBICACIONES!A:G` (reporte de GPS que se pega a mano) y el registro de `ENVIOS SEMINUEVOS` (1200 filas, llenas hasta el límite de la hoja, con MES y AÑO en AC:AD).

Las dos llamadas son secundarias: una falla (rango protegido, cuota) se registra como aviso y no detiene el sync. Como en el resto, nunca se borra ni se sobrescribe contenido.

### Query Sync: el Sheet destino pasa a "REPORTE TARIFA" (2026-10-12)

- Del 10-oct (~16:30 CDMX) al 12-oct (~12:45) la cuenta de servicio no tuvo acceso al Sheet destino (403 al abrirlo); fallaron Query Sync y BALANCE, que lee de ahí la flota. Antes de eso, desde el 8-oct, Query Sync ya fallaba por un filtro de usuario en `TARIFA (QUERY)` (`copyPaste` no admite filas filtradas).
- Al volver el acceso, el Sheet estaba rediseñado como "REPORTE TARIFA". `TARIFA (QUERY)`, `RESUMEN RENTA ACTIVAS` y `QUERY!P:R` son ahora fórmulas matriciales (`ARRAYFORMULA`/`LET`) que se calculan solas sobre `QUERY!A:O`. Se retiraron `TABLA RESUMEN`, `KAM`, `PROYECCION POR CLIENTE` y `TABLA TARIFA`.
- El script ya sólo escribe `QUERY!A2:O` y limpia las filas sobrantes de `A:O`. Se retiraron el espejo de reglas del archivo de Nuvia (además de fallar, su escritura en `QUERY!P2:T2` bloqueaba los derrames de `P1:R1` con `#REF!`), la extensión de fórmulas por fila y el ajuste de filas de TARIFA. Ya no se usa `SPREADSHEET_ID_ORIGINAL`. "Hoy" se calcula con la hora de CDMX.
- El acceso de la cuenta de servicio a este Sheet depende de que esté compartido con ella (ver la nota del 18-sep sobre la Unidad compartida). Si se cambia el modo de compartir, hay que volver a darle acceso de editor.

### Independencia del archivo de Nuvia: pestaña `TARIFA DETALLE` (2026-10-12)

Principio: ningún proceso ni tablero nuestro lee fórmulas o datos del archivo de Nuvia; su versión sólo sirve para comparar. La auditoría de los libros mostró una sola dependencia viva: la pestaña `Rentas activas detalle` del Tablero LP importaba (`IMPORTRANGE`) la `TARIFA (QUERY)` de su archivo, con 27 columnas y la estructura anterior al rediseño. De ella cuelgan unas 6,700 fórmulas del tablero (`Duración rentas`, `RESUMEN DE RENTAS ACTIVAS`, `PROXIMOS RETORNOS`) y el código del sync completo.

- **Pestaña propia.** `REPORTE TARIFA` tiene ahora `TARIFA DETALLE`, con las mismas 27 columnas y encabezados que la TARIFA vieja, calculadas con fórmulas matriciales sobre las pestañas del propio libro (`QUERY`, `ESTADOS`, `ROA`, `EJECUTIVOS`, `CONTRATOS`). Se ajusta sola al número de placas: no necesita script que extienda filas. Las columnas se alinean por la misma condición (línea `RENT` de `QUERY`).
- **Periodo.** La fecha de corte de "Duración avg (meses)" es `EOMONTH(TODAY(),0)`, el fin del mes en curso (antes se tecleaba a mano cada mes). Todo lo que depende de "hoy" se recalcula en cada apertura, así que sirve igual para corte diario, semanal o mensual.
- **PROX RETORNOS.** La regla de Nuvia (todo es "PROX. RETORNO" salvo los clientes que se extienden) quedó como lista editable en `TARIFA DETALLE!AE` en lugar de `IF` anidados; no se importa (sólo A:AB).
- **Contratos.** Se liga por nombre limpio (sin razón social), como en el rediseño de Nuvia.
- **Cliente no registrado.** Si un cliente aún no está en `EJECUTIVOS`, se agrupa con su propio nombre y no se calcula su duración (la TARIFA vieja mostraba `#N/A` y, con el default vacío, el resumen mostraba un renglón sin razón social con 1,544 meses).
- **Tablero LP.** `Rentas activas detalle!A2` importa ahora `TARIFA DETALLE!A:AB` de nuestro libro. Se concedió el acceso de `IMPORTRANGE` entre ambos y se probó antes en una pestaña temporal para que el tablero no pasara por `#REF!`. Respaldos en Drive previos al cambio.
- **Verificación.** Contra la TARIFA vieja de Nuvia, sobre las 780 placas comunes: `PRECIO SIN IVA`, `MENSUAL`, `ESTADO`, `GIRO`, `EJECUTIVO`, `MODELO`, `GRUPO`, `AGRUPACION`, `TIPO DE CUENTA`, `Duración avg`, `PROX RETORNOS` e `AGRUPADO` coinciden celda por celda. Lo que difiere es dato: 37 contratos con fecha de retorno posterior (se extendieron; su `QUERY` aún no lo refleja), 15 placas que entran o salen, 14 filas donde su TARIFA no tiene fórmula de `CODIGO` y la liga de contratos. El tablero queda sin errores; `PROXIMOS RETORNOS` de octubre baja de 28 a 12 por esas extensiones.

### UBICACIONES de la base mantenida por el sync (2026-10-12)

La pestaña `UBICACIONES` de la base (que importa la copia del Query en `ESTADOS` para el ESTADO de cada renta) ya no se pega a mano: el sync completo la actualiza con el reporte de flota y un glosario propio sembrado una vez con la tabla de Nuvia. Detalle y pendientes en `0006-ubicaciones-glosario-hibrido-e-independencia-rentas-activas.md`.

### Lista de rentas activas desde TARIFA DETALLE (2026-10-19)

El tablero LP se reestructuró entre el 17 y el 18-oct y desapareció la pestaña `Rentas activas detalle`, que era un espejo por `IMPORTRANGE` de `TARIFA DETALLE` de la copia del Query. El sync completo la leía antes de escribir nada (la lista de clientes LP para reclasificar el segmento `OTROS` y el historial de rentas activas), así que desde el 18-oct 9:01 cada intento terminó con `WorksheetNotFound: Rentas activas detalle` y no se avanzaron las columnas diarias de `UTILIZACION V3` ni de `UTI. GRUPO DE AUTOS V1` del 17 y 18-oct.

- Decisión: el sync lee `TARIFA DETALLE` directamente del archivo de la copia del Query (secret `SPREADSHEET_ID_QUERY`, el mismo del Query Sync) y ya no depende de ninguna pestaña intermedia del tablero. `_leer_tarifa_detalle()` valida el encabezado de las seis columnas que usa (`PLACA`, `EJECUTIVO`, `PU Date`, `PRECIO SIN IVA`, `CLIENTES`, `AGRUPADO`); si cambian de lugar, el sync se detiene sin escribir y dice qué columna esperaba. La fila 1 es el encabezado y los datos empiezan en la 2 (en el espejo empezaban en la 3).
- Verificación: las 803 placas y los 101 clientes de `TARIFA DETALLE` coinciden con los del `Rentas activas detalle` del original de Nuvia, sin un solo cliente distinto. Los días 17 y 18-oct se recuperaron en orden con la foto de flota de cada fecha (misma técnica que el 9 al 11-oct).
- Lista ON HIRE de `Duración rentas`: sus 814 filas con fórmulas por fila (`XLOOKUP` a la pestaña borrada y un `UNIQUE` en la columna B) quedaron en `#REF!`. Se reemplazaron por una sola fórmula matricial en la columna A, la misma idea que ya usa Nuvia en su archivo, que lee `TARIFA DETALLE` de la copia del Query con un `IMPORTRANGE` (sin pestañas intermedias) y derrama las 14 columnas del detalle: UNIFICADO (`AGRUPADO`), placa, PU Date, Return Date, DIA (hoy - PU), MES (DIA/30), status `ON HIRE`, cliente (`CLIENTES`), ejecutivo, grupo, modelo, periodo (primer día del mes en curso), tarifa diaria (`PRECIO SIN IVA`) y mensual. Contra la lista de Nuvia: las mismas 803 placas, sin diferencias de contenido. `formula_on_hire_desde_tarifa_detalle()` es la fuente única de esa fórmula.
- El sync reconoce las dos formas del bloque (`_localizar_on_hire()`): con la matricial no escribe debajo del ancla, porque pisaría el derrame; `DIA` y `PERIODO` de las filas ON HIRE salen de la fórmula y `asegurar_formulas_on_hire_duracion_rentas()` solo avisa si el ancla da error. Las devoluciones nuevas se siguen insertando arriba del ancla. El promedio `TIEMPO DE VIDA (ACTIVAS)` de este tablero usa rangos abiertos; el de Nuvia termina en la fila 2866 y su lista ON HIRE llega a la 3077, así que deja fuera cerca de 200 rentas.
- Bloques pivote de `RESUMEN` (utilización comercial y operativa por modelo): el 17-oct-2026, entre las 9:01 y las 11:43, el `RESUMEN` del tablero se movió 3 columnas a la izquierda y la corrida de las 11:43 copió la fila 1 de las columnas `Z:AP` sobre las filas 2 a 655, porque `extender_formulas_resumen()` tenía las letras de los bloques fijas (`Y:AP` y `AS:BJ`, las del archivo de Nuvia). Efecto: `AP2:AP657` quedaron con copias de la fórmula guía (`TRANSPOSE(UNIQUE(fila))` con la fila corrida), que bloquearon el derrame de `AP1` y dejaron ~11,700 celdas en `#REF!`; además `Z2:AM657` (14 modelos) quedaron con texto de encabezado en vez de las fórmulas `XLOOKUP` y `AO2:AO657` con un 2026 repetido. Se restauraron las fórmulas (mismo patrón que la columna `Y`, que no se tocó) y se limpiaron las copias; contra el `RESUMEN` de Nuvia los dos bloques coinciden en las 365 fechas comparadas, salvo una celda del 15-oct por 0.01 puntos.
- Corrección: los bloques se buscan por su fórmula guía (`=TRANSPOSE(UNIQUE('UTI. GRUPO DE AUTOS V1'!2:2))` en la fila 1) y abarcan las columnas contiguas con contenido en la fila 2. Además `extender_formulas_resumen()` nunca copia la fila 1 ni una fila con fórmulas de derrame y sólo pega en columnas cuyo destino está vacío (si no hay dónde, avisa y no escribe).

### Hojas renombradas y pasos auxiliares tolerantes (2026-10-20)

El 20-oct el tablero renombró `UTILIZACION V3` a `REPORTE DE FLOTA` y `UTI. GRUPO DE AUTOS V1` a `FLOTA POR GRUPO` (mismos datos). El sync busca esas dos hojas por el nombre guardado en los secrets `WORKSHEET_UTILIZACION` y `WORKSHEET_GRUPO_AUTOS`, así que las tres corridas de las 9:00 fallaron con `WorksheetNotFound`. Con los secrets actualizados la corrida siguiente avanzó las columnas diarias pero cayó en `TABLAS` (diseño nuevo de 68 columnas: un bloque quedó fuera de la hoja y `BK2` es un `=UNIQUE` de derrame) antes de escribir la base, y hubo que completar la base con la foto del 19-oct.

- La base se escribe justo después de avanzar las columnas diarias (el orden respeta que primero se congela la columna de ayer con los datos de ayer). Todo lo demás son pasos auxiliares (periodos y fórmulas de `RESUMEN`, `TABLAS`, fórmulas por fila, gráficos, `Duración rentas`): `_paso_auxiliar()` avisa en el log y como anotación de la corrida y el sync sigue.
- `TABLAS` (`_extender_bloques_formulas()`) tiene las mismas protecciones que `RESUMEN`: omite bloques que quedan fuera de la hoja, no copia una fila con fórmulas de derrame y sólo pega en columnas con el destino vacío. Antes habría copiado `BK2` (`=UNIQUE(RESUMEN!BK:BK)`) sobre las filas 3 a 37.
- La guía de los bloques pivote de `RESUMEN` se reconoce por su fórmula con cualquier nombre de pestaña (Sheets reescribe el nombre dentro de la fórmula al renombrar).
- Los nombres viven en el código (`PESTANA_UTILIZACION = "REPORTE DE FLOTA"`, `PESTANA_GRUPO_AUTOS = "FLOTA POR GRUPO"`); los secrets `WORKSHEET_UTILIZACION` y `WORKSHEET_GRUPO_AUTOS` son opcionales y los sobrescriben. `conectar_sheet_secundario()` acepta nombre o gid (el número tras `#gid=` en la URL, que no cambia al renombrar), prueba el alias conocido (el nombre de antes o el de ahora) y, si no encuentra la pestaña, el error dice cuántas tiene el libro y los nombres más parecidos (el repositorio y sus logs son públicos, así que no se vuelca el inventario completo). Recomendado: poner el gid en los dos secrets.
- La pestaña `TARIFA DETALLE` de la copia del Query (de donde sale la lista de rentas activas) tiene el mismo tratamiento: el secret opcional `WORKSHEET_TARIFA_DETALLE` (nombre o gid) la sobrescribe y, si no existe, el error dice cuántas pestañas tiene el archivo y los nombres más parecidos. Ojo: la fórmula ON HIRE de `Duración rentas` lleva el nombre `TARIFA DETALLE` dentro del `IMPORTRANGE`; si esa pestaña se renombra hay que actualizar también esa fórmula.
- `mantener_formulas_tablero()` y `mantener_graficos()` abrían el libro a través de la primera pestaña de su lista (`UTILIZACION POR GRUPO`, que ya no existe) y, al faltar esa sola pestaña, se omitía todo el mantenimiento por nombre del tablero. Ahora abren el libro sin depender de ninguna pestaña. `BLOQUES_FORMULAS_TABLERO` queda vacío: `UTILIZACION POR GRUPO` desapareció y `RESUMEN RENTA ACTIVAS` (antes `RESUMEN DE RENTAS ACTIVAS`) y `PROXIMOS RETORNOS` pasaron a fórmulas matriciales o `IMPORTRANGE` que se autoextienden. `GRAFICOS UTILIZACION` salió de la lista de gráficos porque la pestaña ya no existe.

### Revisión de los últimos días de la proyección de mantenimiento (2026-10-20)

Al comparar la base con la de Nuvia antes de repuntar `OPERACIONES` se encontró que la columna D de `Proyección de Mantenimientos` tenía tres días con la mitad del valor (6, 9 y 15-oct-2026: 3.58 %, 4.05 % y 4.10 % contra 7.16 %, 6.84 % y 7.95 %). La serie que Maxinet publica hoy coincide con la de Nuvia en esos días: Maxinet publicó un valor provisional y lo corrigió después. La captura sólo llenaba celdas vacías y nunca reescribía una, así que el valor provisional se quedaba para siempre (con `--forzar-mtto` se podía reescribir a mano, pero sólo por línea de comandos).

- Cada corrida contrasta ahora los últimos `VENTANA_REVISION_DIAS` (10) días ya escritos contra la serie de Maxinet y corrige los que difieren más de `TOLERANCIA_REVISION` (el Sheet guarda 4 decimales); lo avisa con un `WARNING` que lista las fechas. Los días más antiguos no se tocan y la fila de hoy tampoco, porque Maxinet la publica hasta mañana. Ya no se respetan ediciones manuales de esa ventana: la fuente es Maxinet.
- Corrección única de los días que ya estaban fuera de la ventana (comparación de los 292 días del año contra Maxinet): 6 y 9-oct (provisionales) y dos que la copia heredó del archivo de Nuvia, 11-ago (6.80 % donde Maxinet dice 6.08 %, dígitos cambiados) y 31-mar (0.56 % contra 0.55 %). Con eso la serie de la base coincide con la de Maxinet en los 292 días; el periodo `octubre 1` pasó de 6.49 % a 7.17 %.
- `OPERACIONES` (tablero) deja de leer `Proyección de Mantenimientos` y `UBICACIONES` de la base de Nuvia y lee las de nuestra base. La importación de la proyección pasó de `F1:G35` a `F1:G60`: la lista de periodos crece cada quincena (el 2026-10-20 ya llegaba a la fila 36) y el tope de 35 filas cortaba los últimos renglones. En `UBICACIONES` las fórmulas de `I:J` son idénticas; la diferencia está en `ONHIRE!G`: la de Nuvia busca la ubicación en la reserva de la placa (243 de 805 unidades salen como "SIN UBICACIÓN") y la nuestra en el estado de la placa (`UBICACIONES!F`, con el estado de Maxinet; 7 sin estado). Donde la de ella tiene ubicación coinciden en las 562 unidades, salvo el nombre del estado (`Coahuila` contra `Coahuila De Zaragoza`, `Michoacán` contra `Michoacán De Ocampo`).
- Se agregó a la proyección de la base la tabla de promedios mensuales que Nuvia tiene en `I27:J38` (`UNIQUE(A:A)` y `AVERAGEIFS`), con la fórmula en las 12 filas para que el mes que cierra no necesite arrastrarse a mano.

Pendiente detectado, sin cambiar: `actualizar_ubicaciones` escribe el odómetro de Maxinet aunque sea 0; en 40 placas la tabla de GPS de Nuvia tiene un kilometraje mayor que 0 y la nuestra quedó en 0.

### Horario de las 8:00 y corte de Maxinet (2026-10-21)

El sync completo del tablero LP pasa de las 9:00 a las 8:00 y la captura de proyección de mantenimiento de las 9:10 a las 8:10 (cron `0 14` y `10 14` UTC, ventanas del Vigilante `08:00` y `08:10`, aviso a las 08:30).

- Corte de Maxinet: sistemas confirmó que el corte diario es entre las 7:00 y las 7:30. Medido el 21-oct-2026 con el reporte de flota de cada fecha: el último mensaje de GPS de la foto de un día cae a las 06:27 del día siguiente (06:27:33 en la del 20-oct, 06:27:34 en la del 19-oct y 06:27:37 en la del 16-oct) y la foto de "hoy" viene vacía hasta que ocurre el corte. Es decir, la foto de la fecha D es la de la madrugada de D+1, no la de la medianoche, y a las 8:00 ya está generada.
- Disponibilidad a las 8:37 del 21-oct: foto de flota del 20-oct (1,691 filas, 41 columnas), % de vencimiento del 20-oct publicado y entregas y retornos del 20-oct. La captura de proyección llena solo los días cerrados que están vacíos, así que si a las 8:10 el histórico de un día aún no estuviera publicado, se llena en la corrida del día siguiente.
- La corrida de prueba del 21-oct se hizo con el código de esta rama.

### Todos los reportes entre las 8:00 y las 8:20 (2026-10-21)

El tablero LP (8:00 y 8:10), el Tablero CP y la Gestoría quedan dentro de la franja de las 8:00 a las 8:20, escalonados cada 5 minutos para no empalmar corridas en Maxinet: Entregas y Encuestas CP a las 8:05, Frecuentes Activos a las 8:10, Clientes Nuevos y Clientes Potenciales a las 8:15 y Gestoría a las 8:20 (después sigue su disparo cada hora). Query Sync y Balance empiezan su horario a las 7:30 (sus primeras corridas caen hacia las 7:40 y las 7:45) para que el tablero de las 8:00 ya tenga datos del día en lo que depende de ellos.

- El Vigilante lanza cada reporte con una sola función de ventanas (`ejecutarMatutino`, cada 5 minutos): a la hora de cada ventana lo dispara si no hay ya una corrida desde esa hora, reintenta hasta 3 veces y avisa si a las 8:45 no hay una exitosa. Los disparadores horarios de Apps Script no caen en el minuto exacto (llegan unos minutos antes o después de lo pedido), por eso la franja no se puede lograr con ellos.
- El cron de respaldo de GitHub de cada workflow se alineó a su ventana. Excepción: Clientes Nuevos conserva el de las 10:00, porque Maxinet importa ese reporte a las 9:00 y a las 9:40; lo importado hoy después de las 8:15 entra con la corrida de las 10:00 o con la del día siguiente.
