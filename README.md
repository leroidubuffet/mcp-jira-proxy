# mcp-jira-proxy

Dos herramientas para trabajar con servidores MCP (Model Context Protocol) en Claude Code:

- **`jira_mcp_server.py`**: Servidor MCP para Jira Cloud. Sin dependencias externas (Python stdlib puro).
- **`mcp_proxy.py`**: Proxy MCP educativo. Se interpone entre Claude y cualquier servidor MCP, deja pasar todo sin modificarlo y escribe un log en lenguaje natural de cada mensaje del protocolo.

---

## jira_mcp_server.py

### Herramientas expuestas

| Tool | Descripción |
|---|---|
| `get_issue` | Detalle completo de un issue de Jira |
| `search_issues` | Búsqueda con JQL |
| `get_my_issues` | Issues asignados al usuario autenticado |
| `create_issue` | Crea una Task, Bug, Story o Epic |
| `add_comment` | Añade un comentario a un issue |
| `transition_issue` | Mueve un issue a un nuevo estado |
| `update_issue` | Actualiza título, descripción, prioridad o asignado |
| `get_projects` | Lista los proyectos accesibles |
| `get_issue_comments` | Lee todos los comentarios de un issue |

### Configuración

Añade esto a `~/.claude.json`:

```json
{
  "mcpServers": {
    "jira": {
      "type": "stdio",
      "command": "python3",
      "args": ["/ruta/a/jira_mcp_server.py"],
      "env": {
        "JIRA_URL": "https://tu-empresa.atlassian.net",
        "JIRA_EMAIL": "tu@empresa.com",
        "JIRA_API_TOKEN": "tu-token"
      }
    }
  }
}
```

Si no tienes uno, genera un API token en [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

### Requisitos

Python 3.10+ (usa `dict | None` en las firmas de tipo). No requiere `pip install`.

> **Nota macOS:** el servidor resuelve automáticamente el problema de certificados SSL del instalador oficial de Python en macOS, cargando los certificados del sistema desde `/etc/ssl/cert.pem`.

---

## mcp_proxy.py

Un proxy transparente que registra cada mensaje del protocolo MCP en lenguaje natural. Útil para entender qué ocurre exactamente cuando Claude llama a una herramienta.

### Cómo funciona

```
Claude Code → [mcp_proxy.py] → [servidor MCP real]
                    ↓
             /tmp/mcp_jira.log  (log en lenguaje natural)
```

El proxy no modifica ningún mensaje. Claude recibe exactamente las mismas respuestas que recibiría hablando directamente con el servidor real.

### Configuración

Sustituye el servidor real por el proxy en `~/.claude.json`:

```json
{
  "mcpServers": {
    "jira-proxy": {
      "type": "stdio",
      "command": "python3",
      "args": ["/ruta/a/mcp_proxy.py"],
      "env": {
        "MCP_PROXY_CMD": "python3",
        "MCP_PROXY_ARGS": "/ruta/a/jira_mcp_server.py",
        "MCP_PROXY_LOG": "/tmp/mcp_jira.log",
        "JIRA_URL": "https://tu-empresa.atlassian.net",
        "JIRA_EMAIL": "tu@empresa.com",
        "JIRA_API_TOKEN": "tu-token"
      }
    }
  }
}
```

| Variable | Descripción |
|---|---|
| `MCP_PROXY_CMD` | Comando para lanzar el servidor real (obligatorio) |
| `MCP_PROXY_ARGS` | Argumentos del servidor real separados por espacios |
| `MCP_PROXY_LOG` | Ruta del fichero de log (por defecto `/tmp/mcp_proxy.log`) |

### Ver el log en tiempo real

En otro terminal:

```bash
tail -f /tmp/mcp_jira.log
```

### Ejemplo de salida

```
════════════════════════════════════════════════════════════
  MCP PROXY — sesión iniciada 2026-05-29 10:36:27
  Servidor real: python3 jira_mcp_server.py
════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────
[10:36:27.072]  🤝  Claude → Servidor   [initialize]
  HANDSHAKE — Claude se conecta al servidor
  Cliente: Claude Code 1.0
  Versión del protocolo solicitada: 2024-11-05
  El servidor responderá con sus capacidades y las tools que expone.

────────────────────────────────────────────────────────────
[10:36:27.143]  ←  Servidor → Claude   [respuesta a initialize]
  ✅ Servidor identificado: jira v1.0.0
  Protocolo acordado: 2024-11-05
  Capacidades: tools
  A partir de aquí Claude puede pedir el catálogo y llamar tools.

────────────────────────────────────────────────────────────
[10:36:28.301]  ⚡  Claude → Servidor   [tools/call]
  LLAMADA — Claude ejecuta una herramienta
  Tool:       create_issue
  Argumentos: {"project_key": "SCRUM", "summary": "Bug en el login"}

────────────────────────────────────────────────────────────
[10:36:28.613]  ←  Servidor → Claude   [respuesta a tools/call / create_issue]
  ✅ Resultado de 'create_issue'
     Issue creado: SCRUM-7
  ⏱  312 ms
```

### Compatible con cualquier servidor MCP

El proxy no es específico de Jira. Apunta `MCP_PROXY_CMD` y `MCP_PROXY_ARGS` a cualquier servidor MCP con transporte stdio:

```json
"MCP_PROXY_CMD": "npx",
"MCP_PROXY_ARGS": "-y @modelcontextprotocol/server-filesystem /tmp"
```

---

## El protocolo MCP en un diagrama

```
Claude Code               Servidor MCP              Sistema externo
    │                          │                           │
    │── initialize ───────────→│                           │
    │←─ {capacidades} ─────────│                           │
    │── tools/list ───────────→│                           │
    │←─ [{nombre, schema}...] ─│                           │
    │── tools/call ───────────→│── HTTP / SDK / socket ───→│
    │                          │←─ respuesta ──────────────│
    │←─ {content: [{text}]} ───│                           │
```

El transporte es stdio (pipe de subproceso) o HTTP/SSE. El proxy intercepta el lado izquierdo de este diagrama.
