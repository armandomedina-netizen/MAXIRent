# Automatizaciones de Maxinet y Google Sheets

Mapa de los procesos que corren en GitHub Actions, de dónde sacan los datos, a dónde los escriben y qué hacer cuando algo cambia. El repositorio es público: aquí no van IDs de archivos, enlaces a Sheets, correos ni credenciales. Los nombres de los secrets sí, porque no revelan nada.

## Procesos

Horarios en hora de Ciudad de México (UTC-6, sin horario de verano). "Disparo externo" es el proyecto de Apps Script `Vigilante_Maxinet`, que lanza el workflow a su hora y avisa por correo si pasa mucho tiempo sin una corrida exitosa. Los avisos llegan a las dos personas que vigilan las automatizaciones, y cada día a las 8:45 el Vigilante envía además un resumen con el estado de las ocho corridas de la mañana y del tablero LP (todas en orden o cuáles fallaron). No está en el repositorio porque lleva el correo del equipo. El reloj de GitHub (`schedule`) llega entre 2 y 7 horas tarde, así que lo que depende solo de él no es puntual.

| Workflow | Qué hace | Horario | Disparo externo | Detalle |
|---|---|---|---|---|
| `maxinet-sync.yml` | Sync completo del tablero LP y de la base (flota, columnas diarias, duración de rentas y retornos, ubicaciones) y captura de la proyección de mantenimiento | 8:00 y 8:10 | Sí (ventanas de 8:00 y 8:10, hasta 3 reintentos) | ADR 0003 y 0006 |
| `maxinet-query-sync.yml` | Baja de Maxinet el cargo de reservas a la copia del Query | 7:40 y después cada hora, lunes a sábado desde las 8:00 | Sí (ventana de 7:40 y disparo cada hora) | ADR 0003 |
| `maxinet-balance.yml` | Entregas, retornos y solicitudes del BALANCE | 7:50 y después cada hora, lunes a sábado desde las 8:00 | Sí (ventana de 7:50 y disparo cada hora) | ADR 0004 |
| `gestoria-lp-cp-sync.yml` | Tickets de gestoría (todos los estatus) | 8:20 y después cada hora, lunes a sábado de 8:30 a 19:00 | Sí (ventana de 8:20 y disparo cada hora) | ADR 0005 |
| `tablero-sac.yml` | Solicitudes de monday (SAC) a Sheets | Cada hora, lunes a viernes de 7:20 a 17:20 y sábado hasta las 14:20 | Sí | `automations/TableroSAC/README.md` |
| `maxinet-clientes-nuevos-cp.yml` | Clientes nuevos del Tablero CP | 8:15 en el Vigilante; el reloj de GitHub lo repite a las 9:00 y a las 10:00, a veces con horas de retraso (Maxinet importa a las 9:00 y a veces a las 9:40) | Sí (ventana de 8:15) | ADR 0002 y 0003 |
| `maxinet-clientes-potenciales-cp.yml` | Clientes potenciales del Tablero CP | 8:15 | Sí (ventana de 8:15) | ADR 0002 |
| `maxinet-mtto-ordenes.yml` | Órdenes de mantenimiento LP: pestaña `ORDENES MTTO` de la Base LP copia con el mes corriente y las órdenes abiertas | 8:30 y después cada hora hasta las 17:30 (reloj de GitHub) | Pendiente (ventana de 8:30 por agregar) | ADR 0017 |
| `maxinet-entregas-cp.yml` | Entregas del Tablero CP (refresca el mes en curso) | 8:05 | Sí (ventana de 8:05) | ADR 0007 |
| `maxinet-encuestas-cp.yml` | Encuestas de satisfacción del Tablero CP | 8:05 | Sí (ventana de 8:05) | ADR 0009 |
| `maxinet-mkt-leads-cp.yml` | Leads externos (Prospectos CP): pestaña `MKT` de la Base CP copia con el mes en curso, estatus TODO (refresca el mes; el mes anterior los primeros 3 días) | 8:20 (reloj de GitHub) | Pendiente (ventana de 8:20 por agregar) | ADR 0019 |
| `maxinet-frecuentes-activos-cp.yml` | Clientes frecuentes activos (semana más reciente) | 8:10 | Sí (ventana de 8:10) | ADR 0008 |
| `tablero-cp-cierre-diario.yml` | Cierre diario de las columnas por día del Tablero CP copia: congela el día anterior, deja vivas las fórmulas del día nuevo y reconstruye desde Maxinet los días que falten | Cada hora al :27 (seguro); disparo exacto recomendado a las 8:25, después del sync que cambia la fecha de FLOTA CP | Por agregar en el Vigilante (8:25 y cada hora al :27) | ADR 0014 |
| `guardia-actualizacion.yml` | Segundo corte después del matutino: comprueba que la información de CP realmente se actualizó y relanza lo que falte | 10:30 (cron de respaldo a las 10:45) | Sí (ventana de 10:30) | ADR 0015 |
| `pruebas.yml` | Pruebas automáticas en cada PR y en cada integración a `main` | Al abrir un PR | No aplica | ADR 0011 |

Los horarios que aparecen en los ADR 0007, 0008 y 0009 (9:30 y 9:45) son los de cuando se escribieron; los vigentes son los de esta tabla.

## Secrets

Todos viven en Settings → Secrets and variables → Actions. Nada de esto se imprime en los logs.

