"""
Tools :: Routing :: Policy
==========================

Applies routing policies: internal tools first, local model preferred,
premium models only for critical tasks, blockchain writes require
approval, privacy-sensitive tasks stay local.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["RoutingPolicyRule", "RoutingPolicyEngine"]

_POLICY_OUTCOMES = ["allow", "deny", "prefer", "skip"]


@dataclass
class RoutingPolicyRule:
    """One routing policy rule: condition decides the action."""

    name: str
    action: str
    condition: Optional[Callable[[Mapping[str, Any]], bool]] = None

    def applies(self, request: Mapping[str, Any]) -> bool:
        if self.condition is None:
            return True
        try:
            return bool(self.condition(request))
        except Exception:  # noqa: BLE001 - failed conditions never crash routing
            return False

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "action": self.action}


class RoutingPolicyEngine:
    """Ordered policy enforcement for routing decisions."""

    def __init__(self) -> None:
        self._rules: List[RoutingPolicyRule] = []

    def add(self, rule: RoutingPolicyRule) -> None:
        if rule.action not in _POLICY_OUTCOMES:
            raise ValueError(f"invalid policy action {rule.action!r}")
        self._rules.append(rule)

    def add_rule(self, name: str, action: str, condition: Optional[Callable[[Mapping[str, Any]], bool]] = None) -> None:
        self.add(RoutingPolicyRule(name=name, action=action, condition=condition))

    def evaluate(self, request: Mapping[str, Any]) -> List[RoutingPolicyRule]:
        """Return every rule that applies to the request, in order."""
        return [rule for rule in self._rules if rule.applies(request)]

    def permitted(self, request: Mapping[str, Any]) -> bool:
        """True when no applicable rule denies the request."""
        return not any(rule.action == "deny" for rule in self.evaluate(request))

    def preferences(self, request: Mapping[str, Any]) -> List[str]:
        """Names of applicable 'prefer' rules (used to boost ordering)."""
        return [rule.name for rule in self.evaluate(request) if rule.action == "prefer"]

    def as_dict(self) -> Dict[str, Any]:
        return {"rules": [rule.as_dict() for rule in self._rules]}


def internal_tools_first_rule() -> RoutingPolicyRule:
    return RoutingPolicyRule(
        name="internal_tools_first",
        action="prefer",
        condition=lambda req: req.get("target_kind") in ("tool", "adapter") and req.get("is_internal", False) is True,
    )


def local_model_preferred_rule() -> RoutingPolicyRule:
    return RoutingPolicyRule(
        name="local_model_preferred",
        action="prefer",
        condition=lambda req: req.get("target_kind") == "model" and req.get("is_local", False) is True,
    )


def premium_model_critical_only_rule() -> RoutingPolicyRule:
    return RoutingPolicyRule(
        name="premium_model_critical_only",
        action="deny",
        condition=lambda req: req.get("target_kind") == "model" and req.get("is_premium", False) is True and req.get("critical", False) is not True,
    )


def blockchain_write_requires_approval_rule() -> RoutingPolicyRule:
    return RoutingPolicyRule(
        name="blockchain_write_requires_approval",
        action="deny",
        condition=lambda req: req.get("target_kind") in ("adapter", "rpc", "tool") and req.get("write_operation", False) is True and req.get("approved", False) is not True,
    )


def privacy_stays_local_rule() -> RoutingPolicyRule:
    return RoutingPolicyRule(
        name="privacy_sensitive_stays_local",
        action="deny",
        condition=lambda req: req.get("privacy_sensitive", False) is True and req.get("is_local", False) is not True,
    )