"""
Tools :: AI Layer
=================

Model-independent, provider-independent, modality-independent AI interface.

The AI Layer hides every provider (OpenAI, Anthropic, Gemini, Grok, DeepSeek,
Mistral, Ollama, local models, ...) behind a common execution contract. The
Planning Engine never knows which provider handled a request; it only asks
for a capability and receives a normalized :class:`AIResponse`.

This package exposes:

* the canonical :class:`BaseAIModel` contract every capability implements;
* a shared :class:`AIError` hierarchy (mirroring the adapters layer) so
  provider-specific failures never leak into the Planner;
* ready-to-use, stdlib-only *local* implementations for every capability so
  the layer works out of the box and can be swapped for real providers.

Two hard rules:

1. A capability may *raise* :class:`AIError` subclasses; it must never leak a
   provider-native exception to a caller.
2. ``execute()`` returns an :class:`AIResponse`; runtime failures are encoded
   as ``ok=False`` responses with an attached ``error``.

Capabilities (each in its own module):

* :mod:`~.llm` -- chat completions, tool calling, streaming, JSON mode.
* :mod:`~.embedding` -- dense vectors with batching, cache, normalization.
* :mod:`~.reranker` -- retrieve -> score -> re-rank.
* :mod:`~.vision` -- image understanding (OCR, diagrams, charts).
* :mod:`~.speech` -- speech-to-text, text-to-speech, VAD.
* :mod:`~.translation` -- translation, language detection, localization.
* :mod:`~.moderation` -- toxicity / PII / jailbreak detection and filtering.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Mapping, Optional

__all__ = [
    "AIError",
    "AIConnectionError",
    "AIAuthenticationError",
    "AIAuthorizationError",
    "AITimeoutError",
    "AIValidationError",
    "AIExecutionError",
    "AIRetryableError",
    "AIFatalError",
    "AIRequest",
    "AIResponse",
    "AIUsage",
    "AIMetadata",
    "BaseAIModel",
    "normalize_text",
    "ChatMessage",
    "LLMClient",
    "LLMRequest",
    "LLMResult",
    "LocalLLM",
    "Embedder",
    "EmbeddingResult",
    "LocalEmbedder",
    "Moderator",
    "ModerationRequest",
    "ModerationResult",
    "LocalModeration",
    "Reranker",
    "RerankItem",
    "RerankResult",
    "LocalReranker",
    "VisionModel",
    "VisionRequest",
    "VisionResult",
    "LocalVision",
    "SpeechModel",
    "SpeechRequest",
    "SpeechResult",
    "LocalSpeech",
    "Translator",
    "TranslationRequest",
    "TranslationResult",
    "LocalTranslator",
]

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Shared error model
# --------------------------------------------------------------------------- #
# Provider failures are translated into this unified hierarchy so callers in
# the Planner / Executor never depend on underlying vendor SDKs.
#
#   AIError
#   ├── AIConnectionError      provider unreachable / dropped
#   ├── AIAuthenticationError  credentials rejected
#   ├── AIAuthorizationError   authenticated but not permitted
#   ├── AITimeoutError         time budget exceeded
#   ├── AIValidationError      request invalid before inference
#   ├── AIExecutionError       inference ran but failed
#   ├── AIRetryableError       transient; safe to retry
#   └── AIFatalError           non-recoverable; do not retry


class AIError(Exception):
    """Base class for every error raised by the AI layer."""

    def __init__(
        self,
        message: str = "",
        *,
        cause: Optional[BaseException] = None,
        provider: str = "unknown",
        model: str = "",
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.provider = provider
        self.model = model
        self.request_id = request_id

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        prefix = f"[{self.provider}"
        if self.model:
            prefix += f":{self.model}"
        if self.request_id:
            prefix += f":{self.request_id}"
        return f"{prefix}] {self.message}"


class AIConnectionError(AIError):
    """The provider could not be reached or the connection dropped."""


class AIAuthenticationError(AIError):
    """Credentials were rejected by the provider."""


class AIAuthorizationError(AIError):
    """The principal lacks the required permissions on the provider."""


class AITimeoutError(AIError):
    """The request exceeded its configured time budget."""


class AIValidationError(AIError):
    """An incoming request failed local validation before inference."""


class AIExecutionError(AIError):
    """The provider executed the request but the inference failed."""


class AIRetryableError(AIError):
    """A transient failure that is safe to retry."""


class AIFatalError(AIError):
    """A non-recoverable failure; retrying is pointless."""


# --------------------------------------------------------------------------- #
# Request / Response data structures
# --------------------------------------------------------------------------- #


@dataclass
class AIUsage:
    """Token and cost accounting attached to an AI response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    retries: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "retries": self.retries,
        }


