"""
Tools :: Security :: Validator
==============================

Input validation and sanitization guardions applied before tool execution.

Whereas the schemas layer defines *what* data should look like, this module
enforces practical safety rules: type coercion, length bounds, allow-lists,
dangerous-pattern rejection and secret masking. Every helper returns a
:class:`ValidationReport` with ``ok`` + ``errors`` so the executor can form a
canonical failure response without throwing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

__all__ = [
    "ValidationReport",
    "ValidationFailure",
    "ValidatorError",
    "validate_length",
    "validate_ranges",
    "validate_allowed",
    "reject_dangerous",
    "guard",
    "ValidatorRule",
    "validate_signature",
    "required_field",
    "length",
    "allowed",
]


@dataclass
class ValidationFailure:
    """One recorded validation failure (field + message)."""

    field: str
    message: str

    def as_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "message": self.message}


@dataclass
class ValidationReport:
    """Result of running guards over an input."""

    ok: bool = True
    errors: Sequence[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors = list(self.errors) + [message]

    def merged(self) -> str:
        return "; ".join(self.errors)


class ValidatorError(ValueError):
    """Raised by :func:`guard` when validation fails."""


ValidatorRule = Callable[[Any], Optional[str]]


def validate_length(value: Any, *, minimum: int = 0, maximum: int = 2**20) -> Optional[str]:
    """Direct length check; returns an error message or ``None``."""
    if value is None:
        return None
    try:
        size = len(value)
    except TypeError:
        return f"has no length: {type(value).__name__}"
    if size < minimum:
        return f"shorter than minimum {minimum}"
    if size > maximum:
        return f"longer than maximum {maximum}"
    return None


def validate_ranges(value: Any, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> Optional[str]:
    """Numeric range check; returns an error message or ``None``."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"not a number: {value!r}"
    if minimum is not None and number < minimum:
        return f"below minimum {minimum}"
    if maximum is not None and number > maximum:
        return f"above maximum {maximum}"
    return None


def validate_allowed(value: Any, values: Sequence[Any]) -> Optional[str]:
    """Allow-list check; returns an error message or ``None``."""
    if value is None:
        return None
    if value not in values:
        return f"must be one of {values!r}"
    return None


def length(minimum: int = 0, maximum: int = 2**20) -> ValidatorRule:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            size = len(value)
        except TypeError:
            return f"has no length: {type(value).__name__}"
        if size < minimum:
            return f"shorter than minimum {minimum}"
        if size > maximum:
            return f"longer than maximum {maximum}"
        return None

    return _check


def allowed(values: Sequence[Any]) -> ValidatorRule:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        if value not in values:
            return f"must be one of {values!r}"
        return None

    return _check


#: A denylist, and denylists are bypassable by construction. This one is a
#: tripwire for obviously hostile input, **not** the defence against SQL
#: injection -- that is parameterised queries, which is what
#: database/repositories.py uses throughout. Nothing here should ever be
#: read as permission to interpolate a value into a query.
_DANGEROUS_PATTERNS = (
    re.compile(r"</?\s*(script|iframe|object|embed)[^>]*>", re.IGNORECASE),
    re.compile(r"\b(?:ALTER|DROP|exec\s*\()\b", re.IGNORECASE),
    re.compile(r"\bUNION\s+(?:ALL\s+)?SELECT\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
)


def reject_dangerous(value: Any) -> Optional[str]:
    """Reject strings containing active-content or SQL injection markers."""
    if not isinstance(value, str):
        return None
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(value):
            return "contains dangerous content"
    return None


def validate_signature(
    data: Mapping[str, Any],
    *,
    required: Sequence[str] = (),
    allowed_not: Sequence[str] = (),
    rules: Optional[Mapping[str, Sequence[ValidatorRule]]] = None,
) -> ValidationReport:
    report = ValidationReport()
    for field_name in required:
        if field_name not in data:
            report.fail(f"missing required field: {field_name}")
    for field_name in allowed_not:
        if field_name in data:
            report.fail(f"unauthorized field: {field_name}")
    for field_name, field_rules in (rules or {}).items():
        if field_name not in data:
            continue
        for rule in field_rules:
            message = rule(data[field_name])
            if message:
                report.fail(f"{field_name}: {message}")
    return report


def guard(data: Mapping[str, Any], *, rules: Sequence[ValidatorRule] = ()) -> None:
    """
    Apply every rule to every field of ``data``; raise on any failure.

    Each rule used to be handed the whole mapping. Rules are written against
    field *values* -- :func:`reject_dangerous` opens with
    ``isinstance(value, str)`` -- so every rule saw a ``dict``, returned
    ``None``, and the gate passed everything. A payload carrying a script tag
    and a DROP statement went through a "hard security gateway" without one
    rule ever looking at it.

    Rules that genuinely need the whole mapping belong in
    :func:`validate_signature`, which is shaped for that.
    """
    report = ValidationReport()
    for rule in rules:
        for field_name, value in data.items():
            message = rule(value)
            if message:
                report.fail(f"{field_name}: {message}")
    if not report.ok:
        raise ValidatorError(report.merged())


def required_field(value: Any, *, name: str) -> Optional[str]:
    if value is None or (isinstance(value, (str, list, dict, tuple)) and not value):
        return f"{name} must be present"
    return None