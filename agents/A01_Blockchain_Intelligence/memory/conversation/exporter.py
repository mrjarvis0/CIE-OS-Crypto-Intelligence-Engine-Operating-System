"""
Conversation Exporter

Exports conversations and messages to JSON, JSONL, and plain-text
transcripts for portability, auditing, and downstream tooling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from memory.base.conversation import Conversation, Message


@dataclass(slots=True)
class ExportOptions:
    """
    Options controlling export granularity.
    """

    include_metadata: bool = True
    include_topics: bool = True
    include_entities: bool = True
    indent: int | None = 2


def message_to_dict(message: Message, options: ExportOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": _role_value(message.role),
        "content": message.content,
        "tokens": message.tokens,
        "created_at": _iso(message.created_at),
    }
    if options.include_metadata:
        payload["metadata"] = dict(message.metadata)
    if options.include_topics:
        payload["topics"] = list(message.topics)
    if options.include_entities:
        payload["entities"] = [dict(entity) for entity in message.entities]
    return payload


def conversation_to_dict(
    conversation: Conversation,
    messages: Iterable[Message],
    options: ExportOptions,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": conversation.id,
        "title": conversation.title,
        "user_id": conversation.user_id,
        "message_count": conversation.message_count,
        "token_count": conversation.token_count,
        "created_at": _iso(conversation.created_at),
        "updated_at": _iso(conversation.updated_at),
        "messages": [message_to_dict(m, options) for m in messages],
    }
    if options.include_topics:
        payload["topics"] = list(conversation.topics)
    if options.include_entities:
        payload["entities"] = [dict(entity) for entity in conversation.entities]
    return payload


class ConversationExporter:
    """
    Exports conversation data to JSON, JSONL, and text.

    Responsibilities:
        * Render conversations to dict payloads
        * Serialize to JSON / JSONL / plain text
        * Respect export granularity options
    """

    def __init__(
        self,
        memory: Any,
        *,
        options: ExportOptions | None = None,
    ) -> None:
        self._memory = memory
        self._options = options or ExportOptions()

    @property
    def memory(self) -> Any:
        return self._memory

    async def load(
        self,
        conversation_id: str,
        *,
        limit: int = 100_000,
    ) -> tuple[Conversation, list[Message]]:
        load_conversation = getattr(self._memory, "load_conversation", None)
        if not callable(load_conversation):
            raise AttributeError("memory source must expose load_conversation()")
        conversation_result = load_conversation(conversation_id)
        conversation = (
            await conversation_result
            if hasattr(conversation_result, "__await__")
            else conversation_result
        )
        if conversation is None:
            raise KeyError(f"Conversation '{conversation_id}' was not found.")
        load_messages = getattr(self._memory, "load_messages", None)
        if not callable(load_messages):
            raise AttributeError("memory source must expose load_messages()")
        messages_result = load_messages(conversation_id, limit=limit)
        messages = (
            await messages_result
            if hasattr(messages_result, "__await__")
            else messages_result
        )
        return conversation, list(messages)

    async def to_dict(
        self,
        conversation_id: str,
        *,
        limit: int = 100_000,
    ) -> dict[str, Any]:
        conversation, messages = await self.load(conversation_id, limit=limit)
        return conversation_to_dict(conversation, messages, self._options)

    async def to_json(
        self,
        conversation_id: str,
        *,
        indent: int | None = None,
    ) -> str:
        payload = await self.to_dict(conversation_id)
        return json.dumps(
            payload,
            indent=self._options.indent if indent is None else indent,
            ensure_ascii=False,
        )

    async def to_jsonl(
        self,
        conversation_id: str,
        *,
        limit: int = 100_000,
    ) -> str:
        conversation, messages = await self.load(conversation_id, limit=limit)
        lines = [
            json.dumps(
                message_to_dict(message, self._options),
                ensure_ascii=False,
            )
            for message in messages
        ]
        return "\n".join(lines)

    async def to_text(
        self,
        conversation_id: str,
        *,
        separator: str = "\n",
    ) -> str:
        conversation, messages = await self.load(conversation_id)
        return separator.join(
            f"{_role_value(message.role)}: {message.content}"
            for message in messages
        )

    async def export_many(
        self,
        conversation_ids: Iterable[str],
        *,
        format: str = "json",
    ) -> list[dict[str, Any]]:
        """
        Export multiple conversations as a list of payloads.
        """
        results: list[dict[str, Any]] = []
        for conversation_id in conversation_ids:
            if format == "json":
                results.append(await self.to_dict(conversation_id))
            else:
                raise ValueError(f"Unsupported export format '{format}'.")
        return results


def _role_value(role: Any) -> str:
    return role.value if hasattr(role, "value") else str(role)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.isoformat()
