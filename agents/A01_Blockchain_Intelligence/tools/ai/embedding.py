"""
Tools :: AI :: Embedding
========================

Generate dense vector embeddings for memory, RAG, vector search, semantic
similarity and clustering.

Supports batching, caching, L2 normalization and provider abstraction.
:class:`LocalEmbedder` produces deterministic stdlib-only vectors (sha256
feature hashing) so the layer runs offline; providers plug in behind the
same :class:`Embedder` interface.

Shipped providers: :class:`OpenAIEmbedder` (and :class:`VoyageEmbedder`,
which speaks the same shape), :class:`OllamaEmbedder` for a local daemon,
and :class:`LocalEmbedder` for no network at all.

Remote embedders batch: a thousand texts is one request per ``batch_size``
chunk, not a thousand requests. Cache hits are served before the batch is
built, so a re-embed of mostly-seen text sends only what is new.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.cache import TTLCache
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
    estimate_cost,
    model_for,
    register_provider,
    resolve_api_key,
)

__all__ = [
    "EmbeddingResult",
    "Embedder",
    "LocalEmbedder",
    "RemoteEmbedder",
    "OpenAIEmbedder",
    "VoyageEmbedder",
    "OllamaEmbedder",
    "cosine_similarity",
    "normalize_vector",
    "l2_norm",
]


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
            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc
        tokens = sum(len(t.split()) for t in texts)
        return self.normalize(
            True,
            data={"vectors": [EmbeddingResult(v, t, self._model, self._dim).as_dict() for v, t in zip(vectors, texts)]},
            request_id=getattr(request, "request_id", ""),
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(
                prompt_tokens=tokens,
                total_tokens=tokens,
                cost=estimate_cost(self.provider, self._model, tokens, 0),
            ),
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


# --------------------------------------------------------------------------- #
# Remote providers
# --------------------------------------------------------------------------- #


class RemoteEmbedder(Embedder):
    """Base class for HTTP embedding providers.

    Subclasses supply :meth:`auth_headers`, :meth:`_payload` and
    :meth:`_vectors`. The batching, caching and normalization above them is
    shared, because getting it wrong is expensive in exactly the same way for
    every provider: an un-batched re-embed of a corpus is thousands of round
    trips for text the cache already held.
    """

    provider = "remote"
    base_url = ""
    embeddings_path = ""
    default_model = ""
    default_dim = 0
    requires_key = True
    #: Inputs per request. Providers cap this; the chunking is ours either way.
    batch_size = 96

    def __init__(
        self,
        *,
        model: str = "",
        api_key: Optional[str] = None,
        base_url: str = "",
        dim: int = 0,
        use_cache: bool = True,
        timeout: float = 60.0,
        max_retries: int = 2,
        batch_size: int = 0,
        transport: Optional[HTTPTransport] = None,
        headers: Optional[Mapping[str, str]] = None,
        logger: Any = None,
    ) -> None:
        resolved = model or model_for(self.capability, self.provider, self.default_model)
        if not resolved:
            raise AIValidationError(
                f"{self.provider} needs an explicit embedding model "
                f"(pass model=..., or set A01_AI_EMBEDDING_MODEL)",
                provider=self.provider,
            )
        super().__init__(
            model=resolved,
            dim=dim or self.default_dim,
            use_cache=use_cache,
            logger=logger,
        )
        self.api_key = resolve_api_key(self.provider, api_key, required=self.requires_key)
        self.timeout = float(timeout)
        if batch_size:
            self.batch_size = int(batch_size)
        self.extra_headers = dict(headers or {})
        self.transport = transport or HTTPTransport(
            base_url or self.resolve_base_url(),
            headers={**self.auth_headers(), **self.extra_headers},
            timeout=timeout,
            max_retries=max_retries,
            provider=self.provider,
        )

    # -- provider hooks ------------------------------------------------------ #

    @classmethod
    def resolve_base_url(cls) -> str:
        return cls.base_url

    def auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def _payload(self, texts: Sequence[str]) -> Dict[str, Any]:
        raise NotImplementedError

    def _vectors(self, data: Mapping[str, Any], count: int) -> List[List[float]]:
        raise NotImplementedError

    # -- embedding ----------------------------------------------------------- #

    def _embed_many(self, texts: Sequence[str]) -> List[List[float]]:
        """One request per chunk; raw (un-normalized) vectors, input order."""
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            chunk = list(texts[start : start + self.batch_size])
            data = self.transport.post_json(
                self.embeddings_path,
                self._payload(chunk),
                timeout=self.timeout,
                model=self._model,
            )
            batch = self._vectors(data, len(chunk))
            if len(batch) != len(chunk):
                raise AIExecutionError(
                    f"provider returned {len(batch)} vectors for {len(chunk)} inputs",
                    provider=self.provider,
                    model=self._model,
                )
            vectors.extend(batch)
        if vectors and self._dim != len(vectors[0]):
            # The model decides the dimension; the configured one was a guess.
            self._dim = len(vectors[0])
        return vectors

    def _embed_one(self, text: str) -> List[float]:
        return self._embed_many([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed many texts, serving cache hits and batching only the misses."""
        if not texts:
            return []
        for text in texts:
            if not text:
                raise AIValidationError("empty text cannot be embedded", provider=self.provider)

        results: List[Optional[List[float]]] = [None] * len(texts)
        pending: List[str] = []
        positions: Dict[str, List[int]] = {}

        for index, text in enumerate(texts):
            cached = self._cache.get(text) if self._cache is not None else None
            if cached is not None:
                results[index] = list(cached)
                continue
            if text in positions:
                # The same text twice in one batch is one embedding, not two.
                positions[text].append(index)
                continue
            positions[text] = [index]
            pending.append(text)

        if pending:
            for text, vector in zip(pending, self._embed_many(pending)):
                normalized = normalize_vector(vector)
                if self._cache is not None:
                    self._cache.set(text, normalized)
                for index in positions[text]:
                    results[index] = list(normalized)

        return [vector if vector is not None else [] for vector in results]


