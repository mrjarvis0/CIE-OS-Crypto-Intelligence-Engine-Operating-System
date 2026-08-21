"""
Tools :: AI :: Providers
========================

Shared plumbing for every non-local provider in the AI layer.

The capability modules (:mod:`~.llm`, :mod:`~.embedding`, ...) own the *shape*
of a request. This module owns everything a real provider needs underneath it:

* where a credential comes from, and how a missing one fails;
* how the HTTP call is made, retried and timed out;
* how a transport failure becomes an :class:`~.AIError`;
* how a streaming body (SSE or JSON-lines) is decoded;
* which provider a caller gets when it does not name one;
* what happens when that provider is down.

Nothing here knows what a completion or an embedding is. Capability code stays
free of urllib, and provider code stays free of transport details.

The HTTP work is delegated to :class:`tools.adapters.rest.RESTAdapter` rather
than re-implemented: retries, TLS policy, timeouts and status translation are
already solved there, and a second HTTP client in the tree would be a second
place for those policies to drift.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..adapters import (
    AdapterAuthenticationError,
    AdapterAuthorizationError,
    AdapterConnectionError,
    AdapterError,
    AdapterRequest,
    AdapterRetryableError,
    AdapterTimeoutError,
    AdapterValidationError,
)
from ..adapters.rest import RESTAdapter
from . import (
    AIAuthenticationError,
    AIAuthorizationError,
    AIConnectionError,
    AIError,
    AIExecutionError,
    AIResponse,
    AIRetryableError,
    AITimeoutError,
    AIValidationError,
    BaseAIModel,
)

__all__ = [
    "API_KEY_ENV",
    "PROVIDER_ALIASES",
    "canonical_provider",
    "api_key_env_names",
    "resolve_api_key",
    "HTTPTransport",
    "encode_multipart",
    "iter_sse_events",
    "iter_json_lines",
    "PRICES",
    "register_price",
    "estimate_cost",
    "ProviderSpec",
    "ProviderRegistry",
    "REGISTRY",
    "register_provider",
    "create_provider",
    "list_providers",
    "provider_spec",
    "ProviderChain",
    "configured_provider",
    "configured_model",
    "model_for",
]


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
# A key is read from the environment and never written to a log, a repr or an
# error message. The only thing an error is allowed to name is the *variable*
# the operator has to set.

#: Vendor environment variables per provider, in resolution order. An empty
#: tuple means the provider needs no credential (a local daemon, say).
API_KEY_ENV: Mapping[str, Tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "grok": ("XAI_API_KEY", "GROK_API_KEY"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "cohere": ("COHERE_API_KEY",),
    "voyage": ("VOYAGE_API_KEY",),
    "deepl": ("DEEPL_API_KEY",),
    "ollama": (),
    "local": (),
}

#: Names callers reach for that mean an already-registered provider.
PROVIDER_ALIASES: Mapping[str, str] = {
    "mock": "local",
    "offline": "local",
    "claude": "anthropic",
    "gpt": "openai",
    "azure": "openai",
    "xai": "grok",
}

#: Prefix for a deployment-local override, e.g. ``A01_AI_OPENAI_API_KEY``.
KEY_ENV_PREFIX = "A01_AI_"


def canonical_provider(name: str) -> str:
    """Lower-case a provider name and resolve any alias to its real name."""
    key = str(name or "").strip().lower()
    return PROVIDER_ALIASES.get(key, key)


def api_key_env_names(provider: str) -> Tuple[str, ...]:
    """Environment variables consulted for ``provider``, in priority order.

    The deployment-local override comes first so an operator can point one A01
    instance at a different account without touching the vendor variable the
    rest of the machine shares.
    """
    canonical = canonical_provider(provider)
    override = f"{KEY_ENV_PREFIX}{canonical.upper()}_API_KEY"
    return (override,) + tuple(API_KEY_ENV.get(canonical, ()))


def resolve_api_key(
    provider: str,
    explicit: Optional[str] = None,
    *,
    required: bool = True,
) -> str:
    """Resolve the credential for ``provider``.

    An explicitly passed key wins; otherwise the environment is read in the
    order given by :func:`api_key_env_names`. When nothing is found and the
    provider needs one, the raised error names the variables to set -- never a
    value, not even a partial one.
    """
    if explicit:
        return str(explicit)

    names = api_key_env_names(provider)
    for name in names:
        value = os.environ.get(name)
        if value:
            return value

    if not required or not API_KEY_ENV.get(canonical_provider(provider), ()):
        return ""
    raise AIAuthenticationError(
        f"no API key found; set one of: {', '.join(names)}",
        provider=canonical_provider(provider),
    )


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2

#: AdapterError -> AIError. Anything unmapped becomes an execution error, so a
#: new transport failure class surfaces as a failure rather than as a crash.
_ERROR_MAP: Tuple[Tuple[type, type], ...] = (
    (AdapterAuthenticationError, AIAuthenticationError),
    (AdapterAuthorizationError, AIAuthorizationError),
    (AdapterTimeoutError, AITimeoutError),
    (AdapterRetryableError, AIRetryableError),
    (AdapterConnectionError, AIConnectionError),
    (AdapterValidationError, AIValidationError),
)


def _default_adapter_factory(**options: Any) -> RESTAdapter:
    return RESTAdapter(**options)


class HTTPTransport:
    """The HTTP seam every remote provider calls through.

    One instance describes one provider endpoint: base URL, standing headers
    (auth, API version), timeout and retry budget. Per-call headers are merged
    over the standing ones.

    ``adapter_factory`` exists so a test can hand in a fake transport without a
    socket anywhere in the picture; production leaves it alone and gets
    :class:`~tools.adapters.rest.RESTAdapter`.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        verify_ssl: bool = True,
        provider: str = "unknown",
        adapter_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.verify_ssl = bool(verify_ssl)
        self.provider = provider
        self._adapter_factory = adapter_factory or _default_adapter_factory

    # -- plumbing ----------------------------------------------------------- #

    def _adapter(self, headers: Optional[Mapping[str, str]] = None) -> Any:
        merged = dict(self.headers)
        merged.update(headers or {})
        return self._adapter_factory(
            base_url=self.base_url,
            headers=merged,
            verify_ssl=self.verify_ssl,
            default_timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def _build(
        self,
        method: str,
        path: str,
        payload: Any,
        params: Optional[Mapping[str, Any]],
        timeout: Optional[float],
    ) -> AdapterRequest:
        return AdapterRequest(
            method=method.upper(),
            path=path,
            params=dict(params or {}),
            data=payload,
            timeout=float(timeout or self.timeout),
            retries=self.max_retries,
        )

    def translate(self, error: Optional[BaseException], *, model: str = "") -> AIError:
        """Translate a transport failure into the AI layer's error hierarchy."""
        if isinstance(error, AIError):
            return error
        message = str(error) if error is not None else "provider call failed"
        for adapter_type, ai_type in _ERROR_MAP:
            if isinstance(error, adapter_type):
                return ai_type(message, cause=error, provider=self.provider, model=model)
        return AIExecutionError(message, cause=error, provider=self.provider, model=model)

    # -- calls -------------------------------------------------------------- #

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        model: str = "",
    ) -> Any:
        """Perform one call and return the decoded body, or raise an AIError."""
        adapter = self._adapter(headers)
        request = self._build(method, path, payload, params, timeout)
        try:
            response = adapter.execute(request)
        except AdapterError as exc:
            raise self.translate(exc, model=model) from exc
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001 - defensive: nothing native escapes
            raise AIExecutionError(
                f"unexpected transport failure: {exc}",
                cause=exc,
                provider=self.provider,
                model=model,
            ) from exc

        if not getattr(response, "ok", False):
            raise self.translate(getattr(response, "error", None), model=model)
        return response.data

    def post_json(self, path: str, payload: Mapping[str, Any], **kwargs: Any) -> Mapping[str, Any]:
        """POST a JSON body and return the parsed JSON response."""
        data = self.request("POST", path, payload=dict(payload), **kwargs)
        return _require_mapping(data, provider=self.provider, model=str(kwargs.get("model", "")))

    def get_json(self, path: str, **kwargs: Any) -> Any:
        """GET and return the parsed JSON response."""
        return self.request("GET", path, **kwargs)

    def post_multipart(
        self,
        path: str,
        *,
        fields: Mapping[str, str],
        files: Mapping[str, Tuple[str, bytes, str]],
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        model: str = "",
    ) -> Any:
        """POST a ``multipart/form-data`` body (file uploads: audio, images)."""
        body, content_type = encode_multipart(fields, files)
        merged = dict(headers or {})
        merged["Content-Type"] = content_type
        return self.request(
            "POST", path, payload=body, headers=merged, timeout=timeout, model=model
        )

    def stream_raw(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        model: str = "",
    ) -> Iterator[bytes]:
        """Iterate the raw response body in chunks (streaming and binary)."""
        adapter = self._adapter(headers)
        request = self._build(method, path, payload, params, timeout)
        try:
            for chunk in adapter.stream(request):
                yield chunk
        except AdapterError as exc:
            raise self.translate(exc, model=model) from exc
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIExecutionError(
                f"unexpected stream failure: {exc}",
                cause=exc,
                provider=self.provider,
                model=model,
            ) from exc

    def post_bytes(self, path: str, payload: Any, **kwargs: Any) -> bytes:
        """POST and return the response body as bytes (audio, images).

        The JSON path decodes the body as text; synthesized audio must not go
        through that, so binary responses are read from the raw stream.
        """
        body = payload if isinstance(payload, (bytes, bytearray)) else dict(payload)
        return b"".join(self.stream_raw("POST", path, payload=body, **kwargs))

    def stream_sse(self, path: str, payload: Mapping[str, Any], **kwargs: Any) -> Iterator[Any]:
        """POST and yield decoded ``data:`` payloads of a Server-Sent-Events body."""
        chunks = self.stream_raw("POST", path, payload=dict(payload), **kwargs)
        for _event, data in iter_sse_events(chunks):
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except (ValueError, TypeError):
                continue

    def stream_json_lines(
        self, path: str, payload: Mapping[str, Any], **kwargs: Any
    ) -> Iterator[Any]:
        """POST and yield decoded newline-delimited JSON objects (Ollama style)."""
        chunks = self.stream_raw("POST", path, payload=dict(payload), **kwargs)
        yield from iter_json_lines(chunks)


