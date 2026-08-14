"""
Conversation Context

Assembles conversation messages into structured, token-bounded context
for prompts. Complements the base ``build_context`` with role-aware
packaging and renderers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from memory.base.conversation import Message, MessageRole

Renderer = Callable[[Message], str]


def _default_render(message: Message) -> str:
    role = message.role.value if hasattr(message.role, "value") else str(message.role)
    return f"{role}: {message.content}"


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass(slots=True)
class ContextResult:
    """
    Assembled context payload.
    """

    blocks: list[str] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    total_tokens: int = 0
    truncated: bool = False

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    def to_text(self, separator: str = "\n") -> str:
        return separator.join(self.blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_count": self.block_count,
            "total_tokens": self.total_tokens,
            "truncated": self.truncated,
            "text": self.to_text(),
        }


class ConversationContext:
    """
    Builds structured context from conversation messages.

    Responsibilities:
        * Package messages into role-tagged blocks
        * Enforce token budgets
        * Render context with configurable renderers
    """

    def __init__(
        self,
        memory: Any,
        *,
        max_tokens: int = 4096,
        include_system: bool = True,
        include_tool: bool = True,
        renderer: Renderer | None = None,
    ) -> None:
        self._memory = memory
        self._max_tokens = max_tokens
        self._include_system = include_system
        self._include_tool = include_tool
        self._renderer = renderer or _default_render

    @property
    def memory(self) -> Any:
        return self._memory

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def update(
        self,
        *,
        max_tokens: int | None = None,
        include_system: bool | None = None,
        include_tool: bool | None = None,
    ) -> None:
        if max_tokens is not None:
            self._max_tokens = max_tokens
        if include_system is not None:
            self._include_system = include_system
        if include_tool is not None:
            self._include_tool = include_tool

    def _include_role(self, role: MessageRole) -> bool:
        if role in {MessageRole.TOOL, MessageRole.FUNCTION}:
            return self._include_tool
        if role == MessageRole.SYSTEM:
            return self._include_system
        return True

    async def build(
        self,
        conversation_id: str,
        *,
        max_tokens: int | None = None,
    ) -> ContextResult:
        """
        Assemble a token-bounded context from the conversation.
        """
        budget = self._max_tokens if max_tokens is None else max_tokens
        window = getattr(self._memory, "get_conversation_window", None)
        if callable(window):
            result = window(conversation_id)
            messages = await result if hasattr(result, "__await__") else result
        else:
            load_messages = getattr(self._memory, "load_messages", None)
            if not callable(load_messages):
                raise AttributeError(
                    "memory source must expose get_conversation_window() or load_messages()"
                )
            result = load_messages(conversation_id, limit=100_000)
            messages = await result if hasattr(result, "__await__") else result
            messages = list(reversed(messages))

        blocks: list[str] = []
        total = 0
        truncated = False
        for message in reversed(messages):
            if not self._include_role(message.role):
                continue
            text = self._renderer(message)
            tokens = message.tokens or _estimate_tokens(text)
            if blocks and total + tokens > budget:
                truncated = True
                break
            blocks.append(text)
            total += tokens

        blocks.reverse()

        return ContextResult(
            blocks=blocks,
            messages=messages,
            total_tokens=total,
            truncated=truncated,
        )

    async def render(
        self,
        conversation_id: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        result = await self.build(
            conversation_id,
            max_tokens=max_tokens,
        )
        return result.to_text()
