"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.helpers

Purpose:
    Genuinely reusable cross-module helpers for the planning subsystem.

Only helpers that are used across multiple planning modules belong here.
Module-specific helpers must live inside their owning module.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
import time

from datetime import UTC, datetime
from typing import Any, Final, TypeVar

T = TypeVar("T")

_SLUG_NON_WORD: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")

# ==============================================================================
# TIME HELPERS
# ==============================================================================


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def iso_now() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return utc_now().isoformat()


def monotonic_ms() -> int:
    """Return high precision monotonic clock in milliseconds."""
    return int(time.perf_counter() * 1000)


def monotonic_seconds() -> float:
    """Return high precision monotonic clock in seconds."""
    return time.perf_counter()


# ==============================================================================
# COPY HELPERS
# ==============================================================================


def deep_copy(value: T) -> T:
    """Return a deep copy of the value."""
    return copy.deepcopy(value)


def shallow_copy(value: T) -> T:
    """Return a shallow copy of the value."""
    return copy.copy(value)


# ==============================================================================
# DICT HELPERS
# ==============================================================================


def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return a non-null metadata dictionary."""
    return metadata or {}


def safe_merge(
    *sources: dict[str, Any] | None,
    deep: bool = False,
) -> dict[str, Any]:
    """
    Merge multiple dictionaries.

    Later sources override earlier keys.

    Parameters
    ----------
    sources
        Dictionaries to merge.

    deep
        When True, merge nested dictionaries recursively.
    """

    merged: dict[str, Any] = {}

    for source in sources:
        source = safe_metadata(source)

        if not deep:
            merged.update(source)
            continue

        for key, value in source.items():
            current = merged.get(key)

            if isinstance(current, dict) and isinstance(value, dict):
                merged[key] = safe_merge(
                    current,
                    value,
                    deep=True,
                )
            else:
                merged[key] = value

    return merged


def flatten_dict(
    data: dict[str, Any],
    *,
    parent_key: str = "",
    separator: str = ".",
) -> dict[str, Any]:
    """
    Flatten a nested dictionary into a single level.

    Examples
    --------
        {"a": {"b": 1}} -> {"a.b": 1}
    """

    items: dict[str, Any] = {}

    for key, value in data.items():
        new_key = (
            f"{parent_key}{separator}{key}"
            if parent_key
            else key
        )

        if isinstance(value, dict):
            items.update(
                flatten_dict(
                    value,
                    parent_key=new_key,
                    separator=separator,
                )
            )
        else:
            items[new_key] = value

    return items


def get_nested(
    data: dict[str, Any],
    path: str,
    default: Any = None,
    *,
    separator: str = ".",
) -> Any:
    """Safely read a value at a dotted path."""
    current: Any = data

    for part in path.split(separator):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]

    return current


# ==============================================================================
# LIST HELPERS
# ==============================================================================


def chunk_list(values: list[T], size: int) -> list[list[T]]:
    """
    Split a list into chunks of the given size.

    Raises
    ------
    ValueError
        When size is not positive.
    """
    if size <= 0:
        raise ValueError("chunk size must be positive")

    return [
        values[index : index + size]
        for index in range(0, len(values), size)
    ]


def unique_preserve_order(values: list[T] | None) -> list[T]:
    """Return unique values while preserving insertion order."""
    seen: set[T] = set()
    result: list[T] = []

    for value in values or []:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def compact(values: list[Any] | None) -> list[Any]:
    """Remove None values from a list."""
    return [value for value in (values or []) if value is not None]


def ensure_list(value: Any) -> list[Any]:
    """
    Coerce a value into a list.

    None becomes an empty list; lists are returned as-is; any other scalar
    or iterable is wrapped or materialized.

    Examples
    --------
        ensure_list(None)     -> []
        ensure_list("x")      -> ["x"]
        ensure_list((1, 2))   -> [1, 2]
    """

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, (tuple, set, frozenset)):
        return list(value)

    return [value]


# ==============================================================================
# TYPE HELPERS
# ==============================================================================


def type_convert(
    value: Any,
    target_type: type[T],
    default: T | None = None,
) -> T | None:
    """
    Safely convert a value to a target type.

    Returns default when conversion fails or is impossible.
    """

    try:
        if target_type is bool:
            if isinstance(value, str):
                return target_type(value.lower() in {"1", "true", "yes", "on"})
            return target_type(value)

        return target_type(value)

    except (TypeError, ValueError):
        return default


def parse_int(
    value: Any,
    default: int | None = None,
) -> int | None:
    """
    Safely parse an integer from common input forms.

    Accepts ints, integral floats, and strings with optional sign,
    whitespace, and digit separators (``1_000``). Returns ``default`` when
    parsing fails or the value is ambiguous (e.g. bool).

    Examples
    --------
        parse_int("42")      -> 42
        parse_int(" -3 ")    -> -3
        parse_int("1_000")   -> 1000
        parse_int("abc")     -> None
    """

    if isinstance(value, bool):
        return default

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value) if value.is_integer() else default

    if isinstance(value, str):
        text = value.strip().replace("_", "")

        try:
            return int(text, 10)
        except (TypeError, ValueError):
            return default

    return default


def slugify(text: str) -> str:
    """
    Convert text into a URL-safe slug.

    Lowercases input and replaces every run of non-alphanumeric characters
    with a single hyphen.

    Examples
    --------
        slugify("Hello, World!")     -> "hello-world"
        slugify("Café & Bakery")     -> "caf-bakery"
    """

    normalized = text.lower()

    return _SLUG_NON_WORD.sub("-", normalized).strip("-")


def truncate(
    text: str,
    *,
    max_length: int,
    ellipsis: str = "...",
) -> str:
    """
    Truncate a string to a maximum length with an ellipsis suffix.

    Never exceeds ``max_length`` total characters. When the ellipsis is
    longer than the limit, hard-cuts at the limit.
    """

    if max_length < 0:
        raise ValueError("max_length must be non-negative")

    if len(text) <= max_length:
        return text

    if max_length <= len(ellipsis):
        return text[:max_length]

    return text[: max_length - len(ellipsis)] + ellipsis


# ==============================================================================
# COMPARISON HELPERS
# ==============================================================================


def object_eq(left: Any, right: Any, *, strict: bool = False) -> bool:
    """
    Compare two objects.

    When strict is True, both type and value must match.
    """

    if strict and type(left) is not type(right):
        return False

    if isinstance(left, dict) and isinstance(right, dict):
        return _dict_eq(left, right)

    return left == right


def _dict_eq(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left.keys() != right.keys():
        return False

    for key, value in left.items():
        if not object_eq(value, right[key], strict=False):
            return False

    return True


# ==============================================================================
# IMPORT HELPERS
# ==============================================================================


def safe_import(
    module_name: str,
    *,
    attribute: str | None = None,
    default: Any = None,
) -> Any:
    """
    Safely import a module or attribute.

    Returns default when the import fails.
    """

    try:
        module = importlib.import_module(module_name)

        if attribute is None:
            return module

        return getattr(module, attribute)

    except (ImportError, AttributeError):
        return default


# ==============================================================================
# TREE BUILDERS
# ==============================================================================


def tree_builder(
    nodes: list[dict[str, Any]],
    *,
    id_key: str = "id",
    parent_key: str = "parent_id",
    children_key: str = "children",
) -> list[dict[str, Any]]:
    """
    Build a nested tree from flat records.

    Each record must provide ``id`` and ``parent_id`` fields.
    Root records have ``parent_id`` set to None.
    """

    by_id: dict[Any, dict[str, Any]] = {}

    for node in nodes:
        node = deep_copy(node)
        node[children_key] = []
        by_id[node[id_key]] = node

    roots: list[dict[str, Any]] = []

    for node in by_id.values():
        parent = node.get(parent_key)

        if parent is not None and parent in by_id:
            by_id[parent][children_key].append(node)
        else:
            roots.append(node)

    return roots


# ==============================================================================
# JSON HELPERS (thin wrappers, canonical form lives in serialization)
# ==============================================================================


def to_json_pretty(data: Any) -> str:
    """Serialize to pretty-printed JSON."""
    return json.dumps(data, indent=2, default=str)


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "utc_now",
    "iso_now",
    "monotonic_ms",
    "monotonic_seconds",
    "deep_copy",
    "shallow_copy",
    "safe_metadata",
    "safe_merge",
    "flatten_dict",
    "get_nested",
    "chunk_list",
    "unique_preserve_order",
    "compact",
    "ensure_list",
    "type_convert",
    "parse_int",
    "slugify",
    "truncate",
    "object_eq",
    "safe_import",
    "tree_builder",
    "to_json_pretty",
]
