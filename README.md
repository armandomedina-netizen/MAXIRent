# Maxi Rent - Centro de Solicitudes

Proyecto para diseñar y desarrollar un centro interno de solicitudes sobre monday.com.

## Estado

Fase inicial de descubrimiento y arquitectura. No se crean ni modifican recursos productivos de monday desde este repositorio.

## Arquitectura inicial

```text
WorkForm -> monday board -> vistas nativas -> automatizaciones -> dashboard
                                                        |
                                                        v
                                      aplicación personalizada
```

La evolución prevista incorpora una monday App y monday code para SLA, recordatorios, escalaciones, configuración y logs antes de considerar infraestructura externa.

## Entorno local

Requisitos:

- Node.js 20 o superior; el proyecto fija Node 24.20.0 en `.nvmrc`.
- npm 11 o compatible.
- OpenAI Codex CLI.
- Acceso autorizado a monday.com.

Preparación:

```bash
nvm use
npm install
cp .env.example .env.local
```

No añadas tokens reales a archivos versionados. El Platform MCP utiliza OAuth almacenado localmente por Codex; el Apps MCP utilizará `MONDAY_TOKEN` sólo cuando esa fase sea autorizada.

## Seguridad

- Inspeccionar antes de proponer cambios.
- No eliminar recursos de monday sin autorización explícita.
- No modificar producción.
- Crear recursos de desarrollo sólo después de autorización.
- No publicar nombres, IDs, exports ni inventarios privados de la cuenta.

Las reglas completas para agentes están en [AGENTS.md](AGENTS.md).