def _require_mapping(data: Any, *, provider: str, model: str = "") -> Mapping[str, Any]:
    """A provider that answered with prose instead of JSON failed; say so."""
    if isinstance(data, Mapping):
        return data
    preview = str(data)[:200]
    raise AIExecutionError(
        f"provider returned a non-JSON body: {preview}", provider=provider, model=model
    )


def encode_multipart(
    fields: Mapping[str, str],
    files: Mapping[str, Tuple[str, bytes, str]],
) -> Tuple[bytes, str]:
    """Build a ``multipart/form-data`` body.

    ``files`` maps a form field to ``(filename, content, content_type)``.
    Returns the body and the ``Content-Type`` header value carrying the
    boundary.
    """
    boundary = f"----a01ai{uuid.uuid4().hex}"
    marker = f"--{boundary}".encode("ascii")
    parts: List[bytes] = []

    for name, value in fields.items():
        parts.append(marker)
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"))
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))

    for name, (filename, content, content_type) in files.items():
        parts.append(marker)
        disposition = f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'
        parts.append(disposition.encode("utf-8"))
        parts.append(f"Content-Type: {content_type}".encode("utf-8"))
        parts.append(b"")
        parts.append(bytes(content))

    parts.append(f"--{boundary}--".encode("ascii"))
    parts.append(b"")
    return b"\r\n".join(parts), f"multipart/form-data; boundary={boundary}"


