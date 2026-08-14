"""
Conversation Replay

Sequentially replays conversation history for recall, evaluation, and
context reconstruction. Supports filtering, pausing, and transcript
rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Callable, Iterable

from memory.base.conversation import Message, MessageRole

Listener = Callable[[Message], Any]


@dataclass(slots=True)
class ReplayStats:
    """
    Accumulated replay statistics.
    """

    total: int = 0
    replayed: int = 0
    skipped: int = 0
    tokens: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "replayed": self.replayed,
            "skipped": self.skipped,
            "tokens": self.tokens,
            "duration_seconds": self.duration_seconds,
        }


class ReplayEngine:
    """
    Replays conversation history sequentially.

    Responsibilities:
        * Stream messages in chronological order
        * Invoke listeners per message
        * Produce a rendered transcript
    """

    def __init__(
        self,
        memory: Any,
        *,
        listeners: Iterable[Listener] | None = None,
        transcript_separator: str = "\n",
    ) -> None:
        self._memory = memory
        self._listeners = list(listeners or [])
        self._transcript_separator = transcript_separator

    @property
    def memory(self) -> Any:
        return self._memory

    @property
    def listeners(self) -> list[Listener]:
        return list(self._listeners)

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def clear_listeners(self) -> None:
        self._listeners.clear()

    async def load(
        self,
        conversation_id: str,
        *,
        limit: int = 1000,
    ) -> list[Message]:
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError("memory source must expose load_messages()")
        result = load_messages(conversation_id, limit=limit)
        messages = await result if hasattr(result, "__await__") else result
        return sorted(messages, key=lambda m: m.created_at)

    async def stream(
        self,
        conversation_id: str,
        *,
        roles: Iterable[MessageRole] | None = None,
        skip_system: bool = False,
        skip_tool: bool = False,
    ) -> AsyncIterator[Message]:
        """
        Yield messages in chronological order, optionally filtered.
        """
        role_set = set(roles) if roles is not None else None
        for message in await self.load(conversation_id):
            if skip_system and message.role == MessageRole.SYSTEM:
                continue
            if skip_tool and message.role in {MessageRole.TOOL, MessageRole.FUNCTION}:
                continue
            if role_set is not None and message.role not in role_set:
                continue
            yield message

    async def run(
        self,
        conversation_id: str,
        *,
        roles: Iterable[MessageRole] | None = None,
        skip_system: bool = False,
        skip_tool: bool = False,
        on_message: Listener | None = None,
    ) -> ReplayStats:
        """
        Replay a conversation, invoking listeners per message.
        """
        stats = ReplayStats()
        stats.started_at = datetime.now(UTC)
        messages = await self.load(conversation_id)
        stats.total = len(messages)
        role_set = set(roles) if roles is not None else None
        for message in messages:
            if skip_system and message.role == MessageRole.SYSTEM:
                stats.skipped += 1
                continue
            if skip_tool and message.role in {MessageRole.TOOL, MessageRole.FUNCTION}:
                stats.skipped += 1
                continue
            if role_set is not None and message.role not in role_set:
                stats.skipped += 1
                continue
            stats.replayed += 1
            stats.tokens += message.tokens
            for listener in self._listeners:
                result = listener(message)
                if hasattr(result, "__await__"):
                    await result
            if on_message is not None:
                result = on_message(message)
                if hasattr(result, "__await__"):
                    await result
        stats.finished_at = datetime.now(UTC)
        return stats

    async def transcript(
        self,
        conversation_id: str,
        *,
        roles: Iterable[MessageRole] | None = None,
        render: Callable[[Message], str] | None = None,
    ) -> str:
        """
        Render a conversation as a text transcript.
        """
        fmt = render or _default_render
        lines = [
            fmt(message)
            async for message in self.stream(
                conversation_id,
                roles=roles,
            )
        ]
        return self._transcript_separator.join(lines)


def _default_render(message: Message) -> str:
    role = message.role.value if hasattr(message.role, "value") else str(message.role)
    return f"{role}: {message.content}"
