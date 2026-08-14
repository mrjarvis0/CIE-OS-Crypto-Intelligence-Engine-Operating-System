"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.rpc.rpc_manager

Purpose:
    High-level RPC coordination layer for selecting, inspecting, and tracking
    blockchain RPC endpoints.

Design goals:
    - No network I/O
    - No secrets
    - Pure coordination layer
    - Registry + fallback orchestration
    - Chain-aware request metadata
    - Safe to import anywhere

Notes:
    This module does not call RPC endpoints itself. It selects endpoints,
    exposes request profiles, and records endpoint health outcomes so runtime
    clients can use the chosen endpoint safely.

    AWS recommends retry/backoff with jitter and circuit-breaker style behavior
    for transient failures and overloaded downstream systems. This manager
    exposes the selection and health-tracking primitives needed for that model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping

from .chains import ChainConfig, ChainName, ChainRegistry, default_registry
from .fallback import (
    FallbackDecision,
    FallbackDecisionResult,
    RpcFallbackManager,
    build_fallback_manager,
)
from .rpc_config import (
    ChainRpcConfig,
    RpcEndpoint,
    RpcHealthStatus,
    RpcRegistry,
    build_default_rpc_registry,
)


# ==============================================================================
# CONSTANTS
# ==============================================================================

DEFAULT_USER_AGENT: Final[str] = "CIE-OS-A01/1.0.0"
DEFAULT_ACCEPT_HEADER: Final[str] = "application/json"


# ==============================================================================
# DATA MODELS
# ==============================================================================

@dataclass(frozen=True, slots=True)
class RpcResolution:
    """
    Resolved RPC selection for a specific chain.

    This is the output that runtime RPC clients should consume.
    """

    chain: ChainName
    chain_config: ChainConfig
    rpc_config: ChainRpcConfig
    endpoint: RpcEndpoint | None
    decision: FallbackDecision
    reason: str = ""
    request_headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30
    retries: int = 3
    backoff_seconds: float = 1.5
    max_backoff_seconds: float = 30.0

    @property
    def url(self) -> str | None:
        return None if self.endpoint is None else self.endpoint.url

    @property
    def transport(self) -> str | None:
        return None if self.endpoint is None or self.endpoint.transport is None else self.endpoint.transport.value

    @property
    def is_available(self) -> bool:
        return self.endpoint is not None and self.endpoint.enabled

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain.value,
            "chain_id": self.chain_config.chain_id,
            "chain_name": self.chain_config.display_name,
            "decision": self.decision.value,
            "reason": self.reason,
            "url": self.url,
            "transport": self.transport,
            "request_headers": dict(self.request_headers),
            "timeout_seconds": self.timeout_seconds,
            "retries": self.retries,
            "backoff_seconds": self.backoff_seconds,
            "max_backoff_seconds": self.max_backoff_seconds,
            "endpoint": None if self.endpoint is None else self.endpoint.as_dict(),
        }


# ==============================================================================
# MANAGER
# ==============================================================================

