# MAXIRent

Desarrollo y gestión de proyectos MAXIRent.

## Centro Interno de Solicitudes

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

Clonar y preparar en una Mac nueva:

```bash
mkdir -p ~/Projects
git clone https://github.com/armandomedina-netizen/MAXIRent.git ~/Projects/maxi-rent-monday
cd ~/Projects/maxi-rent-monday
nvm install
nvm use
npm install
cp .env.example .env.local
```

No añadas tokens reales a archivos versionados. El Platform MCP utiliza OAuth almacenado localmente por Codex; el Apps MCP utilizará `MONDAY_TOKEN` sólo cuando esa fase sea autorizada.

## Codex y monday en cada Mac

Registrar y autenticar el Platform MCP oficial:

```bash
codex mcp add monday --url https://mcp.monday.com/mcp
codex mcp login monday
codex mcp list
```

Mientras el proyecto esté en fase de inspección, configura en `~/.codex/config.toml` una allowlist de sólo lectura:

```toml
[mcp_servers.monday]
url = "https://mcp.monday.com/mcp"
enabled_tools = ["get_user_context", "list_workspaces", "workspace_info", "get_board_info"]
```

Instalar las skills oficiales de monday y seleccionar **Codex** con alcance **Global** cuando el instalador lo solicite:

```bash
npx skills add mondaycom/skills
```

## Seguridad

- Inspeccionar antes de proponer cambios.
- No eliminar recursos de monday sin autorización explícita.
- No modificar producción.
- Crear recursos de desarrollo sólo después de autorización.
- No publicar nombres, IDs, exports ni inventarios privados de la cuenta.

Las reglas completas para agentes están en [AGENTS.md](AGENTS.md).
