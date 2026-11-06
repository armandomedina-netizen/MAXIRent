# ADR 0026: Retiro de las pestañas UBICACIONES, ONHIRE y GRAFICO de la Base LP

Fecha: 2026-11-03

## Contexto

El 2-nov-2026 se eliminaron de la Base LP copia, a propósito, las pestañas `GRAFICO`, `ONHIRE` y `UBICACIONES`. El sync completo escribía `UBICACIONES` todos los días (ADR 0006), así que desde la corrida de las 8:00 del 3-nov el log trae `UBICACIONES: no se pudo actualizar (WorksheetNotFound)`. Es un aviso y no detiene el sync (el paso era auxiliar), pero se repetiría cada día mientras el código busque una pestaña que ya no existe.

## Qué se revisó (3-nov-2026, solo lectura)

Se leyeron las fórmulas de la Base LP, del Tablero LP (41 pestañas), de la copia del Query (9) y de otros nueve libros enlazados desde el Tablero LP, buscando los nombres de las tres pestañas y cualquier `IMPORTRANGE` hacia la Base.

| Pestaña eliminada | Quién la leía | Efecto |
|---|---|---|
| `UBICACIONES` | Solo el paso del sync. Ninguna fórmula de los libros revisados la importa. | Ninguno fuera del aviso del log |
| `ONHIRE` | Solo la columna `AS` ("TIPO DE CUENTA LP") de `RESERVAS CP&LP`, un `XLOOKUP` por reserva: 3,232 celdas con error. `FLOTA LP` del Tablero LP las hereda porque importa la hoja completa; `FLOTA CP` del Tablero CP importa solo `A:AR` y no se afecta. Ningún proceso del repositorio lee ni escribe `AS` (el sync reescribe `B:AN`). | Errores visibles en esa columna |
| `GRAFICO` | Dos celdas de `GRAFICAS` del Tablero CP (`O53` y `O70`) importaban `GRAFICO!A1:C13` y `GRAFICO!I1:K13`: el bloque de envíos a seminuevos por mes (CP 2025 y 2026; CP, LP y TP 2026) que alimenta dos gráficos de seminuevos de CP. Eran fórmulas `COUNTIFS` sobre `ENVIOS SEMINUEVOS` (`MES`, `AÑO` y `BSite`), sin datos a mano. | Dos gráficos del Tablero CP muestran `#REF!`; son los 2 errores que la guardia reporta en `GRAFICAS` desde la corrida de las 17:41 del 2-nov |

Otros hallazgos:

- El ADR 0003 decía que `ESTADOS` (copia del Query) y `OPERACIONES` (Tablero LP) leían `UBICACIONES` de la Base. Hoy `ESTADOS` importa un resumen de GPS de otro libro y `OPERACIONES` solo importa `Proyección de Mantenimientos`: se repuntaron después.
- `ONHIRE` en `maxinet-balance` es una pestaña del libro BALANCE, y en `maxinet-query-sync` es el valor de filtro `Estatus=ONHIRE` de Maxinet. Ninguno es la pestaña eliminada y no cambian.
- Los procesos que abren la Base son `maxinet-sync`, `maxinet-mtto-ordenes`, `maxinet-expedientes-lp` y `maxinet-seminuevos-lp`, y solo leen o escriben `RESERVAS CP&LP`, `Proyección de Mantenimientos`, `ENVIOS SEMINUEVOS`, `ORDENES MTTO` y `EXPEDIENTES LP`.
- No se pudieron revisar cinco libros enlazados desde el Tablero LP a los que la cuenta de servicio no tiene acceso, ni la Base CP, cuyo identificador no aparece en esos enlaces.

## Decisión

1. Se retira del sync completo el paso de `UBICACIONES`: `actualizar_ubicaciones`, su cálculo (`calcular_ubicaciones`), las constantes y sus pruebas. No se deja una versión que omite el paso si la pestaña falta: la pestaña se eliminó a propósito, nadie la lee, y un paso que solo existe para no hacer nada es código que alguien tendría que explicar. Si se vuelve a necesitar, está en el historial (commit `77e30b6`, ADR 0006).
2. Los textos de `maxinet-seminuevos-lp` y su documentación dejan de decir que `GRAFICO` usa la hoja. El filtro `TODAS` (ADR 0024) se mantiene: la hoja conserva el historial de unidades vendidas y `MES` y `AÑO` siguen extendiéndose con sus fórmulas.
3. `maxinet-balance` y `maxinet-query-sync` no cambian.
4. Notas de "retirado" en los ADR 0003, 0006 y 0024, y un párrafo en `docs/automatizaciones.md` sobre qué pestañas de la Base usa cada proceso.

## Consecuencias

- El sync deja de avisar de `UBICACIONES`. El glosario manual de estados que vivía en esa pestaña se va con ella (se puede recuperar del historial de versiones de Sheets; ningún libro revisado lo lee).
- Quedan dos asuntos que no son de código y corresponden a quien mantiene cada libro: la columna `AS` de `RESERVAS CP&LP` (que hoy da error en la Base y en `FLOTA LP`) y los dos gráficos de seminuevos del Tablero CP, que perdieron su fuente. Mientras no se resuelvan, la guardia seguirá marcando `GRAFICAS: 2`, y con razón: los gráficos están rotos.
- Antes de eliminar o renombrar una pestaña de la Base conviene comprobar quién la importa: el Tablero CP importa de ella sin que el repositorio lo registre.
