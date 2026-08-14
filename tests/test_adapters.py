"""Comprehensive adapter test suite.

Spins up real local servers (HTTP/JSON-RPC, RFC6455 WebSocket) and the fake
MCP server, then exercises every adapter's happy path and failure path,
asserting the adapter contract:
    * execute() returns AdapterResponse (never raises protocol-native errors)
    * failures are ok=False with an AdapterError attached
    * transports never leak native exceptions
"""
import json
import os
import sys
import threading
import socket
import struct
import base64
import hashlib
import http.server
import socketserver
import time

sys.path.insert(0, os.path.abspath("agents/A01_Blockchain_Intelligence"))

from tools.adapters import (
    AdapterRequest,
    AdapterConnectionError,
    AdapterTimeoutError,
    AdapterValidationError,
    AdapterAuthenticationError,
    AdapterError,
)
from tools.adapters.python import PythonAdapter
from tools.adapters.rest import RESTAdapter
from tools.adapters.rpc import RPCAdapter
from tools.adapters.websocket import WebSocketAdapter
from tools.adapters.mcp import MCPAdapter
from tools.adapters.cli import CLIAdapter
from tools.adapters.subprocess import SubprocessAdapter
from tools.adapters.docker import DockerAdapter
from tools.adapters.grpc import GRPCAdapter

PASS = []
FAIL = []

def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}  {detail}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")

# --------------------------------------------------------------------------- #
# 1. HTTP + JSON-RPC test server
# --------------------------------------------------------------------------- #

class TestHandler(http.server.BaseHTTPRequestHandler):
    retry_state = {}

    def log_message(self, *a):  # silence
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass  # client aborted (e.g. timeout test)

    def do_GET(self):
        if self.path.startswith("/test"):
            self._send_json({"ok": True, "path": self.path})
        elif self.path.startswith("/auth"):
            if self.headers.get("Authorization") == "Bearer secret":
                self._send_json({"authed": True})
            else:
                self._send_json({"error": "unauthorized"}, code=401)
        elif self.path.startswith("/retry"):
            key = "retry"
            TestHandler.retry_state[key] = TestHandler.retry_state.get(key, 0) + 1
            if TestHandler.retry_state[key] <= 2:
                self._send_json({"error": "boom"}, code=500)
            else:
                self._send_json({"ok": True, "attempts": TestHandler.retry_state[key]})
        elif self.path.startswith("/slow"):
            time.sleep(2.0)
            self._send_json({"ok": True})
        elif self.path.startswith("/jsonrpc"):
            self.handle_rpc()
        else:
            self._send_json({"error": "not found"}, code=404)

    def do_POST(self):
        if self.path.startswith("/jsonrpc"):
            self.handle_rpc()
            return
        body = self._read_body()
        try:
            data = json.loads(body)
        except ValueError:
            data = body.decode("utf-8", "replace")
        self._send_json({"method": "POST", "received": data, "path": self.path})

    def handle_rpc(self):
        body = self._read_body()
        try:
            payload = json.loads(body)
        except ValueError:
            self._send_json({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return
        if isinstance(payload, list):
            out = [self._dispatch(item) for item in payload]
            self._send_json(out)
            return
        self._send_json(self._dispatch(payload))

    def _dispatch(self, item):
        method = item.get("method")
        params = item.get("params") or {}
        rid = item.get("id")
        if method == "add":
            return {"jsonrpc": "2.0", "id": rid, "result": params.get("a", 0) + params.get("b", 0)}
        if method == "echo":
            return {"jsonrpc": "2.0", "id": rid, "result": params}
        if method == "boom":
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "boom failed", "data": {"x": 1}}}
        if method == "returns_without_result":
            return {"jsonrpc": "2.0", "id": rid}
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}}


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# --------------------------------------------------------------------------- #
# 2. RFC6455 WebSocket echo server
# --------------------------------------------------------------------------- #

def ws_magic():
    return "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def ws_read_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("ws closed")
        buf += chunk
    return buf