class OpenAIEmbedder(RemoteEmbedder):
    """OpenAI ``/v1/embeddings`` (also the shape Voyage and most gateways use)."""

    provider = "openai"
    base_url = "https://api.openai.com"
    embeddings_path = "/v1/embeddings"
    default_model = "text-embedding-3-small"
    default_dim = 1536

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    def _payload(self, texts: Sequence[str]) -> Dict[str, Any]:
        return {"model": self._model, "input": list(texts)}

    def _vectors(self, data: Mapping[str, Any], count: int) -> List[List[float]]:
        rows = [row for row in (data.get("data") or []) if isinstance(row, Mapping)]
        # The response carries an index per row and is not required to be in
        # input order; sorting is what keeps vector i attached to text i.
        rows.sort(key=lambda row: int(row.get("index", 0) or 0))
        return [[float(value) for value in (row.get("embedding") or [])] for row in rows]


class VoyageEmbedder(OpenAIEmbedder):
    """Voyage AI embeddings (OpenAI-compatible request and response shape)."""

    provider = "voyage"
    base_url = "https://api.voyageai.com"
    embeddings_path = "/v1/embeddings"
    default_model = "voyage-3"
    default_dim = 1024
    batch_size = 128


class OllamaEmbedder(RemoteEmbedder):
    """Local Ollama daemon (``/api/embed``): no credential, no cost."""

    provider = "ollama"
    base_url = "http://localhost:11434"
    embeddings_path = "/api/embed"
    default_model = ""
    default_dim = 0
    requires_key = False

    @classmethod
    def resolve_base_url(cls) -> str:
        host = os.environ.get("OLLAMA_HOST") or cls.base_url
        return host if "://" in host else f"http://{host}"

    def auth_headers(self) -> Dict[str, str]:
        return {"content-type": "application/json"}

    def _payload(self, texts: Sequence[str]) -> Dict[str, Any]:
        return {"model": self._model, "input": list(texts)}

    def _vectors(self, data: Mapping[str, Any], count: int) -> List[List[float]]:
        rows = data.get("embeddings")
        if rows is None and data.get("embedding") is not None:
            rows = [data.get("embedding")]  # older single-input endpoint shape
        return [[float(value) for value in (row or [])] for row in (rows or [])]


register_provider("embedding", "local", LocalEmbedder, requires_key=False,
                  replace_existing=True, description="Feature-hashed offline vectors")
register_provider("embedding", "openai", OpenAIEmbedder, replace_existing=True,
                  description="OpenAI embeddings")
register_provider("embedding", "voyage", VoyageEmbedder, replace_existing=True,
                  description="Voyage AI embeddings")
register_provider("embedding", "ollama", OllamaEmbedder, requires_key=False,
                  replace_existing=True, description="Local Ollama embeddings")
