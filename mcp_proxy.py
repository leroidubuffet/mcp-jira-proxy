"""
Proxy MCP educativo — se interpone entre Claude y cualquier servidor MCP,
deja pasar todo sin modificarlo y escribe un log explicado en lenguaje natural.

Uso:
  1. Configura el proxy en ~/.claude.json en lugar del servidor real:

     "jira-proxy": {
       "type": "stdio",
       "command": "python3",
       "args": ["/ruta/a/mcp_proxy.py"],
       "env": {
         "MCP_PROXY_CMD": "python3",
         "MCP_PROXY_ARGS": "/ruta/a/jira_mcp_server.py",
         "MCP_PROXY_LOG": "/tmp/mcp_proxy.log",
         ... (resto de env vars del servidor real)
       }
     }

  2. En otra terminal: tail -f /tmp/mcp_proxy.log

  MCP_PROXY_CMD   comando del servidor real (requerido)
  MCP_PROXY_ARGS  argumentos separados por espacio (opcional)
  MCP_PROXY_LOG   ruta del log (por defecto /tmp/mcp_proxy.log)
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

LOG_PATH = os.environ.get("MCP_PROXY_LOG", "/tmp/mcp_proxy.log")
REAL_CMD = os.environ.get("MCP_PROXY_CMD", "")
# MCP_PROXY_ARGS puede ser una ruta con espacios — usamos shlex para parsearla
# correctamente en lugar de split() simple que rompería las rutas.
import shlex
_raw_args = os.environ.get("MCP_PROXY_ARGS", "")
REAL_ARGS = shlex.split(_raw_args) if _raw_args else []

_log_lock = threading.Lock()
_pending: dict[int | str, tuple[str, str]] = {}  # id → (method, tool_name)
_pending_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def _log(symbol: str, direction: str, lines: list[str], latency_ms: float | None = None) -> None:
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    sep = "─" * 60
    parts = [f"\n{sep}", f"[{now}]  {symbol}  {direction}"]
    parts.extend(f"  {l}" for l in lines)
    if latency_ms is not None:
        parts.append(f"  ⏱  {latency_ms:.0f} ms")
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(parts) + "\n")


# ---------------------------------------------------------------------------
# Explicadores
# ---------------------------------------------------------------------------

_METHOD_LABELS = {
    "initialize":               ("🤝", "HANDSHAKE — Claude se conecta al servidor"),
    "notifications/initialized": ("✅", "HANDSHAKE COMPLETO — protocolo negociado"),
    "tools/list":               ("📋", "CATÁLOGO — Claude pide las herramientas disponibles"),
    "tools/call":               ("⚡", "LLAMADA — Claude ejecuta una herramienta"),
    "ping":                     ("💓", "PING — comprobación de vida"),
}

_HANDSHAKE_METHODS = {
    "initialize",
    "notifications/initialized",
    "tools/list",
    "ping",
}


def _explain_request(msg: dict) -> tuple[str, str, list[str]]:
    """Devuelve (símbolo, dirección, líneas de explicación)."""
    method = msg.get("method", "?")
    params = msg.get("params", {})
    msg_id = msg.get("id")

    symbol, label = _METHOD_LABELS.get(method, ("→", f"MÉTODO: {method}"))

    lines = [label]

    if method == "initialize":
        client = params.get("clientInfo", {})
        proto = params.get("protocolVersion", "?")
        lines += [
            f"Cliente: {client.get('name', '?')} {client.get('version', '')}",
            f"Versión del protocolo solicitada: {proto}",
            "El servidor responderá confirmando qué tipos de primitivas soporta (tools, resources, prompts).",
            "Las tools concretas se piden en un mensaje tools/list separado.",
        ]

    elif method == "tools/list":
        lines.append("El servidor devolverá nombre, descripción y schema JSON de cada tool.")

    elif method == "tools/call":
        name = params.get("name", "?")
        args = params.get("arguments", {})
        lines += [
            f"Tool:       {name}",
            f"Argumentos: {json.dumps(args, ensure_ascii=False, indent=None)}",
        ]
        # Registro para correlacionar con la respuesta
        if msg_id is not None:
            with _pending_lock:
                _pending[msg_id] = (method, name)
        return symbol, f"Claude → Servidor   [{method}]", lines

    if method not in ("tools/call",) and msg_id is not None:
        with _pending_lock:
            _pending[msg_id] = (method, "")

    return symbol, f"Claude → Servidor   [{method}]", lines


def _explain_response(msg: dict, latency_ms: float | None) -> tuple[str, str, list[str], float | None]:
    """Devuelve (símbolo, dirección, líneas, latency)."""
    msg_id = msg.get("id")
    result = msg.get("result", {})
    error = msg.get("error")

    with _pending_lock:
        method, tool_name = _pending.pop(msg_id, ("?", ""))

    if error:
        lines = [
            f"❌ ERROR en '{tool_name or method}'",
            f"Código:  {error.get('code', '?')}",
            f"Mensaje: {error.get('message', '?')}",
        ]
        return "❌", f"Servidor → Claude   [error]", lines, latency_ms

    lines = []
    symbol = "←"

    if method == "initialize":
        info = result.get("serverInfo", {})
        caps = result.get("capabilities", {})
        _cap_labels = {
            "tools":     "tools (Claude puede llamar funciones)",
            "resources": "resources (Claude puede leer datos como ficheros o URIs)",
            "prompts":   "prompts (el servidor ofrece plantillas de prompt)",
            "logging":   "logging (el servidor envía logs estructurados)",
        }
        cap_desc = ", ".join(
            _cap_labels.get(k, k) for k in caps.keys()
        ) or "ninguna declarada"
        lines = [
            f"✅ Servidor identificado: {info.get('name', '?')} v{info.get('version', '?')}",
            f"Protocolo acordado: {result.get('protocolVersion', '?')}",
            f"Capacidades: {cap_desc}",
            "A partir de aquí Claude puede pedir el catálogo y llamar tools.",
        ]

    elif method == "tools/list":
        tools = result.get("tools", [])
        names = [t["name"] for t in tools]
        lines = [
            f"✅ {len(tools)} herramientas registradas:",
        ] + [f"   • {n}" for n in names]

    elif method == "tools/call":
        content = result.get("content", [])
        is_error = result.get("isError", False)
        text = content[0].get("text", "(sin contenido)") if content else "(sin contenido)"
        preview_lines = text.splitlines()[:6]
        prefix = "⚠️  ERROR de la tool" if is_error else f"✅ Resultado de '{tool_name}'"
        lines = [prefix] + [f"   {l}" for l in preview_lines]
        if len(text.splitlines()) > 6:
            lines.append(f"   ... ({len(text.splitlines())} líneas en total)")

    elif method == "ping":
        lines = ["✅ Servidor vivo"]

    else:
        lines = [f"✅ Respuesta a '{method}'"]

    direction = f"Servidor → Claude   [respuesta a {method}" + (f" / {tool_name}" if tool_name else "") + "]"
    return symbol, direction, lines, latency_ms


# ---------------------------------------------------------------------------
# Threads de proxy
# ---------------------------------------------------------------------------

def _forward_claude_to_server(proc: subprocess.Popen, start_times: dict) -> None:
    """Lee de stdin (Claude), explica, y reenvía al servidor real."""
    while True:
        raw_line = sys.stdin.readline()
        if not raw_line:
            break
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Registrar tiempo de inicio para calcular latencia en la respuesta
        try:
            msg = json.loads(raw_line)
            if msg.get("id") is not None:
                start_times[msg["id"]] = time.time()
        except Exception:
            pass

        # Reenviar al servidor real siempre
        try:
            proc.stdin.write(raw_line + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            break

        # Explicar
        try:
            msg = json.loads(raw_line)
            symbol, direction, lines = _explain_request(msg)
            _log(symbol, direction, lines)
        except Exception:
            _log("→", "Claude → Servidor  [raw]", [raw_line[:120]])

    proc.stdin.close()


def _forward_server_to_claude(proc: subprocess.Popen, start_times: dict) -> None:
    """Lee del servidor real, explica, y reenvía a stdout (Claude)."""
    while True:
        raw_line = proc.stdout.readline()
        if not raw_line:
            break
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Reenviar a Claude siempre
        sys.stdout.write(raw_line + "\n")
        sys.stdout.flush()

        # Explicar
        try:
            msg = json.loads(raw_line)
            msg_id = msg.get("id")
            latency = None
            if msg_id is not None and msg_id in start_times:
                latency = (time.time() - start_times.pop(msg_id)) * 1000

            if "result" in msg or "error" in msg:
                symbol, direction, lines, lat = _explain_response(msg, latency)
                _log(symbol, direction, lines, lat)
        except Exception:
            _log("←", "Servidor → Claude  [raw]", [raw_line[:120]])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not REAL_CMD:
        sys.stderr.write("Error: MCP_PROXY_CMD no configurado\n")
        sys.exit(1)

    cmd = [REAL_CMD] + REAL_ARGS

    # Cabecera del log
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write(f"{'═' * 60}\n")
        f.write(f"  MCP PROXY — sesión iniciada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"  Servidor real: {' '.join(cmd)}\n")
        f.write(f"{'═' * 60}\n")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

    start_times: dict = {}

    t_in = threading.Thread(
        target=_forward_claude_to_server,
        args=(proc, start_times),
        daemon=True,
    )
    t_out = threading.Thread(
        target=_forward_server_to_claude,
        args=(proc, start_times),
        daemon=True,
    )

    t_in.start()
    t_out.start()
    t_in.join()
    t_out.join()
    proc.wait()

    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'═' * 60}\n")
            f.write(f"  Sesión terminada {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
