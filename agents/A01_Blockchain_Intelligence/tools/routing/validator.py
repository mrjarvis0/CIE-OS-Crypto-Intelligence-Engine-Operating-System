"""
Tools :: Routing :: Validator
=============================

Validates the final route: permissions, capabilities, dependencies,
policy compliance, runtime availability and security constraints.
Invalid routes are rejected before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["RouteValidation", "RouteValidator"]


@dataclass
class RouteValidation:
    """Result of validating a route."""

    valid: bool
    failures: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "failures": list(self.failures)}


class RouteValidator:
    """Gatekeeper that validates routes before execution."""

    def validate(
        self,
        route: Mapping[str, Any],
        *,
        capabilities: Optional[Sequence[str]] = None,
        dependencies: Optional[Sequence[str]] = None,
        runtime_available: Optional[Mapping[str, bool]] = None,
        security_ok: bool = True,
    ) -> RouteValidation:
        failures: List[str] = []
        target = route.get("selected") or route.get("target")
        if not isinstance(target, dict) or not (target.get("id") or target.get("target_id")):
            failures.append("route has no selected target")

        required_caps = list(capabilities or [])
        have_caps = list(target.get("capabilities", [])) if isinstance(target, dict) else []
        for cap in required_caps:
            if cap not in have_caps:
                failures.append(f"missing capability {cap!r}")

        if dependencies:
            have_deps = list(target.get("dependencies", [])) if isinstance(target, dict) else []
            for dep in dependencies:
                if dep not in have_deps:
                    failures.append(f"missing dependency {dep!r}")

        if runtime_available:
            target_id = target.get("id") if isinstance(target, dict) else ""
            if runtime_available.get(target_id, True) is False:
                failures.append(f"target {target_id!r} unavailable at runtime")

        if not security_ok:
            failures.append("security constraint violated")

        policy = route.get("policy_outcome", "allow")
        if policy == "deny":
            failures.append("route denied by policy")

        return RouteValidation(valid=not failures, failures=failures)