# ADR 0016: Radar de cambios de Nuvia en nuestros libros

- Estado: aceptada
- Fecha: 2026-10-27

## Contexto

El 27 de octubre Nuvia empezó a ajustar nuestro Tablero CP copia: renombró `UNIDADES CP` como `REPORTE FLOTA CP` y `DETALLE` como `GRAFICOS` y eliminó `MENU PRINCIPAL`. El cierre diario, que buscaba su pestaña por nombre, falló desde las 10:32 (ADR 0014). Seguirá cambiando cosas, y las automatizaciones dependen de esa estructura; la intención es adaptarlas una vez que ella termine.

## Decisión

Un workflow horario (`radar-nuvia.yml`) vigila la estructura, no los datos, del Tablero CP y de la Base CP copia, y deja el resultado en la pestaña oculta `_RADAR` del Tablero.

- **Huella por pestaña:** nombre, identificador, oculta, número de columnas, filas y columnas congeladas, gráficas, protecciones, celdas combinadas, formatos condicionales, filtro, encabezados (filas 1 a 3) y patrones de las fórmulas de las primeras 60 filas. En los patrones las referencias de celda se generalizan, así que ni los datos que crecen ni la columna viva que avanza cada día cuentan como cambio. No cuenta las filas de datos.
- **Comparación por identificador de pestaña** contra la línea base: distingue un renombre de una pestaña nueva y otra eliminada, y dice qué encabezados cambiaron.
- **Estados:** `sin cambios`; `en curso` (la estructura cambió desde la corrida anterior: Nuvia sigue ajustando); `estable` (los cambios llevan 60 minutos sin moverse: hay que revisarlos). Así no se avisa a mitad de sus ajustes.
- **Aviso:** la guardia de actualización (ADR 0015) lee ese estado. Un cambio `estable` es un pendiente y llega por correo con el enlace de la corrida; si el radar deja de correr por más de 6 horas, la guardia lo marca como no verificado.
- **Detalle privado:** qué pestaña, qué cambió y qué automatización afecta (`IMPACTO`) quedan en `_RADAR`, que está oculta; el registro público del workflow sólo trae nombres de pestañas y conteos.
- **La línea base sólo se actualiza a propósito:** con el workflow `Radar Nuvia` y la opción `aceptar`, después de adaptar las reglas. Mientras no se acepte, la guardia sigue avisando.
- No escribe en los libros de trabajo; sólo en la pestaña oculta `_RADAR`. Reintenta ante 429.

## Qué se hizo ya con los cambios conocidos

- El cierre diario encuentra sus pestañas por identificador y no se rompe con renombres (ADR 0014).
- La guardia acepta el nombre nuevo de las pestañas ya renombradas (ADR 0015).
- La línea base se tomó el 27 de octubre con la estructura de ese día (29 pestañas del Tablero y 22 de la Base), que ya incluye esos tres cambios.

## Alcance y límites

- Vigila los dos libros que Nuvia ajusta (Tablero CP y Base CP copia). Las copias de LP, BALANCE, Query y Gestoría no están en el radar.
- Sólo ve estructura y encabezados: un cambio de contenido de una celda de datos no cuenta, por diseño. Los cambios del formato de números o de colores tampoco.
- Una fila de encabezados que cambia cada mes (por ejemplo, un mes escrito a mano) aparecerá como cambio de encabezados el día que cambie.
- Las reglas de las automatizaciones (por ejemplo, los nombres de pestañas de los secrets `WORKSHEET_*` de la Base) no se adaptan solas: el radar avisa y se adaptan a mano.
