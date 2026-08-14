"""
Memory Serialization and Conversion Utilities

Convert MemoryEntry objects to/from plain dicts and JSON-safe
payloads, and encode/decode memory tags using the ``lt:`` conventions
shared with the base long-term engine.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Sequence

from memory.base.memory import (
    MemoryEntry,
    MemoryMetadata,
    MemoryPriority,
    MemoryType,
)


class SerializationError(Exception):
    pass


class ConvertError(Exception):
    pass


def entry_to_dict(entry: MemoryEntry) -> dict[str, Any]:
    metadata = entry.metadata or MemoryMetadata()
    return {
        "key": entry.key,
        "value": entry.value,
        "metadata": {
            "namespace": metadata.namespace,
            "source": metadata.source,
            "tags": list(metadata.tags or []),
            "confidence": metadata.confidence,
            "priority": (
                metadata.priority.value
                if metadata.priority is not None
                else None
            ),
            "created_at": _iso(metadata.created_at),
            "updated_at": _iso(metadata.updated_at),
            "expires_at": _iso(metadata.expires_at),
        },
    }


def dict_to_entry(payload: dict[str, Any]) -> MemoryEntry:
    metadata = payload.get("metadata") or {}
    created = _parse_dt(metadata.get("created_at"))
    updated = _parse_dt(metadata.get("updated_at"))
    expires = _parse_dt(metadata.get("expires_at"))
    raw_priority = metadata.get("priority")
    priority = _coerce_priority(raw_priority)
    entry_metadata = MemoryMetadata(
        namespace=metadata.get("namespace", "default"),
        source=metadata.get("source"),
        tags=list(metadata.get("tags") or []),
        confidence=metadata.get("confidence", 1.0),
        priority=priority,
        created_at=created,
        updated_at=updated,
        expires_at=expires,
    )
    return MemoryEntry(
        key=payload["key"],
        value=payload["value"],
        metadata=entry_metadata,
    )


def to_json(entry: MemoryEntry) -> str:
    return json.dumps(entry_to_dict(entry), default=str)


def from_json(text: str) -> MemoryEntry:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SerializationError("invalid JSON payload.") from exc
    return dict_to_entry(payload)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _coerce_priority(value: Any) -> MemoryPriority:
    if value is None or isinstance(value, MemoryPriority):
        return value
    try:
        return MemoryPriority(int(value))
    except (ValueError, TypeError):
        return MemoryPriority.NORMAL


def encode_memory_type(memory_type: MemoryType) -> str:
    return f"lt:type:{memory_type.value}"


def decode_memory_type(
    tags: Sequence[str],
    default: MemoryType = MemoryType.LONG_TERM,
) -> MemoryType:
    for tag in tags:
        if tag.startswith("lt:type:"):
            try:
                return MemoryType(tag.removeprefix("lt:type:"))
            except ValueError:
                continue
    return default


def encode_importance(score: float) -> str:
    return f"lt:importance:{score}"


def decode_importance(
    tags: Sequence[str],
    default: float = 0.5,
) -> float:
    for tag in tags:
        if tag.startswith("lt:importance:"):
            try:
                return float(tag.removeprefix("lt:importance:"))
            except ValueError:
                continue
    return default


def encode_priority(priority: MemoryPriority) -> str:
    return f"lt:priority:{priority.value}"


def decode_priority(
    tags: Sequence[str],
    default: MemoryPriority = MemoryPriority.NORMAL,
) -> MemoryPriority:
    for tag in tags:
        if tag.startswith("lt:priority:"):
            raw = tag.removeprefix("lt:priority:")
            try:
                return MemoryPriority(int(raw))
            except (ValueError, TypeError):
                continue
    return default


def build_tags(
    memory_type: MemoryType | None = None,
    importance: float | None = None,
    priority: MemoryPriority | None = None,
    extra: Sequence[str] | None = None,
) -> list[str]:
    tags = list(extra or [])
    if memory_type is not None:
        tags.append(encode_memory_type(memory_type))
    if importance is not None:
        tags.append(encode_importance(importance))
    if priority is not None:
        tags.append(encode_priority(priority))
    return tags
