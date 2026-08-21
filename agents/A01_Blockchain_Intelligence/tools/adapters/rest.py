"""
Tools :: Adapters :: REST Adapter
=================================

Performs HTTP requests against JSON APIs through the unified adapter contract.

Method support: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS.

Features:
    * headers and query-string parameters
    * basic / bearer authentication
    * TLS verification control
    * configurable timeouts and connection read timeouts
    * automatic retries on transient failures with exponential backoff
    * streaming responses (iterating over raw body chunks)

Implemented on top of the standard library ``urllib.request`` so no third-party
HTTP client is required.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, Optional

from . import (
    AdapterAuthenticationError,
    AdapterAuthorizationError,
    AdapterConnectionError,
    AdapterError,
    AdapterRetryableError,
    AdapterRequest,
    AdapterResponse,
    AdapterTimeoutError,
    AdapterTransportError,
    AdapterValidationError,
    BaseAdapter,
    retry,
)

__all__ = ["RESTAdapter", "register"]

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

# HTTP status codes that are safe to retry.
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

_READ_CHUNK = 8192

#: How much of an error body travels with the error. Enough for a JSON error
#: envelope; short enough that a stack trace stays readable and an HTML error
#: page does not end up in the log.
_ERROR_BODY_LIMIT = 400


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """The server's error body, trimmed, as a suffix for the error message."""
    try:
        body = exc.read()
    except Exception:  # noqa: BLE001 - the body is a bonus, never the failure
        return ""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    if len(text) > _ERROR_BODY_LIMIT:
        text = text[:_ERROR_BODY_LIMIT] + "..."
    return ": " + " ".join(text.split())


def register(**options: Any) -> "RESTAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return RESTAdapter(**options)


