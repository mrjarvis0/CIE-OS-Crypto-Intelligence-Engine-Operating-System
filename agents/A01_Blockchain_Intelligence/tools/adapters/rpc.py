"""
Tools :: Adapters :: RPC Adapter
================================

Performs JSON-RPC 2.0 calls against remote endpoints through the unified
adapter contract.

Primary use cases:
    * Ethereum / EVM JSON-RPC nodes (eth_getBalance, eth_call, ...)
    * generic JSON-RPC services
    * internal RPC servers

Capabilities:
    * single and batch (array) requests
    * optional id-less notifications
    * connection pooling with keep-alive HTTP connections
    * retry with exponential backoff on transient failures
    * endpoint failover across a list of fallback URLs

The adapter follows the JSON-RPC 2.0 specification (https://www.jsonrpc.org/spec)
including the ``error`` object shape (``code`` / ``message`` / ``data``) and
parses responses strictly.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.parse
from typing import Any, Dict, Optional, Sequence

from . import (
    AdapterConnectionError,
    AdapterError,
    AdapterRequest,
    AdapterResponse,
    AdapterRetryableError,
    AdapterTimeoutError,
    AdapterTransportError,
    AdapterValidationError,
    BaseAdapter,
    retry,
)

__all__ = ["RPCAdapter", "RPCError", "register"]

# HTTP status codes that are safe to retry (per RFC 7231 semantics).
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# Well-known JSON-RPC 2.0 error codes (spec section 5.1).
RESERVED_CODES = {-32700, -32600, -32601, -32602, -32603}


def register(**options: Any) -> "RPCAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return RPCAdapter(**options)


class RPCError(AdapterTransportError):
    """A JSON-RPC error object was returned by the remote end-point."""

    def __init__(self, code: int, message: str, data: Any = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.code = code
        self.remote_data = data


class RPCAdapter(BaseAdapter):
    """JSON-RPC 2.0 client over HTTP(S) with failover and batching."""

    transport = "rpc"

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        endpoints: Optional[Sequence[str]] = None,
        headers: Optional[Dict[str, str]] = None,
        verify_ssl: bool = True,
        default_timeout: float = 30.0,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if url is None and endpoints is None:
            raise AdapterValidationError(
                "either 'url' or 'endpoints' is required", transport=self.transport
            )
        if endpoints is None:
            endpoints = [url or ""]
        self.endpoints = list(endpoints)
        self.headers = dict(headers or {})
        self.verify_ssl = verify_ssl
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        self._conns: Dict[str, http.client.HTTPConnection] = {}

    # -- connection management ---------------------------------------------- #

    def _conn_for(self, endpoint: str) -> http.client.HTTPConnection:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in ("http", "https"):
            raise AdapterValidationError(
                f"unsupported RPC scheme {parsed.scheme!r}", transport=self.transport
            )
        if not parsed.hostname:
            raise AdapterValidationError(
                f"RPC endpoint has no host: {endpoint!r}", transport=self.transport
            )

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        key = f"{parsed.hostname}:{port}"
        conn = self._conns.get(key)
        if conn is None:
            if parsed.scheme == "https":
                # Lazy: TLS is only needed to open a connection, so a policy
                # blocking the _ssl DLL must fail this request rather than the
                # import of every module that transitively reaches this one.
                import ssl

                ctx = ssl.create_default_context()
                if not self.verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection(
                    parsed.hostname, port, timeout=self.default_timeout, context=ctx
                )
            else:
                conn = http.client.HTTPConnection(
                    parsed.hostname, port, timeout=self.default_timeout
                )
            self._conns[key] = conn
        return conn

    def connect(self, **options: Any) -> "RPCAdapter":
        """Pre-connect pooled connections for every endpoint."""
        for endpoint in self.endpoints:
            self._conn_for(endpoint)
        self._connected = True
        return self

    def close(self) -> None:
        for conn in self._conns.values():
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._conns.clear()
        super().close()

    def _drop_conn(self, conn: http.client.HTTPConnection) -> None:
        """Remove a dead pooled connection so the next call reconnects."""
        dead = next((k for k, v in self._conns.items() if v is conn), None)
        if dead is not None:
            self._conns.pop(dead, None)

    # -- request helpers ---------------------------------------------------- #

    def _post(self, endpoint: str, payload: Any, timeout: float) -> Dict[str, Any]:
        conn = self._conn_for(endpoint)
        body = json.dumps(payload).encode("utf-8")
        path = urllib.parse.urlparse(endpoint).path or "/"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CIE-OS/adapters-rpc",
            **self.headers,
        }
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            status = resp.status
        except TimeoutError as exc:
            # Drop the dead pooled connection so the next call reconnects.
            self._drop_conn(conn)
            raise AdapterTimeoutError(
                f"RPC request timed out for {endpoint}", transport=self.transport
            ) from exc
        except (http.client.HTTPException, OSError) as exc:
            # Drop the dead pooled connection so the next call reconnects.
            self._drop_conn(conn)
            raise AdapterRetryableError(
                f"RPC transport failure for {endpoint}: {exc}", transport=self.transport
            ) from exc

        if status != 200:
            if status in RETRYABLE_STATUS:
                raise AdapterRetryableError(
                    f"RPC HTTP {status} from {endpoint}", transport=self.transport
                )
            raise AdapterTransportError(
                f"RPC HTTP {status} from {endpoint}", transport=self.transport
            )

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise AdapterTransportError(
                f"invalid JSON-RPC response from {endpoint}", transport=self.transport
            ) from exc
        return {"status": status, "body": parsed}

    def _call_single(
        self,
        endpoint: str,
        method: str,
        params: Any,
        rpc_id: Any,
        timeout: float,
    ) -> Any:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if rpc_id is not None:
            payload["id"] = rpc_id

        result = self._post(endpoint, payload, timeout)
        body = result["body"]
        if "error" in body and body["error"] is not None:
            err = body["error"]
            raise RPCError(
                err.get("code", -32000),
                err.get("message", "unknown RPC error"),
                data=err.get("data"),
                transport=self.transport,
            )
        if "result" not in body:
            raise AdapterTransportError(
                f"JSON-RPC response missing 'result' or 'error' from {endpoint}",
                transport=self.transport,
            )
        return body.get("result")

    def _call_with_failover(
        self, method: str, params: Any, rpc_id: Any, timeout: float
    ) -> Any:
        """Try each endpoint; only retryable failures trigger failover."""
        last_err: Optional[AdapterError] = None
        for endpoint in self.endpoints:
            try:
                return self._call_single(endpoint, method, params, rpc_id, timeout)
            except (RPCError, AdapterValidationError):
                raise  # protocol/validation errors are not endpoint problems
            except AdapterRetryableError as exc:
                last_err = exc
                self.log.warning("endpoint %s transient failure: %s", endpoint, exc)
                continue
        if last_err is not None:
            raise last_err
        raise AdapterConnectionError("no endpoints available", transport=self.transport)

    # -- public API --------------------------------------------------------- #

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        method = request.method or "call"
        # NOTE: params is a dict on a frozen dataclass; read, never mutate.
        rpc_id: Any = request.params.get("id", request.request_id)
        timeout = float(request.timeout or self.default_timeout)

        # -- batch mode ---------------------------------------------------- #
        # params["batch"] holds a list of {"method", "params", "id"} objects.
        batch: Any = request.params.get("batch")
        if batch is not None:
            return self._execute_batch(batch, timeout, request.request_id)

        params: Any = request.params.get("params")
        attempts = max(1, request.retries or self.max_retries) + 1

        @retry(attempts=attempts, delay=0.3, backoff=2.0, retryable=AdapterRetryableError)
        def _do() -> Any:
            return self._call_with_failover(method, params, rpc_id, timeout)

        try:
            started = time.monotonic()
            data = _do()
            duration = (time.monotonic() - started) * 1000.0
            return self.normalize_response(
                True,
                data=data,
                method=method,
                request_id=request.request_id,
                duration_ms=duration,
            )
        except AdapterError as exc:
            return self.normalize_response(
                False,
                error=exc,
                method=method,
                request_id=request.request_id,
            )
        except Exception as exc:  # pragma: no cover - defensive translation
            return self.normalize_response(
                False,
                error=AdapterTransportError(
                    f"unexpected RPC failure: {exc}", cause=exc, transport=self.transport
                ),
                method=method,
                request_id=request.request_id,
            )

    def _execute_batch(
        self, batch: Any, timeout: float, request_id: str
    ) -> AdapterResponse:
        if not isinstance(batch, (list, tuple)) or len(batch) == 0:
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    "params['batch'] must be a non-empty list", transport=self.transport
                ),
                method="batch",
                request_id=request_id,
            )

        try:
            payload = [
                {
                    "jsonrpc": "2.0",
                    "method": item["method"],
                    "params": item.get("params"),
                    "id": item.get("id", i + 1),
                }
                for i, item in enumerate(batch)
            ]
        except (KeyError, TypeError, AttributeError) as exc:
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    f"invalid batch entry: {exc}", transport=self.transport
                ),
                method="batch",
                request_id=request_id,
            )

        responses: Any = None
        for endpoint in self.endpoints:
            try:
                responses = self._post(endpoint, payload, timeout)["body"]
                break
            except AdapterRetryableError:
                self.log.warning("endpoint %s failed for batch; trying next", endpoint)
                continue
            except AdapterError as exc:
                return self.normalize_response(
                    False, error=exc, method="batch", request_id=request_id
                )
        if responses is None:
            return self.normalize_response(
                False,
                error=AdapterConnectionError(
                    "all RPC endpoints failed for batch", transport=self.transport
                ),
                method="batch",
                request_id=request_id,
            )
        return self.normalize_response(
            True, data=responses, method="batch", request_id=request_id
        )