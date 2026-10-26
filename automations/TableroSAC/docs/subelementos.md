# Subelementos de los tickets

Cada ticket del tablero de SAC puede tener subelementos en un tablero propio de monday. Miden el proceso por área (área responsable, estado, SLA, tiempos y fechas), así que son la parte del tablero que más interesa analizar. Esta página explica cómo se vuelcan en el Sheet, cómo se activan y qué pasa cuando algo falla.

## Qué se vuelca

La pestaña que el esquema declara con `hoja_subelementos` lleva una fila por subelemento:

- Las primeras columnas son datos del ticket, repetidos en cada fila de sus subelementos: su identificador (`padre_id`), su nombre (`padre_nombre`) y las columnas del ticket que se pidan con `padre_columna`, como la placa.
- La columna clave es el ID del subelemento (origen `id`). No se repite entre filas y es la que se cuenta para verificar la escritura.
- El resto son columnas del tablero de subelementos, con los mismos tipos y reglas de limpieza que las del ticket (README, "Reglas de datos"). Los reflejos y relaciones, por ejemplo los que traen datos del tablero de SLA, llegan como el texto de `display_value`, o en blanco si monday no los trae.

Las dos pestañas se relacionan por el identificador del ticket: un ticket tiene cero, uno o varios subelementos. Es la relación de uno a muchos de un modelo de BI: no se repiten las columnas del ticket en una tabla ancha ni se cuenta dos veces un ticket con dos subelementos. El cruce con otras fuentes usa una columna del ticket que viaja en ambas pestañas (hoy la placa; el VIN se agrega después, ver abajo).

La pestaña es un reflejo de monday: un ticket sin subelementos no genera filas, y si el ticket sale del grupo sus subelementos salen de la pestaña en la siguiente corrida. Un concentrado plano (ticket y subelemento en una sola tabla ancha) se puede derivar de estas dos pestañas y no forma parte de la sincronización.

### Varios subelementos en un mismo ticket

Cada subelemento tiene su propio ID en monday, distinto del ticket y de los demás subelementos. Un ticket con dos subelementos da dos filas: las dos con el mismo identificador de ticket (y la misma placa), cada una con su ID de subelemento. Por eso la clave de la pestaña es el ID del subelemento y la relación con la pestaña de tickets va por el identificador del ticket; la placa sirve para cruzar con otras fuentes, no para distinguir subelementos.

## Cómo se lee

Los subelementos viajan en la misma consulta GraphQL del ticket: cada elemento trae sus columnas y, anidado, `subitems` con las columnas del esquema de subelementos. No hay una consulta por ticket, y los datos del ticket que se copian a cada fila salen de ese mismo elemento. El costo medido es de unos 350 puntos de complejidad por ticket; con páginas de 100 queda muy por debajo del límite por consulta, y el ajuste automático del tamaño de página ya existente cubre los casos raros.

La API devuelve una lista vacía para un ticket sin subelementos. Si la clave `subitems` falta o viene nula, la respuesta es incompleta: se informa el error y la pestaña no se escribe, en lugar de vaciarla.

## Esquema

El grupo declara la pestaña y la sección `subelementos` define el tablero y las columnas (el resto del esquema no cambia):

```json
{
  "grupos": [
    { "hoja": "Pestana A", "grupo_id": "grupo_a", "periodica": true, "hoja_subelementos": "Pestana S" }
  ],
  "subelementos": {
    "tablero_id": 1000000002,
    "columnas": [
      { "encabezado": "Folio", "origen": "padre_id", "tipo": "numero" },
      { "encabezado": "Solicitud", "origen": "padre_nombre" },
      { "encabezado": "Estado del ticket", "origen": "padre_columna", "columna_id": "col_estado" },
      { "encabezado": "ID subelemento", "origen": "id", "tipo": "numero", "clave": true },
      { "encabezado": "Subelemento", "origen": "nombre" },
      { "encabezado": "Estado", "columna_id": "sub_estado" }
    ]
  }
}
```

| Origen | Valor de la columna |
|---|---|
| `columna` | una columna del tablero de subelementos (`columna_id`) |
| `nombre` | el nombre del subelemento |
| `id` | el ID del subelemento (tipo `numero`) |
| `creado` | la fecha y hora de creación del subelemento, en hora de Ciudad de México (tipo `fecha`); marca cuándo empezó el trabajo de esa área |
| `en_marcha` | "Sí" o "No" según el cronómetro de una columna de seguimiento de tiempo (`columna_id`) esté corriendo |
| `padre_id` | el ID del ticket (tipo `numero`), el identificador que relaciona las pestañas |
| `padre_nombre` | el nombre del ticket |
| `padre_columna` | una columna del ticket (`columna_id`); no tiene que estar en la pestaña de tickets |

