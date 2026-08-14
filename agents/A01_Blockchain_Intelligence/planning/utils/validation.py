"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.validation

Purpose:
    Reusable input/schema/domain validation for the planning subsystem.

Validation is infrastructure: every planning module shares the same
validation rules to keep behavior consistent and inputs safe.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .constants import (
    MAX_DEPTH,
    MAX_RETRY,
    MAX_TASKS,
    MAX_TASKS_PER_PLAN,
)

# ==============================================================================
# RESULT TYPES
# ==============================================================================


@dataclass(slots=True)
class ValidationResult:
    """
    Result of a validation operation.
    """

    valid: bool = True

    errors: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Record a validation error."""
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        """Record a non-fatal warning."""
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> None:
        """Merge another validation result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.valid = self.valid and other.valid

    @property
    def error_message(self) -> str:
        """Combined error message string."""
        return "; ".join(self.errors)


def ok_result() -> ValidationResult:
    """Return a valid result."""
    return ValidationResult()


class MissingFieldError(ValueError):
    """
    Raised when required fields are absent from a payload.

    Attributes
    ----------
    missing
        Field names that were required but not present.
    """

    def __init__(
        self,
        missing: list[str],
        *,
        name: str = "payload",
    ) -> None:
        self.missing = list(missing)
        self.name = name
        super().__init__(
            f"{name} missing required field(s): {', '.join(self.missing)}"
        )


def require_fields(
    data: dict[str, Any],
    fields: list[str],
    *,
    name: str = "payload",
) -> None:
    """
    Assert that a payload contains every required field.

    Raises
    ------
    MissingFieldError
        When any required field is absent.
    """

    missing = [field for field in fields if field not in data]

    if missing:
        raise MissingFieldError(missing, name=name)


# ==============================================================================
# PRIMITIVE VALIDATORS
# ==============================================================================


def require_non_empty(
    value: Any,
    *,
    name: str = "value",
    result: ValidationResult | None = None,
) -> ValidationResult:
    """Validate that a value is present and non-empty."""

    result = result or ValidationResult()

    if value is None or value == "":
        result.add_error(f"{name} must not be empty")

    if isinstance(value, (list, dict, tuple, set)) and not value:
        result.add_error(f"{name} must not be empty")

    return result


def validate_type(
    value: Any,
    expected_type: type,
    *,
    name: str = "value",
    result: ValidationResult | None = None,
) -> ValidationResult:
    """Validate that a value has the expected type."""

    result = result or ValidationResult()

    if not isinstance(value, expected_type):
        result.add_error(
            f"{name} must be of type {expected_type.__name__}, "
            f"got {type(value).__name__}"
        )

    return result


def validate_length(
    value: str | list | dict,
    *,
    min_length: int | None = None,
    max_length: int | None = None,
    name: str = "value",
    result: ValidationResult | None = None,
) -> ValidationResult:
    """Validate the length of a string or collection."""

    result = result or ValidationResult()
    length = len(value)

    if min_length is not None and length < min_length:
        result.add_error(
            f"{name} length {length} is below minimum {min_length}"
        )

    if max_length is not None and length > max_length:
        result.add_error(
            f"{name} length {length} exceeds maximum {max_length}"
        )

    return result


def validate_enum(
    value: Any,
    enum_type: type[Enum],
    *,
    name: str = "value",
    result: ValidationResult | None = None,
) -> ValidationResult:
    """Validate that a value is a member of the given enum."""

    result = result or ValidationResult()

    try:
        enum_type(value)
    except (ValueError, TypeError):
        valid_values = [item.value for item in enum_type]
        result.add_error(
            f"{name} must be one of {valid_values}, got {value!r}"
        )

    return result


def validate_pattern(
    value: str,
    pattern: str,
    *,
    name: str = "value",
    flags: int = 0,
    result: ValidationResult | None = None,
) -> ValidationResult:
    """Validate a string against a regex pattern."""

    result = result or ValidationResult()

    if re.fullmatch(pattern, value, flags) is None:
        result.add_error(
            f"{name} does not match required pattern"
        )

    return result


