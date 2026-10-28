# ADR 0015: Guardia de actualización, segundo corte después del matutino

- Estado: aceptada
- Fecha: 2026-10-27

## Contexto

El Vigilante (Apps Script) da por buena una automatización cuando su workflow termina en éxito. Eso no demuestra que la información se actualizó: el 26 de octubre la corrida de las 8:18 de Clientes Nuevos terminó bien con 0 filas, porque Maxinet publica ese reporte a las 9:00 o a las 9:40, y quedaron 7 clientes sin cargar hasta una corrida manual.

## Decisión

Un workflow (`guardia-actualizacion.yml`) corre a las 10:30, después de que termina el matutino y de las dos importaciones de Maxinet, y comprueba el resultado y no la corrida.

- **Verificación con las propias automatizaciones.** Para Clientes Nuevos, Clientes Potenciales, Encuestas, Entregas, Frecuentes Activos y el cierre diario del Tablero corre el modo `DRY_RUN` de cada script, que calcula qué le falta a la hoja frente a Maxinet sin escribir nada, y lee cuántas filas, columnas o semanas faltan. De esa manera aplica exactamente las mismas reglas de duplicados y de llaves que la automatización, y no una copia de ellas.
- **Corrección relanzando el workflow, no escribiendo.** Si falta algo, la guardia dispara el workflow de esa automatización, espera a que termine y vuelve a comprobar. Así la escritura pasa por el grupo de concurrencia de cada workflow y nunca hay dos procesos agregando filas al mismo tiempo, que podría duplicarlas. La guardia no escribe en ninguna hoja.
- **Resultado de cada revisión:** `OK`, `RECUPERADO` (faltaba algo y quedó al día tras relanzar), `PENDIENTE` (sigue faltando), `SIN DATOS` (FLOTA CP no trae la fecha de ayer) o `NO VERIFICADO` (la corrida en seco no se pudo leer). Una salida que no se entiende nunca se da por buena.
- **Además:** comprueba que `FLOTA CP` traiga los datos de ayer, que el cierre diario no tenga columnas pendientes y que 14 pestañas clave del Tablero no tengan celdas con error. Las pestañas con errores conocidos que no son de nosotros (`NOMINA` y `DISPONIBLE+TALLER`) quedan fuera.
- **Reglas de lectura:** en Entregas sólo cuentan las altas y las bajas del bloque del mes; los estatus cambiados no, porque cambian durante el día. Una corrida que no termina con el mensaje de éxito de su script es `NO VERIFICADO`.
- **Código de salida:** 1 si al final algo sigue pendiente, sin datos o sin verificar. El Vigilante de Apps Script dispara la guardia a las 10:30, reintenta una vez si falla y avisa por correo, con el enlace de la corrida, si termina sin éxito. El resumen queda en el resumen del job de GitHub, sin datos de clientes.
- **Pestañas renombradas (2026-10-27):** la lectura de errores acepta el nombre de siempre o el que Nuvia ya les puso (`ALIAS_PESTANAS`: `UNIDADES CP` es hoy `REPORTE FLOTA CP` y `DETALLE` es `GRAFICOS`); si una pestaña no se encuentra, lo informa en lugar de fallar. Estos nombres se actualizan cuando Nuvia termine sus ajustes.
- **Reintentos de Sheets:** la lectura de errores del Tablero reintenta con espera creciente ante 429, porque la cuota de lecturas por minuto se comparte con las demás automatizaciones.

## Alcance

Cubre la familia de CP y el cierre del Tablero. No cubre todavía Tablero LP, BALANCE, Query Sync ni Gestoría, que ya tienen sus propias ventanas y reintentos en el Vigilante. Agregar una revisión nueva es agregar una `Revision` con su lector de salida.

## Verificación

- 24 pruebas con ejecutor y relanzador simulados (`automations/guardia-actualizacion/tests`, en el workflow `Pruebas`): lectores de salida con muestras reales de los logs, relanzar y recuperar, pendiente tras relanzar, relanzado que falla, salida ilegible, Tablero sin datos del día, cierre pendiente, errores en pestañas, reintentos y código de salida.
- Corrida real del 27-oct (sin relanzar): Clientes Nuevos, Potenciales, Encuestas y Frecuentes al día; el Tablero con los datos del 26; sin errores en las 14 pestañas; y un pendiente genuino en Entregas (una entrega que Maxinet quitó después del corte de la mañana).

## Consecuencias

- La guardia corre los scripts en seco y puede relanzar hasta seis workflows: son unos minutos de Actions por día en un repositorio público.
- Encuestas, Clientes Potenciales y Entregas pueden aparecer como `RECUPERADO` casi todos los días, porque llegan encuestas, clientes y cambios después del corte de la mañana. No es una falla.
- Si Maxinet no publica un reporte a las 10:30, la guardia lo marca `PENDIENTE` y avisa; mañana a las 8:00 corre el corte normal.
