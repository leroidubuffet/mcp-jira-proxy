"""
Servidor MCP para Jira Cloud.
Sin dependencias externas — usa solo stdlib (urllib, json, base64).

Configuración (variables de entorno):
  JIRA_URL        https://tu-empresa.atlassian.net
  JIRA_EMAIL      tu@empresa.com
  JIRA_API_TOKEN  token generado en id.atlassian.com/manage-profile/security/api-tokens
"""

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

def _build_ssl_context() -> ssl.SSLContext:
    # En Windows y Linux, create_default_context() encuentra los certs del sistema.
    # En macOS (instalador oficial de Python) no los encuentra — hay que cargarlos.
    ctx = ssl.create_default_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    # Rutas de certificados por sistema operativo
    import platform
    cert_paths = {
        "Darwin": ["/etc/ssl/cert.pem"],
        "Linux": [
            "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu
            "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL/Fedora
            "/etc/ssl/ca-bundle.pem",               # openSUSE
        ],
    }
    for path in cert_paths.get(platform.system(), []):
        if os.path.exists(path):
            ctx.load_verify_locations(path)
            break
    return ctx

_SSL_CONTEXT = _build_ssl_context()

JIRA_URL = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _auth_header() -> str:
    token = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return f"Basic {token}"


def _jira(method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    if not all([JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN]):
        raise RuntimeError("Faltan variables de entorno: JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN")
    url = f"{JIRA_URL}/rest/api/3{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": _auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT) as resp:
            content = resp.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Jira API {e.code}: {e.read().decode(errors='replace')}") from e


# ---------------------------------------------------------------------------
# ADF helpers
# ---------------------------------------------------------------------------

def _adf_to_text(node: dict | None, depth: int = 0) -> str:
    if not node:
        return ""
    t = node.get("type", "")
    content = node.get("content", [])
    if t == "text":
        return node.get("text", "")
    if t in ("paragraph", "heading"):
        return "".join(_adf_to_text(c, depth) for c in content) + "\n"
    if t in ("bulletList", "orderedList"):
        items = []
        for i, item in enumerate(content):
            prefix = "•" if t == "bulletList" else f"{i + 1}."
            text = "".join(_adf_to_text(c, depth + 1) for c in item.get("content", []))
            items.append(f"{'  ' * depth}{prefix} {text.strip()}")
        return "\n".join(items) + "\n"
    if t == "codeBlock":
        return "```\n" + "".join(_adf_to_text(c, depth) for c in content) + "```\n"
    if t == "hardBreak":
        return "\n"
    return "".join(_adf_to_text(c, depth) for c in content)


