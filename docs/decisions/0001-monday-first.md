# ADR 0001: Arquitectura monday-first

- Estado: aceptada
- Fecha: 2026-09-07

## Decisión

El sistema comenzará con WorkForms, boards, vistas, automatizaciones y dashboards nativos de monday.com. monday code será la primera opción para backend, scheduler, SLA, reminders, escalaciones, configuración, almacenamiento y logs.

Platform MCP y Apps MCP tendrán responsabilidades separadas. La infraestructura externa sólo se evaluará cuando exista un requerimiento que las capacidades nativas no puedan cubrir y la decisión quede documentada.

## Consecuencias

- Menor infraestructura operativa durante la validación.
- Los tiempos de SLA y reminders deben almacenarse como configuración, nunca como constantes dispersas.
- Los IDs reales se descubren por MCP y no se publican en este repositorio.
- Las operaciones sobre producción permanecen prohibidas sin autorización explícita.
