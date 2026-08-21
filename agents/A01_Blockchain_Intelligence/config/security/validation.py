"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.security.validation

Purpose:
    Centralized validation helpers for configuration, secret names, URLs, ports,
    filesystem paths, and other trusted runtime inputs.

Design goals:
    - Server-side validation only
    - Strong typing
    - Clear error messages
    - Reusable across config/security modules
    - No network I/O
    - No secrets handling
    - Safe to import anywhere

Notes:
    OWASP recommends centralized input validation on a trusted system and
    validating all untrusted data. Pydantic’s model-centric design is also based
    on typed validation driven by annotations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlparse


#: A secret name is also a filename under ``SecretsConfig.secrets_dir``, so
#: the separator is excluded: ``A/../../.ENV`` matched the previous pattern
#: and addressed a file outside the directory. ``.`` stays permitted because
#: provider names use it, and ``SecretsManager`` rejects ``..`` outright.
SECRET_NAME_PATTERN = re.compile(r"^[A-Z0-9_][A-Z0-9_.-]{0,127}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
HOSTNAME_PATTERN = re.compile(r"^[a-zA-Z0-9.-]+$")


class ValidationError(ValueError):
    """Raised when validation fails."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single validation issue."""

    field: str
    message: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """
    Validation report with structured issues.

    Use this when you want to validate a collection of inputs and get all
    problems at once instead of failing on the first error.
    """

    ok: bool
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    def raise_for_errors(self) -> None:
        if self.ok:
            return
        messages = "; ".join(f"{issue.field}: {issue.message}" for issue in self.issues)
        raise ValidationError(messages)


def _ok() -> ValidationReport:
    return ValidationReport(ok=True, issues=())


def _fail(*issues: ValidationIssue) -> ValidationReport:
    return ValidationReport(ok=False, issues=tuple(issues))


def ensure(condition: bool, field_name: str, message: str, value: Any = None) -> None:
    """Raise ValidationError when condition is false."""
    if not condition:
        raise ValidationError(f"{field_name}: {message}")


def validate_non_empty_string(value: Any, field_name: str, *, max_length: int | None = None) -> str:
    """Validate and return a non-empty string."""
    if not isinstance(value, str):
        raise ValidationError(f"{field_name}: expected string")
    clean = value.strip()
    if not clean:
        raise ValidationError(f"{field_name}: cannot be empty")
    if max_length is not None and len(clean) > max_length:
        raise ValidationError(f"{field_name}: must be at most {max_length} characters")
    return clean


def validate_boolean(value: Any, field_name: str) -> bool:
    """Validate and return a boolean."""
    if isinstance(value, bool):
        return value
    raise ValidationError(f"{field_name}: expected boolean")


def validate_positive_int(
    value: Any,
    field_name: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    """Validate and return a positive integer within optional bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field_name}: expected integer")
    if value < minimum:
        raise ValidationError(f"{field_name}: must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{field_name}: must be <= {maximum}")
    return value


def validate_non_negative_int(value: Any, field_name: str, *, maximum: int | None = None) -> int:
    """Validate and return a non-negative integer."""
    return validate_positive_int(value, field_name, minimum=0, maximum=maximum)


def validate_positive_float(
    value: Any,
    field_name: str,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    """Validate and return a positive float within optional bounds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name}: expected number")
    numeric = float(value)
    if numeric <= minimum:
        raise ValidationError(f"{field_name}: must be > {minimum}")
    if maximum is not None and numeric > maximum:
        raise ValidationError(f"{field_name}: must be <= {maximum}")
    return numeric


def validate_percentage(value: Any, field_name: str) -> float:
    """Validate a percentage in the range 0..100."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name}: expected number")
    numeric = float(value)
    if not (0.0 <= numeric <= 100.0):
        raise ValidationError(f"{field_name}: must be between 0 and 100")
    return numeric


def validate_choice(value: Any, field_name: str, choices: Iterable[str]) -> str:
    """Validate that value is a member of a predefined string set."""
    clean = validate_non_empty_string(value, field_name)
    normalized_choices = {str(choice) for choice in choices}
    if clean not in normalized_choices:
        raise ValidationError(f"{field_name}: invalid choice {clean!r}")
    return clean


def validate_secret_name(name: Any) -> str:
    """
    Validate a secret name used for file/env resolution.
    """
    clean = validate_non_empty_string(name, "secret_name", max_length=128).upper()
    if not SECRET_NAME_PATTERN.fullmatch(clean):
        raise ValidationError(
            "secret_name: must match pattern "
            "^[A-Z0-9_][A-Z0-9_.-]{0,127}$"
        )
    if ".." in clean:
        raise ValidationError("secret_name: must not contain '..'")
    return clean


def validate_env_name(name: Any) -> str:
    """Validate a .env-style environment variable name."""
    clean = validate_non_empty_string(name, "env_name", max_length=64).upper()
    if not ENV_NAME_PATTERN.fullmatch(clean):
        raise ValidationError("env_name: invalid environment variable format")
    return clean


def validate_env_prefix(prefix: Any) -> str:
    """Validate an environment prefix for secret loading."""
    clean = validate_non_empty_string(prefix, "env_prefix", max_length=32).upper()
    if not clean.endswith("_"):
        raise ValidationError("env_prefix: must end with '_'")
    if not ENV_NAME_PATTERN.fullmatch(clean[:-1]):
        raise ValidationError("env_prefix: invalid prefix format")
    return clean


def validate_url(
    value: Any,
    field_name: str = "url",
    *,
    allowed_schemes: Iterable[str] | None = None,
    require_netloc: bool = True,
) -> str:
    """Validate a URL and optionally restrict the scheme."""
    clean = validate_non_empty_string(value, field_name, max_length=2048)
    parsed = urlparse(clean)
    scheme = parsed.scheme.lower()

    if not scheme:
        raise ValidationError(f"{field_name}: missing URL scheme")

    if allowed_schemes is not None and scheme not in {s.lower() for s in allowed_schemes}:
        raise ValidationError(f"{field_name}: unsupported scheme {scheme!r}")

    if require_netloc and scheme != "ipc" and not parsed.netloc:
        raise ValidationError(f"{field_name}: missing network location")

    return clean


def validate_host(value: Any, field_name: str = "host") -> str:
    """Validate a hostname or IP-style host string."""
    clean = validate_non_empty_string(value, field_name, max_length=253)
    if not HOSTNAME_PATTERN.fullmatch(clean):
        raise ValidationError(f"{field_name}: invalid host name")
    return clean


def validate_port(value: Any, field_name: str = "port") -> int:
    """Validate a TCP/UDP port."""
    return validate_positive_int(value, field_name, minimum=1, maximum=65535)


def validate_path_exists(path: Any, field_name: str = "path") -> Path:
    """Validate that a filesystem path exists."""
    if not isinstance(path, (str, Path)):
        raise ValidationError(f"{field_name}: expected path-like value")
    resolved = Path(path)
    if not resolved.exists():
        raise ValidationError(f"{field_name}: path does not exist")
    return resolved


def validate_directory(path: Any, field_name: str = "directory") -> Path:
    """Validate that a filesystem path is an existing directory."""
    resolved = validate_path_exists(path, field_name)
    if not resolved.is_dir():
        raise ValidationError(f"{field_name}: expected directory")
    return resolved


def validate_file(path: Any, field_name: str = "file") -> Path:
    """Validate that a filesystem path is an existing file."""
    resolved = validate_path_exists(path, field_name)
    if not resolved.is_file():
        raise ValidationError(f"{field_name}: expected file")
    return resolved


def validate_unique_strings(
    values: Iterable[Any],
    field_name: str,
    *,
    max_length: int | None = None,
) -> tuple[str, ...]:
    """Validate a collection of unique non-empty strings."""
    seen: set[str] = set()
    output: list[str] = []

    for item in values:
        clean = validate_non_empty_string(item, field_name, max_length=max_length)
        if clean in seen:
            raise ValidationError(f"{field_name}: duplicate value {clean!r}")
        seen.add(clean)
        output.append(clean)

    return tuple(output)


def validate_non_empty_collection(values: Iterable[Any], field_name: str) -> tuple[Any, ...]:
    """Validate that a collection is not empty."""
    items = tuple(values)
    if not items:
        raise ValidationError(f"{field_name}: collection cannot be empty")
    return items


def validate_rpcs(urls: Iterable[Any]) -> ValidationReport:
    """Validate a list of RPC URLs and return a structured report."""
    issues: list[ValidationIssue] = []
    for index, url in enumerate(urls):
        try:
            validate_url(
                url,
                field_name=f"rpc_urls[{index}]",
                allowed_schemes=("http", "https", "ws", "wss", "ipc"),
            )
        except ValidationError as exc:
            issues.append(
                ValidationIssue(
                    field=f"rpc_urls[{index}]",
                    message=str(exc),
                    value=url,
                )
            )
    return _ok() if not issues else _fail(*issues)


def validate_secret_names(names: Iterable[Any]) -> ValidationReport:
    """Validate a list of secret names and return a structured report."""
    issues: list[ValidationIssue] = []
    for index, name in enumerate(names):
        try:
            validate_secret_name(name)
        except ValidationError as exc:
            issues.append(
                ValidationIssue(
                    field=f"secret_names[{index}]",
                    message=str(exc),
                    value=name,
                )
            )
    return _ok() if not issues else _fail(*issues)


__all__ = [
    "ValidationError",
    "ValidationIssue",
    "ValidationReport",
    "ensure",
    "validate_non_empty_string",
    "validate_boolean",
    "validate_positive_int",
    "validate_non_negative_int",
    "validate_positive_float",
    "validate_percentage",
    "validate_choice",
    "validate_secret_name",
    "validate_env_name",
    "validate_env_prefix",
    "validate_url",
    "validate_host",
    "validate_port",
    "validate_path_exists",
    "validate_directory",
    "validate_file",
    "validate_unique_strings",
    "validate_non_empty_collection",
    "validate_rpcs",
    "validate_secret_names",
]
