"""
Tools :: Adapters :: Python Adapter
===================================

Executes local Python callables safely through the unified adapter contract.

Use cases:
    * internal utility functions
    * AI / data processing pipelines
    * mathematical operations
    * local algorithms that are fast enough to run in-process

Design notes:
    * the target callable is resolved by dotted-name lookup within an allow-list
      of importable modules (never from arbitrary user-supplied strings unless
      the operator explicitly opts into ``allow_any``);
    * a wall-clock timeout is enforced by running the callable in a worker thread;
    * exceptions raised by the target are translated into
      :class:`AdapterExecutionError` without leaking the traceback to callers;
    * return values that are not JSON-serializable are wrapped in a ``{"_repr": ...}``
      descriptor so downstream layers always receive JSON-safe payloads.

This adapter is intentionally *in-process*. For isolation-heavy workloads prefer
the ``subprocess`` or ``docker`` adapters.
"""

from __future__ import annotations

import importlib
import inspect
import json
import threading
from typing import Any, Optional

from . import (
    AdapterExecutionError,
    AdapterRequest,
    AdapterResponse,
    AdapterValidationError,
    BaseAdapter,
)

__all__ = ["PythonAdapter", "register"]

DEFAULT_ALLOWED_MODULES: tuple[str, ...] = (
    "math",
    "statistics",
    "datetime",
    "functools",
    "itertools",
    "json",
    "re",
)


def register(**options: Any) -> "PythonAdapter":
    """Factory used by :func:`adapters.get_adapter`."""
    return PythonAdapter(**options)


class PythonAdapter(BaseAdapter):
    """
    Execute local Python callables behind the uniform adapter interface.

    Example
    -------
    >>> adapter = PythonAdapter()
    >>> adapter.execute(AdapterRequest(
    ...     method="call",
    ...     params={"target": "math.gcd", "args": [12, 8]}))
    <AdapterResponse ok=True data=4 ...>
    """

    transport = "python"

    def __init__(
        self,
        *,
        allowed_modules: Optional[tuple[str, ...]] = None,
        allow_any: bool = False,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Restrict dotted-name resolution to these modules by default. If the
        # operator opts into allow_any=True the restriction is removed.
        self._allowed_modules = tuple(allowed_modules or DEFAULT_ALLOWED_MODULES)
        self._allow_any = allow_any
        self.default_timeout = timeout

    # -- resolution --------------------------------------------------------- #

    def _resolve(self, target: str) -> Any:
        """Resolve ``module.path:attribute`` style targets to a callable."""
        if not isinstance(target, str) or not target.strip():
            raise AdapterValidationError(
                "target must be a non-empty string", transport=self.transport
            )

        # Support both "module.attr" and "module:attr" notations.
        target = target.strip()
        module_part: str
        rest: str
        if ":" in target:
            module_part, rest = target.split(":", 1)
        else:
            parts = target.split(".")
            if len(parts) < 2:
                raise AdapterValidationError(
                    f"target {target!r} must include a module", transport=self.transport
                )
            module_part, rest = parts[0], ".".join(parts[1:])

        if not self._allow_any and module_part not in self._allowed_modules:
            raise AdapterValidationError(
                f"module {module_part!r} is not in the allow-list "
                f"{sorted(self._allowed_modules)}",
                transport=self.transport,
            )

        try:
            module = importlib.import_module(module_part)
        except ImportError as exc:  # pragma: no cover - depends on availability
            raise AdapterValidationError(
                f"could not import module {module_part!r}: {exc}",
                transport=self.transport,
            ) from exc

        obj: Any = module
        for bit in rest.split("."):
            if not hasattr(obj, bit):
                raise AdapterValidationError(
                    f"{module_part}:{rest!r} does not exist", transport=self.transport
                )
            obj = getattr(obj, bit)

        if not callable(obj):
            raise AdapterValidationError(
                f"{target!r} resolved to a non-callable value", transport=self.transport
            )
        return obj

    # -- execution ---------------------------------------------------------- #

    def connect(self, **options: Any) -> "PythonAdapter":
        """In-process adapters have no persistent connection to open."""
        self._connected = True
        return self

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        self.validate_request(request)
        method = (request.method or "call").lower()

        if method == "ping":
            return self.normalize_response(True, data="pong", method="ping")

        if method != "call":
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    f"unsupported method {method!r}; expected 'call' or 'ping'",
                    transport=self.transport,
                ),
                method=method,
            )

        try:
            target = str(request.params.get("target") or "")
            args, kwargs = self._parse_call_params(request.params)
            timeout = float(
                request.params.get("timeout") or request.timeout or self.default_timeout
            )
            if timeout <= 0:
                raise AdapterValidationError(
                    "timeout must be a positive number", transport=self.transport
                )
        except (TypeError, ValueError) as exc:
            return self.normalize_response(
                False,
                error=AdapterValidationError(
                    f"malformed call parameters: {exc}", transport=self.transport
                ),
                method="call",
            )

        try:
            func = self._resolve(target)
        except AdapterValidationError as exc:
            return self.normalize_response(False, error=exc, method="call")

        result: Any = None
        error: Optional[BaseException] = None

        def _run() -> None:
            nonlocal result, error
            try:
                # Bind against a partially-bound call to surface signature
                # mismatches early without leaking the traceback.
                _ = inspect.signature(func).bind_partial(*args, **kwargs)
                result = func(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - translated, not leaked
                error = exc

        thread = threading.Thread(
            target=_run, name=f"python-adapter-{request.request_id}", daemon=True
        )
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # Do not kill the thread; report a timeout and let it finish in the
            # background. This keeps shared interpreter state consistent.
            self.log.warning("callable %s exceeded %ss timeout", target, timeout)
            return self.normalize_response(
                False,
                error=AdapterExecutionError(
                    f"callable {target!r} timed out after {timeout}s",
                    transport=self.transport,
                    request_id=request.request_id,
                ),
                method="call",
                request_id=request.request_id,
            )

        if error is not None:
            return self.normalize_response(
                False,
                error=AdapterExecutionError(
                    f"callable {target!r} raised {type(error).__name__}: {error}",
                    cause=error,
                    transport=self.transport,
                    request_id=request.request_id,
                ),
                method="call",
                request_id=request.request_id,
            )

        return self.normalize_response(
            True, data=self._json_safe(result), method="call", request_id=request.request_id
        )

    # -- helpers ------------------------------------------------------------ #

    @staticmethod
    def _parse_call_params(params: dict) -> tuple[list, dict]:
        """Extract ``args``/``kwargs`` from request params with validation."""
        raw_args = params.get("args", ())
        raw_kwargs = params.get("kwargs", {})

        if isinstance(raw_args, (str, bytes)) or not isinstance(raw_args, (list, tuple)):
            raise AdapterValidationError(
                "params['args'] must be a list or tuple", transport="python"
            )
        if not isinstance(raw_kwargs, dict):
            raise AdapterValidationError(
                "params['kwargs'] must be a dict", transport="python"
            )
        return list(raw_args), dict(raw_kwargs)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Return ``value`` if JSON-serializable, else a repr descriptor."""
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return {"_repr": repr(value)}
