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

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Mapping, Optional, Sequence, Set

__all__ = [
    "PermissionError",
    "Permission",
    "Role",
    "PermissionMap",
    "PermissionChecker",
    "allow_all",
    "deny_all",
    "grant_match",
]


class PermissionError(Exception):  # noqa: A001 -- public name, kept for callers
    """
    Raised when a principal lacks the permission required by a tool.

    The base is :class:`Exception`, not the builtin ``PermissionError`` this
    name shadows. The builtin is an :class:`OSError` subclass, so while this
    class inherited from it, any ``except OSError:`` around file or socket
    work -- and there is a lot of that in an agent that reads databases and
    dials RPC endpoints -- silently swallowed an authorization denial and
    carried on. A denial must reach the caller as a denial.

    The name is kept because it is the module's exported API.
    """

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
        """
        True when ``principal`` holds a grant matching ``permission``.

        A ``"*"`` principal key applies to everyone. Without it, the
        ``allow_all()`` helper -- documented as granting ``*`` to every
        principal -- stored its grant under the literal key ``"*"`` and then
        looked it up under the caller's own id, so it matched nobody and
        denied everything. A helper whose name and behaviour are opposites is
        worse than no helper.

        Deny-by-default is unchanged: a map without a ``"*"`` key grants
        nothing it was not given.
        """
        if grant_match(permission, self._store.get(principal, ())):
            return True
        if principal != "*" and grant_match(permission, self._store.get("*", ())):
            return True
        return False

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

    #: How many recent decisions are retained. The list used to be unbounded,
    #: and a long-lived agent appends one entry per permission check forever.
    DECISION_HISTORY: int = 1000

    def __init__(
        self,
        *,
        grants: Optional[Mapping[str, Iterable[str]]] = None,
        history: Optional[int] = None,
    ) -> None:
        self.map = PermissionMap(grants)
        self.decisions: Deque[Mapping[str, object]] = deque(
            maxlen=history if history is not None else self.DECISION_HISTORY
        )

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