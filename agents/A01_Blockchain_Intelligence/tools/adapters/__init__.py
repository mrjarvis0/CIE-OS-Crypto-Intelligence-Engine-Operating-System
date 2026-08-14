"""
Tools :: Adapters Layer
=======================

The Adapters Layer translates between the unified internal Tool interface and
the concrete transports used by external systems: REST, RPC, gRPC, WebSocket,
MCP, CLI, Docker and plain Python callables.

This package exposes:

* the canonical :class:`BaseAdapter` contract every transport must satisfy;
* a shared :class:`AdapterError` hierarchy so transport-specific failures never
  leak upward into the Planning Engine;
* ready-to-use adapter implementations for each supported transport.

Adapters are intentionally free of business logic. They perform protocol
translation, request/response normalization, error translation, connection
management, retries and timeouts. Higher layers interact with every transport
through the same uniform interface.

Two hard rules for every adapter in this package:

1. A transport may *raise* :class:`AdapterError` subclasses (validation,
   connection, timeout, ...); it must never leak a protocol-native exception
   (``urllib``, ``socket``, ``subprocess``, ``grpc``, ...) to a caller.
2. ``execute()`` returns an :class:`AdapterResponse`; runtime failures are
   encoded as ``ok=False`` responses with an attached ``error`` rather than
   uncaught exceptions.
"""

from __future__ import annotations

import abc
import asyncio
import functools
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

__all__ = [
    "AdapterError",
    "AdapterConnectionError",
    "AdapterAuthenticationError",
    "AdapterAuthorizationError",
    "AdapterTimeoutError",
    "AdapterValidationError",
    "AdapterTransportError",
    "AdapterExecutionError",
    "AdapterRetryableError",
    "AdapterFatalError",
    "AdapterRequest",
    "AdapterResponse",
    "AdapterMetadata",
    "BaseAdapter",
    "retry",
    "get_adapter",
    "PythonAdapter",
    "RESTAdapter",
    "RPCAdapter",
    "RPCError",
    "GRPCAdapter",
    "WebSocketAdapter",
    "WSFrame",
    "MCPAdapter",
    "CLIAdapter",
    "DockerAdapter",
    "SubprocessAdapter",
]

logger = logging.getLogger(__name__)

T = TypeVar("T")

# --------------------------------------------------------------------------- #
# Shared error model
# --------------------------------------------------------------------------- #
# Transport-specific failures are translated into this unified hierarchy so
# that callers in the Tool Manager, Executor and Planning Engine never depend
# on the underlying protocols.
#
# Hierarchy:
#   AdapterError
#   ├── AdapterConnectionError      transport unreachable / dropped
#   ├── AdapterAuthenticationError  credentials rejected
#   ├── AdapterAuthorizationError   authenticated but not permitted
#   ├── AdapterTimeoutError         time budget exceeded
#   ├── AdapterValidationError      request invalid before execution
#   ├── AdapterTransportError       protocol-level error from remote
#   ├── AdapterExecutionError       operation ran but failed
#   ├── AdapterRetryableError       transient; safe to retry
#   └── AdapterFatalError           non-recoverable; do not retry


class AdapterError(Exception):
    """Base class for every error raised by an adapter."""

    def __init__(
        self,
        message: str = "",
        *,
        cause: Optional[BaseException] = None,
        transport: str = "unknown",
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.transport = transport
        self.request_id = request_id

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        prefix = f"[{self.transport}"
        if self.request_id:
            prefix += f":{self.request_id}"
        return f"{prefix}] {self.message}"


class AdapterConnectionError(AdapterError):
    """The underlying transport could not be reached or the connection closed."""


class AdapterAuthenticationError(AdapterError):
    """Credentials were rejected by the remote end-point."""


class AdapterAuthorizationError(AdapterError):
    """The authenticated principal lacks the required permissions."""


class AdapterTimeoutError(AdapterError):
    """A request exceeded its configured time budget."""


class AdapterValidationError(AdapterError):
    """An incoming request failed local validation before execution."""


class AdapterTransportError(AdapterError):
    """The remote end-point returned an error at the protocol level."""


class AdapterExecutionError(AdapterError):
    """The transport executed the request but the operation itself failed."""


class AdapterRetryableError(AdapterError):
    """A transient failure that is safe to retry."""


class AdapterFatalError(AdapterError):
    """A non-recoverable failure; retrying is pointless."""


# --------------------------------------------------------------------------- #
# Request / Response data structures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AdapterMetadata:
    """
    Immutable execution metadata attached to every :class:`AdapterResponse`.

    ``started_at`` is the wall-clock time the adapter began the attempt;
    ``duration_ms`` is filled in by the adapter once the attempt completes.
    ``retries`` reports how many *retry* attempts were consumed.
    """

    transport: str
    method: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.monotonic)
    duration_ms: float = 0.0
    retries: int = 0
    status_code: Optional[int] = None
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterRequest:
    """A normalized, transport-independent request descriptor.

    ``method`` is the operation name for this transport: ``"call"`` for
    ``python``, an HTTP verb for ``rest``, a JSON-RPC method for ``rpc``/``mcp``,
    ``"run"`` for ``subprocess``/``cli``, a container action for ``docker``, and
    ``"send"/"recv"`` for ``websocket``. ``path`` is transport-specific
    (URL path, endpoint). ``params`` holds transport-specific arguments.

    The dataclass is frozen; do not mutate ``params``/``headers`` in-place.
    """

    method: str
    path: str = "/"
    params: Dict[str, Any] = field(default_factory=dict)
    data: Any = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    retries: int = 0
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class AdapterResponse:
    """A normalized, transport-independent response.

    ``ok=True`` carries the payload in ``data``; ``ok=False`` carries the
    translated failure in ``error``. ``metadata`` never carries raw protocol
    objects, only JSON-serializable primitives.
    """

    ok: bool
    data: Any = None
    error: Optional[AdapterError] = None
    metadata: AdapterMetadata = field(default_factory=AdapterMetadata)


