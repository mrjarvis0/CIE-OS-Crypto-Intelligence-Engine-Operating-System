"""
Tools :: Governance :: Compliance
=================================

Compliance validation: internal policies, regulatory mapping, security
baselines, organization standards and data handling rules.

Framework-agnostic checks support future ISO 27001 / SOC 2 / NIST AI RMF
/ GDPR mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["ComplianceRequirement", "ComplianceCheck", "ComplianceReport", "ComplianceEngine"]


@dataclass
class ComplianceRequirement:
    """One enforceable requirement."""

    code: str
    description: str
    framework: str = "internal"
    severity: str = "high"
    check: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "framework": self.framework,
            "severity": self.severity,
            "check": self.check,
        }


@dataclass
class ComplianceCheck:
    """Outcome of one requirement against a context."""

    requirement: ComplianceRequirement
    passed: bool
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.requirement.code,
            "framework": self.requirement.framework,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class ComplianceReport:
    """Aggregate compliance result."""

    checks: List[ComplianceCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def pass_rate(self) -> float:
        if not self.checks:
            return 1.0
        return sum(1 for check in self.checks if check.passed) / len(self.checks)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "checks": [check.as_dict() for check in self.checks],
        }


class ComplianceEngine:
    """Registry of requirements and evaluation against execution context."""

    def __init__(self) -> None:
        self._requirements: List[ComplianceRequirement] = []

    def add(self, requirement: ComplianceRequirement) -> ComplianceRequirement:
        self._requirements.append(requirement)
        return requirement

    def evaluate(self, context: Mapping[str, Any]) -> ComplianceReport:
        checks = []
        for requirement in self._requirements:
            passed, detail = self._run(requirement, context)
            checks.append(ComplianceCheck(requirement=requirement, passed=passed, detail=detail))
        return ComplianceReport(checks=checks)

    def _run(self, requirement: ComplianceRequirement, context: Mapping[str, Any]) -> tuple[bool, str]:
        check = requirement.check
        if not check:
            return True, "no check configured"
        field = check
        expected = True
        if ":" in check:
            field, expected = check.split(":", 1)
            if expected in ("true", "false"):
                expected = expected == "true"
            elif expected.isdigit():
                expected = int(expected)
        actual = context.get(field)
        if isinstance(expected, bool):
            return bool(actual) is expected, f"{field}={actual}"
        return actual == expected, f"{field}={actual!r}"

    def by_framework(self, framework: str) -> List[ComplianceRequirement]:
        return [req for req in self._requirements if req.framework == framework]

    def requirements(self) -> List[ComplianceRequirement]:
        return list(self._requirements)