class RESTAdapter(BaseAdapter):
    """HTTP(S) adapter wrapping ``urllib`` into the unified interface."""

    transport = "rest"

    def __init__(
        self,
        *,
        base_url: str = "",
        headers: Optional[Dict[str, str]] = None,
        auth: Optional[tuple[str, str]] = None,
        bearer_token: Optional[str] = None,
        verify_ssl: bool = True,
        default_timeout: float = 30.0,
        max_retries: int = 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.auth = auth
        self.bearer_token = bearer_token
        self.verify_ssl = verify_ssl
        self.default_timeout = default_timeout
        self.max_retries = max_retries

    # -- request building --------------------------------------------------- #

    def _url(self, path: str, params: Dict[str, Any]) -> str:
        if not path:
            path = "/"
        if self.base_url and not path.startswith(("http://", "https://")):
            url = self.base_url + ("" if path.startswith("/") else "/") + path
        else:
            url = path
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return url

    def _request_headers(self, method: str) -> Dict[str, str]:
        hdrs = dict(self.headers)
        if "User-Agent" not in hdrs:
            hdrs["User-Agent"] = "CIE-OS/adapters-rest"
        if self.auth:
            token = f"{self.auth[0]}:{self.auth[1]}"
            hdrs["Authorization"] = "Basic " + base64.b64encode(
                token.encode("utf-8")
            ).decode("ascii")
        elif self.bearer_token:
            hdrs["Authorization"] = "Bearer " + self.bearer_token
        if method in {"POST", "PUT", "PATCH"} and "Content-Type" not in hdrs:
            hdrs["Content-Type"] = "application/json"
        return hdrs

    def _context(self) -> "ssl.SSLContext":
        # Imported here, not at module load. TLS is only needed to *make* a
        # request, so a policy that blocks the _ssl DLL should fail the request
        # that needs it -- not the import of every module that transitively
        # touches this one. Read-only paths (storage, the dashboard) pull this
        # module in through the package tree and must not die because HTTPS is
        # unavailable in the environment they run in.
        import ssl

        ctx = ssl.create_default_context()
        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _build(self, request: AdapterRequest) -> tuple[urllib.request.Request, float]:
        """Build the urllib Request and resolve the effective timeout."""
        method = (request.method or "GET").upper()
        url = self._url(request.path, request.params)

        body: Optional[bytes] = None
        if request.data is not None:
            if isinstance(request.data, (bytes, bytearray)):
                body = bytes(request.data)
            elif isinstance(request.data, str):
                body = request.data.encode("utf-8")
            else:
                body = json.dumps(request.data).encode("utf-8")

        timeout = float(request.timeout or self.default_timeout)
        headers = self._request_headers(method)
        if body is not None and method not in {"POST", "PUT", "PATCH"}:
            # A body on a GET/HEAD/DELETE is usually a caller mistake; keep it
            # but leave Content-Type untouched.
            pass
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        return req, timeout

    # -- single attempt ----------------------------------------------------- #

    def _attempt(self, request: AdapterRequest) -> AdapterResponse:
        method = (request.method or "GET").upper()
        if method not in METHODS:
            raise AdapterValidationError(
                f"unsupported HTTP method {method!r}", transport=self.transport
            )

        req, timeout = self._build(request)
        url = req.full_url

        try:
            started = time.monotonic()
            with urllib.request.urlopen(req, timeout=timeout, context=self._context()) as resp:
                raw = resp.read()
                status = resp.status
                headers = dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            # urlopen raises HTTPError for 4xx/5xx; the response body carries the
            # server's own explanation ("model not found", "rate limit reached",
            # "temperature is not supported on this model") and is the only part
            # of the failure a caller can act on, so it travels with the error.
            detail = _error_detail(exc)
            self.log.debug("HTTP error %s for %s %s", exc.code, method, url)
            if exc.code in RETRYABLE_STATUS:
                raise AdapterRetryableError(
                    f"transient HTTP {exc.code} for {method} {url}{detail}",
                    transport=self.transport,
                ) from exc
            if exc.code in (401,):
                raise AdapterAuthenticationError(
                    f"authentication failed (HTTP 401) for {url}{detail}",
                    transport=self.transport,
                ) from exc
            if exc.code in (403,):
                raise AdapterAuthorizationError(
                    f"forbidden (HTTP 403) for {url}{detail}", transport=self.transport
                ) from exc
            raise AdapterTransportError(
                f"HTTP {exc.code} for {method} {url}{detail}", transport=self.transport
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, ConnectionError)):
                raise AdapterRetryableError(
                    f"connection failure for {url}: {exc.reason}",
                    transport=self.transport,
                ) from exc
            raise AdapterConnectionError(
                f"could not reach {url}: {exc.reason}", transport=self.transport
            ) from exc
        except (TimeoutError) as exc:
            raise AdapterTimeoutError(
                f"request timed out after {timeout}s for {url}",
                transport=self.transport,
            ) from exc

        # Decode and best-effort parse JSON.
        text = raw.decode("utf-8", errors="replace")
        try:
            data: Any = json.loads(text)
        except (ValueError, TypeError):
            data = text

        duration = (time.monotonic() - started) * 1000.0
        return self.normalize_response(
            True,
            data=data,
            method=method,
            request_id=request.request_id,
            status_code=status,
            headers=headers,
            duration_ms=duration,
        )

    # -- public API --------------------------------------------------------- #

    def connect(self, **options: Any) -> "RESTAdapter":
        """Stateless HTTP; mark connected so callers can gate execution."""
        self._connected = True
        return self

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        attempts = max(1, request.retries or self.max_retries) + 1

        @retry(attempts=attempts, delay=0.4, backoff=2.0, retryable=AdapterRetryableError)
        def _do() -> AdapterResponse:
            return self._attempt(request)

        try:
            return _do()
        except AdapterError as exc:
            # Every protocol-family failure is reported as a failed response.
            return self.normalize_response(
                False,
                error=exc,
                method=request.method,
                request_id=request.request_id,
            )
        except Exception as exc:  # pragma: no cover - defensive translation
            return self.normalize_response(
                False,
                error=AdapterTransportError(
                    f"unexpected HTTP failure: {exc}", cause=exc, transport=self.transport
                ),
                method=request.method,
                request_id=request.request_id,
            )

    def stream(self, request: AdapterRequest) -> Iterable[bytes]:
        """Stream the raw response body in chunks.

        The request is built by :meth:`_build`, the same way an executed one is.
        Streaming used to build its own ``Request`` with ``data=None``, which
        silently dropped the body: a streamed POST (an SSE completion, a
        text-to-speech call) arrived at the server with no payload at all.
        """
        self.validate_request(request)
        method = (request.method or "GET").upper()
        if method not in METHODS:
            raise AdapterValidationError(
                f"unsupported HTTP method {method!r}", transport=self.transport
            )
        req, timeout = self._build(request)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout, context=self._context())
        except urllib.error.HTTPError as exc:
            raise AdapterTransportError(
                f"HTTP {exc.code} for {method} {req.full_url}{_error_detail(exc)}",
                transport=self.transport,
            ) from exc
        except urllib.error.URLError as exc:
            raise AdapterConnectionError(
                f"could not reach {req.full_url}: {exc.reason}",
                transport=self.transport,
            ) from exc
        except (TimeoutError) as exc:
            raise AdapterTimeoutError(
                f"request timed out streaming {req.full_url}",
                transport=self.transport,
            ) from exc

        with resp:
            while True:
                try:
                    chunk = resp.read(_READ_CHUNK)
                except (TimeoutError) as exc:
                    raise AdapterTimeoutError(
                        f"stream read timed out for {req.full_url}",
                        transport=self.transport,
                    ) from exc
                except OSError as exc:
                    raise AdapterConnectionError(
                        f"stream interrupted for {req.full_url}: {exc}",
                        transport=self.transport,
                    ) from exc
                if not chunk:
                    break
                yield chunk


# ``socket.timeout`` is an alias of builtin ``TimeoutError`` on Python 3.10+,
# but keeping an explicit reference keeps intent obvious and forwards-compatible.
import socket as _socket  # noqa: E402

socket_timeout = _socket.timeout