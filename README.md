# mcp-jira-proxy

Dos archivos Python. Cero dependencias externas.

| Archivo | Qué hace |
|---|---|
| `jira_mcp_server.py` | Servidor MCP que conecta cualquier agente IA con la API de Jira Cloud |
| `mcp_proxy.py` | Proxy educativo que se interpone entre el agente y cualquier servidor MCP y escribe un log explicado de cada mensaje |

---

## jira_mcp_server.py

### Herramientas disponibles

| Tool | Descripción |
|---|---|
| `get_issue` | Detalle completo de un issue |
| `search_issues` | Búsqueda con JQL |
| `get_my_issues` | Issues asignados al usuario autenticado |
| `create_issue` | Crea una Task, Story, Epic… |
| `add_comment` | Añade un comentario |
| `transition_issue` | Mueve un issue a otro estado |
| `update_issue` | Actualiza título, descripción, prioridad o asignado |
| `get_projects` | Lista los proyectos accesibles |
| `get_issue_comments` | Lee los comentarios de un issue |

### Requisitos

Python 3.10+. No requiere `pip install`.

> **macOS:** el servidor carga automáticamente los certificados SSL del sistema desde `/etc/ssl/cert.pem`, resolviendo el problema habitual del instalador oficial de Python.

### Configuración en Claude Code

Genera un API token en [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) y añade esto a `~/.claude.json`:

```json
{
  "mcpServers": {
    "jira": {
      "type": "stdio",
      "command": "python3",
      "args": ["/ruta/absoluta/a/jira_mcp_server.py"],
      "env": {
        "JIRA_URL": "https://tu-empresa.atlassian.net",
        "JIRA_EMAIL": "tu@empresa.com",
        "JIRA_API_TOKEN": "tu-token"
      }
    }
  }
}
```

Reinicia Claude Code. Las herramientas aparecerán como `mcp__jira__get_issue`, `mcp__jira__create_issue`, etc.

---

## mcp_proxy.py

### Para qué sirve

Permite ver en tiempo real qué mensajes intercambian el agente y un servidor MCP, traducidos a lenguaje natural. Útil para entender el protocolo o depurar integraciones.

### Cómo funciona

Sin proxy, Claude Code lanza y habla directamente con el servidor MCP:

```
Claude Code  ──────────────────────────────→  jira_mcp_server.py  →  Jira
             (entrada "jira" en ~/.claude.json)
```

Con proxy, Claude Code lanza el proxy, y el proxy lanza el servidor real. El servidor Jira sigue siendo necesario — solo cambia quién lo arranca:

```
Claude Code  ──────────────→  mcp_proxy.py  ──→  jira_mcp_server.py  →  Jira
             (entrada          (lanzado por         (lanzado por
             "jira-proxy"      Claude Code)          el proxy)
             en ~/.claude.json)
                    │
                    ↓
             /tmp/mcp_jira.log
             (log explicado)
```

El proxy no modifica ningún mensaje. El agente recibe exactamente las mismas respuestas.

### Configuración en Claude Code

**Paso 1.** Elimina la entrada `jira` directa de `~/.claude.json` y añade `jira-proxy` en su lugar. Si los dos coexisten, Claude Code usará el directo y el proxy no recibirá ningún tráfico.

**Paso 2.** La entrada del proxy necesita los mismos parámetros que tenía el servidor directo, más tres variables propias (`MCP_PROXY_CMD`, `MCP_PROXY_ARGS`, `MCP_PROXY_LOG`):

```json
{
  "mcpServers": {
    "jira-proxy": {
      "type": "stdio",
      "command": "python3",
      "args": ["/ruta/absoluta/a/mcp_proxy.py"],
      "env": {
        "MCP_PROXY_CMD":  "python3",
        "MCP_PROXY_ARGS": "/ruta/absoluta/a/jira_mcp_server.py",
        "MCP_PROXY_LOG":  "/tmp/mcp_jira.log",
        "JIRA_URL":       "https://tu-empresa.atlassian.net",
        "JIRA_EMAIL":     "tu@empresa.com",
        "JIRA_API_TOKEN": "tu-token"
      }
    }
  }
}
```

> **Rutas con espacios:** si la ruta contiene espacios, escríbela entre comillas simples dentro del valor:
> `"MCP_PROXY_ARGS": "'/ruta/con espacios/jira_mcp_server.py'"`

**Paso 3.** Reinicia Claude Code.

**Paso 4.** En otro terminal, abre el log antes de empezar a usar el agente:

```bash
tail -f /tmp/mcp_jira.log
```

### Ejemplo de log

```
════════════════════════════════════════════════════════════
  MCP PROXY — sesión iniciada 2026-05-29 10:36:27
  Servidor real: python3 jira_mcp_server.py
════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────
[10:36:27.072]  🤝  Claude → Servidor   [initialize]
  HANDSHAKE — Claude se conecta al servidor
  Cliente: claude-code 2.1.156
  Versión del protocolo solicitada: 2025-11-25
  El servidor responderá confirmando qué tipos de primitivas soporta.
  Las tools concretas se piden en un mensaje tools/list separado.

────────────────────────────────────────────────────────────
[10:36:27.143]  ←  Servidor → Claude   [respuesta a initialize]
  ✅ Servidor identificado: jira v1.0.0
  Protocolo acordado: 2025-11-25
  Capacidades: tools (Claude puede llamar funciones)

────────────────────────────────────────────────────────────
[10:36:27.200]  📋  Claude → Servidor   [tools/list]
  CATÁLOGO — Claude pide las herramientas disponibles

────────────────────────────────────────────────────────────
[10:36:27.250]  ←  Servidor → Claude   [respuesta a tools/list]
  ✅ 9 herramientas registradas:
     • get_issue
     • search_issues
     • create_issue
     • ...

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

### Usar el proxy con otros servidores MCP

El proxy no contiene ningún código específico de Jira — funciona con cualquier servidor MCP con transporte stdio. Cambia `MCP_PROXY_CMD` y `MCP_PROXY_ARGS` para apuntar al servidor que quieras observar:

```json
"MCP_PROXY_CMD":  "uvx",
"MCP_PROXY_ARGS": "ableton-mcp",
"MCP_PROXY_LOG":  "/tmp/mcp_ableton.log"
```

El proxy es un wrapper **por servidor**, no un interceptor global. Cada servidor que quieras monitorizar necesita su propia entrada en `mcpServers`.

---

## El protocolo MCP

Lo que el proxy registra es el protocolo MCP en bruto: mensajes JSON-RPC 2.0 intercambiados por stdio. El flujo completo de una sesión:

```
Agente                    Servidor MCP              Sistema externo
  │                            │                          │
  │─── initialize ────────────→│                          │
  │←── {serverInfo, caps} ─────│                          │
  │─── tools/list ────────────→│                          │
  │←── [{name, description,    │                          │
  │      inputSchema}...] ─────│                          │
  │                            │                          │
  │─── tools/call ────────────→│─── HTTP / SDK / ... ────→│
  │    {name, arguments}       │                          │
  │                            │←── respuesta ────────────│
  │←── {content:[{text}]} ─────│                          │
```

El transporte habitual es stdio (el cliente lanza el servidor como subproceso). También existe HTTP/SSE para servidores remotos.
