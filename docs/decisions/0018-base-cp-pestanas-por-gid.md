# ADR 0018: Las automatizaciones de la Base CP encuentran su pestaña por gid

- Estado: aceptada
- Fecha: 2026-10-28

## Contexto

Nuvia renombra pestañas de nuestra copia de la Base mientras reorganiza el archivo. El 28 de octubre, entre las 8:00 y las 8:10, Clientes Nuevos, Clientes Potenciales y Entregas fallaron con `WorksheetNotFound` porque sus secrets (`WORKSHEET_*_NAME`) apuntaban a los nombres anteriores (`Reporte Generales Clientes Nuevo`, `Reporte Clientes Potenciales CP`, `ENTREGAS`). Encuestas y Frecuentes Activos siguieron funcionando sólo porque esas pestañas no se renombraron. Era el mismo riesgo que ya se había resuelto en el cierre diario del Tablero (ADR 0014) y en el sync de LP.

## Decisión

- Las cinco automatizaciones (`maxinet-clientes-nuevos-cp`, `maxinet-clientes-potenciales-cp`, `maxinet-encuestas-cp`, `maxinet-entregas-cp`, `maxinet-frecuentes-activos-cp`) resuelven su pestaña con `resolver_pestana`: si el valor del secret es un número es el gid (el número tras `#gid=` en la URL, que no cambia al renombrar) y se abre con `get_worksheet_by_id`; si no, es un nombre, como hasta ahora. El valor por defecto sigue siendo el nombre de siempre.
- Si la pestaña no existe, el error dice qué se pidió y cuántas pestañas tiene el libro, sin volcar sus nombres (los logs son públicos).
- Clientes Potenciales ahora también tolera comillas y espacios en el secret, igual que las demás.
- La guardia de actualización recibe los secrets de Entregas, Encuestas y Frecuentes además de los de Clientes, porque corre cada script en `DRY_RUN` con su mismo entorno.
- Los secrets de estas cinco pestañas se llenan con el gid, no con el nombre. Los gids no se versionan: viven sólo en los secrets.
- La guardia deja de revisar `ENTREGAS POR SUCURSAL`, que Nuvia eliminó del Tablero.

## Consecuencias

- Un renombre de pestaña ya no detiene las automatizaciones, siempre que el secret lleve el gid. Una pestaña eliminada o recreada sí cambia su gid y requiere actualizar el secret.
- La lógica está repetida en cada módulo, igual que el resto del código de conexión, para que cada automatización siga siendo independiente. Una prueba común (`maxinet-entregas-cp/tests/test_pestana_por_gid.py`) la ejerce en los cinco módulos.
- Las fórmulas `IMPORTRANGE` del Tablero que citan una pestaña de la Base por nombre no se actualizan solas al renombrarla; eso depende de los ajustes de Nuvia y no lo cubre este cambio.
