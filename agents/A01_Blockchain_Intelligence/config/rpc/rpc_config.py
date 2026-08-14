"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.rpc.rpc_config

Purpose:
    Typed RPC configuration models and registry helpers for blockchain access.

Design goals:
    - Strong typing
    - No network I/O
    - No secrets
    - Support multiple endpoints per chain
    - Provide failover metadata for rpc_manager
    - Safe to import anywhere
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .chains import ChainConfig, ChainName, ChainRegistry, default_registry

# ==============================================================================
# CONSTANTS
# ==============================================================================

DEFAULT_RPC_TIMEOUT_SECONDS: Final[int] = 30
DEFAULT_RPC_RETRIES: Final[int] = 3
DEFAULT_RPC_BACKOFF_SECONDS: Final[float] = 1.5
DEFAULT_RPC_MAX_BACKOFF_SECONDS: Final[float] = 30.0
DEFAULT_RPC_PRIORITY_STEP: Final[int] = 10

SUPPORTED_RPC_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https", "ws", "wss", "ipc"})


# ==============================================================================
# ENUMS
# ==============================================================================

class RpcTransport(StrEnum):
    """Supported RPC transport types."""

    HTTP = "http"
    HTTPS = "https"
    WS = "ws"
    WSS = "wss"
    IPC = "ipc"