@dataclass(frozen=True)
class AIMetadata:
    """Immutable execution metadata attached to every :class:`AIResponse`."""

    provider: str
    model: str
    capability: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.monotonic)
    duration_ms: float = 0.0
    status: str = "success"
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class AIRequest:
    """The canonical normalized request passed to :meth:`BaseAIModel.execute`.

    Capabilities accept their concrete request types (:class:`~.llm.LLMRequest`,
    :class:`~.vision.VisionRequest`, ...) which are structurally compatible;
    ``AIRequest`` is the generic base carrying the common fields: prompt text,
    system context, per-capability ``params``, time budget and correlation id.
    """

    prompt: str = ""
    system: str = ""
    messages: Sequence[Mapping[str, Any]] = field(default_factory=list)
    params: Mapping[str, Any] = field(default_factory=dict)
    timeout: float = 60.0
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "system": self.system,
            "messages": list(self.messages),
            "params": dict(self.params),
            "timeout": self.timeout,
            "request_id": self.request_id,
        }

    @classmethod
    def build(cls, prompt: str, *, system: str = "", **kwargs: Any) -> "AIRequest":
        return cls(prompt=prompt, system=system, **kwargs)


@dataclass
class AIResponse:
    """A normalized, provider-independent inference result.

    ``ok=True`` carries the payload in ``data``; ``ok=False`` carries the
    translated failure in ``error``. ``metadata`` only holds JSON-serializable
    primitives.
    """

    ok: bool
    data: Any = None
    error: Optional[AIError] = None
    metadata: AIMetadata = field(default_factory=lambda: AIMetadata(provider="unknown", model="", capability=""))
    usage: AIUsage = field(default_factory=AIUsage)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": {"code": type(self.error).__name__, "message": str(self.error)} if self.error else None,
            "metadata": dict(self.metadata.details) if self.metadata else {},
            "usage": self.usage.as_dict(),
        }


# --------------------------------------------------------------------------- #
# Base model contract
# --------------------------------------------------------------------------- #


class BaseAIModel(abc.ABC):
    """The canonical contract every AI capability must implement.

    Lifecycle is stateless: ``execute()``/``aexecute()`` per request, optional
    ``stream()``/``astream()`` for streaming providers. Implementations must
    never raise provider-native exceptions; they translate failures into the
    :mod:`AIError` hierarchy and encode runtime failures as ``ok=False``
    :class:`AIResponse` objects.
    """

    provider: str = "base"
    capability: str = "inference"

    def __init__(self, *, logger: Optional[logging.Logger] = None) -> None:
        self.log = logger or logging.getLogger(f"{__name__}.{type(self).__name__}")
        self._model: str = ""

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    @abc.abstractmethod
    def execute(self, request: AIRequest) -> AIResponse:
        """Execute a normalized request and return a normalized response."""
        raise NotImplementedError

    def aexecute(self, request: AIRequest) -> Any:
        """Async variant of :meth:`execute` (runs in a worker thread)."""

        async def _run() -> AIResponse:
            return await asyncio.get_running_loop().run_in_executor(
                None, self.execute, request
            )

        return _run()

    def stream(self, request: AIRequest) -> Any:
        """Iterate over incremental chunks of a response."""
        response = self.execute(request)
        return iter([response])

    def astream(self, request: AIRequest) -> AsyncIterator[Any]:
        async def _iter() -> AsyncIterator[Any]:
            for chunk in self.stream(request):
                yield chunk

        return _iter()

    # -- helpers ------------------------------------------------------------ #

    def normalize(
        self,
        ok: bool,
        data: Any = None,
        error: Optional[AIError] = None,
        *,
        request_id: str = "",
        duration_ms: float = 0.0,
        usage: Optional[AIUsage] = None,
        status: str = "success",
        **details: Any,
    ) -> AIResponse:
        """Build a normalized :class:`AIResponse` with consistent metadata."""
        meta = AIMetadata(
            provider=self.provider,
            model=self._model,
            capability=self.capability,
            request_id=request_id or uuid.uuid4().hex,
            duration_ms=duration_ms,
            status=status,
            details=details,
        )
        return AIResponse(ok=ok, data=data, error=error, metadata=meta, usage=usage or AIUsage())


def normalize_text(value: Any) -> str:
    """Coerce arbitrary input into a cleaned single-line string."""
    if value is None:
        return ""
    return " ".join(str(value).split())


# --------------------------------------------------------------------------- #
# Capabilities
# --------------------------------------------------------------------------- #
# Each capability lives in its own module (llm, embedding, reranker, vision,
# speech, translation, moderation). The concrete local implementations are
# stdlib-only and re-exported here as public API.
# --------------------------------------------------------------------------- #

from .llm import (  # noqa: E402
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResult,
    LocalLLM,
)
from .embedding import (  # noqa: E402
    Embedder,
    EmbeddingResult,
    LocalEmbedder,
)
from .moderation import (  # noqa: E402
    LocalModeration,
    ModerationRequest,
    ModerationResult,
    Moderator,
)
from .reranker import (  # noqa: E402
    LocalReranker,
    RerankItem,
    RerankResult,
    Reranker,
)
from .vision import (  # noqa: E402
    LocalVision,
    VisionModel,
    VisionRequest,
    VisionResult,
)
from .speech import (  # noqa: E402
    LocalSpeech,
    SpeechModel,
    SpeechRequest,
    SpeechResult,
)
from .translation import (  # noqa: E402
    LocalTranslator,
    TranslationRequest,
    TranslationResult,
    Translator,
)