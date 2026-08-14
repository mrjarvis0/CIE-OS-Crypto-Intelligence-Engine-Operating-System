"""
Tools :: Routing :: Strategy
============================

Defines routing strategies: how execution targets are chosen and
ordered for a given request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .intent import Intent

__all__ = [
    "RoutingStrategy",
    "DirectStrategy",
    "CapabilityStrategy",
    "PriorityStrategy",
    "RuleBasedStrategy",
    "DynamicStrategy",
    "HybridStrategy",
    "MultiAgentStrategy",
    "STRATEGY_REGISTRY",
]


@dataclass
class RoutingStrategy:
    """Base routing strategy: picks candidates for an intent."""

    name: str = "base"

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return list(candidates)


class DirectStrategy(RoutingStrategy):
    """Routes straight to the best single match."""

    def __init__(self) -> None:
        super().__init__(name="direct")

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda c: float(c.get("score", 0.0)), reverse=True)
        return [ordered[0]]


class CapabilityStrategy(RoutingStrategy):
    """Routes by capability match: only candidates whose capabilities
    cover the requested capability set."""

    def __init__(self, required: Sequence[str] = ()) -> None:
        super().__init__(name="capability")
        self.required = list(required)

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        needed = set(self.required or intent.targets)
        matched = []
        for candidate in candidates:
            caps = set(candidate.get("capabilities", []))
            if needed and not caps.intersection(needed):
                continue
            matched.append(candidate)
        return sorted(matched, key=lambda c: float(c.get("score", 0.0)), reverse=True)


class PriorityStrategy(RoutingStrategy):
    """Routes by declared priority: highest priority first."""

    def __init__(self) -> None:
        super().__init__(name="priority")

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(
            candidates,
            key=lambda c: (
                -int(c.get("priority", 0)),
                -float(c.get("score", 0.0)),
            ),
        )


class RuleBasedStrategy(RoutingStrategy):
    """Routes with explicit if/then rules over candidate attributes."""

    def __init__(self, rules: Optional[Sequence[Callable[[Mapping[str, Any]], bool]]] = None) -> None:
        super().__init__(name="rule_based")
        self.rules = list(rules or [])

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        if not self.rules:
            return list(candidates)
        passed = [c for c in candidates if all(rule(c) for rule in self.rules)]
        return passed if passed else list(candidates)


class DynamicStrategy(RoutingStrategy):
    """Adapts ordering based on runtime signals (latency, load)."""

    def __init__(self, signal_key: str = "latency_ms") -> None:
        super().__init__(name="dynamic")
        self.signal_key = signal_key

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(candidates, key=lambda c: float(c.get(self.signal_key, 1e9)))


class HybridStrategy(RoutingStrategy):
    """Combines strategies: capability first, then direct scoring."""

    def __init__(self, required: Sequence[str] = ()) -> None:
        super().__init__(name="hybrid")
        self.capability = CapabilityStrategy(required)
        self.direct = DirectStrategy()

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        narrowed = self.capability.choose(intent, candidates)
        return self.direct.choose(intent, narrowed)


class MultiAgentStrategy(RoutingStrategy):
    """Routes a request across multiple agents; supports parallel fan-out."""

    def __init__(self, max_agents: int = 3) -> None:
        super().__init__(name="multi_agent")
        self.max_agents = max_agents

    def choose(self, intent: Intent, candidates: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        agents = [c for c in candidates if c.get("kind") == "agent"]
        ranked = sorted(agents, key=lambda c: float(c.get("score", 0.0)), reverse=True)
        return ranked[: self.max_agents] or list(candidates)


STRATEGY_REGISTRY: Dict[str, type] = {
    "direct": DirectStrategy,
    "capability": CapabilityStrategy,
    "priority": PriorityStrategy,
    "rule_based": RuleBasedStrategy,
    "dynamic": DynamicStrategy,
    "hybrid": HybridStrategy,
    "multi_agent": MultiAgentStrategy,
}