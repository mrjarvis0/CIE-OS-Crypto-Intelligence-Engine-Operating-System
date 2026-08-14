"""
Tools :: Adapters :: MCP Adapter
================================

Client for the Model Context Protocol (MCP), enabling integration with
standardized AI tool ecosystems over JSON-RPC 2.0 transports.

This adapter implements the core client surface (initialize, tools/list,
tools/call, resources/list, prompts/list) over a stdio transport so that a
tool registry can discover and invoke remote MCP capabilities without
embedding a full SDK.

Capabilities:
    * protocol negotiation (initialize)
    * tool discovery (tools/list)
    * tool invocation (tools/call)
    * resource discovery (resources/list)
    * prompt discovery (prompts/list)
    * JSON-RPC error translation
    * bounded waits: every read is subject to ``request_timeout`` so a silent
      or dead server can never block a caller forever

The default transport is stdio subprocess, which is the most common way to run
MCP servers locally. HTTP/SSE transports can be layered on by subclassing and
overriding :meth:`_rpc`.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any, Dict, List, Optional

from . import (
    AdapterConnectionError,
    AdapterError,
    AdapterExecutionError,
    AdapterRequest,
    AdapterResponse,
    AdapterTimeoutError,
    AdapterValidationError,
    BaseAdapter,
)

__all__ = ["MCPAdapter", "register"]

PROTOCOL_VERSION = "2024-11-05"

# A batch of server lines that arrive together is buffered before dispatch;
# this keeps ordering correct when notifications interleave with responses.
_MAX_BUFFER = 256


def register(**options: Any) -> "MCPAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return MCPAdapter(**options)


class MCPAdapter(BaseAdapter):
    """A client for a subprocess-launched MCP server over stdio JSON-RPC."""

    transport = "mcp"

    def __init__(
        self,
        *,
        command: str = "python",
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        server_name: str = "default",
        request_timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.command = command
        self.args = list(args or [])
        self.cwd = cwd
        self.env = dict(env or {})
        self.server_name = server_name
        self.request_timeout = request_timeout

        self._proc: Optional[subprocess.Popen] = None
        self._initialized = False
        self._counter = 0
        self._pending: Dict[int, queue.Queue] = {}
        self._reader_stop = threading.Event()
        self._reader: Optional[threading.Thread] = None

    # -- transport ---------------------------------------------------------- #

    def connect(self, **options: Any) -> "MCPAdapter":
        """Spawn the MCP server process, start the reader, negotiate protocol."""
        if self._proc is not None:
            if not self._initialized:
                self._initialize()
            return self

        env = {**os.environ, **self.env}
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env=env,
                text=False,
            )
        except OSError as exc:
            raise AdapterConnectionError(
                f"failed to launch MCP server {self.command!r}: {exc}",
                transport=self.transport,
            ) from exc

        self._connected = True
        self._start_reader()
        self._initialize()
        return self

    def _start_reader(self) -> None:
        """Background thread that drains stdout and dispatches by request id."""
        self._reader_stop.clear()
        proc = self._proc

        def _read() -> None:
            assert proc is not None
            assert proc.stdout is not None
            while not self._reader_stop.is_set():
                try:
                    line = proc.stdout.readline()
                except OSError:
                    break
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    # Server emitted garbage; route a parse error to every
                    # caller waiting for a response so they can fail cleanly.
                    self._fail_pending(
                        AdapterConnectionError(
                            f"malformed JSON-RPC line from MCP server: {line!r}",
                            transport=self.transport,
                        )
                    )
                    continue
                rid = msg.get("id")
                if rid is None:
                    # Server-side notification or log line; ignore.
                    continue
                pending = self._pending.get(rid)
                if pending is not None:
                    pending.put(msg)

        self._reader = threading.Thread(
            target=_read, name=f"mcp-reader-{self.server_name}", daemon=True
        )
        self._reader.start()

    def _fail_pending(self, exc: AdapterError) -> None:
        for q in list(self._pending.values()):
            q.put({"__error__": exc})
        self._pending.clear()

    def close(self) -> None:
        self._reader_stop.set()
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
            except OSError:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None
        self._pending.clear()
        self._initialized = False
        super().close()

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    def _rpc(self, method: str, params: Any = None, *, notify: bool = False) -> Any:
        """
        Send a JSON-RPC 2.0 request to the server and wait for its response.

        ``notify=True`` sends a notification (no ``id``) and returns
        immediately without reading a response, per the MCP/JSON-RPC spec.
        """
        if self._proc is None:
            self.connect()
        if self._proc is None or self._proc.stdin is None:  # pragma: no cover
            raise AdapterConnectionError(
                "MCP server not running", transport=self.transport
            )

        rpc_id: Any = None
        if not notify:
            rpc_id = self._next_id()
            response_q: queue.Queue = queue.Queue(maxsize=1)
            self._pending[rpc_id] = response_q

        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if rpc_id is not None:
            payload["id"] = rpc_id
        if params is not None:
            payload["params"] = params

        try:
            self._proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            stderr = self._read_stderr()
            if rpc_id is not None:
                self._pending.pop(rpc_id, None)
            raise AdapterConnectionError(
                f"MCP server process died on write: {stderr or exc}",
                transport=self.transport,
            ) from exc

        if notify:
            return None

        try:
            msg = response_q.get(timeout=self.request_timeout)
        except queue.Empty:
            self._pending.pop(rpc_id, None)
            raise AdapterTimeoutError(
                f"MCP {method!r} timed out after {self.request_timeout}s "
                f"(server {self.server_name!r})",
                transport=self.transport,
            )

        if "__error__" in msg:
            raise msg["__error__"]
        if "error" in msg and msg["error"] is not None:
            err = msg["error"]
            raise AdapterExecutionError(
                f"MCP {method!r} error {err.get('code')}: {err.get('message')}",
                transport=self.transport,
            )
        return msg.get("result")

    def _read_stderr(self) -> str:
        stderr = b""
        if self._proc is not None and self._proc.stderr is not None:
            try:
                stderr = self._proc.stderr.read(4096)
            except OSError:
                pass
        return stderr.decode("utf-8", "replace")

    # -- protocol ----------------------------------------------------------- #

    def _initialize(self) -> None:
        if self._initialized:
            return
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "cie-os-adapters-mcp", "version": "1.0.0"},
            },
        )
        self._initialized = True
        # Notify the server we are ready; never wait for a reply.
        try:
            self._rpc("notifications/initialized", notify=True)
        except AdapterConnectionError:  # pragma: no cover - best-effort
            pass
        self.server_info = result or {}

    # -- public API --------------------------------------------------------- #

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        op = (request.method or "call").lower()

        if op == "initialize":
            try:
                self.connect()
                return self.normalize_response(
                    True, data=getattr(self, "server_info", {}), method=op
                )
            except AdapterError as exc:
                return self.normalize_response(False, error=exc, method=op)

        try:
            self.connect()
        except AdapterError as exc:
            return self.normalize_response(
                False, error=exc, method=op, request_id=request.request_id
            )

        if op == "ping":
            try:
                data = self._rpc("ping")
                return self.normalize_response(True, data=data, method="ping")
            except AdapterError as exc:
                return self.normalize_response(False, error=exc, method="ping")

        mapping = {
            "list_tools": "tools/list",
            "call_tool": "tools/call",
            "list_resources": "resources/list",
            "read_resource": "resources/read",
            "list_prompts": "prompts/list",
            "get_prompt": "prompts/get",
            "tools_list": "tools/list",
            "tools_call": "tools/call",
            "resources_list": "resources/list",
            "prompts_list": "prompts/list",
        }
        rpc_method = mapping.get(op)
        if rpc_method is None:
            raise AdapterValidationError(
                f"unsupported MCP operation {op!r}", transport=self.transport
            )

        params: Any = request.params.get("params") if request.params else None
        if params is None and op in ("call_tool", "tools_call"):
            params = {
                "name": request.params.get("name"),
                "arguments": request.params.get("arguments", {}),
            }
        try:
            data = self._rpc(rpc_method, params)
            return self.normalize_response(
                True, data=data, method=op, request_id=request.request_id
            )
        except AdapterError as exc:
            return self.normalize_response(
                False, error=exc, method=op, request_id=request.request_id
            )

    # -- conveniences ------------------------------------------------------- #

    def list_tools(self) -> List[Any]:
        response = self.execute(AdapterRequest(method="list_tools"))
        result = response.data or {}
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        response = self.execute(
            AdapterRequest(
                method="call_tool",
                params={"name": name, "arguments": arguments or {}},
            )
        )
        return response.data
