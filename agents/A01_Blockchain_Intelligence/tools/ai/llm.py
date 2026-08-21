"""
Tools :: AI :: LLM
==================

Unified interface for all language models.

Supports chat completion, multi-turn conversation, tool calling, JSON mode,
structured output and streaming. Provider-specific SDKs plug in behind
:class:`LLMClient`; a deterministic, stdlib-only :class:`LocalLLM` is shipped
so the layer works with zero external dependencies (used for tests, fallback
and offline mode).

Shipped providers:

* :class:`AnthropicLLM` -- the Messages API (tool use, SSE streaming).
* :class:`OpenAILLM` -- Chat Completions, and :class:`OpenAICompatibleLLM`
  for the several vendors that speak the same wire format
  (:class:`DeepSeekLLM`, :class:`MistralLLM`, :class:`GrokLLM`).
* :class:`OllamaLLM` -- a local model daemon (JSON-lines streaming, no key).
* :class:`LocalLLM` -- deterministic, offline, no network at all.

A provider translates *only* between :class:`LLMRequest`/:class:`LLMResult`
and one vendor's wire format. Everything shared -- credentials, HTTP, retries,
error translation, cost -- lives in :mod:`~.providers`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import (
    AIError,
    AIRequest,
    AIExecutionError,
    AITimeoutError,
    AIUsage,
    AIValidationError,
    AIResponse,
    BaseAIModel,
    normalize_text,
)
from .providers import (
    HTTPTransport,
    estimate_cost,
    model_for,
    register_provider,
    resolve_api_key,
)

__all__ = [
    "ChatMessage",
    "ImagePart",
    "LLMRequest",
    "LLMResult",
    "LLMClient",
    "LocalLLM",
    "RemoteLLM",
    "AnthropicLLM",
    "OpenAICompatibleLLM",
    "OpenAILLM",
    "DeepSeekLLM",
    "MistralLLM",
    "GrokLLM",
    "OllamaLLM",
    "count_tokens",
    "estimate_tokens",
    "loads_lenient",
]


def estimate_tokens(text: str) -> int:
    """Heuristic token count: words + punctuation runs (no tokenizer dep)."""
    if not text:
        return 0
    return len(re.findall(r"\S+", text)) + len(re.findall(r"[,.!?;:()\"'-]", text))


count_tokens = estimate_tokens


def loads_lenient(text: str) -> Any:
    """Parse JSON that a model wrapped in prose or a fenced code block.

    Asking for JSON is not the same as getting only JSON: models routinely
    answer with a ```json fence, or a sentence before the object. The strict
    parse is tried first and the salvage only runs when it fails, so a clean
    answer is never reinterpreted.
    """
    if not text:
        raise ValueError("no text to parse")
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in text")
    return json.loads(text[start : end + 1])


@dataclass
class ImagePart:
    """One image attached to a chat message.

    Carries either raw ``data`` or a remote ``url``; every provider serializes
    it into its own content-block shape. Keeping the payload provider-neutral
    is what lets :mod:`~.vision` drive any multimodal model without knowing
    which one it got.
    """

    data: bytes = b""
    url: str = ""
    media_type: str = "image/png"

    def __post_init__(self) -> None:
        if not self.data and not self.url:
            raise AIValidationError("an image needs either data or a url")

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def as_data_url(self) -> str:
        return self.url or f"data:{self.media_type};base64,{self.base64}"

    def as_dict(self) -> Dict[str, Any]:
        # Deliberately not the payload: a base64 image in a log or a repr is
        # megabytes of noise around the one fact worth recording.
        return {"media_type": self.media_type, "url": self.url, "bytes": len(self.data)}


@dataclass
class ChatMessage:
    """One message in a conversation (role + content + optional attachments)."""

    role: str  # system | user | assistant | tool
    content: str = ""
    name: str = ""
    tool_calls: Sequence[Mapping[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""
    images: Sequence[ImagePart] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            data["name"] = self.name
        if self.tool_calls:
            data["tool_calls"] = list(self.tool_calls)
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.images:
            data["images"] = [image.as_dict() for image in self.images]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChatMessage":
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            name=str(data.get("name", "")),
            tool_calls=list(data.get("tool_calls") or ()),
            tool_call_id=str(data.get("tool_call_id", "")),
            images=[_coerce_image(item) for item in (data.get("images") or ())],
        )


def _coerce_image(item: Any) -> ImagePart:
    """Accept an :class:`ImagePart`, or the plain mapping a caller sent instead."""
    if isinstance(item, ImagePart):
        return item
    if isinstance(item, Mapping):
        raw = item.get("data")
        payload = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw or b"")
        return ImagePart(
            data=payload,
            url=str(item.get("url", "")),
            media_type=str(item.get("media_type", "image/png")),
        )
    raise AIValidationError(f"unsupported image entry: {type(item).__name__}")


@dataclass
class LLMRequest:
    """Normalized request to any language model."""

    messages: Sequence[ChatMessage] = field(default_factory=list)
    system: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024
    json_mode: bool = False
    tools: Sequence[Mapping[str, Any]] = field(default_factory=list)
    tool_choice: str = ""
    stop: Sequence[str] = field(default_factory=list)
    stream: bool = False
    timeout: float = 60.0
    #: Provider-specific passthrough (``thinking``, ``effort``, ``top_p``, ...).
    #: Merged into the request body last, so a caller can reach a vendor
    #: feature the unified request has no field for without a new provider.
    params: Mapping[str, Any] = field(default_factory=dict)
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
                result.json_data = loads_lenient(result.text)
            except (ValueError, TypeError):
                # JSON mode is a request, not a guarantee. The text is still
                # the answer; a caller that needs the object checks json_data.
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


# --------------------------------------------------------------------------- #
# Remote providers
# --------------------------------------------------------------------------- #
# Every provider below is the same three functions -- build a body, read a
# body, read a stream delta -- over the shared transport. Anything a second
# provider would also need belongs in RemoteLLM, not in a provider.

#: Normalized finish reasons. Providers disagree on the vocabulary for the same
#: event ("end_turn" / "stop" / "STOP"), and a caller that branches on it should
#: not have to know which provider answered.
FINISH_REASONS: Mapping[str, str] = {
    "end_turn": "stop",
    "stop": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "length": "length",
    "tool_use": "tool_calls",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "refusal": "refusal",
    "content_filter": "filtered",
    "pause_turn": "pause",
}

JSON_MODE_INSTRUCTION = "Respond with a single valid JSON value and nothing else."


def normalize_finish_reason(value: Any) -> str:
    """Map a provider finish reason onto the layer's vocabulary."""
    return FINISH_REASONS.get(str(value or "").lower(), str(value or "stop"))


class RemoteLLM(LLMClient):
    """Base class for HTTP language-model providers.

    Subclasses supply :meth:`auth_headers`, :meth:`_payload`, :meth:`_parse`
    and (for streaming) :meth:`_delta_text`. Credentials, transport, retries,
    error translation, usage and cost are handled here once.
    """

    provider = "remote"
    base_url = ""
    completions_path = ""
    default_model = ""
    requires_key = True

    def __init__(
        self,
        *,
        model: str = "",
        api_key: Optional[str] = None,
        base_url: str = "",
        timeout: float = 60.0,
        max_retries: int = 2,
        transport: Optional[HTTPTransport] = None,
        headers: Optional[Mapping[str, str]] = None,
        logger: Any = None,
    ) -> None:
        resolved = model or model_for(self.capability, self.provider, self.default_model)
        if not resolved:
            raise AIValidationError(
                f"{self.provider} needs an explicit model id "
                f"(pass model=..., or set A01_AI_LLM_MODEL)",
                provider=self.provider,
            )
        super().__init__(model=resolved, logger=logger)
        self.api_key = resolve_api_key(self.provider, api_key, required=self.requires_key)
        self.timeout = float(timeout)
        self.extra_headers = dict(headers or {})
        self.transport = transport or HTTPTransport(
            base_url or self.resolve_base_url(),
            headers={**self.auth_headers(), **self.extra_headers},
            timeout=timeout,
            max_retries=max_retries,
            provider=self.provider,
        )

    # -- provider hooks ------------------------------------------------------ #

    @classmethod
    def resolve_base_url(cls) -> str:
        return cls.base_url

    def auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def _payload(self, request: LLMRequest, *, stream: bool = False) -> Dict[str, Any]:
        raise NotImplementedError

    def _parse(self, data: Mapping[str, Any], request: LLMRequest) -> LLMResult:
        raise NotImplementedError

    def _delta_text(self, event: Mapping[str, Any]) -> str:
        return ""

    # -- contract ------------------------------------------------------------ #

    def _complete(self, request: LLMRequest) -> LLMResult:
        data = self.transport.post_json(
            self.completions_path,
            self._payload(request),
            timeout=request.timeout,
            model=self._model,
        )
        return self._parse(data, request)

    def _stream_chunks(self, request: LLMRequest) -> Iterable[str]:
        events = self.transport.stream_sse(
            self.completions_path,
            self._payload(request, stream=True),
            timeout=request.timeout,
            model=self._model,
        )
        for event in events:
            if not isinstance(event, Mapping):
                continue
            text = self._delta_text(event)
            if text:
                yield text

    # -- helpers ------------------------------------------------------------- #

    def _usage(self, prompt_tokens: int, completion_tokens: int) -> AIUsage:
        """Token accounting plus a list-price cost estimate for this model."""
        return AIUsage(
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=int(prompt_tokens) + int(completion_tokens),
            cost=estimate_cost(self.provider, self._model, prompt_tokens, completion_tokens),
        )

    def _system_text(self, request: LLMRequest, extra: Sequence[str] = ()) -> str:
        """The system prompt: the request's, plus any per-provider additions."""
        parts = [part for part in ([request.system] + list(extra)) if part]
        if request.json_mode:
            parts.append(JSON_MODE_INSTRUCTION)
        return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #

ANTHROPIC_API_VERSION = "2023-06-01"

#: Model families that removed the sampling parameters. Sending ``temperature``
#: to one of these is a 400 from the API, not a quietly ignored field, so the
#: unified request's temperature is dropped rather than forwarded.
NO_SAMPLING_PREFIXES: Tuple[str, ...] = (
    "claude-fable-",
    "claude-mythos-",
    "claude-opus-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
)


class AnthropicLLM(RemoteLLM):
    """Anthropic Messages API client (tool use, vision, SSE streaming)."""

    provider = "anthropic"
    base_url = "https://api.anthropic.com"
    completions_path = "/v1/messages"
    default_model = "claude-opus-5"
    api_version = ANTHROPIC_API_VERSION

    def auth_headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
            "content-type": "application/json",
        }

    def accepts_sampling(self) -> bool:
        """Whether this model still takes ``temperature``/``top_p``/``top_k``."""
        return not self._model.startswith(NO_SAMPLING_PREFIXES)

    def _payload(self, request: LLMRequest, *, stream: bool = False) -> Dict[str, Any]:
        system, messages = self._conversation(request)
        if not messages:
            raise AIValidationError(
                "anthropic requires at least one user or assistant message",
                provider=self.provider,
                model=self._model,
            )
        payload: Dict[str, Any] = {
            "model": self._model,
            "max_tokens": int(request.max_tokens),
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if request.stop:
            payload["stop_sequences"] = list(request.stop)
        if request.tools:
            payload["tools"] = [self._tool(tool) for tool in request.tools]
        if request.tool_choice:
            payload["tool_choice"] = self._tool_choice(request.tool_choice)
        if self.accepts_sampling():
            payload["temperature"] = float(request.temperature)
        if stream:
            payload["stream"] = True
        payload.update(dict(request.params))
        return payload

    def _conversation(self, request: LLMRequest) -> Tuple[str, List[Dict[str, Any]]]:
        """Split the unified conversation into Anthropic's system + messages."""
        extra_system: List[str] = []
        messages: List[Dict[str, Any]] = []

        for message in request.messages:
            if message.role == "system":
                extra_system.append(message.content)
                continue
            if message.role == "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
                continue

            blocks: List[Dict[str, Any]] = [self._image_block(img) for img in message.images]
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                        "name": str(call.get("name", "")),
                        "input": dict(call.get("arguments") or {}),
                    }
                )
            if not blocks:
                continue
            role = "assistant" if message.role == "assistant" else "user"
            messages.append({"role": role, "content": blocks})

        return self._system_text(request, extra_system), messages

    @staticmethod
    def _image_block(image: ImagePart) -> Dict[str, Any]:
        if image.url:
            return {"type": "image", "source": {"type": "url", "url": image.url}}
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type,
                "data": image.base64,
            },
        }

    @staticmethod
    def _tool(tool: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "name": str(tool.get("name", "")),
            "description": str(tool.get("description", "")),
            "input_schema": dict(
                tool.get("input_schema") or tool.get("parameters") or {"type": "object"}
            ),
        }

    @staticmethod
    def _tool_choice(choice: str) -> Dict[str, Any]:
        if choice in ("auto", "any", "none"):
            return {"type": choice}
        return {"type": "tool", "name": choice}

    def _parse(self, data: Mapping[str, Any], request: LLMRequest) -> LLMResult:
        blocks = [block for block in (data.get("content") or []) if isinstance(block, Mapping)]
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tool_calls = [
            {
                "id": str(b.get("id", "")),
                "name": str(b.get("name", "")),
                "arguments": dict(b.get("input") or {}),
            }
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        # Cached input is billed at a different rate than fresh input; it is
        # counted here as input because the token count must stay true. The
        # cost estimate uses the base rate and so reads high on a cached call.
        prompt_tokens = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        )
        return LLMResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=normalize_finish_reason(data.get("stop_reason")),
            usage=self._usage(prompt_tokens, int(usage.get("output_tokens", 0) or 0)),
            request_id=request.request_id,
            model=str(data.get("model") or self._model),
        )

    def _delta_text(self, event: Mapping[str, Any]) -> str:
        if event.get("type") != "content_block_delta":
            return ""
        delta = event.get("delta") or {}
        if isinstance(delta, Mapping) and delta.get("type") == "text_delta":
            return str(delta.get("text", ""))
        return ""


# --------------------------------------------------------------------------- #
# OpenAI and the vendors that speak its wire format
# --------------------------------------------------------------------------- #


class OpenAICompatibleLLM(RemoteLLM):
    """Chat Completions client.

    OpenAI's request shape is the de-facto second standard: DeepSeek, Mistral,
    Grok, Groq, Together and most self-hosted gateways accept it unchanged.
    Subclasses only change the endpoint, the credential and the default model.
    """

    provider = "openai"
    base_url = "https://api.openai.com"
    completions_path = "/v1/chat/completions"
    default_model = "gpt-4.1-mini"

    #: Newer OpenAI models renamed this field; the vendors that copied the API
    #: mostly did not. It stays configurable rather than sniffed from the model
    #: id, which would guess wrong for every gateway that proxies both.
    max_tokens_field = "max_tokens"

    def __init__(self, *, max_tokens_field: str = "", **options: Any) -> None:
        super().__init__(**options)
        if max_tokens_field:
            self.max_tokens_field = max_tokens_field

    def auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }

    def _payload(self, request: LLMRequest, *, stream: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(request),
            self.max_tokens_field: int(request.max_tokens),
            "temperature": float(request.temperature),
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [self._tool(tool) for tool in request.tools]
        if request.tool_choice:
            payload["tool_choice"] = self._tool_choice(request.tool_choice)
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        payload.update(dict(request.params))
        return payload

    def _messages(self, request: LLMRequest) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        system = self._system_text(request)
        if system:
            messages.append({"role": "system", "content": system})

        for message in request.messages:
            if message.role == "system":
                messages.append({"role": "system", "content": message.content})
                continue
            if message.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
                continue

            entry: Dict[str, Any] = {"role": message.role}
            if message.images:
                parts: List[Dict[str, Any]] = []
                if message.content:
                    parts.append({"type": "text", "text": message.content})
                for image in message.images:
                    parts.append(
                        {"type": "image_url", "image_url": {"url": image.as_data_url()}}
                    )
                entry["content"] = parts
            else:
                entry["content"] = message.content
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                        "type": "function",
                        "function": {
                            "name": str(call.get("name", "")),
                            "arguments": json.dumps(dict(call.get("arguments") or {})),
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(entry)

        return messages

    @staticmethod
    def _tool(tool: Mapping[str, Any]) -> Dict[str, Any]:
        if tool.get("type") == "function" and "function" in tool:
            return dict(tool)
        return {
            "type": "function",
            "function": {
                "name": str(tool.get("name", "")),
                "description": str(tool.get("description", "")),
                "parameters": dict(
                    tool.get("parameters") or tool.get("input_schema") or {"type": "object"}
                ),
            },
        }

    @staticmethod
    def _tool_choice(choice: str) -> Any:
        if choice in ("auto", "none", "required"):
            return choice
        return {"type": "function", "function": {"name": choice}}

    def _parse(self, data: Mapping[str, Any], request: LLMRequest) -> LLMResult:
        choices = data.get("choices") or []
        first = choices[0] if choices and isinstance(choices[0], Mapping) else {}
        message = first.get("message") or {}
        content = message.get("content")
        text = content if isinstance(content, str) else _join_parts(content)

        tool_calls: List[Dict[str, Any]] = []
        for call in message.get("tool_calls") or []:
            if not isinstance(call, Mapping):
                continue
            function = call.get("function") or {}
            tool_calls.append(
                {
                    "id": str(call.get("id", "")),
                    "name": str(function.get("name", "")),
                    "arguments": _decode_arguments(function.get("arguments")),
                }
            )

        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=normalize_finish_reason(first.get("finish_reason")),
            usage=self._usage(
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
            ),
            request_id=request.request_id,
            model=str(data.get("model") or self._model),
        )

    def _delta_text(self, event: Mapping[str, Any]) -> str:
        choices = event.get("choices") or []
        if not choices or not isinstance(choices[0], Mapping):
            return ""
        delta = choices[0].get("delta") or {}
        return str(delta.get("content") or "") if isinstance(delta, Mapping) else ""


def _join_parts(content: Any) -> str:
    """Flatten a multi-part content array into text."""
    if not isinstance(content, (list, tuple)):
        return ""
    return "".join(
        str(part.get("text", "")) for part in content if isinstance(part, Mapping)
    )


def _decode_arguments(raw: Any) -> Dict[str, Any]:
    """Tool arguments arrive as a JSON *string*; keep the raw text if invalid.

    A malformed argument object is the model's mistake, not the transport's;
    dropping it would leave a tool call with no inputs and no explanation.
    """
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        decoded = loads_lenient(str(raw))
    except (ValueError, TypeError):
        return {"_raw": str(raw)}
    return decoded if isinstance(decoded, dict) else {"_raw": str(raw)}


class OpenAILLM(OpenAICompatibleLLM):
    """OpenAI Chat Completions."""

    provider = "openai"


class DeepSeekLLM(OpenAICompatibleLLM):
    """DeepSeek (OpenAI-compatible)."""

    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    default_model = "deepseek-chat"


class MistralLLM(OpenAICompatibleLLM):
    """Mistral (OpenAI-compatible)."""

    provider = "mistral"
    base_url = "https://api.mistral.ai"
    default_model = "mistral-large-latest"


class GrokLLM(OpenAICompatibleLLM):
    """xAI Grok (OpenAI-compatible).

    No default model: xAI's ids move faster than this file does, and a stale
    default fails at the far end with a message about a model the operator
    never chose.
    """

    provider = "grok"
    base_url = "https://api.x.ai"
    default_model = ""


# --------------------------------------------------------------------------- #
# Ollama (local daemon)
# --------------------------------------------------------------------------- #


class OllamaLLM(RemoteLLM):
    """Local Ollama daemon: no credential, newline-delimited JSON streaming."""

    provider = "ollama"
    base_url = "http://localhost:11434"
    completions_path = "/api/chat"
    default_model = ""
    requires_key = False

    @classmethod
    def resolve_base_url(cls) -> str:
        host = os.environ.get("OLLAMA_HOST") or cls.base_url
        return host if "://" in host else f"http://{host}"

    def auth_headers(self) -> Dict[str, str]:
        return {"content-type": "application/json"}

    def _payload(self, request: LLMRequest, *, stream: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(request),
            "stream": bool(stream),
            "options": {
                "temperature": float(request.temperature),
                "num_predict": int(request.max_tokens),
            },
        }
        if request.stop:
            payload["options"]["stop"] = list(request.stop)
        if request.json_mode:
            payload["format"] = "json"
        if request.tools:
            payload["tools"] = [OpenAICompatibleLLM._tool(tool) for tool in request.tools]
        payload.update(dict(request.params))
        return payload

    def _messages(self, request: LLMRequest) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        system = self._system_text(request)
        if system:
            messages.append({"role": "system", "content": system})
        for message in request.messages:
            entry: Dict[str, Any] = {
                "role": "user" if message.role == "tool" else message.role,
                "content": message.content,
            }
            if message.images:
                entry["images"] = [image.base64 for image in message.images if image.data]
            messages.append(entry)
        return messages

    def _parse(self, data: Mapping[str, Any], request: LLMRequest) -> LLMResult:
        message = data.get("message") or {}
        tool_calls = [
            {
                "id": str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                "name": str((call.get("function") or {}).get("name", "")),
                "arguments": _decode_arguments((call.get("function") or {}).get("arguments")),
            }
            for call in (message.get("tool_calls") or [])
            if isinstance(call, Mapping)
        ]
        finish = "tool_calls" if tool_calls else normalize_finish_reason(
            data.get("done_reason") or "stop"
        )
        return LLMResult(
            text=str(message.get("content", "")),
            tool_calls=tool_calls,
            finish_reason=finish,
            usage=self._usage(
                int(data.get("prompt_eval_count", 0) or 0),
                int(data.get("eval_count", 0) or 0),
            ),
            request_id=request.request_id,
            model=str(data.get("model") or self._model),
        )

    def _stream_chunks(self, request: LLMRequest) -> Iterable[str]:
        events = self.transport.stream_json_lines(
            self.completions_path,
            self._payload(request, stream=True),
            timeout=request.timeout,
            model=self._model,
        )
        for event in events:
            if not isinstance(event, Mapping):
                continue
            text = str((event.get("message") or {}).get("content", ""))
            if text:
                yield text


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

register_provider("llm", "local", LocalLLM, requires_key=False, replace_existing=True,
                  description="Deterministic offline completions (no network)")
register_provider("llm", "anthropic", AnthropicLLM, replace_existing=True,
                  description="Anthropic Messages API")
register_provider("llm", "openai", OpenAILLM, replace_existing=True,
                  description="OpenAI Chat Completions")
register_provider("llm", "deepseek", DeepSeekLLM, replace_existing=True,
                  description="DeepSeek (OpenAI-compatible)")
register_provider("llm", "mistral", MistralLLM, replace_existing=True,
                  description="Mistral (OpenAI-compatible)")
register_provider("llm", "grok", GrokLLM, replace_existing=True,
                  description="xAI Grok (OpenAI-compatible)")
register_provider("llm", "ollama", OllamaLLM, requires_key=False, replace_existing=True,
                  description="Local Ollama daemon")
