# AGENTS.md

## Propósito

Construir **Maxi Rent - Centro de Solicitudes**, una herramienta interna sobre monday.com para registrar, asignar, seguir y resolver solicitudes, peticiones e incidencias de empleados.

Este repositorio es público. Nunca se debe versionar información confidencial, credenciales, exports de monday ni inventarios internos de nombres e IDs.

## Flujo obligatorio

Para cada etapa:

1. Diagnosticar el estado existente.
2. Informar brevemente los hallazgos.
3. Proponer la solución.
4. Ejecutar únicamente cuando sea seguro y esté autorizado.
5. Verificar el resultado.
6. Informar versiones, rutas y referencias importantes.
7. Documentar decisiones técnicas relevantes.

Ante un error, analizar la causa, corregirla y volver a verificar. No ocultar fallos ni usar soluciones temporales difíciles de mantener.

## Seguridad y monday

- Nunca eliminar recursos de monday sin autorización explícita.
- No modificar recursos productivos existentes.
- Inspeccionar recursos existentes antes de crear otros; no duplicarlos.
- No inventar board IDs, workspace IDs, column IDs, user IDs, app IDs ni group IDs.
- Obtener IDs reales mediante monday MCP y mantener los inventarios fuera del repositorio público.
- No incluir tokens en código, documentación, commits o archivos públicos.
- `MONDAY_TOKEN` se proporciona únicamente como variable de entorno local para Apps MCP.
- La configuración y las credenciales OAuth de Codex permanecen fuera del repositorio.

Mientras no exista autorización adicional, Platform MCP debe mantenerse restringido a herramientas de lectura. No crear, actualizar, eliminar, notificar ni ejecutar mutaciones GraphQL.

## Aislamiento obligatorio del desarrollo

Todos los proyectos, pruebas y recursos operativos asociados al desarrollo de aplicaciones deben mantenerse exclusivamente dentro del workspace de monday llamado exactamente `Desarrollo de Software`.

Antes de cualquier escritura en monday:

1. Localizar el workspace mediante Platform MCP y obtener su ID real.
2. Verificar inmediatamente antes de la operación que el nombre y el ID corresponden a `Desarrollo de Software`.
3. Identificar el recurso objetivo, su ID real si ya existe y su marca `DEV`, `TEST` o `SANDBOX`.
4. Informar la operación prevista y sus posibles efectos secundarios.
5. Detenerse si el workspace no existe, no es accesible, es ambiguo o no coincide. No crear un workspace alternativo sin autorización explícita.

Dentro de este workspace deben permanecer los boards, folders, WorkDocs, WorkForms y backing boards, dashboards, workflows, automatizaciones, datos de prueba y recursos auxiliares usados por la aplicación.

Está prohibido:

- Crear recursos de desarrollo en otros workspaces.
- Usar boards productivos como backing boards o fuentes de pruebas.
- Conectar workflows o automatizaciones de desarrollo con recursos operativos.
- Modificar, activar, desactivar, duplicar, mover o eliminar workflows existentes.
- Cambiar columnas, permisos, propietarios, vistas, grupos o automatizaciones de boards existentes.
- Suscribir una aplicación en desarrollo a eventos de boards productivos.
- Probar features o deployments sobre producción sin autorización explícita.
- Ejecutar una escritura cuando no se haya validado el workspace objetivo.

Las definiciones de monday Apps pueden existir a nivel de cuenta en el Developer Center. Aun así, todos los recursos y datos utilizados para desarrollar o probarlas deben permanecer en `Desarrollo de Software`.

## Separación de MCPs

### Platform MCP

Usar para datos operativos: workspaces, boards, groups, columns, items, users, forms, docs y estructura general. El endpoint remoto oficial es `https://mcp.monday.com/mcp` mediante Streamable HTTP y OAuth.

### Apps MCP

Usar, en una fase posterior y separada, para apps, features, versiones, deployments, environments, storage y promoción de versiones. Requiere `MONDAY_TOKEN`; comprobar la conexión antes de cualquier operación de escritura.

## Arquitectura por etapas

1. WorkForm -> monday board -> vistas nativas -> automatizaciones -> dashboard.
2. monday App -> monday code -> scheduler -> motor de SLA/reminders -> escalaciones.
3. monday MCP -> Codex -> otros agentes autorizados.
4. Claude API sólo cuando la empresa apruebe créditos y acceso API.

Antes de introducir Azure, AWS, Supabase, Railway, bases de datos externas, Dataverse o Power Apps, justificar por qué monday y monday code no cubren el requerimiento.

## Aplicación prevista

Nombre conceptual: **Maxi Rent - Centro de Solicitudes**.

Frontend preferido:

- React
- TypeScript
- monday SDK
- Vibe Design System

Backend preferido: monday code con Node.js o Python según el caso. Investigar monday code antes de proponer servicios externos.

Features potenciales: Custom Object, Board View, Item View, Dashboard Widget, Workflow blocks y Sidekick/AI Tools. No crearlas sin aprobación.

## Modelo operativo conceptual

Nombre de workspace de desarrollo preferido: `Maxi Rent - Desarrollo`.

Nombre de board de desarrollo preferido: `SOL_Solicitudes_DEV`.

Una solicitud equivale a un item. Columnas conceptuales:

- Solicitud
- Folio
- Solicitante
- Área
- Categoría
- Descripción
- Prioridad
- Estado
- Responsable
- Fecha creación
- Fecha requerida
- Último movimiento
- Último reminder
- Próximo reminder
- Nivel escalación
- SLA vencido
- Activa
- Adjuntos

Prioridades: Crítica, Alta, Media y Baja.

Estados iniciales: Nueva, Asignada, En proceso, En espera, Resuelta, Cerrada y Cancelada.

Las frecuencias de reminders y las reglas de pausa para `En espera` deben ser configurables. No hard-codear tiempos de SLA, reminders ni escalaciones.

## Convenciones de desarrollo

- Node.js 20 o superior; usar la versión de `.nvmrc`.
- TypeScript estricto para código nuevo.
- Separar configuración, lógica de negocio y adaptadores de monday.
- Mantener ambientes DEV claramente identificados.
- Incluir pruebas para reglas de SLA, reminders y transiciones de estado.
- No registrar tokens, datos personales ni payloads sensibles en logs.
