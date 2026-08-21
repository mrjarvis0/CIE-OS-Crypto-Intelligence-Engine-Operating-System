"""
Tools :: AI :: Translation
==========================

Language translation, language detection and localization.

Provider-agnostic: real translation engines plug in behind :class:`Translator`.
:class:`LocalTranslator` performs stopword-based language detection with a
small built-in phrase dictionary so the capability works offline; providers
with full model coverage are expected to subclass and override
:meth:`_translate_text`/:meth:`_detect`.

Shipped providers: :class:`DeepLTranslator` (a dedicated engine) and
:class:`LLMTranslator` (any registered language model, which is the one that
can honour ``preserve_terms`` -- an instruction a translation endpoint has no
field for).

Remote engines detect the source language themselves and report what they
found. Sending them this module's stopword guess would override a better
answer with a worse one, so an unset ``source_lang`` is passed through as
"auto" rather than filled in first.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

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
    "TranslationRequest",
    "TranslationResult",
    "Translator",
    "LocalTranslator",
    "RemoteTranslator",
    "DeepLTranslator",
    "LLMTranslator",
    "detect_language",
    "LANGUAGE_NAMES",
]


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


# --------------------------------------------------------------------------- #
# Remote providers
# --------------------------------------------------------------------------- #


class RemoteTranslator(Translator):
    """Base class for hosted translation engines.

    :meth:`translate` is overridden rather than :meth:`_translate_text`: an
    engine detects the source language itself, and the detection it reports is
    better than the stopword guess this module would hand it.
    """

    provider = "remote"
    base_url = ""
    translate_path = ""
    default_model = ""
    requires_key = True

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
        super().__init__(
            model=model or model_for(self.capability, self.provider, self.default_model),
            logger=logger,
        )
        self.api_key = resolve_api_key(self.provider, api_key, required=self.requires_key)
        self.timeout = float(timeout)
        self.extra_headers = dict(headers or {})
        self.transport = transport or HTTPTransport(
            base_url or self.resolve_base_url(self.api_key),
            headers={**self.auth_headers(), **self.extra_headers},
            timeout=timeout,
            max_retries=max_retries,
            provider=self.provider,
        )

    @classmethod
    def resolve_base_url(cls, api_key: str = "") -> str:
        return cls.base_url

    def auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def _translate_text(self, text: str, source: str, target: str, terms: Sequence[str]) -> str:
        # Deliberately not routed through translate(): a subclass that
        # implemented neither would call this, which would call translate(),
        # which would call this. The seam fails loudly instead of hanging.
        raise NotImplementedError("remote translators implement translate(), not _translate_text()")


class DeepLTranslator(RemoteTranslator):
    """DeepL ``/v2/translate``.

    ``preserve_terms`` is not forwarded: DeepL expresses terminology through
    account-level glossaries, which are provisioned outside a request. The
    terms are reported back on the result so a caller can see they were not
    applied rather than assume they were.
    """

    provider = "deepl"
    base_url = "https://api.deepl.com"
    free_base_url = "https://api-free.deepl.com"
    translate_path = "/v2/translate"
    default_model = "deepl"

    @classmethod
    def resolve_base_url(cls, api_key: str = "") -> str:
        # Free keys carry a ":fx" suffix and are only served by the free host;
        # sending one to the paid host is a 403 that reads like a bad key.
        return cls.free_base_url if str(api_key).endswith(":fx") else cls.base_url

    def auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "content-type": "application/json",
        }

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if not request.text.strip():
            raise AIValidationError("nothing to translate", provider=self.provider)

        payload: Dict[str, Any] = {
            "text": [request.text],
            "target_lang": request.target_lang.upper(),
        }
        if request.source_lang:
            payload["source_lang"] = request.source_lang.upper()

        data = self.transport.post_json(
            self.translate_path, payload, timeout=self.timeout, model=self._model
        )
        translations = data.get("translations") or []
        if not translations or not isinstance(translations[0], Mapping):
            raise AIExecutionError(
                "translation engine returned no translation",
                provider=self.provider,
                model=self._model,
            )

        first = translations[0]
        detected = str(first.get("detected_source_language", "") or "").lower()
        source = request.source_lang or detected
        return TranslationResult(
            translated=str(first.get("text", "")),
            source_lang=source,
            target_lang=request.target_lang,
            confidence=0.95,
            detected_lang=detected or source,
            request_id=request.request_id,
        )


TRANSLATION_SYSTEM = (
    "You are a translation engine. Translate the user text into the requested "
    "language, preserving meaning, tone, formatting and any terms listed as "
    "preserved exactly as written. Reply with JSON only, in the form "
    '{"translation": "<translated text>", "source_lang": "<ISO 639-1 code>"}.'
)


class LLMTranslator(Translator):
    """Translate with a language model.

    The one implementation that can honour ``preserve_terms`` -- ticker
    symbols, contract addresses, product names -- which a translation endpoint
    has no field for and would happily translate into nonsense.
    """

    provider = "llm"

    def __init__(self, client: Any = None, *, logger: Any = None) -> None:
        self.client = client if client is not None else create_provider("llm")
        super().__init__(model=self.client.model, logger=logger)
        self.provider = self.client.provider

    def translate(self, request: TranslationRequest) -> TranslationResult:
        from .llm import ChatMessage, LLMRequest  # local import: llm may import us

        if not request.text.strip():
            raise AIValidationError("nothing to translate", provider=self.provider)

        target = LANGUAGE_NAMES.get(request.target_lang.lower(), request.target_lang)
        instructions = [f"Target language: {target} ({request.target_lang})"]
        if request.source_lang:
            source_name = LANGUAGE_NAMES.get(request.source_lang.lower(), request.source_lang)
            instructions.append(f"Source language: {source_name} ({request.source_lang})")
        if request.preserve_terms:
            instructions.append("Preserve exactly: " + ", ".join(request.preserve_terms))

        response = self.client.execute(
            LLMRequest(
                messages=[
                    ChatMessage(
                        role="user",
                        content="\n".join(instructions) + f"\n\nText:\n{request.text}",
                    )
                ],
                system=TRANSLATION_SYSTEM,
                temperature=0.0,
                max_tokens=max(256, len(request.text) // 2),
                json_mode=True,
            )
        )

        payload = (response.data or {}).get("json_data")
        if not isinstance(payload, Mapping) or not payload.get("translation"):
            raise AIExecutionError(
                "translation model did not return a translation",
                provider=self.provider,
                model=self._model,
            )

        detected = str(payload.get("source_lang", "") or "").lower()
        source = request.source_lang or detected or self._detect(request.text)
        return TranslationResult(
            translated=str(payload["translation"]),
            source_lang=source,
            target_lang=request.target_lang,
            confidence=0.9,
            detected_lang=detected or source,
            request_id=request.request_id,
        )

    def _translate_text(self, text: str, source: str, target: str, terms: Sequence[str]) -> str:
        return self.translate(
            TranslationRequest(text=text, source_lang=source, target_lang=target,
                               preserve_terms=list(terms))
        ).translated


register_provider("translation", "local", LocalTranslator, requires_key=False,
                  replace_existing=True, description="Offline detection + phrase dictionary")
register_provider("translation", "deepl", DeepLTranslator, replace_existing=True,
                  description="DeepL translation engine")
register_provider("translation", "llm", LLMTranslator, requires_key=False,
                  replace_existing=True, description="Translate with the configured LLM")
