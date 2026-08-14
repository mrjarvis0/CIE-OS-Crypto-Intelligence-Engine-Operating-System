"""
Tools :: Security :: Authorization
==================================

Right-or-reject gate between execution and tool invocation.

Authorization answers: for this authenticated principal, may they perform this
permission against this target (tool)? It composes a lightweight rule table
with a permission map and role grants, and always makes an explicit decision --
deny is the default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .permissions import PermissionChecker, PermissionError, Role

__all__ = [
    "AuthorizationError",
    "Rule",
    "Authorizer",
    "compile_rules",
    "requirement_rule",
]


class AuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks authorization."""

    code = "AUTHORIZATION_DENIED"


@dataclass(frozen=True)
class Rule:
    """A single authorization rule."""

    permission: str = "*"
    targets: Tuple[str, ...] = ()
    allow: bool = True

    def matches(self, permission: str, tool: str) -> bool:
        if self.permission != "*" and self.permission != permission:
            return False
        if self.targets and tool not in self.targets and "*" not in self.targets:
            return False
        return True


def requirement_rule(permission: str, *, targets: Sequence[str] = ()) -> Rule:
    """Shortcut for an allow-rule covering ``permission``."""
    return Rule(permission=permission, targets=tuple(targets), allow=True)


def compile_rules(rules: Iterable[Mapping[str, Any]]) -> Tuple[Rule, ...]:
    """Parse raw rule dicts into :class:`Rule` instances."""
    compiled = []
    for raw in rules:
        target_list = raw.get("targets", ())
        targets = tuple(target_list) if isinstance(target_list, (list, tuple)) else ()
        compiled.append(
            Rule(
                permission=str(raw.get("permission", "*")),
                targets=targets,
                allow=bool(raw.get("allow", True)),
            )
        )
    return tuple(compiled)


class Authorizer:
    """Default-deny gate between a principal and a tool permission.

    Evaluation order
    ----------------
    1. Explicit :class:`Rule` list (first matching rule decides).
    2. Whenever a matching rule is found it wins (allow or deny).
    3. The permission checker / roles are consulted.
    4. Otherwise access is denied.
    """

    def __init__(
        self,
        *,
        permissions: Optional[PermissionChecker] = None,
        rules: Iterable[Rule] = (),
    ) -> None:
        self.permissions = permissions or PermissionChecker()
        self.rules: Tuple[Rule, ...] = tuple(rules)

    def add_rule(self, rule: Rule) -> None:
        self.rules = self.rules + (rule,)

    # -- evaluation -------------------------------------------------------- #

    def evaluate(self, *, principal: str, permission: str, tool: str = "") -> Mapping[str, Any]:
        for rule in self.rules:
            if rule.matches(permission, tool):
                return {
                    "allowed": rule.allow,
                    "permission": permission,
                    "tool": tool,
                    "source": "rule",
                }
        allowed = self.permissions.map.allows(principal, permission)
        return {
            "allowed": allowed,
            "permission": permission,
            "tool": tool,
            "source": "permission",
        }

    def authorize(self, *, principal: str, permission: str, tool: str = "") -> None:
        decision = self.evaluate(principal=principal, permission=permission, tool=tool)
        if not decision["allowed"]:
            raise AuthorizationError(permission, principal=principal)

    def may(self, *, principal: str, permission: str, tool: str = "") -> bool:
        try:
            self.authorize(principal=principal, permission=permission, tool=tool)
            return True
        except AuthorizationError:
            return False