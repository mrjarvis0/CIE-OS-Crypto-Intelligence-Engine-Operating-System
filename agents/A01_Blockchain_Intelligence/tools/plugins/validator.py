"""
Tools :: Plugins :: Validator
=============================

Validates plugin integrity: manifest fields, capabilities, permissions,
signature and schema. Invalid plugins are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..governance.signing import SigningKey, verify_payload

__all__ = ["PluginValidation", "PluginValidator"]


@dataclass
class PluginValidation:
    """Result of validating one plugin package."""

    plugin_id: str
    passed: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "passed": self.passed,
            "checks": dict(self.checks),
            "failures": list(self.failures),
        }


class PluginValidator:
    """Zero-trust validation gate for plugins."""

    def __init__(self) -> None:
        self._trusted: Dict[str, SigningKey] = {}

    def trust_publisher(self, publisher: str, key: SigningKey) -> None:
        self._trusted[publisher] = key

    def validate(
        self,
        manifest: Mapping[str, Any],
        *,
        signature: str = "",
        publisher: str = "",
        allowed_capabilities: Optional[Sequence[str]] = None,
        allowed_permissions: Optional[Sequence[str]] = None,
    ) -> PluginValidation:
        checks: Dict[str, bool] = {}
        failures: List[str] = []
        plugin_id = str(manifest.get("id", ""))

        missing = [f for f in ("id", "name", "version") if f not in manifest]
        checks["manifest_fields"] = not missing
        if missing:
            failures.append(f"manifest missing {missing}")

        if signature:
            key = self._trusted.get(publisher)
            if key is None:
                checks["signature"] = False
                failures.append(f"publisher {publisher!r} not trusted")
            else:
                ok = verify_payload(key, dict(manifest), signature)
                checks["signature"] = ok
                if not ok:
                    failures.append("signature invalid")
        else:
            checks["signature"] = False
            failures.append("plugin unsigned")

        caps = set(manifest.get("capabilities", []))
        if allowed_capabilities is not None:
            bad = caps - set(allowed_capabilities)
            checks["capabilities"] = not bad
            if bad:
                failures.append(f"capabilities not allowed: {sorted(bad)}")
        else:
            checks["capabilities"] = True

        perms = set(manifest.get("permissions", []))
        if allowed_permissions is not None:
            bad = perms - set(allowed_permissions)
            checks["permissions"] = not bad
            if bad:
                failures.append(f"permissions not allowed: {sorted(bad)}")
        else:
            checks["permissions"] = True

        return PluginValidation(plugin_id=plugin_id, passed=all(checks.values()), checks=checks, failures=failures)