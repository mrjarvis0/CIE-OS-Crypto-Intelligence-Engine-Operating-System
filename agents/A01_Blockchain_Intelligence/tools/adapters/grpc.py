"""
Tools :: Adapters :: gRPC Adapter
=================================

Invokes gRPC services through the unified adapter contract.

Capabilities:
    * unary-unary calls
    * client-streaming, server-streaming and bidirectional streaming
    * metadata (headers) injection
    * deadline-based timeouts
    * secure (TLS with root certificates) and insecure channels
    * gRPC status-code translation into the shared :class:`AdapterError`
      hierarchy via :func:`grpc.StatusCode`

The actual gRPC wire protocol requires the third-party ``grpcio`` package. This
adapter therefore imports it lazily and raises a clear, actionable error if it
is unavailable. Callers who do not use gRPC never pay an import cost.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import (
    AdapterAuthenticationError,
    AdapterAuthorizationError,
    AdapterConnectionError,
    AdapterError,
    AdapterExecutionError,
    AdapterRequest,
    AdapterResponse,
    AdapterTimeoutError,
    AdapterValidationError,
    BaseAdapter,
)

__all__ = ["GRPCAdapter", "register"]


def register(**options: Any) -> "GRPCAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return GRPCAdapter(**options)


class GRPCAdapter(BaseAdapter):
    """
    gRPC client adapter.

    ``stub`` is either a *module* that owns the generated service Stub class
    (e.g. ``helloworld_pb2_grpc``), or a *class* directly. ``service`` selects
    the class name on the module, defaulting to ``"Stub"``. ``method`` inside a
    request selects the RPC name on the stub.

    Example
    -------
    >>> import helloworld_pb2_grpc
    >>> adapter = GRPCAdapter(target="localhost:50051", stub=helloworld_pb2_grpc)
    >>> adapter.execute(AdapterRequest(method="SayHello", data={"name": "world"}))
    """

    transport = "grpc"

    def __init__(
        self,
        *,
        target: str = "localhost:50051",
        stub: Any = None,
        service: str = "Stub",
        secure: bool = False,
        root_certificates: Optional[bytes] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.target = target
        self.stub = stub
        self.service = service
        self.secure = secure
        self.root_certificates = root_certificates
        self._channel: Any = None
        self._client: Any = None

    def _import_grpc(self) -> Any:
        try:
            import grpc  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise AdapterValidationError(
                "gRPC support requires the 'grpcio' package (pip install grpcio)",
                transport=self.transport,
            ) from exc
        return grpc

    def connect(self, **options: Any) -> "GRPCAdapter":
        grpc = self._import_grpc()
        if self.secure:
            creds = grpc.ssl_channel_credentials(self.root_certificates)
            self._channel = grpc.secure_channel(self.target, creds)
        else:
            self._channel = grpc.insecure_channel(self.target)

        if self.stub is None:
            raise AdapterValidationError(
                "a generated stub (module or class) must be provided via 'stub'",
                transport=self.transport,
            )
        stub_class = (
            getattr(self.stub, self.service) if not isinstance(self.stub, type) else self.stub
        )
        self._client = stub_class(self._channel)
        self._connected = True
        return self

    def close(self) -> None:
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
        self._channel = None
        self._client = None
        super().close()

    # -- helpers ------------------------------------------------------------ #

    def _method(self, request: AdapterRequest) -> Any:
        if self._client is None:
            self.connect()
        name = request.method
        if not name:
            raise AdapterValidationError(
                "request.method is the gRPC method name", transport=self.transport
            )
        method = getattr(self._client, name, None)
        if method is None:
            raise AdapterValidationError(
                f"no method {name!r} on {type(self._client).__name__}",
                transport=self.transport,
            )
        return method

    def _is_server_streaming(self, method: Any) -> bool:
        """Best-effort detection of response-streaming RPCs."""
        attrs = getattr(method, "_attrs", None)
        if attrs is not None:
            try:
                return bool(attrs.response_streaming)
            except AttributeError:
                return False
        return False

    def _translate_error(self, grpc: Any, exc: BaseException, method: str) -> AdapterError:
        """Map a grpcio RpcError into the shared error hierarchy by status code."""
        code = getattr(exc, "code", lambda: None)()
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            return AdapterTimeoutError(
                f"gRPC deadline exceeded for {method}", transport=self.transport
            )
        if code == grpc.StatusCode.UNAUTHENTICATED:
            return AdapterAuthenticationError(
                f"gRPC authentication failed for {method}",
                transport=self.transport,
            )
        if code == grpc.StatusCode.PERMISSION_DENIED:
            return AdapterAuthorizationError(
                f"gRPC permission denied for {method}",
                transport=self.transport,
            )
        if code in (
            grpc.StatusCode.UNAVAILABLE,
            grpc.StatusCode.CANCELLED,
        ):
            return AdapterConnectionError(
                f"gRPC {code.name} for {method}: {exc}",
                transport=self.transport,
            )
        return AdapterExecutionError(
            f"gRPC call failed for {method}: {exc}",
            cause=exc,
            transport=self.transport,
        )

    def _payload(self, request: AdapterRequest) -> Any:
        return request.data if request.data is not None else request.params

    def _metadata(self, request: AdapterRequest) -> List[Tuple[str, str]]:
        return [(k, str(v)) for k, v in request.headers.items()]

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        try:
            grpc = self._import_grpc()
            self.connect()
            method = self._method(request)
        except AdapterError as exc:
            return self.normalize_response(
                False, error=exc, method=request.method, request_id=request.request_id
            )

        kwargs: Dict[str, Any] = {"timeout": float(request.timeout or 30.0)}
        if request.headers:
            kwargs["metadata"] = self._metadata(request)

        try:
            if self._is_server_streaming(method):
                responses = list(method(self._payload(request), **kwargs))
                return self.normalize_response(
                    True,
                    data=responses,
                    method=request.method,
                    request_id=request.request_id,
                )

            result = method(self._payload(request), **kwargs)
            return self.normalize_response(
                True, data=result, method=request.method, request_id=request.request_id
            )
        except BaseException as exc:  # noqa: BLE001 - grpc errors are translated
            translated = self._translate_error(grpc, exc, request.method or "")
            return self.normalize_response(
                False,
                error=translated,
                method=request.method,
                request_id=request.request_id,
            )

    def stream(self, request: AdapterRequest) -> Iterator[Any]:
        """Yield responses from a server-streaming gRPC method."""
        self.validate_request(request)
        grpc = self._import_grpc()
        self.connect()
        method = self._method(request)
        kwargs: Dict[str, Any] = {"timeout": float(request.timeout or 30.0)}
        if request.headers:
            kwargs["metadata"] = self._metadata(request)
        try:
            for response in method(self._payload(request), **kwargs):
                yield response
        except BaseException as exc:  # noqa: BLE001 - translated
            raise self._translate_error(grpc, exc, request.method or "")