def ws_handle(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        data += conn.recv(4096)
    head = data.decode("latin-1")
    key = None
    for line in head.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    accept = base64.b64encode(hashlib.sha1((key + ws_magic()).encode()).digest()).decode()
    resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    conn.sendall(resp.encode("latin-1"))

    while True:
        try:
            b0, b1 = ws_read_exact(conn, 2)
        except ConnectionError:
            return
        opcode = b0 & 0x0F
        length = b1 & 0x7F
        masked = bool(b1 & 0x80)
        if length == 126:
            length = struct.unpack(">H", ws_read_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", ws_read_exact(conn, 8))[0]
        mask = ws_read_exact(conn, 4) if masked else b""
        payload = ws_read_exact(conn, length) if length else b""
        if masked:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))

        if opcode == 0x8:  # close
            conn.close()
            return
        if opcode == 0x9:  # ping -> pong
            conn.sendall(bytes([0x8A, len(payload)]) + payload)
            continue
        # echo text/binary back (unmasked, fin=1)
        if length < 126:
            hdr = bytes([0x80 | opcode, length])
        elif length < 65536:
            hdr = bytes([0x80 | opcode, 126]) + struct.pack(">H", length)
        else:
            hdr = bytes([0x80 | opcode, 127]) + struct.pack(">Q", length)
        conn.sendall(hdr + payload)


def ws_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=ws_handle, args=(conn,), daemon=True).start()


# --------------------------------------------------------------------------- #
# 3. Main test runner
# --------------------------------------------------------------------------- #

