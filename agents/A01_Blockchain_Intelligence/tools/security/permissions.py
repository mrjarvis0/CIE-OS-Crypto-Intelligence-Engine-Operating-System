"""
Tools :: Security :: Permissions
================================

Central authorization vocabulary: permission strings, roles, grants and a
:class:`PermissionChecker` used by the core executor and governance to decide
whether an actor may invoke a tool.

The model is deliberately simple and composable:

* A permission is a dotted string (``security.read``, ``blockchain.write``).
* A role groups several permission grants for a principal.
* Wildcards (``security.*``) are supported in grants.
* ``PermissionError`` is raised (with a structured code) on denial, so the
  executor can translate it into a canonical failure response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set

__all__ = [
    "PermissionError",
    "Permission",
    "Role",
    "PermissionMap",
    "PermissionChecker",
    "allow_all",
    "deny_all",
]


class PermissionError(PermissionError):
    """Raised when a principal lacks the permission required by a tool."""

    code = "PERMISSION_DENIED"

    def __init__(self, permission: str, *, principal: str = "") -> None:
        self.permission = permission
        self.principal = principal
        message = (
            f"principal {principal!r} lacks permission {permission!r}"
            if principal
            else f"permission denied: {permission!r}"
        )
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Permission:
    """Descriptor for a single permission string."""

    name: str
    description: str = ""

    @property
    def namespace(self) -> str:
        return self.name.split(".", 1)[0] if "." in self.name else self.name

    @property
    def action(self) -> str:
        return self.name.split(".", 1)[1] if "." in self.name else "*"

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Role:
    """Named bundle of permissions grantable to a principal."""

    name: str
    permissions: Sequence[str] = field(default_factory=list)
    description: str = ""

    def grants(self, permission: str) -> bool:
        return grant_match(permission, self.permissions)


def grant_match(permission: str, grants: Iterable[str]) -> bool:
    """
    True when ``permission`` matches any grant (supporting ``*`` wildcards).

    A grant of ``security.*`` matches ``security.read`` but not
    ``blockchain.read``; ``*`` matches everything.
    """
    for grant in grants:
        if grant == "*":
            return True
        if grant.endswith((".*", ":*")):
            if permission.startswith(grant[:-1]):
                return True
        if grant == permission:
            return True
    return False


class PermissionMap:
    """
    Immutable-ish mapping from principal -> set of granted permissions.

    Principals may be user ids, service accounts or role names. The map is
    optimized for cheap ``allows(principal, permission)`` checks.
    """

    def __init__(self, grants: Optional[Mapping[str, Iterable[str]]] = None) -> None:
        self._store: Dict[str, Set[str]] = {
            p: set(g) for p, g in (grants or {}).items()
        }

    def grant(self, principal: str, permission: str) -> None:
        self._store.setdefault(principal, set()).add(permission)

    def revoke(self, principal: str, permission: str) -> None:
        bucket = self._store.get(principal)
        if bucket:
            bucket.discard(permission)

    def has_any(self, principal: str) -> bool:
        return bool(self._store.get(principal))

    def allows(self, principal: str, permission: str) -> bool:
        grants = self._store.get(principal, ())
        return grant_match(permission, grants)

    def principal_permissions(self, principal: str) -> Sequence[str]:
        return sorted(self._store.get(principal, ()))

    def as_dict(self) -> Dict[str, List[str]]:
        return {p: sorted(g) for p, g in self._store.items()}


class PermissionChecker:
    """
    Convenience façade over a :class:`PermissionMap` that raises a structured
    :class:`PermissionError` when a check fails and records decisions for the
    monitoring/governance layers.
    """

    def __init__(self, *, grants: Optional[Mapping[str, Iterable[str]]] = None) -> None:
        self.map = PermissionMap(grants)
        self.decisions: List[Mapping[str, object]] = []

    def check(self, principal: str, permission: str, *, tool: str = "") -> bool:
        allowed = self.map.allows(principal, permission)
        self.decisions.append(
            {
                "principal": principal,
                "permission": permission,
                "tool": tool,
                "allowed": allowed,
            }
        )
        if not allowed:
            raise PermissionError(permission, principal=principal)
        return True

    def may(self, principal: str, permission: str) -> bool:
        try:
            self.check(principal, permission)
            return True
        except PermissionError:
            return False


def allow_all() -> PermissionChecker:
    """Checker that grants ``*`` to every principal (explicitly permissive)."""
    return PermissionChecker(grants={"*": ["*"]})


def deny_all() -> PermissionChecker:
    """Checker with no grants: every call raises PermissionError."""
    return PermissionChecker(grants={})