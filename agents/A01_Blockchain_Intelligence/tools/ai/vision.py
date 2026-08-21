"""
Tools :: AI :: Vision
=====================

Image understanding: OCR, object detection, scene/diagram/chart analysis and
document understanding.

Provider-agnostic: real vision models plug in behind :class:`VisionModel`;
:class:`LocalVision` provides a deterministic stdlib-only analyzer that
extracts image metadata (format sniffing, dimensions from headers where
possible) and returns a structured analysis payload, so the capability is
exercisable offline.

:class:`LLMVision` is the working implementation: it drives *any* multimodal
language model registered in the layer, because every one of them takes the
same thing -- an image and a question -- and the differences between their
content-block formats are already handled by the LLM providers. A dedicated
``AnthropicVision`` and ``OpenAIVision`` would be the same class twice with a
different image serializer, and the serializer is not this module's problem.
"""

from __future__ import annotations

import io
import re
import struct
import time
import uuid
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
from .providers import create_provider, register_provider

__all__ = [
    "VisionRequest",
    "VisionResult",
    "VisionModel",
    "LocalVision",
    "LLMVision",
    "sniff_image_format",
    "sniff_dimensions",
    "media_type_for",
]


def sniff_image_format(data: bytes) -> str:
    """Detect image format from magic bytes (stdlib only)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] in (b"BM",):
        return "bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] in (b"\xff\xd8",):
        return "jpeg"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    if data[:4] == b"II*\x00" or data[:4] == b"MM\x00*":
        return "tiff"
    return "unknown"


def sniff_dimensions(data: bytes, fmt: str) -> tuple:
    """Best-effort dimension extraction from image headers."""
    try:
        if fmt == "png" and len(data) >= 24:
            return struct.unpack(">II", data[16:24])
        if fmt == "gif" and len(data) >= 10:
            return struct.unpack("<HH", data[6:10])
        if fmt == "bmp" and len(data) >= 26:
            width, height = struct.unpack("<ii", data[18:26])
            return width, height
        if fmt == "jpeg" and len(data) >= 4:
            offset = 2
            while offset < min(len(data) - 1, 2048):
                if data[offset] != 0xFF:
                    offset += 1
                    continue
                marker = data[offset + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
                    return width, height
                length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
                offset += 2 + length
    except (struct.error, IndexError):
        pass
    return (0, 0)


@dataclass
class VisionRequest:
    """One vision inference request."""

    image: Any = None          # bytes | file-path | data-url
    prompt: str = "describe this image"
    tasks: Sequence[str] = field(default_factory=lambda: ("analysis",))
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class VisionResult:
    """Structured vision output."""

    analysis: Mapping[str, Any] = field(default_factory=dict)
    ocr_text: str = ""
    objects: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    format: str = ""
    dimensions: tuple = (0, 0)
    request_id: str = ""

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "analysis": dict(self.analysis),
            "ocr_text": self.ocr_text,
            "objects": list(self.objects),
            "labels": list(self.labels),
            "format": self.format,
            "dimensions": list(self.dimensions),
            "request_id": self.request_id,
        }


def _as_bytes(image: Any) -> bytes:
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    if isinstance(image, memoryview):
        return image.tobytes()
    if isinstance(image, str):
        if image.startswith("data:"):
            import base64

            _, _, payload = image.partition(",")
            return base64.b64decode(payload)
        with open(image, "rb") as handle:  # file path
            return handle.read()
    if hasattr(image, "read"):
        return image.read()
    raise AIValidationError(f"unsupported image input: {type(image).__name__}")


class VisionModel(BaseAIModel):
    """Base class for vision providers."""

    capability = "vision"

    def __init__(self, *, model: str = "local", logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"

    def _analyze(self, request: VisionRequest, data: bytes) -> VisionResult:
        raise NotImplementedError

    def analyze(self, request: VisionRequest) -> VisionResult:
        data = _as_bytes(request.image)
        return self._analyze(request, data)

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        if isinstance(request, VisionRequest):
            req = request
        else:
            params = getattr(request, "params", None) or {}
            req = VisionRequest(image=params.get("image"), prompt=str(params.get("prompt", "describe this image")), request_id=getattr(request, "request_id", ""))
        try:
            result = self.analyze(req)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc
        return self.normalize(
            True,
            data=result.as_dict(),
            request_id=req.request_id,
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(prompt_tokens=len(req.prompt.split())),
            tasks=list(req.tasks),
        )


class LocalVision(VisionModel):
    """Deterministic metadata-based image analyzer (no external deps)."""

    provider = "local"

    def _analyze(self, request: VisionRequest, data: bytes) -> VisionResult:
        fmt = sniff_image_format(data)
        width, height = sniff_dimensions(data, fmt)
        prompt_lower = request.prompt.lower()
        analysis: Dict[str, Any] = {
            "format": fmt,
            "size_bytes": len(data),
            "dimensions": (width, height),
            "note": "deterministic local analysis (no model inference)",
        }
        objects: List[str] = []
        labels: List[str] = []
        if fmt == "unknown":
            labels.append("unrecognized_image")
            analysis["confidence"] = 0.0
        else:
            labels.append(fmt)
            if width and height:
                if width >= height:
                    labels.append("landscape")
                else:
                    labels.append("portrait")
            objects.append("canvas" if fmt == "png" else fmt)
            analysis["confidence"] = 0.6
        if "chart" in prompt_lower or "graph" in prompt_lower:
            labels.append("chart_candidate")
        if "wallet" in prompt_lower or "screenshot" in prompt_lower:
            labels.append("ui_screenshot")
        return VisionResult(
            analysis=analysis,
            objects=objects,
            labels=labels,
            format=fmt,
            dimensions=(width, height),
            request_id=request.request_id,
        )


# --------------------------------------------------------------------------- #
# Model-backed vision
# --------------------------------------------------------------------------- #

#: Sniffed format -> IANA media type. Providers reject an image whose declared
#: type does not match its bytes, so the type is read from the bytes.
MEDIA_TYPES: Mapping[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "ico": "image/x-icon",
}

VISION_SYSTEM = (
    "You analyse images. Reply with JSON only, in the form "
    '{"description": "<what the image shows>", "ocr_text": "<all text in the '
    'image, verbatim, or an empty string>", "objects": ["<object>"], '
    '"labels": ["<short label>"]}.'
)


def media_type_for(data: bytes) -> str:
    """The media type for image bytes, from their magic number."""
    return MEDIA_TYPES.get(sniff_image_format(data), "application/octet-stream")


class LLMVision(VisionModel):
    """Image understanding through any multimodal language model.

    The image goes to the model as an attachment on a normal chat message and
    comes back as a JSON analysis. Format and dimensions are still read from
    the bytes locally: they are facts about the file, and asking a model to
    guess what ``struct.unpack`` can read is slower and worse.

    ``provider`` reports the language model's own provider so the response is
    attributed to the vendor that did the work.
    """

    provider = "llm"

    def __init__(self, client: Any = None, *, logger: Any = None) -> None:
        self.client = client if client is not None else create_provider("llm")
        super().__init__(model=self.client.model, logger=logger)
        self.provider = self.client.provider

    def _analyze(self, request: VisionRequest, data: bytes) -> VisionResult:
        from .llm import ChatMessage, ImagePart, LLMRequest  # local import

        if not data:
            raise AIValidationError("no image data to analyse", provider=self.provider)

        fmt = sniff_image_format(data)
        width, height = sniff_dimensions(data, fmt)
        tasks = [str(task) for task in (request.tasks or ())]
        prompt = request.prompt or "describe this image"
        if "ocr" in tasks:
            prompt += "\nTranscribe every piece of text visible in the image."

        response = self.client.execute(
            LLMRequest(
                messages=[
                    ChatMessage(
                        role="user",
                        content=prompt,
                        images=[ImagePart(data=data, media_type=media_type_for(data))],
                    )
                ],
                system=VISION_SYSTEM,
                temperature=0.0,
                max_tokens=2048,
                json_mode=True,
            )
        )

        payload = (response.data or {}).get("json_data")
        if not isinstance(payload, Mapping):
            raise AIExecutionError(
                "vision model did not return a structured analysis",
                provider=self.provider,
                model=self._model,
            )

        analysis: Dict[str, Any] = {
            "description": str(payload.get("description", "")),
            "format": fmt,
            "size_bytes": len(data),
            "dimensions": (width, height),
            "model": self._model,
            "tasks": tasks,
        }
        return VisionResult(
            analysis=analysis,
            ocr_text=str(payload.get("ocr_text", "") or ""),
            objects=[str(item) for item in (payload.get("objects") or [])],
            labels=[str(item) for item in (payload.get("labels") or [])],
            format=fmt,
            dimensions=(width, height),
            request_id=request.request_id,
        )


register_provider("vision", "local", LocalVision, requires_key=False,
                  replace_existing=True, description="Offline image metadata analysis")
register_provider("vision", "llm", LLMVision, requires_key=False,
                  replace_existing=True, description="Analyse with the configured multimodal LLM")
