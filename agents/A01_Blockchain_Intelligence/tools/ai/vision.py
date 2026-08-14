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
"""

from __future__ import annotations

import io
import re
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from . import AIUsage, AIValidationError, AIResponse, BaseAIModel

__all__ = ["VisionRequest", "VisionResult", "VisionModel", "LocalVision", "sniff_image_format"]


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
            from . import AIExecutionError

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