"""
Tools :: Governance :: Verification
===================================

Final governance verification: policy revalidation, runtime verification,
evidence validation, output validation and governance completeness.

Acts as the final checkpoint before execution results are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["VerificationResult", "Verifier"]


@dataclass
class VerificationResult:
    """Outcome of the final governance gate."""

    passed: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": dict(self.checks),
            "failures": list(self.failures),
        }


class Verifier:
    """Runs named boolean checks; all must pass."""

    def __init__(self) -> None:
        self._checks: Dict[str, callable] = {}

    def register(self, name: str, check: callable) -> None:
        self._checks[name] = check

    def verify(self, context: Mapping[str, Any]) -> VerificationResult:
        checks: Dict[str, bool] = {}
        failures: List[str] = []
        for name, check in self._checks.items():
            try:
                passed = bool(check(context))
            except Exception as exc:  # noqa: BLE001 - never leak into governance
                passed = False
                failures.append(f"{name}: {exc}")
            checks[name] = passed
            if not passed:
                failures.append(name)
        return VerificationResult(passed=all(checks.values()), checks=checks, failures=failures)

    def check_names(self) -> List[str]:
        return list(self._checks)