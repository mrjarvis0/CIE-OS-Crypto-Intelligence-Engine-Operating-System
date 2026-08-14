"""Fake MCP server used by the adapter test suite.

Speaks the stdio JSON-RPC subset our MCPAdapter uses:
- reads one JSON-RPC 2.0 message per line from stdin
- responds on stdout, one JSON object per line
- `notifications/initialized` and other id-less messages are ignored
- tools/call with name "boom" emits a malformed (non-JSON) line to simulate
  a broken server; "sleep" sleeps 5s to trigger client timeouts
"""
import json
import sys
import time

def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue

        method = msg.get("method")
        rid = msg.get("id")
        if rid is None:
            # Notifications produce no reply.
            continue

        result = None
        error = None
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": "echo", "description": "echo args", "inputSchema": {"type": "object"}}
                ]
            }
        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            if name == "boom":
                # Simulate a server that speaks garbage.
                sys.stdout.write("this is not json at all\n")
                sys.stdout.flush()
                continue
            if name == "sleep":
                time.sleep(5)
                result = {"content": [], "isError": False}
            else:
                result = {"content": [{"type": "text", "text": f"echo:{params.get('arguments', {})}"}], "isError": False}
        elif method == "notifications/initialized":
            continue
        else:
            error = {"code": -32601, "message": f"method not found: {method}"}

        reply = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            reply["error"] = error
        else:
            reply["result"] = result
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)