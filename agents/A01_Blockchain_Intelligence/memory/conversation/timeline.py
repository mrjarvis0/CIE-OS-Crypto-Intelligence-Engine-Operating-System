"""
Conversation Timeline

Builds chronological timelines of conversations and messages with
optional day/hour bucketing and participant rollups.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from memory.base.conversation import Message


@dataclass(slots=True)
class TimelineEntry:
    """
    A single point on a conversation timeline.
    """

    timestamp: datetime
    conversation_id: str
    message_id: str
    role: str
    content: str
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "tokens": self.tokens,
        }


@dataclass(slots=True)
class Timeline:
    """
    Assembled chronological timeline.
    """

    entries: list[TimelineEntry] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "entries": [entry.to_dict() for entry in self.entries],
        }


class TimelineBuilder:
    """
    Builds chronological timelines from conversation messages.

    Responsibilities:
        * Order messages chronologically
        * Bucket by day or hour
        * Roll up participant activity
    """

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        return self._memory

    async def build(
        self,
        conversation_id: str,
        *,
        limit: int = 1000,
        reverse: bool = False,
    ) -> Timeline:
        """
        Build a chronological timeline for one conversation.
        """
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError("memory source must expose load_messages()")
        result = load_messages(conversation_id, limit=limit)
        messages = await result if hasattr(result, "__await__") else result
        ordered = sorted(messages, key=lambda m: m.created_at)
        if reverse:
            ordered = list(reversed(ordered))
        entries = [
            TimelineEntry(
                timestamp=_as_utc(message.created_at),
                conversation_id=conversation_id,
                message_id=message.id,
                role=_role_value(message.role),
                content=message.content,
                tokens=message.tokens,
            )
            for message in ordered
        ]
        return Timeline(entries=entries)

    async def bucket_by_day(
        self,
        conversation_id: str,
        *,
        limit: int = 1000,
    ) -> dict[date, int]:
        """
        Count messages per calendar day.
        """
        timeline = await self.build(conversation_id, limit=limit)
        counts: Counter = Counter()
        for entry in timeline.entries:
            counts[_as_utc(entry.timestamp).date()] += 1
        return dict(sorted(counts.items()))

    async def participant_rollup(
        self,
        conversation_id: str,
        *,
        limit: int = 1000,
    ) -> dict[str, dict[str, Any]]:
        """
        Roll up per-role message and token activity.
        """
        timeline = await self.build(conversation_id, limit=limit)
        per_role: dict[str, dict[str, Any]] = {}
        for entry in timeline.entries:
            bucket = per_role.setdefault(
                entry.role,
                {"count": 0, "tokens": 0},
            )
            bucket["count"] += 1
            bucket["tokens"] += entry.tokens
        return per_role


def _role_value(role: Any) -> str:
    return role.value if hasattr(role, "value") else str(role)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
