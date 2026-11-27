# ADR 0034: Esperar a Maxinet antes de correr las automatizaciones

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

Maxinet es un servidor externo y único del que dependen todas las automatizaciones. El domingo 22-nov-2026 rechazó conexiones (`Connection refused`) durante varias horas y fallaron 22 workflows a la vez (71 corridas); el jueves 19-nov había pasado algo parecido durante unos 25 minutos (ADR 0033). Con las reglas de entonces:

- Cada corrida sólo reintenta la conexión alrededor de medio minuto (`Retry` de 5 intentos con `backoff_factor=2`).
- Las ventanas del Vigilante reintentan 3 veces con 5 minutos de por medio y se rinden.
- Los diarios se quedan sin datos hasta que el reloj de GitHub (a veces con horas de retraso) o alguien los relanza. El domingo, el sync diario del Tablero LP y del Tablero CP no corrió bien hasta las 14:41.
- Cada corrida fallida deja una marca roja en Actions: 71 en una sola mañana, todas con la misma causa, que tapan los fallos que sí hay que mirar.

## Decisión

Un paso común, `Esperar a Maxinet` (acción compuesta `.github/actions/esperar-maxinet`, script `esperar.sh`), como segundo paso de 19 workflows, justo después del checkout y antes de instalar dependencias:

- **Qué hace.** Pide `GET {MAXINET_BASE_URL}/` cada 30 segundos hasta que responde o se acaba la espera. "Arriba" es cualquier HTTP de 200 a 499 (el servidor atiende); una conexión rechazada, un tiempo agotado o un 5xx (la aplicación caída) cuentan como caído. Si vuelve, la automatización corre normalmente con una advertencia que dice cuánto esperó; si no, falla con `Maxinet no respondió en N min`, como antes pero tarde.
- **Cuánto espera.** 180 minutos los diarios y 40 los horarios (Query Sync, BALANCE, Expedientes LP, Gestoría y Órdenes Mtto), porque la siguiente corrida horaria ocupa su lugar. El `timeout-minutes` de cada job sube lo mismo (+5); el del sync completo, que ya incluía 120 minutos de espera de la foto de flota, queda en 335.
- **Qué no se imprime.** La URL de Maxinet es un secret: el script nunca la escribe en el log, sólo el código de `curl`, el HTTP y los minutos de espera (el primer aviso y luego uno cada 10 intentos).
- **Qué queda fuera.** La Guardia de actualización (debe reportar el estado real, no esperar), el cierre diario del Tablero CP (sólo usa Maxinet para reconstruir días y funciona sin él) y la Bitácora CP (su decisión sigue abierta, PR #70). Tampoco entran Tablero SAC, MKT Monday ni la ficha preliminar, que no usan Maxinet.
- **Sin cambios en los scripts.** Siguen con sus propios reintentos y salvaguardas; la espera sólo evita que arranquen contra un servidor caído.

## Consecuencias

- Una caída de hasta tres horas ya no deja corridas rojas ni datos atrasados: los diarios arrancan solos cuando Maxinet vuelve. Una más larga falla como hoy, y entonces el Vigilante (con su ventana ampliada, ver propuesta aparte) o una corrida manual la recuperan.
- Mientras espera, la corrida aparece como "en curso". El Vigilante no lanza otra (sólo lo hace si no hay ninguna en curso) y el resumen de las 8:45 la sigue contando como pendiente, que es lo cierto.
- Cada job que espera ocupa un runner. El repositorio es público (minutos de Actions gratis) y el límite de la cuenta gratuita es de 20 jobs simultáneos: con los 19 diarios y los horarios esperando a la vez, algunos hacen fila, pero ninguno se pierde y todos corren en cuanto Maxinet vuelve. La concurrencia de cada workflow (`cancel-in-progress: false`) limita las corridas pendientes a una por workflow.
- La Guardia espera como máximo 15 minutos a un relanzado: en una caída larga lo reportará como pendiente, que es lo cierto.
- No cubre que Maxinet responda pero no haya generado la foto de flota de un día (ADR 0033), ni un cambio de columnas del reporte.
- La sonda tiene pruebas con servidores HTTP reales en local (`automations/_comun/tests/test_esperar_maxinet.py`, dentro del proyecto `_comun` de `pruebas.yml`).