El esquema se rechaza antes de tocar monday o Sheets si `hoja_subelementos` aparece sin la sección `subelementos`, si el tablero de subelementos es el mismo que el de tickets, si falta una columna `padre_id`, si la clave no es una sola columna con origen `id`, o si una pestaña (de tickets o de subelementos) se repite. `schema.example.json` trae el formato completo con IDs de mentira.

## Crear la pestaña (una sola vez)

El sincronizador nunca crea pestañas ni cambia su estructura. La pestaña de subelementos se crea a mano en el libro:

1. Una pestaña con el mismo nombre que `hoja_subelementos`.
2. En la fila 1, los encabezados de `subelementos.columnas`, idénticos y en el mismo orden. Con otros encabezados el sincronizador no escribe nada en esa pestaña.
3. Filas suficientes: si faltan, el sincronizador agrega las necesarias y repite el formato de la última fila.
4. Formatos de las columnas de fecha (`yyyy-mm-dd hh:mm` si traen hora) y duración (`[h]:mm:ss`), y la fila 1 fija. Las celdas se escriben con tipo, así que el formato es lo único que decide cómo se muestran.
5. La cuenta de servicio como editora del libro, como en las demás pestañas.

## Activación, en este orden

1. Mezclar en `main` el código que lee subelementos. Con el secret de esquema anterior se comporta como antes: sólo sincroniza tickets.
2. Crear la pestaña (arriba) y comprobar sus encabezados.
3. Con el esquema local actualizado, correr `python monday_sac_sync.py --periodicas --dry-run --comparar` y revisar los conteos de las dos pestañas; después una corrida real y una segunda para confirmar que no cambia nada.
4. Actualizar el secret `MONDAY_SAC_SCHEMA_JSON` con el contenido de `private/monday-sac-schema.min.json` y revisar la primera corrida de Actions.

El orden importa: con el secret nuevo y sin la pestaña, la corrida marca error en la pestaña de subelementos (los tickets siguen sincronizándose). Con el código anterior y el secret nuevo la corrida se detiene antes de leer, porque el formato nuevo no lo reconoce.

Para desactivar basta quitar `hoja_subelementos` del grupo en el secret: los tickets siguen igual y la pestaña de subelementos queda como estaba.

## Qué pasa cuando algo falla

| Situación | Resultado |
|---|---|
| La pestaña de subelementos no existe o tiene otros encabezados | falla sólo esa pestaña, sin escribir; los tickets se sincronizan |
| El tablero de subelementos no es visible o falta una de sus columnas, o una columna del ticket que se copia a las filas | falla la pestaña de subelementos; los tickets se leen y se sincronizan sin subelementos |
| monday no devuelve bien los subelementos (clave `subitems` ausente o nula, error de lectura) | igual que arriba: los tickets se leen aparte y se sincronizan, la pestaña de subelementos queda como estaba |
| No hay lectura de tickets | ninguna de las dos pestañas se toca |
| Una pestaña de tickets con encabezados distintos | falla sólo esa pestaña; la de subelementos se sincroniza |
| monday devuelve 0 subelementos y la pestaña tiene más de 20 filas | no se vacía sin `--aceptar-vacio` |
| El ID de un subelemento aparece dos veces en la lectura | se escribe una vez y el repetido se cuenta en el log |
| Al terminar, la pestaña no tiene las filas que trajo monday | error de verificación en esa pestaña |

En todos los casos la corrida termina con código 1 si alguna pestaña quedó con error, y el log sólo lleva conteos.

## Agregar una columna del ticket a las filas (el VIN)

Es sólo configuración: una columna más con origen `padre_columna` en `subelementos.columnas` y el encabezado correspondiente en la pestaña. No hace falta que la columna esté en la pestaña de tickets.

Insertar la columna en medio de la pestaña desplaza las siguientes: entre el cambio en el Sheet y la actualización del secret, la verificación de encabezados detiene la escritura de esa pestaña sin dañar nada. Conviene hacer los dos cambios en una ventana sin corridas (el domingo no corre ninguna) o agregar la columna al final.

## Verificación manual

- `python monday_sac_sync.py --periodicas --dry-run --comparar` cuenta las filas de monday y las compara con la pestaña, por columna, sin imprimir valores.
- El número de filas de subelementos debe ser igual a la suma de los subelementos de los tickets del grupo; se puede comprobar con una consulta GraphQL de sólo lectura que cuente los `subitems` de cada ticket.
- Los cronómetros y las fórmulas que dependen de la hora actual cambian solos entre una corrida y otra: es lo esperado.
