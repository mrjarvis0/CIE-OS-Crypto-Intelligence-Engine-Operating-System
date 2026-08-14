"""
Tools :: Core :: Permissions
============================

Central authorization facade every tool executor consults.

Thin, protocol-agnostic layer over the security package. The executor
checks principal permissions before dispatch and raises a domain
:class:`PermissionDeniedError` when a check fails. Tool authors never see
this; executors and gates do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence, Set

from ..security.permissions import PermissionMap, grant_match
from .exceptions import PermissionDeniedError

__all__ = [
    "ActionSet",
    "PermissionMap",
    "ToolPermissionMap",
    "PermissionDeniedError",
]

# Canonical actions the executor recognizes on tools.
TOOL_ACTIONS = ("read", "execute", "configure", "install", "uninstall", "update")


@dataclass(frozen=True)
class ActionSet:
    """Set of actions a principal holds over a tool scope."""

    scope: str = "*"
    actions: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", set(self.actions))

    def allows(self, action: str) -> bool:
        return action in self.actions

    def as_dict(self) -> Mapping[str, object]:
        return {"scope": self.scope, "actions": sorted(self.actions)}


class ToolPermissionMap:
    """
    Permission map specialized for tool actions.

    Grants are stored as ``<action>:<scope>`` strings and matched with the
    security layer's wildcard semantics, so ``execute:*`` authorizes
    ``execute:chain-intel``.
    """

    def __init__(self, grants: Optional[Mapping[str, Iterable[str]]] = None) -> None:
        self._map = PermissionMap(grants)

    def grant(self, principal: str, action: str, scope: str = "*") -> None:
        self._map.grant(principal, f"{action}:{scope if scope not in (None, '*') else '*'}")

    def allows(self, principal: str, action: str, scope: str = "*") -> bool:
        permission = f"{action}:{scope}" if scope not in (None, "*") else action
        return self._map.allows(principal, permission)

    def check(self, principal: str, action: str, scope: str = "*") -> None:
        """Raise :class:`PermissionDeniedError` when the action is not granted."""
        if not self.allows(principal, action, scope):
            raise PermissionDeniedError(
                f"principal {principal!r} lacks permission {action}:{scope}"
            )


def canonical_action(action: str) -> str:
    if action not in TOOL_ACTIONS:
        raise PermissionDeniedError(f"unknown tool action {action!r}")
    return action