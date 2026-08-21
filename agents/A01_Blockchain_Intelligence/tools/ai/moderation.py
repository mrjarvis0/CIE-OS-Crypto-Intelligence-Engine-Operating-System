"""
Tools :: AI :: Moderation
=========================

AI safety: toxicity detection, PII detection, jailbreak detection, prompt
safety, output filtering and policy enforcement.

Provider-agnostic: real moderation models plug in behind :class:`Moderator`.
:class:`LocalModeration` provides deterministic pattern-based checks
(keyword lists, regexes for PII, jailbreak phrase patterns) so the
capability runs fully offline; providers may override each check.

Shipped providers: :class:`OpenAIModeration` (the hosted classifier) and
:class:`LLMModeration` (any registered language model as the judge).

A hosted classifier answers about *content* -- toxicity, hate, sexual,
violence -- and says nothing about PII, jailbreaks or prompt injection, which
are the three this agent most needs to catch. Remote providers therefore keep
running the local patterns for those flags and merge both verdicts, so no
enabled flag is silently left unchecked.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import (
    AIError,
    AIExecutionError,
    AIRequest,
    AIResponse,
    AIUsage,
    AIValidationError,
    BaseAIModel,
)
from .providers import (
    HTTPTransport,
    create_provider,
    model_for,
    register_provider,
    resolve_api_key,
)

__all__ = [
    "ModerationRequest",
    "ModerationResult",
    "Moderator",
    "LocalModeration",
    "RemoteModeration",
    "OpenAIModeration",
    "LLMModeration",
    "FLAGS",
    "REASONS",
]


FLAGS = ("toxic", "hate", "sexual", "violence", "pii", "jailbreak", "malware", "prompt_injection")
REASONS = (
    "toxic language",
    "hate speech",
    "sexual content",
    "violence",
    "pii exposure",
    "jailbreak attempt",
    "malware instruction",
    "prompt injection",
)

# Deterministic keyword / pattern catalog (offline, conservative).
_TOXIC_WORDS = ("stupid", "idiot", "hate you", "shut up", "loser", "scumbag", "trash")
_HATE_WORDS = ("kill all", "exterminate", "die you", "hate group")
_SEXUAL_WORDS = ("nsfw", "explicit sex", "porn")
_VIOLENCE_WORDS = ("kill yourself", "bomb recipe", "make a bomb", "knife attack", "shooting plan")
_MALWARE_WORDS = ("ransomware", "keylogger", "cryptojacker", "steal credentials", "spyware", "exploit kit")
_JAILBREAK_PATTERNS = (
    r"\bignore (all |your |previous )?(instructions|prompts)\b",
    r"\byou are now (a |an )?[\w\s]{1,20}without (rules|limitations|restrictions)\b",
    r"\b(dan mode|developer mode|do anything now|free from jail)\b",
    r"\bbypass (the |its )?(safety|guardrails|content policy)\b",
    r"\bpretend to be (another )?(ai|model|assistant|chatbot)\b",
)
_PII_PATTERNS = {
    "email": r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
    "phone": r"(\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]?){13,16}\b",
    "crypto_address": r"\b(1|3|bc1|0x)[A-Za-z0-9]{25,}\b",
}
_PROMPT_INJECTION_PATTERNS = (
    r"\b(ignore|disregard) (the )?(above|previous|prior) (instructions|context|prompt)\b",
    r"\b(reveal|show|print|output) (your|the) (system prompt|instructions|hidden prompt)\b",
    r"\bact as (a )?different (ai|model|assistant) now\b",
    r"\b(simulate|pretend) (the )?chatbot (without|no) restrictions\b",
)


@dataclass
class ModerationRequest:
    """One moderation check request."""

    text: str = ""
    flags: Sequence[str] = field(default_factory=lambda: FLAGS)
    policy: str = "default"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class ModerationResult:
    """Normalized moderation verdict."""

    flagged: bool = False
    flags_hit: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    filtered: bool = False
    request_id: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "flagged": self.flagged,
            "flags_hit": list(self.flags_hit),
            "reasons": list(self.reasons),
            "scores": dict(self.scores),
            "filtered": self.filtered,
            "request_id": self.request_id,
        }


class Moderator(BaseAIModel):
    """Base class for moderation providers."""

    capability = "moderation"

    def __init__(self, *, model: str = "local", logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"

    def _check(self, request: ModerationRequest) -> ModerationResult:
        raise NotImplementedError

    def moderate(self, request: ModerationRequest) -> ModerationResult:
        if not request.text.strip():
            raise AIValidationError("empty text cannot be moderated", provider=self.provider)
        return self._check(request)

    def sanitize(self, text: str, *, redact: bool = True) -> str:
        """Return a policy-safe version of the text (may redact PII)."""
        result = self.moderate(ModerationRequest(text=text))
        safe = text
        if redact and "pii" in result.flags_hit:
            for kind, pattern in _PII_PATTERNS.items():
                safe = re.sub(pattern, f"[{kind}-redacted]", safe)
        return safe if not result.flagged else safe

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        if isinstance(request, ModerationRequest):
            req = request
        else:
            params = getattr(request, "params", None) or {}
            req = ModerationRequest(
                text=str(params.get("text", "")),
                policy=str(params.get("policy", "default")),
                request_id=getattr(request, "request_id", ""),
            )
        try:
            result = self.moderate(req)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc
        return self.normalize(
            True,
            data=result.as_dict(),
            request_id=req.request_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(prompt_tokens=len(req.text.split())),
            policy=req.policy,
        )


class LocalModeration(Moderator):
    """Deterministic pattern-based moderation (fully offline)."""

    provider = "local"

    def _check(self, request: ModerationRequest) -> ModerationResult:
        text_lower = request.text.lower()
        text = request.text
        flags_hit: List[str] = []
        reasons: List[str] = []
        scores: Dict[str, float] = {}
        enabled = set(request.flags) or set(FLAGS)

        def _flag(kind: str, reason: str, score: float) -> None:
            flags_hit.append(kind)
            reasons.append(reason)
            scores[kind] = max(scores.get(kind, 0.0), score)

        if "toxic" in enabled and any(word in text_lower for word in _TOXIC_WORDS):
            _flag("toxic", "toxic language", 0.8)
        if "hate" in enabled and any(word in text_lower for word in _HATE_WORDS):
            _flag("hate", "hate speech", 0.9)
        if "sexual" in enabled and any(word in text_lower for word in _SEXUAL_WORDS):
            _flag("sexual", "sexual content", 0.9)
        if "violence" in enabled and any(word in text_lower for word in _VIOLENCE_WORDS):
            _flag("violence", "violence", 0.9)
        if "malware" in enabled and any(word in text_lower for word in _MALWARE_WORDS):
            _flag("malware", "malware instruction", 0.95)
        if "jailbreak" in enabled:
            for pattern in _JAILBREAK_PATTERNS:
                if re.search(pattern, text_lower):
                    _flag("jailbreak", "jailbreak attempt", 0.9)
                    break
        if "prompt_injection" in enabled:
            for pattern in _PROMPT_INJECTION_PATTERNS:
                if re.search(pattern, text_lower):
                    _flag("prompt_injection", "prompt injection", 0.85)
                    break
        if "pii" in enabled:
            for kind, pattern in _PII_PATTERNS.items():
                if re.search(pattern, text):
                    _flag("pii", "pii exposure", 0.7)
                    break

        return ModerationResult(
            flagged=bool(flags_hit),
            flags_hit=flags_hit,
            reasons=reasons,
            scores=scores,
            filtered=bool(flags_hit),
            request_id=request.request_id,
        )


# --------------------------------------------------------------------------- #
# Remote providers
# --------------------------------------------------------------------------- #


def merge_results(*results: ModerationResult) -> ModerationResult:
    """Combine verdicts: any flag anywhere flags, and the highest score wins."""
    flags_hit: List[str] = []
    reasons: List[str] = []
    scores: Dict[str, float] = {}
    request_id = ""
    # Not recomputed from flags_hit: a provider can flag something this layer
    # has no flag name for, and re-deriving the verdict would clear it.
    flagged = False

    for result in results:
        request_id = request_id or result.request_id
        flagged = flagged or result.flagged
        for flag in result.flags_hit:
            if flag not in flags_hit:
                flags_hit.append(flag)
        for reason in result.reasons:
            if reason not in reasons:
                reasons.append(reason)
        for name, score in result.scores.items():
            scores[name] = max(scores.get(name, 0.0), float(score))

    return ModerationResult(
        flagged=flagged,
        flags_hit=flags_hit,
        reasons=reasons,
        scores=scores,
        filtered=flagged,
        request_id=request_id,
    )


class RemoteModeration(Moderator):
    """Base class for hosted moderation providers.

    ``local_flags`` names the checks the vendor does not perform. Those are run
    from :class:`LocalModeration` and merged in, so enabling a flag always
    means it was actually checked by something.
    """

    provider = "remote"
    base_url = ""
    moderation_path = ""
    default_model = ""
    requires_key = True
    local_flags: Sequence[str] = ("pii", "jailbreak", "prompt_injection")

    def __init__(
        self,
        *,
        model: str = "",
        api_key: Optional[str] = None,
        base_url: str = "",
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: Optional[HTTPTransport] = None,
        headers: Optional[Mapping[str, str]] = None,
        logger: Any = None,
    ) -> None:
        resolved = model or model_for(self.capability, self.provider, self.default_model)
        if not resolved:
            raise AIValidationError(
                f"{self.provider} needs an explicit moderation model",
                provider=self.provider,
            )
        super().__init__(model=resolved, logger=logger)
        self.api_key = resolve_api_key(self.provider, api_key, required=self.requires_key)
        self.timeout = float(timeout)
        self.extra_headers = dict(headers or {})
        self._local = LocalModeration()
        self.transport = transport or HTTPTransport(
            base_url or self.base_url,
            headers={**self.auth_headers(), **self.extra_headers},
            timeout=timeout,
            max_retries=max_retries,
            provider=self.provider,
        )

    # -- provider hooks ------------------------------------------------------ #

    def auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def _payload(self, request: ModerationRequest) -> Dict[str, Any]:
        raise NotImplementedError

    def _verdict(self, data: Mapping[str, Any], request: ModerationRequest) -> ModerationResult:
        raise NotImplementedError

    # -- contract ------------------------------------------------------------ #

    def _check(self, request: ModerationRequest) -> ModerationResult:
        data = self.transport.post_json(
            self.moderation_path,
            self._payload(request),
            timeout=self.timeout,
            model=self._model,
        )
        remote = self._verdict(data, request)

        enabled = set(request.flags or FLAGS)
        pending = [flag for flag in self.local_flags if flag in enabled]
        if not pending:
            return remote
        local = self._local.moderate(replace(request, flags=tuple(pending)))
        return merge_results(remote, local)


#: OpenAI category -> the layer's flag vocabulary. Categories the layer has no
#: flag for are still reported (as a reason and a score under the vendor's own
#: name) rather than dropped, so a flagged result is never silently narrowed.
OPENAI_CATEGORY_FLAGS: Mapping[str, str] = {
    "harassment": "toxic",
    "harassment/threatening": "toxic",
    "hate": "hate",
    "hate/threatening": "hate",
    "sexual": "sexual",
    "sexual/minors": "sexual",
    "violence": "violence",
    "violence/graphic": "violence",
    "self-harm": "violence",
    "self-harm/intent": "violence",
    "self-harm/instructions": "violence",
    "illicit/violent": "violence",
}


class OpenAIModeration(RemoteModeration):
    """OpenAI ``/v1/moderations`` classifier, plus the local pattern checks."""

    provider = "openai"
    base_url = "https://api.openai.com"
    moderation_path = "/v1/moderations"
    default_model = "omni-moderation-latest"

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    def _payload(self, request: ModerationRequest) -> Dict[str, Any]:
        return {"model": self._model, "input": request.text}

    def _verdict(self, data: Mapping[str, Any], request: ModerationRequest) -> ModerationResult:
        results = data.get("results") or []
        first = results[0] if results and isinstance(results[0], Mapping) else {}
        categories = first.get("categories") or {}
        category_scores = first.get("category_scores") or {}
        enabled = set(request.flags or FLAGS)

        flags_hit: List[str] = []
        reasons: List[str] = []
        scores: Dict[str, float] = {}

        for name, hit in categories.items():
            score = float(category_scores.get(name, 0.0) or 0.0)
            scores[str(name)] = score
            if not hit:
                continue
            flag = OPENAI_CATEGORY_FLAGS.get(str(name))
            if flag is None:
                reasons.append(f"provider category: {name}")
                continue
            if flag not in enabled:
                continue
            if flag not in flags_hit:
                flags_hit.append(flag)
                reasons.append(REASONS[FLAGS.index(flag)])
            scores[flag] = max(scores.get(flag, 0.0), score)

        flagged = bool(flags_hit) or bool(reasons)
        return ModerationResult(
            flagged=flagged,
            flags_hit=flags_hit,
            reasons=reasons,
            scores=scores,
            filtered=flagged,
            request_id=request.request_id,
        )


MODERATION_SYSTEM = (
    "You are a content-safety classifier. Judge the text against the requested "
    "flags only. Reply with JSON only, in the form "
    '{"flags": [{"flag": "<one of the requested flags>", "score": <0..1>, '
    '"reason": "<short reason>"}]} '
    "and return an empty list when nothing applies."
)


class LLMModeration(Moderator):
    """Moderate with a language model instead of a dedicated classifier.

    Useful where policy is bespoke enough that a fixed category list does not
    express it. ``provider`` reports the language model's own provider so the
    verdict is attributed to the vendor that produced it.
    """

    provider = "llm"

    def __init__(self, client: Any = None, *, logger: Any = None) -> None:
        self.client = client if client is not None else create_provider("llm")
        super().__init__(model=self.client.model, logger=logger)
        self.provider = self.client.provider

    def _check(self, request: ModerationRequest) -> ModerationResult:
        from .llm import ChatMessage, LLMRequest  # local import: llm may import us

        enabled = [flag for flag in (request.flags or FLAGS) if flag in FLAGS]
        prompt = (
            f"Requested flags: {', '.join(enabled)}\n"
            f"Policy: {request.policy}\n\n"
            f"Text:\n{request.text}"
        )
        response = self.client.execute(
            LLMRequest(
                messages=[ChatMessage(role="user", content=prompt)],
                system=MODERATION_SYSTEM,
                temperature=0.0,
                max_tokens=512,
                json_mode=True,
            )
        )
        payload = (response.data or {}).get("json_data")
        rows = payload.get("flags") if isinstance(payload, Mapping) else payload
        if not isinstance(rows, (list, tuple)):
            raise AIExecutionError(
                "moderation model did not return a flag list",
                provider=self.provider,
                model=self._model,
            )

        flags_hit: List[str] = []
        reasons: List[str] = []
        scores: Dict[str, float] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            flag = str(row.get("flag", "")).strip().lower()
            if flag not in enabled:
                continue
            if flag not in flags_hit:
                flags_hit.append(flag)
                reasons.append(str(row.get("reason") or REASONS[FLAGS.index(flag)]))
            score = max(0.0, min(1.0, float(row.get("score", 1.0) or 0.0)))
            scores[flag] = max(scores.get(flag, 0.0), score)

        return ModerationResult(
            flagged=bool(flags_hit),
            flags_hit=flags_hit,
            reasons=reasons,
            scores=scores,
            filtered=bool(flags_hit),
            request_id=request.request_id,
        )


register_provider("moderation", "local", LocalModeration, requires_key=False,
                  replace_existing=True, description="Offline pattern-based safety checks")
register_provider("moderation", "openai", OpenAIModeration, replace_existing=True,
                  description="OpenAI moderation classifier + local patterns")
register_provider("moderation", "llm", LLMModeration, requires_key=False,
                  replace_existing=True, description="Moderate with the configured LLM")
