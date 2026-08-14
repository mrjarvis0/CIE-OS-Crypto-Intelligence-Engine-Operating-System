"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.rpc.fallback

Purpose:
    RPC endpoint fallback, health tracking, and failover selection.

Design goals:
    - No network I/O
    - No secrets
    - Retry-aware
    - Cooldown-aware
    - Circuit-breaker-style behavior
    - Safe to import anywhere

Notes:
    Transient failures should be retried using exponential backoff, and repeated
    failures should trip a fallback/circuit-breaker style protection so callers
    stop hammering the same unhealthy endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import Any, Final

from .chains import ChainName
from .rpc_config import ChainRpcConfig, RpcEndpoint, RpcHealthStatus, RpcRegistry


# ==============================================================================
# CONSTANTS
# ==============================================================================

DEFAULT_FAILURE_THRESHOLD: Final[int] = 3
DEFAULT_COOLDOWN_SECONDS: Final[float] = 30.0


# ==============================================================================
# ENUMS
# ==============================================================================

class FallbackDecision(StrEnum):
    """Selection outcome when asking for an RPC endpoint."""

    SELECTED = "selected"
    DEGRADED = "degraded"
    FALLBACK = "fallback"
    NONE_AVAILABLE = "none_available"


# ==============================================================================
# DATA MODELS
# ==============================================================================

@dataclass(slots=True)
class EndpointState:
    """Mutable health state for a single RPC endpoint."""

    endpoint: RpcEndpoint
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_at: float | None = None
    last_success_at: float | None = None
    circuit_open_until: float | None = None

    def is_circuit_open(self, now: float | None = None) -> bool:
        current = monotonic() if now is None else now
        return self.circuit_open_until is not None and self.circuit_open_until > current

    def is_available(self, now: float | None = None) -> bool:
        current = monotonic() if now is None else now
        return self.endpoint.enabled and not self.is_circuit_open(current)

    def mark_success(self) -> None:
        self.consecutive_failures = 0
        self.total_successes += 1
        self.last_success_at = monotonic()
        self.circuit_open_until = None

    def mark_failure(self, *, failure_threshold: int, cooldown_seconds: float) -> None:
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure_at = monotonic()

        if self.consecutive_failures >= failure_threshold:
            self.circuit_open_until = monotonic() + cooldown_seconds

    def mark_disabled(self) -> None:
        self.endpoint = RpcEndpoint(
            url=self.endpoint.url,
            transport=self.endpoint.transport,
            priority=self.endpoint.priority,
            timeout_seconds=self.endpoint.timeout_seconds,
            retries=self.endpoint.retries,
            backoff_seconds=self.endpoint.backoff_seconds,
            max_backoff_seconds=self.endpoint.max_backoff_seconds,
            health_status=RpcHealthStatus.DISABLED,
            enabled=False,
            tags=self.endpoint.tags,
            notes=self.endpoint.notes,
        )

    def effective_health(self, now: float | None = None) -> RpcHealthStatus:
        current = monotonic() if now is None else now
        if not self.endpoint.enabled:
            return RpcHealthStatus.DISABLED
        if self.is_circuit_open(current):
            return RpcHealthStatus.UNHEALTHY
        if self.consecutive_failures >= 1:
            return RpcHealthStatus.DEGRADED
        return RpcHealthStatus.HEALTHY


@dataclass(frozen=True, slots=True)
class FallbackDecisionResult:
    """Result returned when the fallback manager selects an endpoint."""

    chain: ChainName
    endpoint: RpcEndpoint | None
    decision: FallbackDecision
    reason: str = ""


# ==============================================================================
# MANAGER
# ==============================================================================