# ==============================================================================
# SCHEMA VALIDATION
# ==============================================================================

_SCHEMA_KEYS = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "any": object,
}


def validate_schema(
    data: dict[str, Any],
    schema: dict[str, Any],
    *,
    required: list[str] | None = None,
    name: str = "payload",
    result: ValidationResult | None = None,
) -> ValidationResult:
    """
    Validate a dictionary against a schema.

    Parameters
    ----------
    data
        Dictionary to validate.

    schema
        Mapping of field name to type key (str/int/float/bool/list/dict/any).

    required
        Field names that must be present.
    """

    result = result or ValidationResult()

    if not isinstance(data, dict):
        result.add_error(f"{name} must be a dict")
        return result

    for field_name in required or []:
        if field_name not in data:
            result.add_error(f"{name} is missing required field '{field_name}'")

    for field_name, expected in schema.items():
        if field_name not in data:
            continue

        type_key = (
            expected if isinstance(expected, str) else "any"
        )

        expected_type = _SCHEMA_KEYS.get(type_key)

        if expected_type is None:
            result.add_warning(
                f"unknown schema type key '{type_key}' for '{field_name}'"
            )
            continue

        value = data[field_name]

        if expected_type is not object and not isinstance(value, expected_type):
            result.add_error(
                f"field '{field_name}' must be {type_key}, "
                f"got {type(value).__name__}"
            )

    return result


# ==============================================================================
# CALLABLE REGISTRY
# ==============================================================================


