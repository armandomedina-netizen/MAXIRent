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
