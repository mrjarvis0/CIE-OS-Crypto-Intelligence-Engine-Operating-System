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

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from .permissions import PermissionChecker, PermissionError

__all__ = [
    "AuthorizationError",
    "Rule",
    "Authorizer",
    "compile_rules",
    "requirement_rule",
    "deny_rule",
]


class AuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks authorization."""

    code = "AUTHORIZATION_DENIED"


@dataclass(frozen=True)
class Rule:
    """
    One authorization rule.

    ``permission`` has **no default**, and that is the point. The previous
    signature defaulted every field to a match-anything value, so ``Rule()``
    -- and any rule dict that lost its ``permission`` key in a config edit --
    evaluated to "allow every permission, on every tool, for every principal".
    A gate whose most likely typo is total bypass is not a gate. Naming the
    permission is now the caller's job, and ``*`` remains expressible for the
    cases that genuinely mean it.

    ``principals`` scopes a rule to named identities. Empty means the rule
    applies to any principal, which is why an allow-rule should normally name
    them and a deny-rule normally should not.
    """

    permission: str
    targets: Tuple[str, ...] = ()
    principals: Tuple[str, ...] = ()
    allow: bool = True

    def __post_init__(self) -> None:
        if not str(self.permission).strip():
            raise ValueError("a rule must name the permission it governs")

    def matches(self, permission: str, tool: str, principal: str = "") -> bool:
        if self.permission != "*" and self.permission != permission:
            return False
        if self.targets and tool not in self.targets and "*" not in self.targets:
            return False
        if (
            self.principals
            and principal not in self.principals
            and "*" not in self.principals
        ):
            return False
        return True


def requirement_rule(
    permission: str,
    *,
    targets: Sequence[str] = (),
    principals: Sequence[str] = (),
) -> Rule:
    """Shortcut for an allow-rule covering ``permission``."""
    return Rule(
        permission=permission,
        targets=tuple(targets),
        principals=tuple(principals),
        allow=True,
    )


def deny_rule(permission: str, *, targets: Sequence[str] = ()) -> Rule:
    """Shortcut for a deny-rule. Deny wins over any allow, see :class:`Authorizer`."""
    return Rule(permission=permission, targets=tuple(targets), allow=False)


def compile_rules(rules: Iterable[Mapping[str, Any]]) -> Tuple[Rule, ...]:
    """
    Parse raw rule dicts into :class:`Rule` instances.

    Raises :class:`ValueError` on an entry that does not name a permission.
    Rules arrive from configuration, and configuration is edited by hand; a
    malformed entry must stop the load rather than become a permissive rule
    that nothing reports.
    """
    compiled = []
    for index, raw in enumerate(rules):
        if "permission" not in raw:
            raise ValueError(
                f"rule[{index}] does not name a permission; "
                "an unnamed rule would match everything"
            )

        target_list = raw.get("targets", ())
        targets = tuple(target_list) if isinstance(target_list, (list, tuple)) else ()

        principal_list = raw.get("principals", ())
        principals = (
            tuple(principal_list)
            if isinstance(principal_list, (list, tuple))
            else ()
        )

        compiled.append(
            Rule(
                permission=str(raw["permission"]),
                targets=targets,
                principals=principals,
                allow=bool(raw.get("allow", True)),
            )
        )
    return tuple(compiled)


class Authorizer:
    """Default-deny gate between a principal and a tool permission.

    Evaluation order
    ----------------
    1. Any matching **deny** rule -- an explicit deny wins outright.
    2. Any matching **allow** rule.
    3. The permission map for the principal.
    4. Otherwise denied.

    Deny is checked across the whole rule set before allow, rather than
    letting the first match win. Under first-match-wins, appending an allow
    rule silently overrides a deny placed earlier, and the resulting grant is
    invisible in a diff of the appended line.
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

    def evaluate(
        self, *, principal: str, permission: str, tool: str = ""
    ) -> Mapping[str, Any]:
        matching = [
            rule
            for rule in self.rules
            if rule.matches(permission, tool, principal)
        ]

        for rule in matching:
            if not rule.allow:
                return {
                    "allowed": False,
                    "permission": permission,
                    "tool": tool,
                    "principal": principal,
                    "source": "deny-rule",
                }

        if matching:
            return {
                "allowed": True,
                "permission": permission,
                "tool": tool,
                "principal": principal,
                "source": "allow-rule",
            }

        allowed = self.permissions.map.allows(principal, permission)
        return {
            "allowed": allowed,
            "permission": permission,
            "tool": tool,
            "principal": principal,
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
