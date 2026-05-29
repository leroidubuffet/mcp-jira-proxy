# mcp-jira-proxy

Dos archivos Python. Cero dependencias externas.

| Archivo | Que hace |
|---|---|
| `jira_mcp_server.py` | Servidor MCP que conecta cualquier agente IA con la API de Jira Cloud |
| `mcp_inspector.py` | Proxy educativo que se interpone entre el agente y cualquier servidor MCP y escribe un log explicado de cada mensaje |

---

## jira_mcp_server.py

### Herramientas disponibles

| Tool | Descripcion |
|---|---|
| `get_issue` | Detalle completo de un issue |
| `search_issues` | Busqueda con JQL |
| `get_my_issues` | Issues asignados al usuario autenticado |
| `create_issue` | Crea una Task, Story, Epic... |
| `add_comment` | Anade un comentario |
| `transition_issue` | Mueve un issue a otro estado |
| `update_issue` | Actualiza titulo, descripcion, prioridad o asignado |
| `get_projects` | Lista los proyectos accesibles |
| `get_issue_comments` | Lee los comentarios de un issue |

### Requisitos

Python 3.10+. No requiere `pip install`.

> **macOS:** el servidor carga automaticamente los certificados SSL del sistema desde `/etc/ssl/cert.pem`, resolviendo el problema habitual del instalador oficial de Python.

### Configuracion en Claude Code

Genera un API token en [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

Abre `~/.claude.json` y anade la seccion `mcpServers` con esta entrada:

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

Reinicia Claude Code. Las herramientas apareceran como `mcp__jira__get_issue`, `mcp__jira__create_issue`, etc.

---

## mcp_inspector.py

### Para que sirve

Permite ver en tiempo real que mensajes intercambian el agente y un servidor MCP, traducidos a lenguaje natural. Util para entender el protocolo o depurar integraciones.

### Como funciona

Sin proxy, Claude Code lanza y habla directamente con el servidor MCP:

```
Claude Code  ──────────────────────────────>  jira_mcp_server.py  ->  Jira
             (entrada "jira" en ~/.claude.json)
```

Con proxy, Claude Code lanza el proxy, y el proxy lanza el servidor real:

```
Claude Code  ────────────>  mcp_inspector.py  ──>  jira_mcp_server.py  ->  Jira
             (entrada         (lanzado por        (lanzado por
             "jira-proxy"     Claude Code)         el proxy)
             en ~/.claude.json)
                    |
                    v
             /tmp/mcp_jira.log
             (log explicado)
```

El proxy no modifica ningun mensaje. El agente recibe exactamente las mismas respuestas.

### Configuracion en Claude Code

**Paso 1.** Localiza la entrada `jira` en `~/.claude.json`. Tiene este aspecto:

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

Borra esa entrada completamente. Si la entrada `jira` y la entrada `jira-proxy` coexisten en el archivo, Claude Code usara el servidor directo y el proxy no recibira ningun trafico.

**Paso 2.** Anade la entrada del proxy en su lugar. Necesita las mismas variables de entorno que tenia el servidor directo (`JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`), mas tres variables propias del proxy (`MCP_PROXY_CMD`, `MCP_PROXY_ARGS`, `MCP_PROXY_LOG`):

```json
{
  "mcpServers": {
    "jira-proxy": {
      "type": "stdio",
      "command": "python3",
      "args": ["/ruta/absoluta/a/mcp_inspector.py"],
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

> **Rutas con espacios:** si la ruta contiene espacios, escríbela entre comillas simples dentro del valor de `MCP_PROXY_ARGS`:
> `"MCP_PROXY_ARGS": "'/ruta/con espacios/jira_mcp_server.py'"`

**Paso 3.** Reinicia Claude Code.

**Paso 4.** En otro terminal, abre el log antes de empezar a usar el agente:

```bash
tail -f /tmp/mcp_jira.log
```

### Ejemplo de log

```
============================================================
  MCP PROXY -- sesion iniciada 2026-05-29 10:36:27
  Servidor real: python3 jira_mcp_server.py
============================================================

------------------------------------------------------------
[10:36:27.072]  Handshake   Claude -> Servidor   [initialize]
  HANDSHAKE -- Claude se conecta al servidor
  Cliente: claude-code 2.1.156
  Version del protocolo solicitada: 2025-11-25
  El servidor respondere confirmando que tipos de primitivas soporta.
  Las tools concretas se piden en un mensaje tools/list separado.

------------------------------------------------------------
[10:36:27.143]  <-  Servidor -> Claude   [respuesta a initialize]
  Servidor identificado: jira v1.0.0
  Protocolo acordado: 2025-11-25
  Capacidades: tools (Claude puede llamar funciones)

------------------------------------------------------------
[10:36:27.200]  Catalogo   Claude -> Servidor   [tools/list]
  CATALOGO -- Claude pide las herramientas disponibles

------------------------------------------------------------
[10:36:27.250]  <-  Servidor -> Claude   [respuesta a tools/list]
  9 herramientas registradas:
     * get_issue
     * search_issues
     * create_issue
     * ...

------------------------------------------------------------
[10:36:28.301]  Llamada   Claude -> Servidor   [tools/call]
  LLAMADA -- Claude ejecuta una herramienta
  Tool:       create_issue
  Argumentos: {"project_key": "SCRUM", "summary": "Bug en el login"}

------------------------------------------------------------
[10:36:28.613]  <-  Servidor -> Claude   [respuesta a tools/call / create_issue]
  Resultado de 'create_issue'
     Issue creado: SCRUM-7
  310 ms
```

### Usar el proxy con otros servidores MCP

El proxy no contiene ningun codigo especifico de Jira. Funciona con cualquier servidor MCP con transporte stdio. Cambia `MCP_PROXY_CMD`, `MCP_PROXY_ARGS` y `MCP_PROXY_LOG` para apuntar al servidor que quieras observar:

```json
"MCP_PROXY_CMD":  "uvx",
"MCP_PROXY_ARGS": "ableton-mcp",
"MCP_PROXY_LOG":  "/tmp/mcp_ableton.log"
```

El proxy es un wrapper por servidor, no un interceptor global. Cada servidor que quieras monitorizar necesita su propia entrada en `mcpServers`.

---

## El protocolo MCP

Lo que el proxy registra es el protocolo MCP en bruto: mensajes JSON-RPC 2.0 intercambiados por stdio. El flujo completo de una sesion:

```
Agente                    Servidor MCP              Sistema externo
  |                            |                          |
  |--- initialize ------------>|                          |
  |<-- {serverInfo, caps} -----|                          |
  |--- tools/list ------------>|                          |
  |<-- [{name, description,    |                          |
  |      inputSchema}...] -----|                          |
  |                            |                          |
  |--- tools/call ------------>|--- HTTP / SDK / ... ---->|
  |    {name, arguments}       |                          |
  |                            |<-- respuesta ------------|
  |<-- {content:[{text}]} -----|                          |
```

El transporte habitual es stdio: el cliente lanza el servidor como subproceso y se comunica con el por stdin/stdout. Para servidores remotos existe HTTP/SSE.
