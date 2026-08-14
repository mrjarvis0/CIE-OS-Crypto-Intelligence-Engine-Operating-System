"""
Conversation History

Persistent conversation history access with ordering, pagination, and
pruning. Thin facade over a ``ConversationMemory``-like source using
duck typing — no duplicated persistence logic.
"""

from __future__ import annotations

from typing import Any, Callable

from memory.base.conversation import Message

MessageSource = Any


def _ensure_async(result: Any):
    return result if hasattr(result, "__await__") else None


class ConversationHistory:
    """
    Manages persistent conversation history.

    Responsibilities:
        * Append and read messages
        * Paginate history access
        * Prune by age or size
    """

    def __init__(
        self,
        memory: MessageSource,
        *,
        default_page_size: int = 50,
    ) -> None:
        self._memory = memory
        self._default_page_size = default_page_size

    @property
    def memory(self) -> MessageSource:
        return self._memory

    async def append(
        self,
        conversation_id: str,
        role: Any,
        content: str,
        **kwargs: Any,
    ) -> Message:
        add_message = getattr(self._memory, "add_message", None)
        if not callable(add_message):
            raise AttributeError("memory source must expose add_message()")
        result = add_message(
            conversation_id,
            role,
            content,
            **kwargs,
        )
        if hasattr(result, "__await__"):
            return await result
        return result

    async def read(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[Message]:
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError("memory source must expose load_messages()")
        result = load_messages(
            conversation_id,
            limit=limit if limit is not None else self._default_page_size,
        )
        if hasattr(result, "__await__"):
            return await result
        return result

    async def get(
        self,
        message_id: str,
    ) -> Message | None:
        get_message = getattr(self._memory, "get_message", None)
        if not callable(get_message):
            raise AttributeError("memory source must expose get_message()")
        result = get_message(message_id)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def paginate(
        self,
        conversation_id: str,
        *,
        page: int = 0,
        page_size: int | None = None,
    ) -> tuple[list[Message], int]:
        """
        Return a page of messages plus the total count.
        """
        size = page_size or self._default_page_size
        messages = await self.read(
            conversation_id,
            limit=(page + 1) * size,
        )
        ordered = list(reversed(messages))

        total = len(ordered)
        count_fn = getattr(self._memory, "count", None)
        if callable(count_fn):
            result = count_fn(conversation_id)
            if hasattr(result, "__await__"):
                total = await result
            else:
                total = result

        start = page * size
        chunk = ordered[start : start + size]
        return chunk, int(total or 0)

    async def update(
        self,
        message_id: str,
        **kwargs: Any,
    ) -> Message | None:
        update_message = getattr(self._memory, "update_message", None)
        if not callable(update_message):
            raise AttributeError("memory source must expose update_message()")
        result = update_message(message_id, **kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def delete(
        self,
        message_id: str,
    ) -> bool:
        delete_message = getattr(self._memory, "delete_message", None)
        if not callable(delete_message):
            raise AttributeError("memory source must expose delete_message()")
        result = delete_message(message_id)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def prune(
        self,
        conversation_id: str,
        *,
        keep_count: int = 50,
    ) -> int:
        """
        Prune old messages, keeping the most recent ``keep_count``.
        """
        truncate = getattr(self._memory, "truncate_conversation", None)
        if callable(truncate):
            result = truncate(conversation_id, keep_count=keep_count)
            if hasattr(result, "__await__"):
                return await result
            return result
        messages = await self.read(conversation_id, limit=keep_count + 1)
        ordered = list(reversed(messages))
        if len(ordered) <= keep_count:
            return 0
        removed = 0
        for message in ordered[keep_count:]:
            if await self.delete(message.id):
                removed += 1
        return removed
