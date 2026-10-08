# Decisiones: sincronización monday -> Google Sheets (TableroSAC)

Fecha: 2026-10-07. Estado: código y pruebas listos; primera sincronización real de la pestaña periódica hecha el 7-oct; horario aprobado y pendiente de activar.

## Contexto

El tablero de tickets de SAC de monday alimenta dashboards y análisis desde un Google Sheet con una pestaña por grupo del tablero. Tres pestañas se cargaron a mano desde un chat; un chat no puede mover las más de mil filas del grupo de tickets resueltos, y la carga manual no se repite sola. El Sheet debe tener siempre la misma estructura (mismas columnas, mismo orden) y refrescarse de forma idempotente.

## Decisiones

1. **Carpeta y rama propias.** Todo el proyecto vive en `automations/TableroSAC/` y se desarrolla en la rama `monday-sac-sync`, creada desde `origin/main`. No modifica archivos de las demás automatizaciones; el único archivo compartido que toca es `.gitignore` (sólo agrega líneas).

2. **El esquema con IDs reales no se versiona.** El repositorio es público y `AGENTS.md` prohíbe versionar inventarios de nombres e IDs de monday. El código es genérico; el tablero, los grupos y las columnas se leen de `private/monday-sac-schema.json` (ignorado por git) o del secret `MONDAY_SAC_SCHEMA_JSON` en Actions. `schema.example.json` documenta el formato con IDs de mentira y las pruebas usan datos sintéticos.

3. **Lectura directa de la API GraphQL.** La herramienta MCP `get_board_items_page` falla con las columnas reflejadas, así que se usan `items_page` y `next_items_page` con los fragmentos que exponen `display_value`, páginas de 100 y cursor. Se pide sólo `column_values` de las columnas del esquema. Si monday responde que la consulta excede la complejidad por consulta, la página se reduce a la mitad hasta un mínimo; ante 429, 5xx, cortes de red o presupuesto de complejidad agotado se reintenta con espera. La versión de la API se fija en `2026-07` (la vigente el 7-oct-2026; `2025-04` ya está en mantenimiento).

4. **Antes de leer, se valida el esquema contra el tablero.** Una columna o grupo que ya no existe detiene la corrida: de otro modo una columna borrada en monday dejaría una columna del Sheet en blanco sin avisar.

5. **Escritura con tipo (`RAW`).** Números como números, fechas y duraciones como número de serie y el resto como texto literal. Con `USER_ENTERED`, Sheets reinterpreta el texto libre: un texto que empiece con `=`, `+` o `-`, o que parezca número o fecha, se convierte en fórmula, número o fecha. En las columnas de fecha, duración y número el valor resultante es el mismo que dejó la carga previa: los números de serie coinciden con los de las filas ya cargadas, y la comparación contra la pestaña lo confirma por columna.

6. **Escribir primero y limpiar después.** Las filas nuevas se escriben de A2 hacia abajo y sólo después se borran los valores sobrantes, de modo que los dashboards nunca ven la pestaña vacía a media corrida. Al final se cuenta el número de filas de la pestaña y debe coincidir con el de monday.

7. **Protecciones.** No se escribe si la fila 1 difiere del esquema. No se crean ni borran pestañas. No se vacía una pestaña de más de 20 filas cuando monday devuelve 0 elementos, salvo con `--aceptar-vacio`. Al ampliar una pestaña se repite el formato de la última fila para que las filas nuevas conserven los formatos de fecha y duración.

8. **Registro sin datos.** Los logs de Actions de un repositorio público los ve cualquiera: sólo se imprimen conteos, y un filtro enmascara el token, el ID del Sheet y el ID del tablero por si el mensaje de una librería los trae. La comparación contra lo que ya hay en la pestaña cuenta celdas distintas por columna sin imprimir valores.

9. **Una sola pestaña periódica.** Nuvia indicó que sólo una de las tablas es de interés y que funciona como un estatus: lo que haya en monday es lo único que se proyecta. El esquema marca esa pestaña con `periodica` y la opción `--periodicas` sincroniza sólo las marcadas, de modo que el workflow público no lleva nombres de pestañas. La pestaña es un reflejo exacto del grupo: lo que sale del grupo desaparece en la siguiente corrida. Las demás pestañas del esquema se sincronizan sólo si se piden por nombre.

10. **Horario.** Entre una actualización y la siguiente pasan a lo más 2 horas y la información del día está lista antes de las 10:00. De lunes a viernes corre a las 7, 9, 11, 13, 15 y 17 h; el sábado a las 7, 9, 11 y 13 h más una corrida de cierre a las 14:00; el domingo no corre. El disparo exacto lo hace un Apps Script que llama a `workflow_dispatch`, porque los `schedule` de GitHub se retrasan y a veces se saltan, y el cron del workflow (cada hora a los 20 minutos) queda como seguro. `tests/test_programacion.py` comprueba que ambos cumplen el requisito.

## Verificación de la primera corrida (7-oct)

- `--dry-run --comparar` antes de escribir: las 13 filas de monday coinciden con las 13 de la pestaña, en el mismo orden. De las 36 columnas sólo difieren las dos de duración, por exactamente la misma cantidad de horas en las 13 filas (el tiempo que los cronómetros corrieron desde la carga manual); no hay diferencias de tipo.
- Sincronización real: 13 filas escritas y 13 con datos en la pestaña después. Una segunda corrida dio los mismos conteos. La estructura de la pestaña (columnas, fila fija, color) y los formatos de fecha y duración quedaron intactos.

## Pendiente

- Carga de las demás pestañas: pendiente, no se ha pedido (la de tickets resueltos tiene más de mil filas).
- Activar la programación: faltan los secrets del repositorio, mezclar la rama en `main` y crear los disparadores de Apps Script (pasos en `programacion.md`).
- El Sheet destino tiene el acceso general "cualquier persona con el enlace" como lector y contiene datos de clientes; queda a decisión del dueño del archivo.
