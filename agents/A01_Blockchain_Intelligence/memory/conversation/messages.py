"""
Message Store

Storage and retrieval of individual conversation messages with roles
and metadata. Thin facade over a ``ConversationMemory``-like source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from memory.base.conversation import Message, MessageRole


class MessageStore:
    """
    Stores and retrieves conversation messages.

    Responsibilities:
        * Insert messages with role metadata
        * Query by session and time
        * Batch operations
    """

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    @property
    def memory(self) -> Any:
        return self._memory

    async def add(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
        **kwargs: Any,
    ) -> Message:
        add_message = getattr(self._memory, "add_message", None)
        if not callable(add_message):
            raise AttributeError("memory source must expose add_message()")
        result = add_message(conversation_id, role, content, **kwargs)
        return await result if hasattr(result, "__await__") else result

    async def get(
        self,
        message_id: str,
    ) -> Message | None:
        get_message = getattr(self._memory, "get_message", None)
        if not callable(get_message):
            raise AttributeError("memory source must expose get_message()")
        result = get_message(message_id)
        return await result if hasattr(result, "__await__") else result

    async def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        role: MessageRole | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[Message]:
        """
        List messages for a conversation with optional filters.
        """
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError("memory source must expose load_messages()")
        needs_filter = (
            role is not None or since is not None or until is not None
        )
        fetch_limit = 100_000 if needs_filter else limit
        result = load_messages(conversation_id, limit=fetch_limit)
        messages = await result if hasattr(result, "__await__") else result
        filtered = messages
        if role is not None:
            filtered = [m for m in filtered if m.role == role]
        if since is not None:
            filtered = [m for m in filtered if m.created_at >= since]
        if until is not None:
            filtered = [m for m in filtered if m.created_at <= until]
        return filtered[:limit]

    async def query(
        self,
        conversation_id: str,
        *,
        roles: Iterable[MessageRole] | None = None,
        limit: int = 100,
    ) -> list[Message]:
        role_set = set(roles) if roles is not None else None
        messages = await self.list_for_conversation(
            conversation_id,
            limit=limit,
        )
        if role_set is None:
            return messages
        return [m for m in messages if m.role in role_set]

    async def update(
        self,
        message_id: str,
        **kwargs: Any,
    ) -> Message | None:
        update_message = getattr(self._memory, "update_message", None)
        if not callable(update_message):
            raise AttributeError("memory source must expose update_message()")
        result = update_message(message_id, **kwargs)
        return await result if hasattr(result, "__await__") else result

    async def delete(
        self,
        message_id: str,
    ) -> bool:
        delete_message = getattr(self._memory, "delete_message", None)
        if not callable(delete_message):
            raise AttributeError("memory source must expose delete_message()")
        result = delete_message(message_id)
        return await result if hasattr(result, "__await__") else result

    async def add_many(
        self,
        conversation_id: str,
        messages: Iterable[tuple[MessageRole, str]],
        **kwargs: Any,
    ) -> list[Message]:
        """
        Insert multiple (role, content) messages in order.
        """
        inserted: list[Message] = []
        for role, content in messages:
            inserted.append(
                await self.add(
                    conversation_id,
                    role,
                    content,
                    **kwargs,
                )
            )
        return inserted

    async def delete_many(
        self,
        message_ids: Iterable[str],
    ) -> int:
        removed = 0
        for message_id in message_ids:
            if await self.delete(message_id):
                removed += 1
        return removed

    async def count(
        self,
        conversation_id: str,
    ) -> int:
        return len(
            await self.list_for_conversation(conversation_id, limit=100_000)
        )
