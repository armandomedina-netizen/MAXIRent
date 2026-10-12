# 0006 - UBICACIONES con glosario híbrido y camino hacia Rentas activas detalle independiente de Nuvia

Fecha: 2026-10-12

## Contexto

La hoja `Rentas activas detalle` del tablero LP es un `IMPORTRANGE` del Query ORIGINAL de Nuvia (`'TARIFA (QUERY)'!A:AB`). La alimentan `RESUMEN DE RENTAS ACTIVAS`, `PROXIMOS RETORNOS`, `Duración rentas` (filas ON HIRE), `HISTORIAL ACTIVAS` y el sync. Si Nuvia deja de actualizar o de compartir ese archivo, el tablero queda con una lista de rentas vieja. El principio fijado es que ningún proceso en producción depende de sus archivos; su versión sólo sirve para comparar.

La fuente propia ya existe: el Query Sync baja cada hora el Cargo de Reservas de Maxinet a la pestaña `QUERY` de nuestra copia, cuya pestaña `TARIFA (QUERY)` tiene las mismas fórmulas que la de Nuvia salvo la columna `X`. Faltaban cuatro piezas para poder apuntarle el tablero:

- `X` (PROX RETORNOS): Nuvia marca como próximo retorno todo lo que no está en su lista "SE EXTIENDE"; la copia sólo marcaba los retornos del mes en curso.
- `TABLA RESUMEN!B1` (fecha de corte): Nuvia la cambia a mano al fin de mes.
- `EJECUTIVOS!Q…`: la copia importaba `Duración rentas` del tablero original.
- `ESTADOS` → columna `B` (ESTADO): la copia importaba `UBICACIONES!A:G` de la base ORIGINAL, una tabla de GPS que Nuvia pega a mano (la nuestra iba unas tres semanas atrasada).

## Decisión

1. Cadena objetivo: Maxinet → Query Sync (`QUERY`) → `TARIFA (QUERY)` de la copia → `Rentas activas detalle`. El repunte del tablero se hace sólo cuando la copia del Query tenga la regla `X` de Nuvia, la fecha de corte automática y sus importaciones `ESTADOS` y `EJECUTIVOS` apuntando a nuestra base y a nuestro tablero. Esa parte (rama `query-sync-filtros`, PR #5) queda fuera de este cambio.
2. `UBICACIONES` de la base pasa a mantenerse sola. `actualizar_ubicaciones()` corre en el sync completo con el reporte de flota que ya se descarga y escribe por placa: último mensaje (B), kilometraje = odómetro (C), `RT` en GPS (E) sólo si estaba vacío y el reporte lo marca, y estado (F) con el campo `Estado` de Maxinet.
3. Glosario híbrido manual-automático. Cuando Maxinet no trae `Estado` para una placa, se conserva el valor que ya hay en F: es el glosario propio, que se completa a mano hasta tener la extracción de los proveedores de GPS (los accesos están en trámite). La localización (D) nunca se toca; los totales de la derecha (`I:J`) y la fórmula `=TODAY()-B` de G se conservan, y las placas nuevas se agregan al final con esa fórmula.
4. Nombres de estado: Maxinet escribe `Coahuila`, `Michoacán` y `Ciudad de México`; la tabla histórica usa `Coahuila De Zaragoza`, `Michoacán De Ocampo` y `Ciudad De México`. Se normalizan para que el ranking de unidades por estado no cuente dos veces el mismo estado.
5. Una placa puede aparecer en dos filas (bloque `RT` y bloque `VIRTUAL`: 25 casos en la tabla de Nuvia). Se actualizan todas las filas de la placa, de modo que la búsqueda por la primera coincidencia nunca vea datos viejos.
6. Semilla única (2026-10-12): la tabla de Nuvia (1,648 filas) más las 43 filas de 42 placas que sólo tenía la nuestra se cargaron una sola vez como glosario inicial, con respaldo previo. Desde entonces la tabla es nuestra y ningún proceso lee la de Nuvia. Es el mismo precedente que el detalle de `Duración rentas` y el historial de NUEVAS.
7. Un fallo al actualizar `UBICACIONES` se registra como aviso y no detiene el sync (misma política que el resto de las hojas secundarias). El log sólo informa conteos.

## Verificación (2026-10-12)

- Dos corridas seguidas del sync completo desde la rama: la primera dejó 1,873 placas (182 nuevas, 1,560 con estado de Maxinet, 99 del reporte sin estado en el glosario); la segunda, 0 nuevas y 0 actualizadas.
- Contra la tabla de Nuvia (del 6-oct): 1,621 placas comunes, 220 con otro estado (sobre todo unidades que se movieron en la semana) y 99 sin estado en el glosario, 11 de ellas con renta activa.
- Los totales de `UBICACIONES!I:J` y las fórmulas de G siguen intactos.

## Consecuencias y pendientes

- Las unidades sin estado en el glosario (hoy 99, 11 en renta) se completan a mano en la columna F; el valor escrito se conserva en las corridas siguientes mientras Maxinet no lo traiga.
- Cuando lleguen los accesos a los proveedores de GPS se reemplaza la parte manual por una extracción, y D (localización) podrá actualizarse también.
- `UBICACIONES` y `ONHIRE` están protegidas en la base: la cuenta de servicio debe seguir como editora de `UBICACIONES`.
- Sigue pendiente repuntar `Rentas activas detalle` (y después `GRAFICOS UTILIZACION`, `OPERACIONES`, `DETALLE BALANCE` y `SINIESTROS`) a nuestros archivos.
