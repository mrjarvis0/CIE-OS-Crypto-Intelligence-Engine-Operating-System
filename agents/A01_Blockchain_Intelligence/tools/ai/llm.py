"""
Tools :: AI :: LLM
==================

Unified interface for all language models.

Supports chat completion, multi-turn conversation, tool calling, JSON mode,
structured output and streaming. Provider-specific SDKs plug in behind
:class:`LLMClient`; a deterministic, stdlib-only :class:`LocalLLM` is shipped
so the layer works with zero external dependencies (used for tests, fallback
and offline mode).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import (
    AIError,
    AIExecutionError,
    AITimeoutError,
    AIUsage,
    AIValidationError,
    AIResponse,
    BaseAIModel,
    normalize_text,
)

__all__ = [
    "ChatMessage",
    "LLMRequest",
    "LLMResult",
    "LLMClient",
    "LocalLLM",
    "count_tokens",
    "estimate_tokens",
]


def estimate_tokens(text: str) -> int:
    """Heuristic token count: words + punctuation runs (no tokenizer dep)."""
    if not text:
        return 0
    return len(re.findall(r"\S+", text)) + len(re.findall(r"[,.!?;:()\"'-]", text))


count_tokens = estimate_tokens


@dataclass
class ChatMessage:
    """One message in a conversation (role + content + optional name)."""

    role: str  # system | user | assistant | tool
    content: str = ""
    name: str = ""
    tool_calls: Sequence[Mapping[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            data["name"] = self.name
        if self.tool_calls:
            data["tool_calls"] = list(self.tool_calls)
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChatMessage":
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            name=str(data.get("name", "")),
            tool_calls=list(data.get("tool_calls") or ()),
            tool_call_id=str(data.get("tool_call_id", "")),
        )


@dataclass
class LLMRequest:
    """Normalized request to any language model."""

    messages: Sequence[ChatMessage] = field(default_factory=list)
    system: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    json_mode: bool = False
    tools: Sequence[Mapping[str, Any]] = field(default_factory=list)
    stop: Sequence[str] = field(default_factory=list)
    stream: bool = False
    timeout: float = 60.0
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def build(cls, prompt: str, **overrides: Any) -> "LLMRequest":
        return cls(messages=[ChatMessage(role="user", content=prompt)], **overrides)


@dataclass
class LLMResult:
    """Normalized completion output."""

    text: str = ""
    json_data: Any = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: AIUsage = field(default_factory=AIUsage)
    request_id: str = ""
    model: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "json_data": self.json_data,
            "tool_calls": list(self.tool_calls),
            "finish_reason": self.finish_reason,
            "usage": self.usage.as_dict(),
            "request_id": self.request_id,
            "model": self.model,
        }


class LLMClient(BaseAIModel):
    """Base class for any language-model provider client.

    Subclasses implement :meth:`_complete` (sync) and may override
    :meth:`_stream_chunks`. :meth:`execute` handles validation, JSON mode,
    tool-call extraction, usage accounting and error translation.
    """

    capability = "llm"

    def __init__(self, *, model: str = "local", logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"

    # -- provider hooks ------------------------------------------------------ #

    def _complete(self, request: LLMRequest) -> LLMResult:
        raise NotImplementedError

    def _stream_chunks(self, request: LLMRequest) -> Iterable[str]:
        result = self._complete(request)
        yield result.text

    # -- contract ------------------------------------------------------------ #

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        if not isinstance(request, LLMRequest):
            raise AIValidationError("expected LLMRequest", provider=self.provider)
        if not request.messages and not request.system:
            raise AIValidationError("request has no messages", provider=self.provider)
        try:
            result = self._complete(request)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc

        usage = result.usage or AIUsage()
        if request.json_mode and result.json_data is None:
            try:
                result.json_data = json.loads(result.text)
            except json.JSONDecodeError:
                pass
        return self.normalize(
            True,
            data=result.as_dict(),
            request_id=request.request_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=usage,
            model=self._model,
            finish_reason=result.finish_reason,
        )

    def stream(self, request: LLMRequest) -> Iterable[Dict[str, Any]]:
        if not isinstance(request, LLMRequest):
            raise AIValidationError("expected LLMRequest", provider=self.provider)
        for chunk in self._stream_chunks(request):
            yield {"type": "delta", "text": chunk, "model": self._model}


class LocalLLM(LLMClient):
    """
    Deterministic stdlib-only LLM used for offline mode and tests.

    Produces a faithful, rule-based completion:

    * echoes the last user message with a short template response;
    * JSON mode returns ``{"answer": <text>}``;
    * tool calling returns a canned ``tool_calls`` entry when a tool named
      ``calculator`` is declared;
    * ``count_tokens`` drives usage accounting.
    """

    provider = "local"

    def _complete(self, request: LLMRequest) -> LLMResult:
        last_user = ""
        for message in reversed(list(request.messages)):
            if message.role == "user":
                last_user = message.content
                break
        prompt = last_user or normalize_text(request.system)

        tool_calls: List[Dict[str, Any]] = []
        if request.tools:
            for tool in request.tools:
                if str(tool.get("name", "")).lower() in ("calculator", "math"):
                    tool_calls.append(
                        {"id": f"call_{uuid.uuid4().hex[:8]}", "name": tool.get("name"), "arguments": {}}
                    )

        if request.json_mode:
            text = json.dumps({"answer": prompt}, ensure_ascii=False)
            finish = "stop"
        elif tool_calls:
            text = ""
            finish = "tool_calls"
        else:
            text = f"{prompt}\n\n[local-llm] deterministic completion"
            finish = "stop"

        prompt_tokens = estimate_tokens(" ".join(m.content for m in request.messages))
        completion_tokens = estimate_tokens(text)
        usage = AIUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
        return LLMResult(
            text=text,
            json_data=json.loads(text) if request.json_mode else None,
            tool_calls=tool_calls,
            finish_reason=finish,
            usage=usage,
            request_id=request.request_id,
            model=self._model,
        )