def _to_adf(text: str) -> dict:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return {
        "type": "doc", "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _fmt_issue(issue: dict) -> str:
    f = issue.get("fields", {})
    desc = _adf_to_text(f.get("description")).strip() if f.get("description") else "(sin descripción)"
    return "\n".join([
        f"[{issue['key']}] {f.get('summary', '')}",
        f"  Tipo:      {(f.get('issuetype') or {}).get('name', '?')}",
        f"  Estado:    {(f.get('status') or {}).get('name', '?')}",
        f"  Prioridad: {(f.get('priority') or {}).get('name', '?')}",
        f"  Asignado:  {(f.get('assignee') or {}).get('displayName', 'Sin asignar')}",
        f"  Reporter:  {(f.get('reporter') or {}).get('displayName', '?')}",
        f"  Creado:    {f.get('created', '?')[:10]}",
        f"  URL:       {JIRA_URL}/browse/{issue['key']}",
        f"\nDescripción:\n{desc}",
    ])


def tool_get_issue(args: dict) -> str:
    return _fmt_issue(_jira("GET", f"/issue/{args['issue_key']}", params={"fields": "*all"}))


def tool_search_issues(args: dict) -> str:
    max_r = min(max(1, args.get("max_results", 20)), 50)
    data = _jira("POST", "/search", body={
        "jql": args["jql"], "maxResults": max_r,
        "fields": ["summary", "status", "assignee", "priority", "issuetype"],
    })
    issues = data.get("issues", [])
    if not issues:
        return f"Sin resultados para: {args['jql']}"
    lines = [f"Resultados ({len(issues)} de {data.get('total', '?')}):"]
    for issue in issues:
        f = issue["fields"]
        lines.append(
            f"  {issue['key']:15} [{(f.get('status') or {}).get('name', '?'):15}] "
            f"{f.get('summary', '')[:60]}"
            f"\n{'':17} Asignado: {(f.get('assignee') or {}).get('displayName', '—')} · "
            f"Prioridad: {(f.get('priority') or {}).get('name', '?')}"
        )
    return "\n".join(lines)


def tool_get_my_issues(args: dict) -> str:
    status = args.get("status", "")
    jql = "assignee = currentUser()"
    if status:
        jql += f' AND status = "{status}"'
    jql += " ORDER BY updated DESC"
    return tool_search_issues({"jql": jql, "max_results": 30})


def tool_create_issue(args: dict) -> str:
    fields: dict = {
        "project": {"key": args["project_key"]},
        "summary": args["summary"],
        "issuetype": {"name": args.get("issue_type", "Task")},
    }
    if args.get("description"):
        fields["description"] = _to_adf(args["description"])
    if args.get("priority"):
        fields["priority"] = {"name": args["priority"]}
    if args.get("assignee_account_id"):
        fields["assignee"] = {"accountId": args["assignee_account_id"]}
    data = _jira("POST", "/issue", body={"fields": fields})
    return f"Issue creado: {data['key']}\nURL: {JIRA_URL}/browse/{data['key']}"


def tool_add_comment(args: dict) -> str:
    _jira("POST", f"/issue/{args['issue_key']}/comment", body={"body": _to_adf(args["body"])})
    return f"Comentario añadido a {args['issue_key']}."


def tool_transition_issue(args: dict) -> str:
    key = args["issue_key"]
    name = args["transition_name"]
    data = _jira("GET", f"/issue/{key}/transitions")
    match = next((t for t in data.get("transitions", []) if t["name"].lower() == name.lower()), None)
    if not match:
        available = [t["name"] for t in data.get("transitions", [])]
        return f"Transición '{name}' no encontrada. Disponibles: {available}"
    _jira("POST", f"/issue/{key}/transitions", body={"transition": {"id": match["id"]}})
    return f"{key} movido a '{match['name']}'."


def tool_update_issue(args: dict) -> str:
    fields: dict = {}
    if args.get("summary"):
        fields["summary"] = args["summary"]
    if args.get("description"):
        fields["description"] = _to_adf(args["description"])
    if args.get("priority"):
        fields["priority"] = {"name": args["priority"]}
    if args.get("assignee_account_id"):
        fields["assignee"] = {"accountId": args["assignee_account_id"]}
    if not fields:
        return "No se proporcionó ningún campo para actualizar."
    _jira("PUT", f"/issue/{args['issue_key']}", body={"fields": fields})
    return f"{args['issue_key']} actualizado correctamente."


def tool_get_projects(_args: dict) -> str:
    data = _jira("GET", "/project/search", params={"maxResults": "50", "orderBy": "name"})
    projects = data.get("values", [])
    if not projects:
        return "No se encontraron proyectos."
    lines = [f"{'Clave':<12} {'Nombre':<40} Tipo", "-" * 60]
    for p in projects:
        lines.append(f"{p['key']:<12} {p['name']:<40} {p.get('projectTypeKey', '?')}")
    return "\n".join(lines)


def tool_get_issue_comments(args: dict) -> str:
    key = args["issue_key"]
    data = _jira("GET", f"/issue/{key}/comment", params={"orderBy": "created"})
    comments = data.get("comments", [])
    if not comments:
        return f"{key} no tiene comentarios."
    parts = []
    for c in comments:
        author = (c.get("author") or {}).get("displayName", "?")
        created = c.get("created", "")[:16].replace("T", " ")
        body = _adf_to_text(c.get("body")).strip()
        parts.append(f"[{created}] {author}:\n{body}")
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Tool registry & schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_issue",
        "description": "Devuelve todos los detalles de un issue de Jira (título, estado, descripción, asignado, prioridad).",
        "inputSchema": {
            "type": "object",
            "properties": {"issue_key": {"type": "string", "description": "Clave del issue, p.ej. PROJ-123"}},
            "required": ["issue_key"],
        },
    },
    {
        "name": "search_issues",
        "description": "Busca issues usando JQL. Ejemplos: 'project = PROJ AND status = \"In Progress\"', 'assignee = currentUser() ORDER BY updated DESC'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "jql": {"type": "string", "description": "Consulta JQL"},
                "max_results": {"type": "integer", "description": "Máximo de resultados (1-50)", "default": 20},
            },
            "required": ["jql"],
        },
    },
    {
        "name": "get_my_issues",
        "description": "Lista los issues asignados al usuario autenticado.",
        "inputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string", "description": "Filtra por estado, p.ej. 'In Progress'. Vacío = todos."}},
        },
    },
    {
        "name": "create_issue",
        "description": "Crea un nuevo issue en Jira.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_key": {"type": "string", "description": "Clave del proyecto, p.ej. PROJ"},
                "summary": {"type": "string", "description": "Título del issue"},
                "description": {"type": "string", "description": "Descripción en texto plano"},
                "issue_type": {"type": "string", "description": "Task, Bug, Story o Epic", "default": "Task"},
                "priority": {"type": "string", "description": "Highest, High, Medium, Low, Lowest"},
                "assignee_account_id": {"type": "string", "description": "Account ID del asignado"},
            },
            "required": ["project_key", "summary"],
        },
    },
    {
        "name": "add_comment",
        "description": "Añade un comentario a un issue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Clave del issue"},
                "body": {"type": "string", "description": "Texto del comentario"},
            },
            "required": ["issue_key", "body"],
        },
    },
    {
        "name": "transition_issue",
        "description": "Cambia el estado de un issue, p.ej. de 'To Do' a 'In Progress'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Clave del issue"},
                "transition_name": {"type": "string", "description": "Nombre del estado destino"},
            },
            "required": ["issue_key", "transition_name"],
        },
    },
    {
        "name": "update_issue",
        "description": "Actualiza campos de un issue existente. Solo se modifican los campos con valor.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Clave del issue"},
                "summary": {"type": "string", "description": "Nuevo título"},
                "description": {"type": "string", "description": "Nueva descripción"},
                "priority": {"type": "string", "description": "Nueva prioridad"},
                "assignee_account_id": {"type": "string", "description": "Account ID del nuevo asignado"},
            },
            "required": ["issue_key"],
        },
    },
    {
        "name": "get_projects",
        "description": "Lista los proyectos de Jira accesibles con el token configurado.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_issue_comments",
        "description": "Devuelve los comentarios de un issue en orden cronológico.",
        "inputSchema": {
            "type": "object",
            "properties": {"issue_key": {"type": "string", "description": "Clave del issue"}},
            "required": ["issue_key"],
        },
    },
]

HANDLERS = {
    "get_issue": tool_get_issue,
    "search_issues": tool_search_issues,
    "get_my_issues": tool_get_my_issues,
    "create_issue": tool_create_issue,
    "add_comment": tool_add_comment,
    "transition_issue": tool_transition_issue,
    "update_issue": tool_update_issue,
    "get_projects": tool_get_projects,
    "get_issue_comments": tool_get_issue_comments,
}

# ---------------------------------------------------------------------------
# MCP JSON-RPC 2.0 server loop (stdio)
# ---------------------------------------------------------------------------

def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _handle(msg: dict) -> dict | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jira", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # notification, no response

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = HANDLERS.get(name)
        if not handler:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Tool '{name}' no encontrada"},
            }
        try:
            result = handler(args)
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": result}]},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
            }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if msg_id is not None:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Método '{method}' no soportado"},
        }
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        response = _handle(msg)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