class Validator:
    """
    Composable validator with chained checks.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._checks: list[Callable[[Any, ValidationResult], None]] = []

    def add_check(
        self,
        check: Callable[[Any, ValidationResult], None],
    ) -> "Validator":
        """Append a check callable."""
        self._checks.append(check)
        return self

    def validate(self, value: Any) -> ValidationResult:
        """Run every check against the value."""
        result = ValidationResult()

        for check in self._checks:
            check(value, result)

        return result

    def __call__(self, value: Any) -> ValidationResult:
        return self.validate(value)


def chain_validators(
    *validators: Callable[[Any], ValidationResult],
) -> Callable[[Any], ValidationResult]:
    """Combine multiple validators into one."""

    def combined(value: Any) -> ValidationResult:
        result = ValidationResult()

        for validator in validators:
            result.merge(validator(value))

        return result

    return combined


# ==============================================================================
# PLANNING VALIDATORS
# ==============================================================================


def validate_goal(
    goal: Any,
    *,
    name: str = "goal",
) -> ValidationResult:
    """Validate a goal object/contract."""

    result = ValidationResult()
    require_non_empty(getattr(goal, "description", None), name="goal.description", result=result)
    require_non_empty(getattr(goal, "id", None), name="goal.id", result=result)
    return result


def validate_task(
    task: Any,
    *,
    name: str = "task",
) -> ValidationResult:
    """Validate a task object/contract."""

    result = ValidationResult()
    require_non_empty(getattr(task, "id", None), name="task.id", result=result)
    validate_type(getattr(task, "priority", None), int, name="task.priority", result=result)
    return result


def validate_plan(
    plan: Any,
    *,
    name: str = "plan",
) -> ValidationResult:
    """Validate a plan object/contract."""

    result = ValidationResult()
    require_non_empty(getattr(plan, "id", None), name="plan.id", result=result)

    tasks = getattr(plan, "tasks", None)

    if tasks is not None:
        validate_length(
            tasks,
            min_length=1,
            max_length=MAX_TASKS_PER_PLAN,
            name="plan.tasks",
            result=result,
        )

    return result


def validate_workflow(
    workflow: Any,
    *,
    name: str = "workflow",
) -> ValidationResult:
    """Validate a workflow object/contract."""

    result = ValidationResult()
    require_non_empty(getattr(workflow, "id", None), name="workflow.id", result=result)
    require_non_empty(getattr(workflow, "name", None), name="workflow.name", result=result)
    return result


def validate_dependency(
    dependency: Any,
    *,
    name: str = "dependency",
) -> ValidationResult:
    """Validate a task dependency object/contract."""

    result = ValidationResult()
    require_non_empty(getattr(dependency, "task_id", None), name="dependency.task_id", result=result)
    require_non_empty(getattr(dependency, "depends_on", None), name="dependency.depends_on", result=result)
    return result


# ==============================================================================
# BOOLEAN VALIDATORS
# ==============================================================================

# Thin boolean wrappers for guard clauses and filter predicates.


def is_valid_goal(goal: Any) -> bool:
    """Whether a goal object/contract passes validation."""
    return validate_goal(goal).valid


def is_valid_task(task: Any) -> bool:
    """Whether a task object/contract passes validation."""
    return validate_task(task).valid


def is_valid_plan(plan: Any) -> bool:
    """Whether a plan object/contract passes validation."""
    return validate_plan(plan).valid


def is_valid_workflow(workflow: Any) -> bool:
    """Whether a workflow object/contract passes validation."""
    return validate_workflow(workflow).valid


def _validate_int_range(
    value: int,
    *,
    min_value: int,
    max_value: int,
    name: str,
) -> ValidationResult:
    """Validate an integer against inclusive bounds without allocation."""
    result = ValidationResult()

    if not isinstance(value, int) or isinstance(value, bool):
        result.add_error(f"{name} must be an integer")
        return result

    if value < min_value:
        result.add_error(f"{name} {value} is below minimum {min_value}")

    if value > max_value:
        result.add_error(f"{name} {value} exceeds maximum {max_value}")

    return result


def validate_task_count(count: int) -> ValidationResult:
    """Validate a task count against system limits."""
    return _validate_int_range(
        count,
        min_value=1,
        max_value=MAX_TASKS,
        name="task count",
    )


def validate_depth(depth: int) -> ValidationResult:
    """Validate a decomposition depth against system limits."""
    return _validate_int_range(
        depth,
        min_value=0,
        max_value=MAX_DEPTH,
        name="decomposition depth",
    )


def validate_retry_count(count: int) -> ValidationResult:
    """Validate a retry count against system limits."""
    return _validate_int_range(
        count,
        min_value=0,
        max_value=MAX_RETRY,
        name="retry count",
    )


# ==============================================================================
# PERMISSION VALIDATION
# ==============================================================================


@dataclass(slots=True)
class PermissionValidator:
    """
    Enforces a permission allow-list.

    Permissions are enforced structurally in harness code, never by
    prompting, matching enterprise agent security practice.
    """

    allowed: set[str] = field(default_factory=set)

    def allow(self, *permissions: str) -> None:
        """Grant permissions."""
        self.allowed.update(permissions)

    def revoke(self, *permissions: str) -> None:
        """Revoke permissions."""
        self.allowed.difference_update(permissions)

    def is_allowed(self, permission: str) -> bool:
        """Whether a permission is granted."""
        return permission in self.allowed

    def validate(self, permission: str) -> ValidationResult:
        """Return a validation result for a permission request."""
        result = ValidationResult()

        if not self.is_allowed(permission):
            result.add_error(f"permission '{permission}' is not allowed")

        return result


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "ValidationResult",
    "ok_result",
    "MissingFieldError",
    "require_fields",
    "require_non_empty",
    "validate_type",
    "validate_length",
    "validate_enum",
    "validate_pattern",
    "validate_schema",
    "Validator",
    "chain_validators",
    "validate_goal",
    "validate_task",
    "validate_plan",
    "validate_workflow",
    "validate_dependency",
    "is_valid_goal",
    "is_valid_task",
    "is_valid_plan",
    "is_valid_workflow",
    "validate_task_count",
    "validate_depth",
    "validate_retry_count",
    "PermissionValidator",
]
