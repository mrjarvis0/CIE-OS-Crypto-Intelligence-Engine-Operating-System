"""
Conversation Window

Sliding-window management over conversation messages for context
budgeting and truncation. Provides token accounting and oldest-message
eviction over any ``ConversationMemory``-like source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory.base.conversation import Message


def estimate_tokens(text: str) -> int:
    """
    Estimate token count using a 4-chars-per-token heuristic.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass(slots=True)
class WindowResult:
    """
    Outcome of a windowing operation.
    """

    messages: list[Message] = field(default_factory=list)
    total_tokens: int = 0
    kept: int = 0
    dropped: int = 0
    truncated: bool = False

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept": self.kept,
            "dropped": self.dropped,
            "total_tokens": self.total_tokens,
            "truncated": self.truncated,
            "message_count": self.message_count,
        }


class ConversationWindow:
    """
    Manages the active conversation context window.

    Responsibilities:
        * Enforce message and token budgets
        * Sliding window truncation
        * Oldest-message eviction
    """

    def __init__(
        self,
        memory: Any,
        *,
        max_tokens: int = 4096,
        max_messages: int | None = None,
        tokenizer: Any | None = None,
    ) -> None:
        self._memory = memory
        self._max_tokens = max_tokens
        self._max_messages = max_messages
        self._tokenizer = tokenizer

    @property
    def memory(self) -> Any:
        return self._memory

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def max_messages(self) -> int | None:
        return self._max_messages

    def update_limits(
        self,
        *,
        max_tokens: int | None = None,
        max_messages: int | None = None,
    ) -> None:
        if max_tokens is not None:
            if max_tokens <= 0:
                raise ValueError("max_tokens must be strictly positive.")
            self._max_tokens = max_tokens
        if max_messages is not None:
            self._max_messages = max_messages

    def _count_tokens(self, message: Message) -> int:
        if self._tokenizer is not None:
            count = self._tokenizer(message.content)
            if isinstance(count, int):
                return max(0, count)
        if message.tokens > 0:
            return message.tokens
        return estimate_tokens(message.content)

    async def window(
        self,
        conversation_id: str,
        *,
        start_idx: int = 0,
        end_idx: int | None = None,
    ) -> list[Message]:
        get_window = getattr(self._memory, "get_conversation_window", None)
        if callable(get_window):
            result = get_window(
                conversation_id,
                start_idx=start_idx,
                end_idx=end_idx,
            )
            return await result if hasattr(result, "__await__") else result
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError(
                "memory source must expose get_conversation_window() or load_messages()"
            )
        result = load_messages(conversation_id, limit=100_000)
        messages = await result if hasattr(result, "__await__") else result
        return list(reversed(messages))[start_idx:end_idx]

    async def budget(
        self,
        conversation_id: str,
        *,
        max_tokens: int | None = None,
    ) -> WindowResult:
        """
        Keep messages within the token budget, dropping the oldest
        first while always retaining the newest message.
        """
        messages = await self.window(conversation_id)
        budget = self._max_tokens if max_tokens is None else max_tokens
        ordered = list(reversed(messages))
        kept: list[Message] = []
        total = 0
        truncated = False
        dropped = 0

        for index, message in enumerate(ordered):
            tokens = self._count_tokens(message)
            if len(kept) > 0 and total + tokens > budget:
                truncated = True
                dropped += 1
                continue
            kept.append(message)
            total += tokens
            if (
                self._max_messages is not None
                and len(kept) >= self._max_messages
            ):
                truncated = True
                dropped += len(ordered) - index - 1
                break

        return WindowResult(
            messages=list(reversed(kept)),
            total_tokens=total,
            kept=len(kept),
            dropped=dropped,
            truncated=truncated,
        )

    async def evict(
        self,
        conversation_id: str,
        *,
        keep_count: int = 50,
    ) -> int:
        """
        Remove the oldest messages beyond ``keep_count``.
        """
        messages = await self.window(conversation_id)
        if len(messages) <= keep_count:
            return 0
        truncate = getattr(self._memory, "truncate_conversation", None)
        if callable(truncate):
            result = truncate(conversation_id, keep_count=keep_count)
            return await result if hasattr(result, "__await__") else result
        removed = 0
        delete_message = getattr(self._memory, "delete_message", None)
        for message in messages[: len(messages) - keep_count]:
            if callable(delete_message):
                result = delete_message(message.id)
                await result if hasattr(result, "__await__") else None
                removed += 1
        return removed

    async def latest(
        self,
        conversation_id: str,
        *,
        count: int = 10,
    ) -> list[Message]:
        """
        Return the most recent messages (chronological order).
        """
        messages = await self.window(conversation_id)
        return messages[-count:]
