"""
Memory Validation Utilities

Validators for keys, values, and tags used across engines.
"""

from __future__ import annotations

from typing import Any, Iterable


class ValidationError(Exception):
    pass


def valid_key(key: Any) -> bool:
    return isinstance(key, str) and bool(key.strip())


def require_key(key: Any) -> str:
    if not valid_key(key):
        raise ValidationError("key must be a non-empty string.")
    return key


def require_value(value: Any) -> Any:
    if value is None:
        raise ValidationError("value cannot be None.")
    return value


def valid_tags(tags: Iterable[Any]) -> bool:
    return all(isinstance(tag, str) and bool(tag) for tag in tags)


def require_tags(tags: Iterable[str]) -> list[str]:
    normalized = list(tags)
    if not valid_tags(normalized):
        raise ValidationError("tags must be non-empty strings.")
    return normalized


def normalize_tags(
    tags: Iterable[str] | None,
) -> list[str]:
    """
    Normalize tags: strip whitespace, drop empties, dedupe.
    """
    if tags is None:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        cleaned = str(tag).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def validate_namespace(namespace: Any) -> str:
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValidationError("namespace must be a non-empty string.")
    return namespace
