"""
Conversation Analytics

Computes descriptive analytics over conversations: message counts by
role, token volumes, activity windows, topics, and entities.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from memory.base.conversation import Message


@dataclass(slots=True)
class ConversationAnalyticsResult:
    """
    Aggregate analytics for a conversation.
    """

    conversation_id: str
    message_count: int = 0
    token_count: int = 0
    roles: dict[str, int] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    first_message_at: datetime | None = None
    last_message_at: datetime | None = None
    message_rate_per_day: float = 0.0

    @property
    def activity_days(self) -> float:
        if self.first_message_at is None or self.last_message_at is None:
            return 0.0
        delta = self.last_message_at - self.first_message_at
        return max(1.0, delta.total_seconds() / 86400.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "message_count": self.message_count,
            "token_count": self.token_count,
            "roles": dict(self.roles),
            "topics": list(self.topics),
            "entities": [dict(entity) for entity in self.entities],
            "first_message_at": (
                self.first_message_at.isoformat()
                if self.first_message_at is not None
                else None
            ),
            "last_message_at": (
                self.last_message_at.isoformat()
                if self.last_message_at is not None
                else None
            ),
            "message_rate_per_day": self.message_rate_per_day,
        }


class ConversationAnalytics:
    """
    Computes descriptive conversation analytics.

    Responsibilities:
        * Aggregate role and token statistics
        * Summarize topics and entities
        * Estimate activity rates
    """

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        return self._memory

    async def analyze(
        self,
        conversation_id: str,
        *,
        limit: int = 100_000,
    ) -> ConversationAnalyticsResult:
        """
        Analyze a single conversation.
        """
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError("memory source must expose load_messages()")
        result = load_messages(conversation_id, limit=limit)
        messages = await result if hasattr(result, "__await__") else result

        roles: Counter = Counter()
        tokens = 0
        first: datetime | None = None
        last: datetime | None = None
        topics: Counter = Counter()

        for message in messages:
            role = _role_value(message.role)
            roles[role] += 1
            tokens += message.tokens
            stamp = message.created_at
            if first is None or stamp < first:
                first = stamp
            if last is None or stamp > last:
                last = stamp
            for topic in message.topics:
                topics[topic] += 1

        return ConversationAnalyticsResult(
            conversation_id=conversation_id,
            message_count=len(messages),
            token_count=tokens,
            roles=dict(roles),
            topics=[name for name, _ in topics.most_common()],
            entities=[dict(entity) for entity in _aggregate_entities(messages)],
            first_message_at=first,
            last_message_at=last,
            message_rate_per_day=(
                len(messages) / result_activity_days(first, last)
                if len(messages)
                else 0.0
            ),
        )

    async def list_summary(
        self,
        *,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Summarize all conversations.
        """
        list_conversations = getattr(self._memory, "list_conversations", None)
        if not callable(list_conversations):
            raise AttributeError("memory source must expose list_conversations()")
        result = list_conversations(user_id=user_id)
        conversations = await result if hasattr(result, "__await__") else result
        summary = []
        for conversation in conversations:
            summary.append(
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "user_id": conversation.user_id,
                    "message_count": conversation.message_count,
                    "token_count": conversation.token_count,
                    "created_at": conversation.created_at,
                    "updated_at": conversation.updated_at,
                }
            )
        summary.sort(key=lambda item: item["updated_at"], reverse=True)
        return summary


def _role_value(role: Any) -> str:
    return role.value if hasattr(role, "value") else str(role)


def _aggregate_entities(messages: list[Message]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for message in messages:
        for entity in message.entities:
            name = entity.get("name")
            if not name:
                continue
            bucket = by_name.setdefault(
                name,
                {
                    "name": name,
                    "type": entity.get("type", "unknown"),
                    "frequency": 0,
                },
            )
            bucket["frequency"] += 1
    return sorted(
        by_name.values(),
        key=lambda item: item["frequency"],
        reverse=True,
    )


def result_activity_days(first: datetime | None, last: datetime | None) -> float:
    if first is None or last is None:
        return 1.0
    return max(1.0, (last - first).total_seconds() / 86400.0)