class RpcHealthStatus(StrEnum):
    """Endpoint health classification."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"


# ==============================================================================
# VALIDATION HELPERS
# ==============================================================================

def _validate_url(url: str) -> None:
    clean = url.strip()
    if not clean:
        raise ValueError("RPC URL cannot be empty")

    parsed = urlparse(clean)
    scheme = parsed.scheme.lower()

    if scheme not in SUPPORTED_RPC_SCHEMES:
        raise ValueError(f"Unsupported RPC URL scheme: {url!r}")

    if scheme != "ipc" and not parsed.netloc:
        raise ValueError(f"RPC URL must include a network location: {url!r}")


def _infer_transport(url: str) -> RpcTransport:
    scheme = urlparse(url.strip()).scheme.lower()
    if scheme == "http":
        return RpcTransport.HTTP
    if scheme == "https":
        return RpcTransport.HTTPS
    if scheme == "ws":
        return RpcTransport.WS
    if scheme == "wss":
        return RpcTransport.WSS
    if scheme == "ipc":
        return RpcTransport.IPC
    raise ValueError(f"Unsupported RPC transport: {scheme!r}")


# ==============================================================================
# MODELS
# ==============================================================================

@dataclass(frozen=True, slots=True)
class RpcEndpoint:
    """Immutable RPC endpoint definition."""

    url: str
    transport: RpcTransport | None = None
    priority: int = 0
    timeout_seconds: int = DEFAULT_RPC_TIMEOUT_SECONDS
    retries: int = DEFAULT_RPC_RETRIES
    backoff_seconds: float = DEFAULT_RPC_BACKOFF_SECONDS
    max_backoff_seconds: float = DEFAULT_RPC_MAX_BACKOFF_SECONDS
    health_status: RpcHealthStatus = RpcHealthStatus.UNKNOWN
    enabled: bool = True
    tags: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        clean_url = self.url.strip()
        _validate_url(clean_url)

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.retries < 0:
            raise ValueError("retries must be >= 0")
        if self.backoff_seconds <= 0:
            raise ValueError("backoff_seconds must be greater than zero")
        if self.max_backoff_seconds <= 0:
            raise ValueError("max_backoff_seconds must be greater than zero")
        if self.priority < 0:
            raise ValueError("priority must be >= 0")

        object.__setattr__(self, "url", clean_url)

        if self.transport is None:
            object.__setattr__(self, "transport", _infer_transport(clean_url))

    @property
    def scheme(self) -> str:
        return urlparse(self.url).scheme.lower()

    @property
    def is_ws(self) -> bool:
        return self.transport in {RpcTransport.WS, RpcTransport.WSS}

    @property
    def is_http(self) -> bool:
        return self.transport in {RpcTransport.HTTP, RpcTransport.HTTPS}

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "transport": self.transport.value if self.transport else None,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "retries": self.retries,
            "backoff_seconds": self.backoff_seconds,
            "max_backoff_seconds": self.max_backoff_seconds,
            "health_status": self.health_status.value,
            "enabled": self.enabled,
            "tags": self.tags,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class ChainRpcConfig:
    """RPC configuration attached to a blockchain chain."""

    chain: ChainConfig
    endpoints: tuple[RpcEndpoint, ...] = ()
    default_timeout_seconds: int = DEFAULT_RPC_TIMEOUT_SECONDS
    default_retries: int = DEFAULT_RPC_RETRIES
    default_backoff_seconds: float = DEFAULT_RPC_BACKOFF_SECONDS
    default_max_backoff_seconds: float = DEFAULT_RPC_MAX_BACKOFF_SECONDS
    request_headers: Mapping[str, str] = field(default_factory=dict)
    user_agent: str = "CIE-OS-A01/1.0.0"
    active_endpoint_index: int = 0
    prefer_websocket: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be > 0")
        if self.default_retries < 0:
            raise ValueError("default_retries must be >= 0")
        if self.default_backoff_seconds <= 0:
            raise ValueError("default_backoff_seconds must be > 0")
        if self.default_max_backoff_seconds <= 0:
            raise ValueError("default_max_backoff_seconds must be > 0")
        if self.active_endpoint_index < 0:
            raise ValueError("active_endpoint_index must be >= 0")

        normalized_headers = {
            str(k).strip(): str(v).strip()
            for k, v in self.request_headers.items()
            if str(k).strip()
        }
        object.__setattr__(self, "request_headers", normalized_headers)

        for endpoint in self.endpoints:
            if endpoint.transport is None:
                raise ValueError(f"Endpoint transport could not be inferred: {endpoint.url!r}")

    @property
    def has_endpoints(self) -> bool:
        return len(self.endpoints) > 0

    @property
    def primary_endpoint(self) -> RpcEndpoint | None:
        if not self.endpoints:
            return None
        index = min(self.active_endpoint_index, len(self.endpoints) - 1)
        return self.endpoints[index]

    @property
    def ordered_endpoints(self) -> tuple[RpcEndpoint, ...]:
        return tuple(sorted(self.endpoints, key=lambda endpoint: (not endpoint.enabled, endpoint.priority)))

    def enabled_endpoints(self) -> tuple[RpcEndpoint, ...]:
        return tuple(endpoint for endpoint in self.ordered_endpoints if endpoint.enabled)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain.name.value,
            "chain_id": self.chain.chain_id,
            "default_timeout_seconds": self.default_timeout_seconds,
            "default_retries": self.default_retries,
            "default_backoff_seconds": self.default_backoff_seconds,
            "default_max_backoff_seconds": self.default_max_backoff_seconds,
            "request_headers": dict(self.request_headers),
            "user_agent": self.user_agent,
            "active_endpoint_index": self.active_endpoint_index,
            "prefer_websocket": self.prefer_websocket,
            "enabled": self.enabled,
            "endpoints": [endpoint.as_dict() for endpoint in self.endpoints],
        }


@dataclass(slots=True)
class RpcRegistry:
    """Registry of RPC settings by chain."""

    configs: Mapping[ChainName, ChainRpcConfig] = field(default_factory=dict)

    def get(self, chain: ChainName | str) -> ChainRpcConfig:
        key = chain if isinstance(chain, ChainName) else ChainName(str(chain).lower())
        if key not in self.configs:
            raise KeyError(f"No RPC config registered for chain: {chain!r}")
        return self.configs[key]

    def contains(self, chain: ChainName | str) -> bool:
        try:
            self.get(chain)
            return True
        except (KeyError, ValueError):
            return False

    def all(self) -> tuple[ChainRpcConfig, ...]:
        return tuple(self.configs.values())

    def enabled(self) -> tuple[ChainRpcConfig, ...]:
        return tuple(cfg for cfg in self.configs.values() if cfg.enabled)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {key.value: cfg.as_dict() for key, cfg in self.configs.items()}


# ==============================================================================
# BUILDERS
# ==============================================================================

def _build_rpc_endpoints_for_urls(
    chain: ChainConfig,
    urls: Sequence[str],
) -> tuple[RpcEndpoint, ...]:
    endpoints: list[RpcEndpoint] = []

    for index, url in enumerate(urls):
        endpoints.append(
            RpcEndpoint(
                url=url,
                priority=index * DEFAULT_RPC_PRIORITY_STEP,
                timeout_seconds=DEFAULT_RPC_TIMEOUT_SECONDS,
                retries=DEFAULT_RPC_RETRIES,
                backoff_seconds=DEFAULT_RPC_BACKOFF_SECONDS,
                max_backoff_seconds=DEFAULT_RPC_MAX_BACKOFF_SECONDS,
                tags=(chain.name.value,),
            )
        )

    return tuple(endpoints)


def build_default_rpc_registry(
    registry: ChainRegistry | None = None,
    overrides: Mapping[ChainName, Sequence[str]] | None = None,
) -> RpcRegistry:
    """
    Build a default registry from chain metadata.

    Args:
        registry: optional source chain registry
        overrides: optional chain-specific RPC URL overrides
    """
    source = registry or default_registry()
    mapping: dict[ChainName, ChainRpcConfig] = {}

    for chain in source:
        urls: Sequence[str] = chain.rpc_urls
        if overrides and chain.name in overrides:
            urls = overrides[chain.name]

        endpoints = _build_rpc_endpoints_for_urls(chain, urls)

        mapping[chain.name] = ChainRpcConfig(
            chain=chain,
            endpoints=endpoints,
            request_headers={
                "Accept": "application/json",
                "User-Agent": "CIE-OS-A01/1.0.0",
            },
        )

    return RpcRegistry(configs=mapping)


# ==============================================================================
# HELPERS
# ==============================================================================

def normalize_rpc_urls(urls: Iterable[str]) -> tuple[str, ...]:
    """Validate and normalize a sequence of RPC URLs."""
    normalized: list[str] = []
    for url in urls:
        clean = url.strip()
        _validate_url(clean)
        normalized.append(clean)
    return tuple(normalized)


__all__ = [
    "RpcTransport",
    "RpcHealthStatus",
    "RpcEndpoint",
    "ChainRpcConfig",
    "RpcRegistry",
    "build_default_rpc_registry",
    "normalize_rpc_urls",
]