def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    http_port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    http_url = f"http://127.0.0.1:{http_port}"

    ws_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ws_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ws_srv.bind(("127.0.0.1", 0))
    ws_port = ws_srv.getsockname()[1]
    threading.Thread(target=ws_server, args=(ws_port,), daemon=True).start()

    fake_mcp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_mcp_server.py")

    print("=== python adapter ===")
    pa = PythonAdapter()
    r = pa.execute(AdapterRequest(method="call", params={"target": "math.gcd", "args": [12, 8]}))
    check("python math.gcd", r.ok and r.data == 4, str(r.data))
    r = pa.execute(AdapterRequest(method="call", params={"target": "os.system", "args": ["echo hi"]}))
    check("python os blocked", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error))
    r = pa.execute(AdapterRequest(method="call", params={"target": "math.sqrt", "args": [16]}))
    check("python math.sqrt", r.ok and r.data == 4.0, str(r.data))
    r = pa.execute(AdapterRequest(method="call", params={"target": "json.dumps", "args": [1, 2], "kwargs": {}}, timeout=0.01))
    check("python bad call returns response", hasattr(r, "ok") and not r.ok, str(r.error))
    r = pa.execute(AdapterRequest(method="call", params={"target": "time.sleep", "args": [5]}, timeout=0.2))
    check("python timeout", not r.ok and r.error is not None, type(r.error).__name__)
    r = pa.execute(AdapterRequest(method="ping"))
    check("python ping", r.ok and r.data == "pong", str(r.data))
    r = pa.execute(AdapterRequest(method="call", params={"target": "itertools.count"}))
    check("python json-safe repr", r.ok and "_repr" in r.data, str(r.data)[:60])

    print("=== rest adapter ===")
    ra = RESTAdapter(base_url=http_url)
    ra.connect()
    r = ra.execute(AdapterRequest(method="GET", path="/test", params={"a": 1}))
    check("rest GET", r.ok and r.data.get("ok") is True, str(r.data))
    check("rest metadata status", r.metadata.status_code == 200, str(r.metadata.status_code))
    r = ra.execute(AdapterRequest(method="GET", path="/auth"))
    check("rest 401 translated", not r.ok and isinstance(r.error, AdapterAuthenticationError), str(r.error))
    r = ra.execute(AdapterRequest(method="POST", path="/echo", data={"x": [1, 2]}))
    check("rest POST json", r.ok and r.data.get("received") == {"x": [1, 2]}, str(r.data))
    r = ra.execute(AdapterRequest(method="GET", path="/retry", retries=3))
    check("rest retry recovers", r.ok, str(r.data))
    r = ra.execute(AdapterRequest(method="BREW", path="/test"))
    check("rest bad method", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error))
    ra2 = RESTAdapter(base_url="http://127.0.0.1:1")
    r = ra2.execute(AdapterRequest(method="GET", path="/", timeout=2))
    check("rest unreachable", not r.ok and r.error is not None, type(r.error).__name__)
    ra3 = RESTAdapter(base_url=http_url, default_timeout=5)
    r = ra3.execute(AdapterRequest(method="GET", path="/slow", timeout=0.5))
    check("rest timeout", not r.ok and isinstance(r.error, AdapterTimeoutError), type(r.error).__name__)
    chunks = list(ra.stream(AdapterRequest(method="GET", path="/test")))
    check("rest stream chunks", len(chunks) >= 1, f"{len(chunks)} chunks")

    print("=== rpc adapter ===")
    rpc = RPCAdapter(url=f"{http_url}/jsonrpc")
    rpc.connect()
    r = rpc.execute(AdapterRequest(method="add", params={"params": {"a": 2, "b": 3}}))
    check("rpc add", r.ok and r.data == 5, str(r.data))
    req = AdapterRequest(method="echo", params={"params": {"k": "v"}})
    orig_params = dict(req.params)
    r = rpc.execute(req)
    check("rpc echo", r.ok and r.data == {"k": "v"}, str(r.data))
    check("rpc params not mutated", req.params == orig_params, str(req.params))
    r = rpc.execute(AdapterRequest(method="boom", params={"params": {}}))
    check("rpc error translated", not r.ok and r.error is not None, str(r.error)[:70])
    r = rpc.execute(AdapterRequest(method="returns_without_result", params={"params": {}}))
    check("rpc no result", not r.ok, str(r.error)[:60])
    r = rpc.execute(AdapterRequest(method="batch", params={"batch": [{"method": "add", "params": {"a": 1, "b": 2}}, {"method": "add", "params": {"a": 10, "b": 20}}]}))
    check("rpc batch", r.ok and isinstance(r.data, list) and r.data[0]["result"] == 3, str(r.data)[:80])
    rpc2 = RPCAdapter(endpoints=[f"http://127.0.0.1:1/jsonrpc", f"{http_url}/jsonrpc"])
    r = rpc2.execute(AdapterRequest(method="add", params={"params": {"a": 5, "b": 5}}))
    check("rpc failover", r.ok and r.data == 10, str(r.data))
    rpc3 = RPCAdapter(endpoints=["http://127.0.0.1:1/jsonrpc", "http://127.0.0.1:2/jsonrpc"])
    r = rpc3.execute(AdapterRequest(method="add", params={"params": {"a": 1, "b": 1}}, retries=0, timeout=1))
    check("rpc all dead", not r.ok and r.error is not None, type(r.error).__name__)
    rpc.close()

    print("=== subprocess adapter ===")
    sp = SubprocessAdapter()
    r = sp.execute(AdapterRequest(method="run", params={"argv": [sys.executable, "-c", "print('hello from sub')"]}))
    check("subprocess run", r.ok and "hello from sub" in r.data["stdout"], str(r.data["stdout"]))
    r = sp.execute(AdapterRequest(method="run", params={"argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}))
    check("subprocess exit code", not r.ok and r.error is not None, str(r.data.get("returncode")))
    r = sp.execute(AdapterRequest(method="run", params={"argv": [sys.executable, "-c", "import time; time.sleep(5)"]}, timeout=0.5))
    check("subprocess timeout", not r.ok and isinstance(r.error, AdapterTimeoutError), type(r.error).__name__)
    r = sp.execute(AdapterRequest(method="ping"))
    check("subprocess ping", r.ok and r.data == "pong", str(r.data))
    lines = list(sp.stream(AdapterRequest(method="run", params={"argv": [sys.executable, "-u", "-c", "print('l1'); print('l2')"]})))
    check("subprocess stream", lines == ["l1", "l2"], str(lines))

    print("=== cli adapter ===")
    resolved_name = os.path.basename(sys.executable)
    if resolved_name.lower().endswith(".exe"):
        resolved_name = resolved_name[:-4]
    cli = CLIAdapter(allowed_commands=(resolved_name,))
    cli.connect()
    r = cli.execute(AdapterRequest(method="run", params={"argv": [sys.executable, "-c", "print('cli ok')"]}))
    check("cli allowed runs", r.ok and "cli ok" in r.data["stdout"], str(r.data["stdout"]))
    cli2 = CLIAdapter(allowed_commands=("git",))
    r = cli2.execute(AdapterRequest(method="run", params={"argv": [sys.executable, "-c", "print('nope')"]}))
    check("cli denied", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error))
    r = cli2.execute(AdapterRequest(method="run", params={"argv": "echo hi"}))
    check("cli string rejected", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error))

    print("=== websocket adapter ===")
    ws = WebSocketAdapter(url=f"ws://127.0.0.1:{ws_port}", read_timeout=5)
    ws.connect()
    ws.send_text("hello")
    frame = ws.recv()
    check("ws text roundtrip", frame.opcode == 0x1 and frame.payload == b"hello", str(frame.payload))
    ws.send_json({"a": [1, 2]})
    frame = ws.recv()
    check("ws json roundtrip", frame.payload == json.dumps({"a": [1, 2]}).encode(), str(frame.payload))
    r = ws.execute(AdapterRequest(method="send", data="via-exec"))
    check("ws send via execute", r.ok, str(r.error))
    frame = ws.recv()
    check("ws recv echoes", frame.payload == b"via-exec", str(frame.payload))
    ws.close()

    ws2 = WebSocketAdapter(url=f"ws://127.0.0.1:{ws_port}", read_timeout=3)
    ws2.connect()
    ws2.close()
    ws2.connect()
    check("ws reconnect", True, "reconnected ok")
    ws2.close()

    print("=== mcp adapter ===")
    mcp = MCPAdapter(command=sys.executable, args=[fake_mcp], server_name="test")
    r = mcp.execute(AdapterRequest(method="initialize"))
    check("mcp initialize", r.ok and r.data.get("serverInfo", {}).get("name") == "fake-mcp", str(r.data)[:80])
    r = mcp.execute(AdapterRequest(method="list_tools"))
    check("mcp list_tools", r.ok and "echo" in str(r.data), str(r.data)[:80])
    r = mcp.execute(AdapterRequest(method="call_tool", params={"name": "echo", "arguments": {"x": 1}}))
    check("mcp call_tool", r.ok and "echo:{'x': 1}" in str(r.data), str(r.data)[:100])
    r = mcp.execute(AdapterRequest(method="call_tool", params={"name": "boom", "arguments": {}}))
    check("mcp malformed server reply -> failed", not r.ok and isinstance(r.error, AdapterConnectionError), type(r.error).__name__)
    mcp_fast = MCPAdapter(command=sys.executable, args=[fake_mcp], server_name="fast", request_timeout=1)
    r = mcp_fast.execute(AdapterRequest(method="call_tool", params={"name": "sleep", "arguments": {}}))
    check("mcp timeout", not r.ok and isinstance(r.error, AdapterTimeoutError), type(r.error).__name__)
    mcp_fast.close()
    r = mcp.execute(AdapterRequest(method="list_prompts"))
    check("mcp unknown method error", not r.ok and r.error is not None, str(r.error)[:70])
    tools = mcp.list_tools()
    check("mcp list_tools convenience", len(tools) >= 1, str(tools))
    mcp.close()

    mcp2 = MCPAdapter(command=sys.executable, args=[fake_mcp], server_name="test2")
    r = mcp2.execute(AdapterRequest(method="ping"))
    check("mcp ping", r.ok, str(r))
    mcp2.close()

    print("=== grpc adapter (no grpcio) ===")
    g = GRPCAdapter(target="localhost:50051", stub=None)
    r = g.execute(AdapterRequest(method="anything"))
    check("grpc missing dep", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error)[:60])

    print("=== docker adapter (unreachable) ===")
    d = DockerAdapter(base_url="http://127.0.0.1:1")
    r = d.execute(AdapterRequest(method="list"))
    check("docker unreachable", not r.ok and isinstance(r.error, AdapterConnectionError), type(r.error).__name__)
    r = d.execute(AdapterRequest(method="ping"))
    check("docker ping", r.ok, str(r.data))
    r = d.execute(AdapterRequest(method="bogus"))
    check("docker bad action", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error)[:60])
    r = d.execute(AdapterRequest(method="run", params={}))
    check("docker run no image", not r.ok and isinstance(r.error, AdapterValidationError), str(r.error)[:60])

    httpd.shutdown()

    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()