def _as_text(chunk: Any) -> str:
    if isinstance(chunk, (bytes, bytearray)):
        return bytes(chunk).decode("utf-8", errors="replace")
    return str(chunk)


def iter_sse_events(chunks: Iterable[bytes]) -> Iterator[Tuple[str, str]]:
    """Decode a Server-Sent-Events byte stream into ``(event, data)`` pairs.

    Events are separated by a blank line and may be split across chunks at any
    byte, so the buffer is only cut on a completed record. Multi-line ``data:``
    fields are joined with newlines, per the SSE grammar.
    """
    buffer = ""
    for chunk in chunks:
        buffer += _as_text(chunk)
        buffer = buffer.replace("\r\n", "\n")
        while "\n\n" in buffer:
            block, _, buffer = buffer.partition("\n\n")
            event = _parse_sse_block(block)
            if event is not None:
                yield event
    if buffer.strip():
        event = _parse_sse_block(buffer)
        if event is not None:
            yield event


def _parse_sse_block(block: str) -> Optional[Tuple[str, str]]:
    name = "message"
    data: List[str] = []
    for line in block.split("\n"):
        if not line or line.startswith(":"):
            continue
        field_name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field_name == "event":
            name = value
        elif field_name == "data":
            data.append(value)
    if not data:
        return None
    return name, "\n".join(data)


def iter_json_lines(chunks: Iterable[bytes]) -> Iterator[Any]:
    """Decode a newline-delimited JSON byte stream into objects."""
    buffer = ""
    for chunk in chunks:
        buffer += _as_text(chunk)
        while "\n" in buffer:
            line, _, buffer = buffer.partition("\n")
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except (ValueError, TypeError):
                continue
    if buffer.strip():
        try:
            yield json.loads(buffer)
        except (ValueError, TypeError):
            return


