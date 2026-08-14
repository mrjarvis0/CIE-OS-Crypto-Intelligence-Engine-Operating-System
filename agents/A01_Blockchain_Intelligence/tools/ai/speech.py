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

from . import AIUsage, AIValidationError, AIResponse, BaseAIModel

__all__ = ["SpeechRequest", "SpeechResult", "SpeechModel", "LocalSpeech", "energy_of", "pcm_energy"]


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


def _read_audio(request: SpeechRequest) -> bytes:
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
            from . import AIExecutionError

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