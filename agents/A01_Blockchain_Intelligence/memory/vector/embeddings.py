"""
Embedding Service

Generates embeddings for memory content via pluggable embedding
providers with caching and normalization.

Default implementation: LocalHashEmbedder — deterministic, zero-dep,
stdlib-only (hashlib + struct). Suitable for local dev, tests, and
small-scale production. Pluggable: any class matching the
EmbeddingProvider protocol (async def embed(text) -> list[float]) can
be injected.
"""

from __future__ import annotations

import hashlib
import struct
import time
from typing import Any, Iterable, Optional

DEFAULT_DIM = 128
DEFAULT_SEED_PREFIX = "vector_memory"


def _build_vector(text: str, dim: int, seed: str) -> list[float]:
    vec = [0.0] * dim
    ngram_len = 3
    for i in range(max(1, len(text) - ngram_len + 1)):
        ngram = text[i : i + ngram_len]
        h = hashlib.sha256(f"{seed}:{ngram}".encode("utf-8")).digest()
        idx = struct.unpack("<Q", h[:8])[0] % dim
        val = (struct.unpack("<q", h[8:16])[0]) / (2**63)
        vec[idx] += val
    norm = sum(x * x for x in vec) ** 0.5
    if norm == 0.0:
        return [0.0] * dim
    return [x / norm for x in vec]


def _normalize_inplace(vector: list[float]) -> list[float]:
    norm = sum(x * x for x in vector) ** 0.5
    if norm == 0.0:
        return [0.0] * len(vector)
    return [x / norm for x in vector]


class LocalHashEmbedder:
    """
    Deterministic local embedder using SHA-256 hashing.

    Produces fixed-length float vectors from arbitrary text without
    any external ML model or library. Same input always yields the
    same vector (process-stable and cross-process stable).

    Responsibilities:
        * Encode text into embedding vectors
        * Cache embeddings for reuse
        * Normalize vector output
        * Estimate token count and embedding cost
    """

    def __init__(
        self,
        *,
        dim: int = DEFAULT_DIM,
        seed: str = DEFAULT_SEED_PREFIX,
        cache: dict[str, list[float]] | None = None,
        max_cache_size: int = 10_000,
    ) -> None:
        self._dim = dim
        self._seed = seed
        self._cache: dict[str, list[float]] = cache if cache is not None else {}
        self._max_cache_size = max_cache_size
        self._hits = 0
        self._misses = 0

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def embed(self, text: str) -> list[float]:
        if text in self._cache:
            self._hits += 1
            return list(self._cache[text])
        self._misses += 1
        vec = _build_vector(text, self._dim, self._seed)
        vec = _normalize_inplace(vec)
        if len(self._cache) >= self._max_cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[text] = vec
        return list(vec)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def normalize(self, vector: list[float]) -> list[float]:
        return _normalize_inplace(vector)

    def token_count(self, text: str) -> int:
        return len(text.split())

    def estimate_cost(self, text: str) -> float:
        tokens = self.token_count(text)
        return tokens * 0.0001

    def cache_embedding(self, text: str, vector: list[float]) -> None:
        self._cache[text] = list(vector)

    def get_cached_embedding(self, text: str) -> list[float] | None:
        return self._cache.get(text)

    def clear_cache(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict:
        return {
            "dim": self._dim,
            "cache_size": len(self._cache),
            "max_cache_size": self._max_cache_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (
                self._hits / (self._hits + self._misses)
                if (self._hits + self._misses) > 0
                else 0.0
            ),
        }


class ResilientEmbedding:
    """
    Multi-source embedding with failover and retry.

    Tries each configured provider in order, logging and skipping any
    that raise or return an invalid/wrong-dimension vector. Ends at a
    guaranteed local fallback embedder, so an unavailable remote/online
    provider can never crash retrieval.
    """

    def __init__(
        self,
        providers: Iterable[Any] = (),
        *,
        fallback: Any | None = None,
        dim: int = DEFAULT_DIM,
        seed: str = DEFAULT_SEED_PREFIX,
        attempts: int = 1,
        base_delay: float = 0.05,
        max_delay: float = 0.5,
    ) -> None:
        self._providers = list(providers or [])
        self._fallback = (
            fallback
            if fallback is not None
            else LocalHashEmbedder(dim=dim, seed=seed)
        )
        self._dim = (
            getattr(self._fallback, "dim", None)
            if fallback is not None
            else dim
        )
        self._attempts = max(1, attempts)
        self._base_delay = max(0.0, base_delay)
        self._max_delay = max(self._base_delay, max_delay)
        self._errors: list[str] = []

    @property
    def fallback(self) -> Any:
        return self._fallback

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    def _coerce(self, result: Any) -> list[float]:
        if result is None:
            raise ValueError("provider returned None")
        vector = list(result)
        if not vector:
            raise ValueError("provider returned empty vector")
        if self._dim is not None and len(vector) != self._dim:
            raise ValueError(
                f"provider dimension {len(vector)} != expected {self._dim}"
            )
        return _normalize_inplace(vector)

    def embed(self, text: str) -> list[float]:
        for provider in self._providers:
            candidate = None
            for attempt in range(self._attempts):
                try:
                    candidate = self._coerce(provider.embed(text))
                    return candidate
                except Exception as exc:  # noqa: BLE001
                    self._errors.append(f"{type(provider).__name__}: {exc}")
                    if attempt < self._attempts - 1:
                        time.sleep(
                            min(self._base_delay * (2**attempt), self._max_delay)
                        )
        return self._fallback.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def stats(self) -> dict:
        return {
            "providers": len(self._providers),
            "cloud_errors": len(self._errors),
        }


class EmbeddingService:
    """
    Produces vector embeddings for text content.

    Responsibilities:
        * Encode text into embedding vectors
        * Cache embeddings for reuse
        * Normalize vector output
    """

    def __init__(
        self,
        *,
        dim: int = DEFAULT_DIM,
        seed: str = DEFAULT_SEED_PREFIX,
        cache: dict[str, list[float]] | None = None,
        max_cache_size: int = 10_000,
    ) -> None:
        self._embedder = LocalHashEmbedder(
            dim=dim,
            seed=seed,
            cache=cache,
            max_cache_size=max_cache_size,
        )

    @property
    def embedder(self) -> LocalHashEmbedder:
        return self._embedder

    def embed(self, text: str) -> list[float]:
        return self._embedder.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_batch(texts)

    def normalize(self, vector: list[float]) -> list[float]:
        return self._embedder.normalize(vector)

    def token_count(self, text: str) -> int:
        return self._embedder.token_count(text)

    def estimate_cost(self, text: str) -> float:
        return self._embedder.estimate_cost(text)

    def cache_embedding(self, text: str, vector: list[float]) -> None:
        self._embedder.cache_embedding(text, vector)

    def get_cached_embedding(self, text: str) -> list[float] | None:
        return self._embedder.get_cached_embedding(text)

    def clear_cache(self) -> None:
        self._embedder.clear_cache()

    def stats(self) -> dict:
        return self._embedder.stats()