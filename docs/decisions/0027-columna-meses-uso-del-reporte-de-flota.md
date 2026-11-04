# ADR 0027: Columna "Meses uso" del reporte de flota

Fecha: 2026-11-04

## Contexto

El 4-nov-2026 Maxinet agregó una columna al final del reporte de flota (`reporte-flota-general.php`): **Meses uso**, después de `EntryDate`. La corrida de las 8:00 de ese día todavía traía 41 columnas y salió bien; la siguiente del sync completo (la del cron atrasado de GitHub, a las 14:36) falló sin escribir nada:

```
El reporte de flota trae [42] columnas y el script espera 41: Maxinet cambió la estructura
```

La falla era el candado de ancho del sync (es lo que debe pasar cuando Maxinet cambia la estructura: no pegar columnas corridas). De no corregirse, la corrida de las 8:00 del día siguiente habría fallado igual y la base y el Tablero LP se habrían quedado un día atrás.

`EntryDate` no es nueva: se agregó el 9-oct-2026 (junto con `VIN`) y ya estaba en todos los destinos (columna `AP` de la base; `FLOTA LP` y `FLOTA CP` la heredan). Sólo faltaba "Meses uso".

## Quién usa el reporte

Sólo dos procesos piden el reporte de flota a Maxinet (`includes/gpsrt/reporte-flota-maxirent.php`):

- `maxinet-sync` (cada mañana): escribe el bloque `B:AP` de `RESERVAS CP&LP` en la base; de ahí lo importan `FLOTA LP` (Tablero LP, `A:AS`) y `FLOTA CP` (Tablero CP, `A:AR`).
- `tablero-cp-cierre-diario` (`recuperar_dias.py`): descarga el reporte de un día pasado para reconstruir las columnas de `FLOTA CP` cuando el cierre no corrió.

## Decisión

1. **Se acepta el ancho de 42 columnas** y se sigue exigiendo exactamente ese ancho (41 o 43 siguen siendo "cambió la estructura"). Se prefiere fallar sin escribir a ignorar columnas desconocidas: una columna insertada a la mitad correría el bloque sin avisar.
2. **"Meses uso" no va en el bloque contiguo `B:AP`.** A la derecha de `AP` están las fórmulas del dueño de la hoja (`STATUS DISPONIBLE`, `UNIDADES`, `TIPO DE CUENTA LP`); escribir ahí las pisaría, y moverlas a la derecha cambiaría la letra de columnas que otros libros leen por letra (`FLOTA CP` importa `A:AR`, `FLOTA LP` importa `A:AS` y las fórmulas del tablero las citan). Por eso la columna se agrega **al final de la tabla**, después de `TIPO DE CUENTA LP` (columna `AT` de la base), y ninguna letra existente cambia.
3. **El sync la ubica por encabezado, no por letra.** `actualizar_columnas_fuera_del_bloque` busca "Meses uso" en la fila 1 de la base y escribe ahí, en el mismo orden de filas que el bloque (cada placa queda alineada). No escribe si el encabezado no existe, si cae dentro de `A:AP` o si la columna trae fórmulas. Es un paso auxiliar: la base ya está al día cuando corre y un problema de esta columna se avisa en el log y como anotación de la corrida, sin detener el sync.
4. **`FLOTA LP` la importa** (`A:AS` pasa a `A:AT`; se insertó una columna en `AT` para que el derrame no choque con la tabla de la hoja, `Placa`/`Entrie Data`/`Meses`/`Estatus`, que se recorre una columna a la derecha). **`FLOTA CP` no**: nadie la usa ahí y ampliar su importación movería columnas que el cierre diario usa por letra (`ESTATICAS`, `LATERAL`). Si se necesita, la forma sin riesgo es una segunda importación de una sola columna al final de la hoja.
5. **`recuperar_dias.py` acepta los 42 valores** y usa los 41 primeros (los que importa `FLOTA CP`, `E:AS`); el valor 42 no se mapea para no caer sobre las columnas estáticas que empiezan en `AT`.

## Consecuencias

- La corrida de las 8:00 trae la columna sola. Mientras el encabezado exista, no hay nada que mantener.
- Si Maxinet vuelve a agregar columnas al final del reporte, el sync fallará con el mismo mensaje (y sin escribir) hasta que se agreguen a `COLUMNAS`: el procedimiento está en `docs/automatizaciones.md`.
- La hoja `FLOTA LP` calcula sus propios "Meses" (`Entrie Data` contra la fecha del reporte, menos 1): con la columna de Maxinet ya disponible se pueden comparar o reemplazar; eso lo decide quien mantiene la hoja.