# --------------------------------------------------------------------------- #
# Retry helper
# --------------------------------------------------------------------------- #

RetryableTypes = Union[Type[BaseException], Tuple[Type[BaseException], ...]]


def retry(
    attempts: int = 3,
    *,
    delay: float = 0.5,
    backoff: float = 2.0,
    retryable: RetryableTypes = AdapterRetryableError,
):
    """
    Decorator that retries a callable on retryable failures.

    Parameters
    ----------
    attempts:
        Maximum number of attempts (>= 1).
    delay:
        Initial delay between attempts, in seconds.
    backoff:
        Multiplier applied to the delay after each failed attempt.
    retryable:
        Exception type (or tuple of types) that is safe to retry.

    The decorated function preserves its ``__name__``, ``__doc__`` and
    signature metadata via :func:`functools.wraps`.
    """

    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorate(func: T) -> T:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _delay = delay
                last: Optional[BaseException] = None
                for attempt in range(1, attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except retryable as exc:  # type: ignore[arg-type]
                        last = exc
                        if attempt == attempts:
                            break
                        await asyncio.sleep(_delay)
                        _delay *= backoff
                raise last  # type: ignore[misc]

            return _async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _delay = delay
            last: Optional[BaseException] = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable as exc:  # type: ignore[arg-type]
                    last = exc
                    if attempt == attempts:
                        break
                    time.sleep(_delay)
                    _delay *= backoff
            raise last  # type: ignore[misc]

        return _sync_wrapper  # type: ignore[return-value]

    return decorate


# --------------------------------------------------------------------------- #
# Base adapter contract
# --------------------------------------------------------------------------- #


class BaseAdapter(abc.ABC):
    """
    The canonical contract every transport adapter must implement.

    Implementations should be lightweight, stateless where possible, and never
    raise protocol-native exceptions to callers. Instead they must translate
    failures into the :mod:`AdapterError` hierarchy and encode runtime failures
    as ``ok=False`` :class:`AdapterResponse` objects.

    Lifecycle
    ---------
    connect() -> execute()/stream() -> close()

    Adapters may lazily connect during ``execute()``; the explicit ``connect()``
    and ``close()`` hooks exist for transports that pool long-lived connections.
    """

    transport: str = "base"

    def __init__(self, *, logger: Optional[logging.Logger] = None) -> None:
        self.log = logger or logging.getLogger(f"{__name__}.{type(self).__name__}")
        self._connected = False

    # -- lifecycle ---------------------------------------------------------- #

    @abc.abstractmethod
    def connect(self, **options: Any) -> "BaseAdapter":
        """Open (or lazily configure) the underlying transport connection."""
        raise NotImplementedError

    def close(self) -> None:
        """Release any resources held by the adapter."""
        self._connected = False

    async def aclose(self) -> None:
        """Async variant of :meth:`close` for adapters with async resources."""
        self.close()

    # -- execution ---------------------------------------------------------- #

    @abc.abstractmethod
    def execute(self, request: AdapterRequest) -> AdapterResponse:
        """Execute a normalized request and return a normalized response."""
        raise NotImplementedError

    def stream(self, request: AdapterRequest) -> Any:
        """
        Execute a request and return an iterator over result chunks.

        Returns an async iterator when the adapter is async-capable, otherwise
        a synchronous iterator. The default implementation returns the whole
        response as a single chunk.
        """
        response = self.execute(request)
        return iter([response])

    async def aexecute(self, request: AdapterRequest) -> AdapterResponse:
        """
        Async variant of :meth:`execute`.

        The default implementation runs the synchronous execute in a thread so
        async callers are never blocked.
        """
        return await asyncio.get_running_loop().run_in_executor(
            None, self.execute, request
        )

    def astream(self, request: AdapterRequest) -> AsyncIterator[Any]:
        """
        Async variant of :meth:`stream`.
        """

        async def _iter() -> AsyncIterator[Any]:
            for chunk in self.stream(request):
                yield chunk

        return _iter()

    # -- helpers ------------------------------------------------------------ #

    def health_check(self, timeout: float = 5.0) -> bool:
        """
        Probe the transport and return True if it is usable.

        A health check should be cheap and must not raise; failures return
        False rather than propagating an exception.
        """
        try:
            response = self.execute(AdapterRequest(method="PING", timeout=timeout))
            return response.ok
        except AdapterError:
            return False

    def validate_request(self, request: AdapterRequest) -> None:
        """
        Validate that a request is well-formed for this transport.

        Raises :class:`AdapterValidationError` on invalid input.
        """
        if not isinstance(request, AdapterRequest):
            raise AdapterValidationError(
                "request must be an AdapterRequest", transport=self.transport
            )
        if not request.method:
            raise AdapterValidationError(
                "request.method is required", transport=self.transport
            )

    def normalize_response(
        self,
        ok: bool,
        data: Any = None,
        error: Optional[AdapterError] = None,
        **meta: Any,
    ) -> AdapterResponse:
        """
        Build a normalized :class:`AdapterResponse` with consistent metadata.

        Accepts optional ``method``, ``request_id``, ``status_code``, ``headers``,
        ``retries`` and ``duration_ms`` keyword arguments.
        """
        metadata = AdapterMetadata(
            transport=self.transport,
            method=str(meta.get("method") or "execute"),
            request_id=str(meta.get("request_id") or uuid.uuid4().hex),
            duration_ms=float(meta.get("duration_ms", 0.0)),
            retries=int(meta.get("retries", 0)),
            status_code=meta.get("status_code"),
            headers=dict(meta.get("headers") or {}),
        )
        return AdapterResponse(ok=ok, data=data, error=error, metadata=metadata)


# --------------------------------------------------------------------------- #
# Adapter registry
# --------------------------------------------------------------------------- #
# Concrete adapters are imported lazily so that packages with optional
# third-party dependencies (``grpcio``) are only loaded on demand.
# --------------------------------------------------------------------------- #

_ADAPTER_MODULES: Dict[str, str] = {
    "python": "python",
    "rest": "rest",
    "rpc": "rpc",
    "grpc": "grpc",
    "websocket": "websocket",
    "ws": "websocket",
    "mcp": "mcp",
    "cli": "cli",
    "docker": "docker",
    "subprocess": "subprocess",
}


def get_adapter(name: str, **options: Any) -> BaseAdapter:
    """
    Factory that returns a ready-to-use adapter by transport name.

    Supported names: ``python``, ``rest``, ``rpc``, ``grpc``, ``websocket``
    (alias ``ws``), ``mcp``, ``cli``, ``docker``, ``subprocess``.

    ``options`` are forwarded to the adapter constructor. Adapters with
    mandatory configuration (e.g. ``rpc`` requires ``url``) must be passed
    those options here.
    """
    module_name = _ADAPTER_MODULES.get(name.strip().lower())
    if module_name is None:
        raise AdapterValidationError(
            f"unknown adapter: {name!r}", transport="registry"
        )

    module = __import__(f"{__name__}.{module_name}", fromlist=["register"])
    adapter = module.register(**options)  # type: ignore[attr-defined]
    if not isinstance(adapter, BaseAdapter):
        raise AdapterValidationError(
            f"adapter {name!r} did not produce a BaseAdapter", transport="registry"
        )
    return adapter


# --------------------------------------------------------------------------- #
# Concrete adapters
# --------------------------------------------------------------------------- #
# The concrete transport adapters are re-exported here as public API. Their
# modules import optional third-party dependencies lazily, so loading this
# package never fails when e.g. ``grpcio`` is not installed.
# --------------------------------------------------------------------------- #

from .cli import CLIAdapter  # noqa: E402
from .docker import DockerAdapter  # noqa: E402
from .grpc import GRPCAdapter  # noqa: E402
from .mcp import MCPAdapter  # noqa: E402
from .python import PythonAdapter  # noqa: E402
from .rest import RESTAdapter  # noqa: E402
from .rpc import RPCAdapter, RPCError  # noqa: E402
from .subprocess import SubprocessAdapter  # noqa: E402
from .websocket import WebSocketAdapter, WSFrame  # noqa: E402
