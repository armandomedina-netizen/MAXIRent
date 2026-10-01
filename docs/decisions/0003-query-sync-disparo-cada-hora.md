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