class RpcFallbackManager:
    """Track RPC endpoint health and pick the next usable endpoint."""

    def __init__(
        self,
        registry: RpcRegistry,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be greater than zero")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be greater than zero")

        self._registry = registry
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._states: dict[tuple[ChainName, str], EndpointState] = {}
        self._seed_states()

    def _seed_states(self) -> None:
        for chain_config in self._registry.all():
            for endpoint in chain_config.endpoints:
                self._states[(chain_config.chain.name, endpoint.url)] = EndpointState(endpoint=endpoint)

    def get_chain_config(self, chain: ChainName | str) -> ChainRpcConfig:
        return self._registry.get(chain)

    def get_state(self, chain: ChainName | str, url: str) -> EndpointState:
        chain_name = chain if isinstance(chain, ChainName) else ChainName(str(chain).lower())
        key = (chain_name, url.strip())
        if key not in self._states:
            raise KeyError(f"Unknown endpoint state for chain={chain_name!r}, url={url!r}")
        return self._states[key]

    def mark_success(self, chain: ChainName | str, url: str) -> None:
        self.get_state(chain, url).mark_success()

    def mark_failure(self, chain: ChainName | str, url: str, *, hard_disable: bool = False) -> None:
        state = self.get_state(chain, url)
        state.mark_failure(
            failure_threshold=self._failure_threshold,
            cooldown_seconds=self._cooldown_seconds,
        )
        if hard_disable:
            state.mark_disabled()

    def mark_disabled(self, chain: ChainName | str, url: str) -> None:
        state = self.get_state(chain, url)
        state.mark_disabled()

    def mark_healthy(self, chain: ChainName | str, url: str) -> None:
        state = self.get_state(chain, url)
        state.endpoint = RpcEndpoint(
            url=state.endpoint.url,
            transport=state.endpoint.transport,
            priority=state.endpoint.priority,
            timeout_seconds=state.endpoint.timeout_seconds,
            retries=state.endpoint.retries,
            backoff_seconds=state.endpoint.backoff_seconds,
            max_backoff_seconds=state.endpoint.max_backoff_seconds,
            health_status=RpcHealthStatus.HEALTHY,
            enabled=True,
            tags=state.endpoint.tags,
            notes=state.endpoint.notes,
        )
        state.mark_success()

    def get_available_endpoints(self, chain: ChainName | str) -> tuple[EndpointState, ...]:
        chain_config = self.get_chain_config(chain)
        now = monotonic()
        states = [
            self.get_state(chain_config.chain.name, endpoint.url)
            for endpoint in chain_config.ordered_endpoints
        ]
        return tuple(state for state in states if state.is_available(now))

    def select_endpoint(
        self,
        chain: ChainName | str,
        *,
        prefer_websocket: bool = False,
    ) -> FallbackDecisionResult:
        chain_config = self.get_chain_config(chain)
        now = monotonic()

        ordered_states = [
            self.get_state(chain_config.chain.name, endpoint.url)
            for endpoint in chain_config.ordered_endpoints
            if endpoint.enabled
        ]

        if prefer_websocket:
            ws_states = [
                state for state in ordered_states
                if state.endpoint.is_ws and state.is_available(now)
            ]
            if ws_states:
                chosen = ws_states[0]
                status = chosen.effective_health(now)
                return FallbackDecisionResult(
                    chain=chain_config.chain.name,
                    endpoint=chosen.endpoint,
                    decision=FallbackDecision.SELECTED if status == RpcHealthStatus.HEALTHY else FallbackDecision.DEGRADED,
                    reason="selected websocket endpoint",
                )

        available = [state for state in ordered_states if state.is_available(now)]
        if available:
            chosen = available[0]
            status = chosen.effective_health(now)
            return FallbackDecisionResult(
                chain=chain_config.chain.name,
                endpoint=chosen.endpoint,
                decision=FallbackDecision.SELECTED if status == RpcHealthStatus.HEALTHY else FallbackDecision.DEGRADED,
                reason="selected best available endpoint",
            )

        if ordered_states:
            return FallbackDecisionResult(
                chain=chain_config.chain.name,
                endpoint=ordered_states[0].endpoint,
                decision=FallbackDecision.FALLBACK,
                reason="all usable endpoints are temporarily unavailable",
            )

        return FallbackDecisionResult(
            chain=chain_config.chain.name,
            endpoint=None,
            decision=FallbackDecision.NONE_AVAILABLE,
            reason="no rpc endpoints configured",
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a serializable view of endpoint health."""
        output: dict[str, dict[str, Any]] = {}
        for (chain_name, url), state in self._states.items():
            output.setdefault(chain_name.value, {})[url] = {
                "url": state.endpoint.url,
                "enabled": state.endpoint.enabled,
                "priority": state.endpoint.priority,
                "health_status": state.effective_health().value,
                "consecutive_failures": state.consecutive_failures,
                "total_failures": state.total_failures,
                "total_successes": state.total_successes,
                "circuit_open_until": state.circuit_open_until,
            }
        return output

    def reset_chain(self, chain: ChainName | str) -> None:
        chain_name = chain if isinstance(chain, ChainName) else ChainName(str(chain).lower())
        for (state_chain, _url), state in self._states.items():
            if state_chain == chain_name:
                state.consecutive_failures = 0
                state.total_failures = 0
                state.total_successes = 0
                state.last_failure_at = None
                state.last_success_at = None
                state.circuit_open_until = None


# ==============================================================================
# FACTORY
# ==============================================================================

def build_fallback_manager(
    registry: RpcRegistry | None = None,
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
) -> RpcFallbackManager:
    """Build a default fallback manager from a registry."""
    from .rpc_config import build_default_rpc_registry

    rpc_registry = registry or build_default_rpc_registry()
    return RpcFallbackManager(
        rpc_registry,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )


__all__ = [
    "FallbackDecision",
    "EndpointState",
    "FallbackDecisionResult",
    "RpcFallbackManager",
    "build_fallback_manager",
]
