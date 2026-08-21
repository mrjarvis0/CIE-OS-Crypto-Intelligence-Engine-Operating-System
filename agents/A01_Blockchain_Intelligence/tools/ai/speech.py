"""
Tools :: AI :: Speech
=====================

Speech intelligence: speech-to-text, text-to-speech, voice activity
detection and speaker hints.

Provider-agnostic: real speech models plug in behind :class:`SpeechModel`.
:class:`LocalSpeech` provides deterministic stdlib-only implementations:
energy-based VAD on raw PCM frames, a stub transcriber and a WAV
synthesizer (sine-wave beeps via the :mod:`wave` module) so the capability
works offline and in tests.

:class:`OpenAISpeech` is the hosted implementation: multipart upload for
speech-to-text, a binary response for text-to-speech. Voice activity
detection stays local -- it is arithmetic over PCM frames, and shipping audio
to a datacentre to compute an RMS would be slower, dearer and no more correct.
"""

from __future__ import annotations

import io
import math
import struct
import time
import uuid
import wave
from dataclasses import dataclass, field
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
from .providers import HTTPTransport, model_for, register_provider, resolve_api_key

__all__ = [
    "SpeechRequest",
    "SpeechResult",
    "SpeechModel",
    "LocalSpeech",
    "OpenAISpeech",
    "energy_of",
    "pcm_energy",
]


def pcm_energy(frames: bytes, *, sample_width: int = 2) -> float:
    """RMS energy of little-endian PCM frames (0.0 for empty input)."""
    if not frames or sample_width <= 0:
        return 0.0
    count = len(frames) // sample_width
    if count == 0:
        return 0.0
    code = "h" if sample_width == 2 else "b" if sample_width == 1 else "i"
    fmt = "<" + code * count
    total = 0.0
    samples = struct.unpack(fmt, frames[: count * sample_width])
    for sample in samples:
        total += float(sample) * float(sample)
    return math.sqrt(total / count) / 32768.0 if sample_width == 2 else math.sqrt(total / count)


energy_of = pcm_energy


@dataclass
class SpeechRequest:
    """One speech operation request."""

    mode: str = "stt"           # stt | tts | vad | speaker
    audio: Any = None           # bytes (wav/pcm) or file path for stt/vad
    text: str = ""              # text for tts
    sample_rate: int = 16000
    sample_width: int = 2
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class SpeechResult:
    """Normalized speech output."""

    transcript: str = ""
    audio: bytes = b""          # synthesized wav bytes (tts)
    activity: bool = False      # vad
    segments: List[Mapping[str, Any]] = field(default_factory=list)
    speakers: List[str] = field(default_factory=list)
    request_id: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "transcript": self.transcript,
            "audio_bytes": len(self.audio),
            "activity": self.activity,
            "segments": list(self.segments),
            "speakers": list(self.speakers),
            "request_id": self.request_id,
        }


def _pcm_frames(data: bytes) -> bytes:
    """
    The PCM payload, with a RIFF container stripped when there is one.

    ``SpeechRequest.audio`` accepts "wav/pcm", and measuring a wav *file* byte
    for byte measures its 44-byte header as though it were signal. The header
    is text and length fields -- ``RIFF``, ``WAVE``, ``fmt ``, ``data`` -- so
    it is loud: a file of pure digital silence reads as energy 0.05 against a
    0.02 activity threshold, and voice detection fires on silence.
    """
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            return handle.readframes(handle.getnframes())
    except (wave.Error, EOFError):
        # Not a container this build can parse; the raw bytes are the best
        # available answer, and refusing here would lose a usable signal.
        return data


def _read_source(request: SpeechRequest) -> bytes:
    """The audio exactly as given: bytes, a file path, or a readable stream.

    No container is stripped here. An upload must carry its header -- a
    transcription endpoint identifies the codec from it, and headerless PCM is
    rejected as an unrecognized format.
    """
    audio = request.audio
    if isinstance(audio, (bytes, bytearray)):
        return bytes(audio)
    if isinstance(audio, memoryview):
        return audio.tobytes()
    if isinstance(audio, str):
        with open(audio, "rb") as handle:
            return handle.read()
    if hasattr(audio, "read"):
        return audio.read()
    return b""