# --------------------------------------------------------------------------- #
# Cost accounting
# --------------------------------------------------------------------------- #
# Published list prices, in USD per million tokens, as (input, output).
# A model that is not listed is priced at 0.0 rather than guessed: an invented
# number in a budget report is worse than an obvious zero.

PRICES: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("anthropic", "claude-fable-5"): (10.0, 50.0),
    ("anthropic", "claude-opus-5"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-8"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-7"): (5.0, 25.0),
    ("anthropic", "claude-opus-4-6"): (5.0, 25.0),
    ("anthropic", "claude-sonnet-5"): (3.0, 15.0),
    ("anthropic", "claude-sonnet-4-6"): (3.0, 15.0),
    ("anthropic", "claude-haiku-4-5"): (1.0, 5.0),
    ("local", "local"): (0.0, 0.0),
}


def register_price(
    provider: str, model: str, input_per_mtok: float, output_per_mtok: float
) -> None:
    """Record list pricing for a model so its usage carries a cost estimate."""
    PRICES[(canonical_provider(provider), str(model))] = (
        float(input_per_mtok),
        float(output_per_mtok),
    )


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate the USD cost of one call; 0.0 when the model is not priced."""
    canonical = canonical_provider(provider)
    rates = PRICES.get((canonical, str(model)))
    if rates is None:
        # Longest-prefix match, so a dated or regional variant of a listed model
        # ("claude-opus-5-20260101") still prices.
        candidates = [
            (key[1], value)
            for key, value in PRICES.items()
            if key[0] == canonical and key[1] and str(model).startswith(key[1])
        ]
        if not candidates:
            return 0.0
        rates = max(candidates, key=lambda item: len(item[0]))[1]
    prompt_rate, completion_rate = rates
    return (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000.0


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProviderSpec:
    """One registered implementation of one capability."""

    capability: str
    name: str
    factory: Callable[..., Any]
    requires_key: bool = True
    description: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "name": self.name,
            "requires_key": self.requires_key,
            "description": self.description,
            "key_env": list(api_key_env_names(self.name)) if self.requires_key else [],
        }


class ProviderRegistry:
    """Capability -> provider name -> factory.

    The Planner asks for a capability and, optionally, a provider name; it
    never imports a provider class. That is what keeps provider choice a
    deployment decision instead of a code change.
    """

    def __init__(self) -> None:
        self._specs: Dict[Tuple[str, str], ProviderSpec] = {}

    def register(self, spec: ProviderSpec, *, replace_existing: bool = False) -> ProviderSpec:
        key = (spec.capability, canonical_provider(spec.name))
        if key in self._specs and not replace_existing:
            raise AIValidationError(
                f"provider {spec.name!r} already registered for {spec.capability!r}"
            )
        self._specs[key] = spec
        return spec

    def unregister(self, capability: str, name: str) -> None:
        self._specs.pop((capability, canonical_provider(name)), None)

    def get(self, capability: str, name: str) -> ProviderSpec:
        spec = self._specs.get((capability, canonical_provider(name)))
        if spec is None:
            known = ", ".join(self.names(capability)) or "none"
            raise AIValidationError(
                f"unknown {capability} provider {name!r} (registered: {known})"
            )
        return spec

    def names(self, capability: str) -> Tuple[str, ...]:
        return tuple(sorted(key[1] for key in self._specs if key[0] == capability))

    def capabilities(self) -> Tuple[str, ...]:
        return tuple(sorted({key[0] for key in self._specs}))

    def create(self, capability: str, name: Optional[str] = None, **options: Any) -> Any:
        """Build a capability instance, defaulting to the configured provider."""
        chosen = name or configured_provider(capability)
        return self.get(capability, chosen).factory(**options)

    def as_dict(self) -> Dict[str, List[Dict[str, Any]]]:
        catalog: Dict[str, List[Dict[str, Any]]] = {}
        for (capability, _name), spec in sorted(self._specs.items()):
            catalog.setdefault(capability, []).append(spec.as_dict())
        return catalog


REGISTRY = ProviderRegistry()


def register_provider(
    capability: str,
    name: str,
    factory: Callable[..., Any],
    *,
    requires_key: bool = True,
    description: str = "",
    replace_existing: bool = False,
) -> ProviderSpec:
    """Register one provider implementation for one capability."""
    return REGISTRY.register(
        ProviderSpec(
            capability=capability,
            name=canonical_provider(name),
            factory=factory,
            requires_key=requires_key,
            description=description,
        ),
        replace_existing=replace_existing,
    )


def create_provider(capability: str, name: Optional[str] = None, **options: Any) -> Any:
    """Build a capability instance from the default registry."""
    return REGISTRY.create(capability, name, **options)


def list_providers(capability: str) -> Tuple[str, ...]:
    """Provider names registered for ``capability``."""
    return REGISTRY.names(capability)


def provider_spec(capability: str, name: str) -> ProviderSpec:
    """The registered spec for one provider of one capability."""
    return REGISTRY.get(capability, name)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
# Environment names line up with `config.settings.AISettings` (prefix A01_AI_),
# with a per-capability override so an operator can run, say, a hosted LLM and
# a local embedder without two config systems.


def configured_provider(capability: str = "", default: str = "local") -> str:
    """The provider name to use when a caller does not name one."""
    if capability:
        specific = os.environ.get(f"{KEY_ENV_PREFIX}{capability.upper()}_PROVIDER")
        if specific:
            return canonical_provider(specific)
    return canonical_provider(os.environ.get(f"{KEY_ENV_PREFIX}PROVIDER") or default)


def configured_model(capability: str = "", default: str = "") -> str:
    """The model id to use when a caller does not name one."""
    if capability:
        specific = os.environ.get(f"{KEY_ENV_PREFIX}{capability.upper()}_MODEL")
        if specific:
            return specific
    return os.environ.get(f"{KEY_ENV_PREFIX}MODEL_NAME") or default


def model_for(capability: str, provider: str, default: str = "") -> str:
    """The model id for one provider of one capability.

    The configured model id only applies to the *configured* provider. An
    operator who sets ``A01_AI_MODEL_NAME`` for OpenAI must not have that id
    quietly sent to Anthropic when a failover kicks in -- a model id is not
    portable between vendors, and the request would fail at the far end for a
    reason nobody could see from here.
    """
    if canonical_provider(provider) == configured_provider(capability, default=""):
        configured = configured_model(capability)
        if configured:
            return configured
    return default


# --------------------------------------------------------------------------- #
# Failover
# --------------------------------------------------------------------------- #

#: Failures worth trying the next provider for. An authentication or validation
#: error is not one of them: the same request fails the same way everywhere, and
#: retrying it elsewhere only spends another provider's quota.
FAILOVER_ERRORS: Tuple[type, ...] = (
    AIRetryableError,
    AIConnectionError,
    AITimeoutError,
    AIExecutionError,
)


class ProviderChain(BaseAIModel):
    """Try each provider in order; return the first normalized success.

    The response is the serving provider's own, so accounting still attributes
    the call correctly; a ``fallback_from`` entry is added to its metadata so a
    silent degradation is visible in a log.
    """

    provider = "chain"

    def __init__(
        self,
        models: Sequence[BaseAIModel],
        *,
        capability: str = "",
        retryable: Sequence[type] = FAILOVER_ERRORS,
        logger: Any = None,
    ) -> None:
        super().__init__(logger=logger)
        if not models:
            raise AIValidationError("a provider chain needs at least one model")
        self.models: Tuple[BaseAIModel, ...] = tuple(models)
        self.capability = capability or self.models[0].capability
        self.retryable: Tuple[type, ...] = tuple(retryable)
        self._model = self.models[0].model

    def execute(self, request: Any) -> AIResponse:
        skipped: List[str] = []
        last: Optional[AIError] = None

        for model in self.models:
            try:
                response = model.execute(request)
            except self.retryable as exc:  # type: ignore[misc]
                last = exc
                skipped.append(f"{model.provider}:{type(exc).__name__}")
                self.log.warning(
                    "ai provider %s failed (%s); trying next",
                    model.provider,
                    type(exc).__name__,
                )
                continue
            return self._annotate(response, skipped) if skipped else response

        raise last if last is not None else AIExecutionError(
            "every provider in the chain failed", provider=self.provider
        )

    def stream(self, request: Any) -> Iterator[Any]:
        last: Optional[AIError] = None
        for model in self.models:
            try:
                yield from model.stream(request)
                return
            except self.retryable as exc:  # type: ignore[misc]
                last = exc
                continue
        raise last if last is not None else AIExecutionError(
            "every provider in the chain failed", provider=self.provider
        )

    @staticmethod
    def _annotate(response: AIResponse, skipped: Sequence[str]) -> AIResponse:
        details = dict(response.metadata.details)
        details["fallback_from"] = list(skipped)
        return replace(response, metadata=replace(response.metadata, details=details))
