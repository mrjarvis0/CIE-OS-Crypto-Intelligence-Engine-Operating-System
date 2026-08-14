"""
Tools :: AI :: Translation
==========================

Language translation, language detection and localization.

Provider-agnostic: real translation engines plug in behind :class:`Translator`.
:class:`LocalTranslator` performs stopword-based language detection with a
small built-in phrase dictionary so the capability works offline; providers
with full model coverage are expected to subclass and override
:meth:`_translate_text`/:meth:`_detect`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

from . import AIUsage, AIValidationError, AIResponse, BaseAIModel

__all__ = ["TranslationRequest", "TranslationResult", "Translator", "LocalTranslator", "detect_language", "LANGUAGE_NAMES"]


LANGUAGE_NAMES = {
    "en": "english",
    "es": "spanish",
    "fr": "french",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
    "nl": "dutch",
    "hi": "hindi",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
    "ru": "russian",
    "ar": "arabic",
    "tr": "turkish",
    "pl": "polish",
    "sv": "swedish",
    "da": "danish",
    "fi": "finnish",
    "no": "norwegian",
    "cs": "czech",
}

# Small stopword fingerprints per language for detection.
_STOPWORDS = {
    "en": {"the", "and", "is", "are", "of", "to", "in", "that", "with", "for"},
    "es": {"el", "la", "de", "y", "en", "es", "un", "una", "que", "por"},
    "fr": {"le", "la", "les", "de", "et", "en", "est", "un", "une", "que"},
    "de": {"der", "die", "das", "und", "ist", "mit", "von", "zu", "ein", "eine"},
    "it": {"il", "lo", "la", "di", "e", "è", "che", "un", "una", "per"},
    "pt": {"o", "a", "os", "as", "de", "e", "em", "um", "uma", "que"},
    "nl": {"de", "het", "en", "van", "een", "is", "dat", "met", "voor", "niet"},
    "hi": {"है", "और", "में", "के", "से", "का", "की", "यह", "हैं", "नहीं"},
    "zh": {"的", "了", "是", "在", "和", "有", "不", "我", "他", "这"},
    "ja": {"の", "に", "は", "を", "で", "が", "と", "も", "て", "です"},
    "ko": {"의", "에", "는", "을", "이", "가", "도", "와", "에서", "입니다"},
    "ru": {"и", "в", "на", "не", "что", "с", "по", "как", "это", "я"},
    "ar": {"في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "كان", "أن"},
    "tr": {"ve", "bir", "bu", "ile", "de", "da", "için", "gibi", "çok", "ben"},
    "sv": {"och", "att", "det", "som", "en", "på", "av", "för", "med", "är"},
    "pl": {"i", "w", "na", "z", "do", "się", "to", "nie", "jest", "że"},
    "da": {"og", "at", "det", "som", "en", "på", "af", "for", "med", "er"},
    "fi": {"ja", "on", "se", "että", "ei", "kuin", "sen", "hän", "vielä", "myös"},
    "cs": {"a", "se", "na", "v", "je", "to", "že", "pro", "s", "z"},
    "no": {"og", "at", "det", "som", "en", "på", "av", "for", "med", "er"},
}


def detect_language(text: str, default: str = "en") -> str:
    """Stopword-overlap language detection (best-effort, offline)."""
    words = set(w.lower() for w in text.split())
    best_lang, best_score = default, 0
    for lang, stops in _STOPWORDS.items():
        score = len(words & stops)
        if score > best_score:
            best_lang, best_score = lang, score
    return best_lang


@dataclass
class TranslationRequest:
    """One translation / detection request."""

    text: str = ""
    target_lang: str = "en"
    source_lang: str = ""      # auto-detect when empty
    preserve_terms: Sequence[str] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class TranslationResult:
    """Normalized translation output."""

    translated: str = ""
    source_lang: str = ""
    target_lang: str = ""
    confidence: float = 0.0
    detected_lang: str = ""
    request_id: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "translated": self.translated,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "confidence": self.confidence,
            "detected_lang": self.detected_lang,
            "request_id": self.request_id,
        }


class Translator(BaseAIModel):
    """Base class for translation providers."""

    capability = "translation"

    def __init__(self, *, model: str = "local", logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"

    def _detect(self, text: str) -> str:
        return detect_language(text)

    def _translate_text(self, text: str, source: str, target: str, terms: Sequence[str]) -> str:
        raise NotImplementedError

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not request.text.strip():
            raise AIValidationError("nothing to translate", provider=self.provider)
        source = request.source_lang or self._detect(request.text)
        translated = self._translate_text(request.text, source, request.target_lang, request.preserve_terms)
        return TranslationResult(
            translated=translated,
            source_lang=source,
            target_lang=request.target_lang,
            confidence=0.95,
            detected_lang=source,
            request_id=request.request_id,
        )

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        if isinstance(request, TranslationRequest):
            req = request
        else:
            params = getattr(request, "params", None) or {}
            req = TranslationRequest(
                text=str(params.get("text", "")),
                target_lang=str(params.get("target_lang", "en")),
                source_lang=str(params.get("source_lang", "")),
                request_id=getattr(request, "request_id", ""),
            )
        try:
            result = self.translate(req)
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
        )


class LocalTranslator(Translator):
    """
    Offline translator: detects the language and applies a small built-in
    phrase dictionary; unknown phrases pass through unchanged (provider
    subclasses are expected to perform real translation).
    """

    provider = "local"

    # Phrase dictionary: (source, target, phrase) -> phrase
    _PHRASES = {
        ("en", "es"): {"hello": "hola", "thank you": "gracias", "yes": "sí", "no": "no", "help": "ayuda"},
        ("es", "en"): {"hola": "hello", "gracias": "thank you", "sí": "yes", "ayuda": "help"},
        ("en", "fr"): {"hello": "bonjour", "thank you": "merci", "yes": "oui", "help": "aide"},
        ("fr", "en"): {"bonjour": "hello", "merci": "thank you", "oui": "yes", "aide": "help"},
        ("en", "hi"): {"hello": "नमस्ते", "thank you": "धन्यवाद", "help": "मदद"},
        ("hi", "en"): {"नमस्ते": "hello", "धन्यवाद": "thank you", "मदद": "help"},
        ("en", "zh"): {"hello": "你好", "thank you": "谢谢", "help": "帮助"},
        ("zh", "en"): {"你好": "hello", "谢谢": "thank you", "帮助": "help"},
    }

    def _translate_text(self, text: str, source: str, target: str, terms: Sequence[str]) -> str:
        dictionary = self._PHRASES.get((source, target), {})
        words = text.split()
        translated = [dictionary.get(word.lower(), word) for word in words]
        joined = " ".join(translated)
        for phrase, mapped in dictionary.items():
            if " " in phrase and phrase in joined.lower():
                joined = joined.replace(phrase, mapped)
        return joined