def _read_audio(request: SpeechRequest) -> bytes:
    """The PCM signal, with any container header removed (for analysis)."""
    return _pcm_frames(_read_source(request))


class SpeechModel(BaseAIModel):
    """Base class for speech providers."""

    capability = "speech"

    def __init__(self, *, model: str = "local", logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"

    def _handle(self, request: SpeechRequest) -> SpeechResult:
        raise NotImplementedError

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        if isinstance(request, SpeechRequest):
            req = request
        else:
            params = getattr(request, "params", None) or {}
            req = SpeechRequest(
                mode=str(params.get("mode", "stt")),
                audio=params.get("audio"),
                text=str(params.get("text", "")),
                request_id=getattr(request, "request_id", ""),
            )
        try:
            result = self._handle(req)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc
        return self.normalize(
            True,
            data=result.as_dict(),
            request_id=req.request_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(prompt_tokens=len(req.text.split()) if req.mode == "tts" else 0),
            mode=req.mode,
        )


class LocalSpeech(SpeechModel):
    """Stdlib-only speech capability: energy VAD, beep TTS, stub STT."""

    provider = "local"

    def _handle(self, request: SpeechRequest) -> SpeechResult:
        mode = request.mode
        if mode == "vad":
            frames = _read_audio(request)
            rms = pcm_energy(frames, sample_width=request.sample_width)
            active = rms > 0.02
            return SpeechResult(
                activity=active,
                segments=[{"start": 0, "end": len(frames) // (request.sample_width * 2) if active else 0, "active": active}],
                request_id=request.request_id,
            )
        if mode == "stt":
            frames = _read_audio(request)
            rms = pcm_energy(frames, sample_width=request.sample_width)
            transcript = "[silence]" if rms < 0.02 else "[audio detected - local stub, no speech model]"
            return SpeechResult(transcript=transcript, activity=rms >= 0.02, request_id=request.request_id)
        if mode == "tts":
            return SpeechResult(audio=self._synthesize(request.text, request.sample_rate), request_id=request.request_id)
        if mode == "speaker":
            return SpeechResult(speakers=["speaker-0"], request_id=request.request_id)
        raise AIValidationError(f"unknown speech mode {mode!r}", provider=self.provider)

    @staticmethod
    def _synthesize(text: str, sample_rate: int = 16000) -> bytes:
        """Deterministic WAV synthesis: a tone whose pitch follows the text length."""
        buffer = io.BytesIO()
        duration = max(0.2, min(2.0, len(text) * 0.05))
        freq = 220.0 + (len(text) % 24) * 20.0
        total = int(sample_rate * duration)
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            frames = bytearray()
            for index in range(total):
                value = int(12000 * math.sin(2.0 * math.pi * freq * index / sample_rate))
                frames += struct.pack("<h", value)
            wav.writeframes(bytes(frames))
        return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Remote providers
# --------------------------------------------------------------------------- #

#: Sniffed container -> upload filename. Transcription endpoints read the codec
#: from the extension as well as the bytes, and reject what they cannot name.
AUDIO_EXTENSIONS: Mapping[str, str] = {
    b"RIFF": "wav",
    b"OggS": "ogg",
    b"fLaC": "flac",
    b"\x1aE\xdf\xa3": "webm",
    b"ID3": "mp3",
}


def sniff_audio_format(data: bytes) -> str:
    """Best-effort container detection for an audio upload."""
    for magic, extension in AUDIO_EXTENSIONS.items():
        if data[: len(magic)] == magic:
            return extension
    if data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3":
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    return "wav"


class OpenAISpeech(SpeechModel):
    """OpenAI speech: ``/v1/audio/transcriptions`` and ``/v1/audio/speech``.

    The same wire format is served by several gateways (Groq, Azure, local
    proxies), so ``base_url`` is enough to point this at one of them.

    Two models are in play -- one transcribes, one synthesizes -- so ``model``
    names the transcription model and ``tts_model`` the synthesis one, rather
    than pretending a single id covers both directions.
    """

    provider = "openai"
    capability = "speech"
    base_url = "https://api.openai.com"
    transcription_path = "/v1/audio/transcriptions"
    speech_path = "/v1/audio/speech"
    default_model = "whisper-1"
    default_tts_model = "tts-1"
    requires_key = True

    def __init__(
        self,
        *,
        model: str = "",
        tts_model: str = "",
        voice: str = "alloy",
        audio_format: str = "wav",
        language: str = "",
        api_key: Optional[str] = None,
        base_url: str = "",
        timeout: float = 120.0,
        max_retries: int = 2,
        transport: Optional[HTTPTransport] = None,
        headers: Optional[Mapping[str, str]] = None,
        logger: Any = None,
    ) -> None:
        super().__init__(
            model=model or model_for(self.capability, self.provider, self.default_model),
            logger=logger,
        )
        self.tts_model = tts_model or self.default_tts_model
        self.voice = voice
        self.audio_format = audio_format
        self.language = language
        self.api_key = resolve_api_key(self.provider, api_key, required=self.requires_key)
        self.timeout = float(timeout)
        self.extra_headers = dict(headers or {})
        self._local = LocalSpeech()
        self.transport = transport or HTTPTransport(
            base_url or self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", **self.extra_headers},
            timeout=timeout,
            max_retries=max_retries,
            provider=self.provider,
        )

    def _handle(self, request: SpeechRequest) -> SpeechResult:
        if request.mode == "stt":
            return self._transcribe(request)
        if request.mode == "tts":
            return self._synthesize(request)
        if request.mode == "vad":
            # Arithmetic over PCM frames; no round trip earns its latency here.
            return self._local._handle(request)
        raise AIValidationError(
            f"{self.provider} speech does not support mode {request.mode!r}",
            provider=self.provider,
            model=self._model,
        )

    def _transcribe(self, request: SpeechRequest) -> SpeechResult:
        audio = _read_source(request)
        if not audio:
            raise AIValidationError("no audio to transcribe", provider=self.provider)

        extension = sniff_audio_format(audio)
        fields = {"model": self._model, "response_format": "json"}
        if self.language:
            fields["language"] = self.language

        data = self.transport.post_multipart(
            self.transcription_path,
            fields=fields,
            files={"file": (f"audio.{extension}", audio, f"audio/{extension}")},
            timeout=request_timeout(request, self.timeout),
            model=self._model,
        )
        if not isinstance(data, Mapping):
            raise AIExecutionError(
                "transcription endpoint returned a non-JSON body",
                provider=self.provider,
                model=self._model,
            )
        transcript = str(data.get("text", ""))
        return SpeechResult(
            transcript=transcript,
            activity=bool(transcript.strip()),
            segments=[
                segment for segment in (data.get("segments") or []) if isinstance(segment, Mapping)
            ],
            request_id=request.request_id,
        )

    def _synthesize(self, request: SpeechRequest) -> SpeechResult:
        if not request.text.strip():
            raise AIValidationError("no text to synthesize", provider=self.provider)
        audio = self.transport.post_bytes(
            self.speech_path,
            {
                "model": self.tts_model,
                "input": request.text,
                "voice": self.voice,
                "response_format": self.audio_format,
            },
            timeout=request_timeout(request, self.timeout),
            model=self.tts_model,
        )
        if not audio:
            raise AIExecutionError(
                "speech endpoint returned no audio", provider=self.provider, model=self.tts_model
            )
        return SpeechResult(audio=audio, request_id=request.request_id)


def request_timeout(request: SpeechRequest, default: float) -> float:
    """Audio calls are slow; a per-request timeout overrides the client one."""
    return float(getattr(request, "timeout", 0.0) or default)


register_provider("speech", "local", LocalSpeech, requires_key=False,
                  replace_existing=True, description="Offline VAD, beep TTS, stub STT")
register_provider("speech", "openai", OpenAISpeech, replace_existing=True,
                  description="OpenAI transcription and text-to-speech")
