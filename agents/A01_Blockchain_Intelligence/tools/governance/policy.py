"""
Tools :: Governance :: Policy
=============================

Central policy engine: runtime evaluation of allowlists, denylists,
capability restrictions and conditional rules.

A :class:`PolicyRule` evaluates to ``allow`` / ``deny`` / ``skip``; the
engine folds all rules in order (first decisive wins unless ``strict``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["PolicyDecision", "PolicyRule", "PolicyEngine"]

_ALLOW = "allow"
_DENY = "deny"
_SKIP = "skip"

Condition = Callable[[Mapping[str, Any]], bool]


def _default_condition(context: Mapping[str, Any]) -> bool:
    return True


@dataclass
class PolicyDecision:
    """Outcome of a policy evaluation."""

    verdict: str = "deny"
    rule: str = ""
    reasons: List[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict == _ALLOW

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "rule": self.rule,
            "reasons": list(self.reasons),
            "allowed": self.allowed,
        }


@dataclass
class PolicyRule:
    """One named governance rule."""

    name: str
    action: str = _DENY
    tool_ids: Optional[Sequence[str]] = None
    namespaces: Optional[Sequence[str]] = None
    capabilities: Optional[Sequence[str]] = None
    condition: Optional[Condition] = None
    priority: int = 0

    def evaluate(self, context: Mapping[str, Any]) -> str:
        """Return ``allow`` / ``deny`` / ``skip`` for this context."""
        predicate = self.condition or _default_condition
        if not predicate(context):
            return _SKIP
        if self.tool_ids is not None and context.get("tool_id") in self.tool_ids:
            return self.action
        if self.namespaces is not None and context.get("namespace") in self.namespaces:
            return self.action
        if self.capabilities is not None:
            if set(self.capabilities) & set(context.get("capabilities", [])):
                return self.action
        if self.tool_ids is None and self.namespaces is None and self.capabilities is None:
            return self.action
        return _SKIP

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "action": self.action,
            "tool_ids": list(self.tool_ids) if self.tool_ids is not None else None,
            "namespaces": list(self.namespaces) if self.namespaces is not None else None,
            "capabilities": list(self.capabilities) if self.capabilities is not None else None,
            "priority": self.priority,
        }


class PolicyEngine:
    """Rule folding engine: first decisive rule wins unless ``strict`` (deny by default)."""

    def __init__(self, rules: Optional[Sequence[PolicyRule]] = None, *, strict: bool = True) -> None:
        self.rules: List[PolicyRule] = list(rules or [])
        self.strict = strict

    def add(self, rule: PolicyRule) -> PolicyRule:
        self.rules.append(rule)
        return rule

    def evaluate(self, context: Mapping[str, Any]) -> PolicyDecision:
        """Evaluate a context dict: ``tool_id``, ``namespace``, ``capabilities``..."""
        ordered = sorted(self.rules, key=lambda r: r.priority, reverse=True)
        for rule in ordered:
            verdict = rule.evaluate(context)
            if verdict == _SKIP:
                continue
            return PolicyDecision(verdict=verdict, rule=rule.name, reasons=[f"matched rule {rule.name}"])
        verdict = _DENY if self.strict else _ALLOW
        return PolicyDecision(verdict=verdict, rule="__default__", reasons=["no rule matched"])

    def allow(self, context: Mapping[str, Any]) -> bool:
        return self.evaluate(context).allowed

    def as_dict(self) -> Dict[str, Any]:
        return {"strict": self.strict, "rules": [rule.as_dict() for rule in self.rules]}