- **Maxinet y Google:** `MAXINET_BASE_URL`, `MAXINET_USER`, `MAXINET_PASS`, `GOOGLE_CREDS_JSON` (cuenta de servicio; debe ser editora de los archivos que se escriben y de las pestañas protegidas).
- **Archivos de Sheets:** `SPREADSHEET_ID` (base LP), `SPREADSHEET_ID_SECUNDARIO` (tablero LP), `SPREADSHEET_ID_QUERY` (copia del Query), `SPREADSHEET_ID_BALANCE`, `SPREADSHEET_ID_GESTORIA`, `SPREADSHEET_ID_CLIENTES_NUEVOS` (base del Tablero CP) y `SPREADSHEET_ID_SAC`.
- **Pestañas con secret:** `WORKSHEET_NAME` (base), `WORKSHEET_FLOTA_LP`, `WORKSHEET_QUERY_NAME`, `WORKSHEET_CLIENTES_NUEVOS_NAME` y `WORKSHEET_CLIENTES_POTENCIALES_NAME`.
- **Pestañas opcionales** (si el secret no existe se usa el nombre por defecto del código; aceptan nombre o gid): `WORKSHEET_UTILIZACION`, `WORKSHEET_GRUPO_AUTOS`, `WORKSHEET_TARIFA_DETALLE`, `WORKSHEET_DURACION_ACTIVAS`, `WORKSHEET_DURACION_RETORNOS`, `WORKSHEET_ENTREGAS_NAME`, `WORKSHEET_ENCUESTAS_NAME`, `WORKSHEET_FRECUENTES_NAME` y `WORKSHEET_GESTORIA_NAME`. `WORKSHEET_MTTO_ORDENES` también es opcional pero sólo acepta el nombre (por defecto `ORDENES MTTO`), porque la automatización crea la pestaña en la Base LP copia (`SPREADSHEET_ID`) si no existe.
- **monday:** `MONDAY_TOKEN` y `MONDAY_SAC_SCHEMA_JSON` (solo Tablero SAC).
- `SPREADSHEET_ID_ORIGINAL` (el Query original de Nuvia) se eliminó el 22-oct-2026; ningún workflow lo leía desde el 12-oct.

## Qué hacer cuando algo cambia

**Renombraron una pestaña.** Las pestañas que el sync busca por secret (`WORKSHEET_UTILIZACION`, `WORKSHEET_GRUPO_AUTOS`, `WORKSHEET_TARIFA_DETALLE`, `WORKSHEET_DURACION_ACTIVAS`, `WORKSHEET_DURACION_RETORNOS`) aceptan el nombre o el gid, que es el número después de `#gid=` en la URL de la pestaña y no cambia al renombrarla. Con el gid en el secret un cambio de nombre ya no afecta. Si el nombre no existe pero hay otro igual salvo mayúsculas, acentos o espacios (`Duracion` / `Duración`), se usa ese y el log lo avisa. Si no hay ninguno, el error dice cuántas pestañas tiene el libro y los nombres más parecidos, sin volcar el inventario completo (los logs son públicos). Una fórmula que lleva el nombre de una pestaña dentro de un `IMPORTRANGE` sí se rompe al renombrarla y hay que corregirla en el Sheet.

**Movieron o borraron columnas.** Los lectores validan los encabezados que usan; si no coinciden se detienen sin escribir y el mensaje dice qué columna esperaban. Las extensiones de fórmulas hacia abajo (`RESUMEN`, `TABLAS`) nunca copian una fila de encabezados o con fórmulas de derrame (`UNIQUE`, `TRANSPOSE`, `FILTER`...) y solo pegan en columnas con el destino vacío. Letras de columna escritas a mano en el código son un riesgo cuando el tablero se reestructura: toda letra nueva debe pasar por esas protecciones.

**Un paso auxiliar falla.** Lo crítico del sync completo (descarga, avance de las columnas diarias y escritura de la base) va primero. `RESUMEN`, `TABLAS`, `HISTORIAL ACTIVAS`, `Duración retornos`, `Duracion de rentas` y los gráficos son pasos auxiliares: si fallan, el log y el resumen de la corrida llevan un aviso (`::warning`) y el sync sigue. Un aviso repetido hay que atenderlo; no se arregla solo.

**Un día se quedó sin procesar.** Maxinet devuelve la foto de flota de cualquier fecha pasada. El avance diario de las columnas debe recuperarse en orden, un día a la vez, y esperar a que la hoja de flota muestre la fecha antes de pasar al siguiente día (si no, se congela la columna con datos de otro día). Hoy el procedimiento se hace con un script local; está pendiente versionarlo.

**A qué hora hay datos nuevos.** Maxinet cierra la foto de flota del día anterior de madrugada (entre las 7:00 y las 7:30 según sistemas; el último mensaje de GPS de cada foto cae a las 06:27 del día siguiente). Por eso el sync completo corre a las 8:00: antes del corte la foto del día anterior todavía no existe y el reporte de "hoy" viene vacío.

**Sospechas de que algo no corre.** `gh run list --workflow <archivo>.yml --limit 10` muestra las últimas corridas, su evento (`schedule` o `workflow_dispatch`) y su resultado. Una corrida completa de `maxinet-sync.yml` que falla antes de escribir deja el tablero un día atrás.

## Trabajar en el repositorio

- Cada cambio va en una rama y un PR con las secciones Problema, Cambios, Verificación y Notas, sin firmas de herramientas. Antes de integrar se corre el workflow desde la rama y se pide la aprobación explícita.
- Pruebas locales: `cd automations/maxinet-sync && pip install -r requirements-dev.txt && python -m pytest tests -q`. Trabajan con hojas simuladas: no necesitan credenciales ni red.
- Las versiones de las dependencias están fijadas en cada `requirements.txt`. Para subirlas, se cambia la versión en un PR y se corren las pruebas y el workflow.
- Los procesos no leen archivos de terceros: sus archivos solo sirven para comparar. Una carga única desde un archivo ajeno es aceptable si queda documentada en un ADR.
