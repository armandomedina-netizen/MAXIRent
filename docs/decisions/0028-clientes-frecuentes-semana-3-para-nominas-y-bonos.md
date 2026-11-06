# ADR 0028: Pestaña "Clientes frecuentes Semana 3" para nóminas y bonos

- Estado: aceptada
- Fecha: 2026-11-06

## Contexto

Para calcular nóminas y bonos se usa el reporte de Clientes Frecuentes Activos tal como está en la tercera semana de cada mes, no la semana más reciente. La pestaña `Clientes Frecuentes Activos 35` de la Base CP (ADR 0008) se reemplaza cada vez que Maxinet publica una semana; un archivo con la semana 3 se pegaba a mano (`CLIENTES FRECUENTES 3RA SEMANA`, con la semana del 17-oct).

## Hallazgos que fijan el diseño

- El reporte `cp-reporte-clientes-frecuentes-activos-v2.php` tiene un selector "Semana" cuyas opciones son sábados. Maxinet publica cada opción siete días después de su fecha (la del 17-oct apareció el sábado 24-oct y la del 24-oct el sábado 31-oct, medido con el historial de corridas), con la foto cerrada en la madrugada del sábado. Hay cortes irregulares de fin de mes que no son sábado (2026-08-31, 2026-09-04, 2026-01-07).
- Por eso el tercer viernes del mes todavía no existe la semana que termina de armar los tres cortes (en octubre, los sábados 3, 10 y 17): se publica el sábado siguiente al cuarto viernes.

## Decisión

- Nueva pestaña `Clientes frecuentes Semana 3`, clonada de `Clientes Frecuentes Activos 35` (mismo formato, columnas y fórmula `TIPO`), en el mismo libro. La pestaña que se pegaba a mano no se toca.
- La automatización es la misma (`maxinet_frecuentes_activos_cp.py`) en modo `SEMANA_DEL_MES=3`, con su propio workflow (`maxinet-frecuentes-semana3-cp.yml`, diario a las 8:15) y grupo de concurrencia. Elige la semana más reciente del selector que sea el N-ésimo sábado de su mes (día 15 a 21 para la 3), la carga una vez y la deja congelada hasta que se publique la del mes siguiente. Si la hoja ya trae esa semana (según la nota "Semana cargada: N (fecha)") no descarga ni escribe; `FORZAR=1` la refresca y `PERIODO=<id>` fija otra.
- Elegir "la tercera más reciente publicada" en lugar de depender de un día de la semana hace que la carga ocurra sola el día en que Maxinet publica la semana, se recupere sola si un día falla y deje, mientras tanto, la semana 3 del mes anterior, que es lo que se usa para la nómina.
- Mismas protecciones que la pestaña normal: columnas validadas, no escribe si el reporte trae menos de la mitad de los clientes, `Comentario` manual respetado.
- El nombre por defecto de la pestaña en este modo es `Clientes frecuentes Semana 3`, de modo que un secret faltante nunca hace escribir la semana 3 sobre `Clientes Frecuentes Activos 35`. Se recomienda el secret `WORKSHEET_FRECUENTES_SEMANA3_NAME` con el gid.

## Consecuencias

- La pestaña de octubre se llena con la semana del 17-oct (semana 194) en la primera corrida. La de noviembre (sábado 21) se cargará sola cuando Maxinet la publique, el sábado 28-nov.
- Si en algún momento se necesita otra semana del mes (la 2, la 4), basta otro workflow con `SEMANA_DEL_MES` distinto.
