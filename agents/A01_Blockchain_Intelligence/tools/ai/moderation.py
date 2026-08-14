"""
Tools :: AI :: Moderation
=========================

AI safety: toxicity detection, PII detection, jailbreak detection, prompt
safety, output filtering and policy enforcement.

Provider-agnostic: real moderation models plug in behind :class:`Moderator`.
:class:`LocalModeration` provides deterministic pattern-based checks
(keyword lists, regexes for PII, jailbreak phrase patterns) so the
capability runs fully offline; providers may override each check.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import AIUsage, AIValidationError, AIResponse, BaseAIModel

__all__ = ["ModerationRequest", "ModerationResult", "Moderator", "LocalModeration", "FLAGS", "REASONS"]


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
            from . import AIExecutionError

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