class RpcManager:
    """
    High-level RPC selection and health-tracking coordinator.

    Responsibilities:
    - Select the best endpoint for a chain
    - Merge request headers
    - Record endpoint success/failure
    - Expose snapshot/reporting helpers
    - Avoid any actual network I/O
    """

    def __init__(
        self,
        *,
        chain_registry: ChainRegistry | None = None,
        rpc_registry: RpcRegistry | None = None,
        fallback_manager: RpcFallbackManager | None = None,
        default_user_agent: str = DEFAULT_USER_AGENT,
        default_accept_header: str = DEFAULT_ACCEPT_HEADER,
    ) -> None:
        self._chain_registry = chain_registry or default_registry()
        self._rpc_registry = rpc_registry or build_default_rpc_registry(self._chain_registry)
        self._fallback_manager = fallback_manager or build_fallback_manager(self._rpc_registry)
        self._default_user_agent = default_user_agent
        self._default_accept_header = default_accept_header

    @classmethod
    def from_defaults(cls) -> "RpcManager":
        """Build a manager from the default chain registry and RPC registry."""
        chain_registry = default_registry()
        rpc_registry = build_default_rpc_registry(chain_registry)
        fallback_manager = build_fallback_manager(rpc_registry)
        return cls(
            chain_registry=chain_registry,
            rpc_registry=rpc_registry,
            fallback_manager=fallback_manager,
        )

    # --------------------------------------------------------------------------
    # Registry access
    # --------------------------------------------------------------------------

    @property
    def chain_registry(self) -> ChainRegistry:
        return self._chain_registry

    @property
    def rpc_registry(self) -> RpcRegistry:
        return self._rpc_registry

    @property
    def fallback_manager(self) -> RpcFallbackManager:
        return self._fallback_manager

    def get_chain_config(self, chain: ChainName | str) -> ChainConfig:
        return self._chain_registry.get_by_name(chain)

    def get_rpc_config(self, chain: ChainName | str) -> ChainRpcConfig:
        return self._rpc_registry.get(chain)

    def list_supported_chains(self) -> tuple[ChainName, ...]:
        return self._chain_registry.names()

    # --------------------------------------------------------------------------
    # Resolution
    # --------------------------------------------------------------------------

    def resolve(
        self,
        chain: ChainName | str,
        *,
        prefer_websocket: bool = False,
        extra_headers: Mapping[str, str] | None = None,
    ) -> RpcResolution:
        """
        Resolve the best RPC endpoint for a chain.

        This function never performs network I/O.
        """
        chain_config = self.get_chain_config(chain)
        rpc_config = self.get_rpc_config(chain)
        selection = self._fallback_manager.select_endpoint(
            chain_config.name,
            prefer_websocket=prefer_websocket or rpc_config.prefer_websocket,
        )

        headers: dict[str, str] = {
            "Accept": self._default_accept_header,
            "User-Agent": self._default_user_agent,
            **dict(rpc_config.request_headers),
        }
        if extra_headers:
            headers.update({str(k): str(v) for k, v in extra_headers.items() if str(k).strip()})

        endpoint = selection.endpoint
        if endpoint is None and rpc_config.primary_endpoint is not None:
            endpoint = rpc_config.primary_endpoint

        timeout_seconds = (
            endpoint.timeout_seconds
            if endpoint is not None
            else rpc_config.default_timeout_seconds
        )
        retries = (
            endpoint.retries
            if endpoint is not None
            else rpc_config.default_retries
        )
        backoff_seconds = (
            endpoint.backoff_seconds
            if endpoint is not None
            else rpc_config.default_backoff_seconds
        )
        max_backoff_seconds = (
            endpoint.max_backoff_seconds
            if endpoint is not None
            else rpc_config.default_max_backoff_seconds
        )

        return RpcResolution(
            chain=chain_config.name,
            chain_config=chain_config,
            rpc_config=rpc_config,
            endpoint=endpoint,
            decision=selection.decision,
            reason=selection.reason,
            request_headers=headers,
            timeout_seconds=timeout_seconds,
            retries=retries,
            backoff_seconds=backoff_seconds,
            max_backoff_seconds=max_backoff_seconds,
        )

    def resolve_url(
        self,
        chain: ChainName | str,
        *,
        prefer_websocket: bool = False,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        """Resolve only the endpoint URL. Raises if no endpoint is available."""
        resolution = self.resolve(
            chain,
            prefer_websocket=prefer_websocket,
            extra_headers=extra_headers,
        )
        if resolution.url is None:
            raise RuntimeError(f"No RPC endpoint available for chain {chain!r}")
        return resolution.url

    def resolve_headers(
        self,
        chain: ChainName | str,
        *,
        prefer_websocket: bool = False,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Resolve request headers for a chain."""
        return dict(
            self.resolve(
                chain,
                prefer_websocket=prefer_websocket,
                extra_headers=extra_headers,
            ).request_headers
        )

    # --------------------------------------------------------------------------
    # Health tracking
    # --------------------------------------------------------------------------

    def record_success(self, chain: ChainName | str, url: str) -> None:
        self._fallback_manager.mark_success(chain, url)

    def record_failure(
        self,
        chain: ChainName | str,
        url: str,
        *,
        hard_disable: bool = False,
    ) -> None:
        self._fallback_manager.mark_failure(chain, url, hard_disable=hard_disable)

    def record_disabled(self, chain: ChainName | str, url: str) -> None:
        self._fallback_manager.mark_disabled(chain, url)

    def record_healthy(self, chain: ChainName | str, url: str) -> None:
        self._fallback_manager.mark_healthy(chain, url)

    def refresh_chain(self, chain: ChainName | str) -> None:
        """
        Reset transient endpoint failures for a chain.

        Useful after a dependency comes back online.
        """
        self._fallback_manager.reset_chain(chain)

    # --------------------------------------------------------------------------
    # Introspection
    # --------------------------------------------------------------------------

    def is_chain_configured(self, chain: ChainName | str) -> bool:
        return self._rpc_registry.contains(chain)

    def has_usable_endpoint(self, chain: ChainName | str) -> bool:
        resolution = self.resolve(chain)
        return resolution.endpoint is not None and resolution.endpoint.enabled

    def get_primary_endpoint(self, chain: ChainName | str) -> RpcEndpoint | None:
        return self.get_rpc_config(chain).primary_endpoint

    def get_enabled_endpoints(self, chain: ChainName | str) -> tuple[RpcEndpoint, ...]:
        return self.get_rpc_config(chain).enabled_endpoints()

    def snapshot(self) -> dict[str, Any]:
        """
        Return a serializable operational snapshot.
        """
        return {
            "chains": [chain.value for chain in self._chain_registry.names()],
            "rpc_registry": self._rpc_registry.as_dict(),
            "fallback": self._fallback_manager.snapshot(),
        }

    def health_report(self) -> dict[str, dict[str, str]]:
        """
        Return chain-level health classification.
        """
        report: dict[str, dict[str, str]] = {}
        for chain in self._chain_registry.names():
            resolved = self.resolve(chain)
            report[chain.value] = {
                "decision": resolved.decision.value,
                "reason": resolved.reason,
                "endpoint_health": (
                    resolved.endpoint.health_status.value
                    if resolved.endpoint is not None
                    else RpcHealthStatus.UNHEALTHY.value
                ),
            }
        return report

    # --------------------------------------------------------------------------
    # Convenience helpers
    # --------------------------------------------------------------------------

    def build_request_context(
        self,
        chain: ChainName | str,
        *,
        prefer_websocket: bool = False,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Build a ready-to-send request context for downstream RPC clients.
        """
        resolved = self.resolve(
            chain,
            prefer_websocket=prefer_websocket,
            extra_headers=extra_headers,
        )
        return {
            "chain": resolved.chain.value,
            "url": resolved.url,
            "transport": resolved.transport,
            "headers": dict(resolved.request_headers),
            "timeout_seconds": resolved.timeout_seconds,
            "retries": resolved.retries,
            "backoff_seconds": resolved.backoff_seconds,
            "max_backoff_seconds": resolved.max_backoff_seconds,
            "decision": resolved.decision.value,
            "reason": resolved.reason,
        }


# ==============================================================================
# DEFAULT INSTANCE
# ==============================================================================

default_rpc_manager: Final[RpcManager] = RpcManager.from_defaults()


# ==============================================================================
# EXPORTS
# ==============================================================================

__all__ = [
    "RpcResolution",
    "RpcManager",
    "default_rpc_manager",
]
