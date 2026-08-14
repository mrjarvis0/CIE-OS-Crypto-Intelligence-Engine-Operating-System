"""
Tools :: AI :: Embedding
========================

Generate dense vector embeddings for memory, RAG, vector search, semantic
similarity and clustering.

Supports batching, caching, L2 normalization and provider abstraction.
:class:`LocalEmbedder` produces deterministic stdlib-only vectors (sha256
feature hashing) so the layer runs offline; providers plug in behind the
same :class:`Embedder` interface.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence

from ..utils.cache import TTLCache
from . import AIError, AIUsage, AIValidationError, AIResponse, BaseAIModel

__all__ = ["EmbeddingResult", "Embedder", "LocalEmbedder", "cosine_similarity", "normalize_vector", "l2_norm"]


@dataclass
class EmbeddingResult:
    """One embedding vector with provenance."""

    vector: List[float]
    text: str = ""
    model: str = ""
    dim: int = 0

    def as_dict(self) -> Mapping[str, Any]:
        return {"vector": list(self.vector), "text": self.text, "model": self.model, "dim": self.dim}


def l2_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(v) ** 2 for v in vector)) or 1.0


def normalize_vector(vector: Sequence[float]) -> List[float]:
    """L2-normalize in place of copy; zero vectors stay zero."""
    norm = l2_norm(vector)
    if norm == 0.0:
        return [0.0] * len(vector)
    return [float(v) / norm for v in vector]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 for mismatched/empty vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (l2_norm(a) * l2_norm(b))


class Embedder(BaseAIModel):
    """Base class for embedding providers."""

    capability = "embedding"

    def __init__(self, *, model: str = "local", dim: int = 384, use_cache: bool = True, logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"
        self._dim = dim
        self._cache: Optional[TTLCache[str, List[float]]] = TTLCache(default_ttl=3600.0, maxsize=4096) if use_cache else None

    def _embed_one(self, text: str) -> List[float]:
        raise NotImplementedError

    def embed(self, text: str) -> List[float]:
        """Embed a single text (cached, normalized)."""
        if not text:
            raise AIValidationError("empty text cannot be embedded", provider=self.provider)
        if self._cache is not None:
            hit = self._cache.get(text)
            if hit is not None:
                return list(hit)
        vector = normalize_vector(self._embed_one(text))
        if self._cache is not None:
            self._cache.set(text, vector)
        return vector

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        return [self.embed(text) for text in texts]

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        params = getattr(request, "params", None) or {}
        texts = params.get("texts") if isinstance(params, Mapping) else None
        if texts is None:
            texts = [str(getattr(request, "data", "") or "")]
        if not texts:
            raise AIValidationError("no texts to embed", provider=self.provider)
        try:
            vectors = self.embed_batch(list(texts))
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            from . import AIExecutionError

            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc
        return self.normalize(
            True,
            data={"vectors": [EmbeddingResult(v, t, self._model, self._dim).as_dict() for v, t in zip(vectors, texts)]},
            request_id=getattr(request, "request_id", ""),
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(prompt_tokens=sum(len(t.split()) for t in texts)),
        )


class LocalEmbedder(Embedder):
    """
    Deterministic feature-hashed embedder (stdlib only).

    Splits text into word features and hashes each into a sparse-indexed
    vector before L2 normalization. Semantically similar texts (shared words)
    yield similar vectors, which is enough for offline tests and fallback.
    """

    provider = "local"

    def _embed_one(self, text: str) -> List[float]:
        vector = [0.0] * self._dim
        for token in re.findall(r"[a-z0-9_]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return vector