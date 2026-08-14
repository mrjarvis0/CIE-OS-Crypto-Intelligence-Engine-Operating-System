"""
Tools :: Utils :: Validation
============================

Lightweight, dependency-free validation primitives shared by the schemas,
security and core layers.

The emphasis is on strictness where it matters (presence, types, ranges,
enumerations, patterns) and on producing *actionable* error messages that
tell the caller exactly which field failed and why.  Every validator returns
a ``(ok, errors)`` tuple or raises :class:`ValidationError` on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Pattern, Sequence, Tuple, Type

__all__ = [
    "ValidationError",
    "ValidationResult",
    "Validator",
    "required",
    "optional",
    "of_type",
    "in_range",
    "in_enum",
    "matches",
    "min_length",
    "max_length",
    "is_truthy",
    "validate",
    "validate_dict",
    "ensure_type",
    "ensure_string",
]


class ValidationError(ValueError):
    """Raised when a value fails validation, carrying field context."""

    def __init__(self, message: str, *, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field

    def __str__(self) -> str:
        return f"{self.field}: {self.message}" if self.field else self.message


@dataclass
class ValidationResult:
    """Outcome of a validation pass: ok + per-field errors."""

    ok: bool = True
    errors: Dict[str, str] = field(default_factory=dict)

    def fail(self, field: str, message: str) -> None:
        self.ok = False
        self.errors[field] = message

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "errors": dict(self.errors)}


Validator = Callable[[Any], Optional[str]]


def required(name: str = "value") -> Validator:
    """Factory: reject ``None`` and empty strings/lists/dicts."""

    def _check(value: Any) -> Optional[str]:
        if value is None:
            return f"{name} is required"
        if isinstance(value, (str, list, tuple, dict, set, bytes)) and len(value) == 0:
            return f"{name} must not be empty"
        return None

    return _check


def optional(name: str = "value") -> Validator:
    """Factory: accept ``None``; run no further checks (identity validator)."""

    def _check(value: Any) -> Optional[str]:
        return None

    return _check


def of_type(
    types: Type[Any] | Tuple[Type[Any], ...], name: str = "value"
) -> Validator:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, types):
            label = getattr(types, "__name__", str(types))
            return f"{name} must be {label}, got {type(value).__name__}"
        return None

    return _check


def in_range(minimum: Optional[float] = None, maximum: Optional[float] = None, name: str = "value") -> Validator:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f"{name} must be numeric"
        if minimum is not None and number < minimum:
            return f"{name} must be >= {minimum}"
        if maximum is not None and number > maximum:
            return f"{name} must be <= {maximum}"
        return None

    return _check


def in_enum(allowed: Sequence[Any], name: str = "value") -> Validator:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        if value not in allowed:
            return f"{name} must be one of {list(allowed)}"
        return None

    return _check


def matches(pattern: Pattern[str], name: str = "value") -> Validator:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not pattern.fullmatch(value):
            return f"{name} does not match required pattern"
        return None

    return _check


def min_length(length: int, name: str = "value") -> Validator:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        if len(value) < length:
            return f"{name} must be at least {length} characters"
        return None

    return _check


def max_length(length: int, name: str = "value") -> Validator:
    def _check(value: Any) -> Optional[str]:
        if value is None:
            return None
        if len(value) > length:
            return f"{name} must be at most {length} characters"
        return None

    return _check


def is_truthy(name: str = "value") -> Validator:
    def _check(value: Any) -> Optional[str]:
        if not value:
            return f"{name} must be truthy"
        return None

    return _check


def validate(
    value: Any,
    validators: Iterable[Validator],
    *,
    raise_on_error: bool = False,
    name: str = "value",
) -> Tuple[bool, List[str]]:
    """Run a sequence of validators; returns (ok, messages)."""
    messages: List[str] = []
    for validator in validators:
        message = validator(value)
        if message is not None:
            messages.append(message)
    if raise_on_error and messages:
        raise ValidationError("; ".join(messages), field=name)
    return (not messages), messages


def validate_dict(
    data: Mapping[str, Any],
    rules: Mapping[str, Iterable[Validator]],
    *,
    allow_extra: bool = True,
    raise_on_error: bool = False,
) -> ValidationResult:
    """Validate a mapping against per-field validator lists."""
    result = ValidationResult()
    for field, validators in rules.items():
        if field not in data:
            result.fail(field, "missing required field")
            continue
        ok, messages = validate(data[field], validators, name=field)
        if not ok:
            result.fail(field, "; ".join(messages))
    if not allow_extra:
        extra = set(data.keys()) - set(rules.keys())
        for field in sorted(extra):
            result.fail(field, "unknown field")
    if raise_on_error and not result.ok:
        first_field, first_msg = next(iter(result.errors.items()))
        raise ValidationError(first_msg, field=first_field)
    return result


def ensure_type(value: Any, types: Type[Any] | Tuple[Type[Any], ...], name: str = "value") -> Any:
    """Coerce-or-raise type guard; returns the value unchanged when valid."""
    if isinstance(value, types):
        return value
    raise ValidationError(
        f"expected {getattr(types, '__name__', str(types))}, got {type(value).__name__}",
        field=name,
    )


def ensure_string(value: Any, name: str = "value") -> str:
    """Return a non-empty string or raise ValidationError."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValidationError("must be a non-empty string", field=name)


def to_number(value: Any, name: str = "value") -> float:
    """Parse a number (int/float/numeric-string) or raise ValidationError."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("must be numeric", field=name) from exc