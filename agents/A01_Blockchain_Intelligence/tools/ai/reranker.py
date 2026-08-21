"""
Tools :: AI :: Reranker
=======================

Improve retrieval quality by re-scoring candidate results.

Pipeline: retrieve -> score -> re-rank -> return best results. The local
implementation scores candidates with lexical overlap (token Jaccard with
an IDF-style boost); real cross-encoder providers plug in behind the same
:class:`Reranker` interface.

Shipped providers:

* :class:`CohereReranker` -- a hosted cross-encoder (one request, all docs).
* :class:`LLMReranker` -- any registered language model scoring the batch,
  for deployments that already pay for an LLM and do not want a second vendor.
* :class:`LocalReranker` -- lexical, offline, no cost.

A remote reranker scores the whole candidate set in one call. Scoring one
document per request would multiply latency by the size of the result page,
which is exactly the page a reranker exists to improve.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

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
    "RerankItem",
    "RerankResult",
    "Reranker",
    "LocalReranker",
    "RemoteReranker",
    "CohereReranker",
    "LLMReranker",
    "jaccard_score",
    "overlap_score",
]


@dataclass
class RerankItem:
    """One candidate with its (re-)score and rank."""

    text: str
    score: float = 0.0
    rank: int = 0
    id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Mapping[str, Any]:
        return {"text": self.text, "score": self.score, "rank": self.rank, "id": self.id, "metadata": dict(self.metadata)}


@dataclass
class RerankResult:
    """Ordered list of re-ranked items."""

    items: List[RerankItem] = field(default_factory=list)

    def best(self) -> Optional[RerankItem]:
        return self.items[0] if self.items else None

    def as_dict(self) -> Mapping[str, Any]:
        return {"items": [item.as_dict() for item in self.items]}


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def overlap_score(query: str, document: str) -> float:
    """Fraction of query tokens present in the document (0..1)."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(document)
    return len(query_tokens & doc_tokens) / len(query_tokens)


def jaccard_score(query: str, document: str) -> float:
    """Jaccard similarity between query and document token sets."""
    query_tokens = _tokens(query)
    doc_tokens = _tokens(document)
    union = query_tokens | doc_tokens
    if not union:
        return 0.0
    return len(query_tokens & doc_tokens) / len(union)


class Reranker(BaseAIModel):
    """Base class for re-ranking providers."""

    capability = "reranker"

    def __init__(self, *, model: str = "local", top_k: int = 5, logger: Any = None) -> None:
        super().__init__(logger=logger)
        self._model = model or "local"
        self._top_k = top_k

    def _score(self, query: str, document: str) -> float:
        raise NotImplementedError

    def rerank(self, query: str, documents: Sequence[str], *, top_k: Optional[int] = None) -> RerankResult:
        if not query:
            raise AIValidationError("empty query", provider=self.provider)
        k = top_k or self._top_k
        scored = [RerankItem(text=doc, score=self._score(query, doc)) for doc in documents]
        scored.sort(key=lambda item: item.score, reverse=True)
        for rank, item in enumerate(scored[:k], start=1):
            item.rank = rank
        return RerankResult(items=scored[:k])

    def execute(self, request: AIRequest) -> AIResponse:
        started = time.monotonic()
        params = getattr(request, "params", None) or {}
        query = str(params.get("query", ""))
        documents = list(params.get("documents") or ())
        if not query or not documents:
            raise AIValidationError("rerank requires query and documents", provider=self.provider)
        try:
            result = self.rerank(query, documents)
        except AIError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AIExecutionError(str(exc), provider=self.provider, model=self._model) from exc
        return self.normalize(
            True,
            data=result.as_dict(),
            request_id=getattr(request, "request_id", ""),
            duration_ms=(time.monotonic() - started) * 1000.0,
            usage=AIUsage(prompt_tokens=len(query.split()) + sum(len(d.split()) for d in documents)),
        )


class LocalReranker(Reranker):
    """Lexical re-ranker (token overlap + IDF-style boost)."""

    provider = "local"

    def _score(self, query: str, document: str) -> float:
        overlap = overlap_score(query, document)
        if overlap == 0.0:
            return 0.0
        # Rare query tokens (longer/less frequent) get a mild boost.
        rarity = sum(1.0 for token in _tokens(query) if len(token) >= 6) / max(len(_tokens(query)), 1)
        return overlap * (1.0 + 0.25 * rarity)


# --------------------------------------------------------------------------- #
# Remote providers
# --------------------------------------------------------------------------- #


class RemoteReranker(Reranker):
    """Base class for hosted cross-encoder rerankers.

    :meth:`rerank` is overridden rather than :meth:`_score`: the whole
    candidate set goes in one request, and the per-document hook only exists
    so the inherited contract still answers for a single pair.
    """

    provider = "remote"
    base_url = ""
    rerank_path = ""
    default_model = ""
    requires_key = True

    def __init__(
        self,
        *,
        model: str = "",
        api_key: Optional[str] = None,
        base_url: str = "",
        top_k: int = 5,
        timeout: float = 60.0,
        max_retries: int = 2,
        transport: Optional[HTTPTransport] = None,
        headers: Optional[Mapping[str, str]] = None,
        logger: Any = None,
    ) -> None:
        resolved = model or model_for(self.capability, self.provider, self.default_model)
        if not resolved:
            raise AIValidationError(
                f"{self.provider} needs an explicit rerank model "
                f"(pass model=..., or set A01_AI_RERANKER_MODEL)",
                provider=self.provider,
            )
        super().__init__(model=resolved, top_k=top_k, logger=logger)
        self.api_key = resolve_api_key(self.provider, api_key, required=self.requires_key)
        self.timeout = float(timeout)
        self.extra_headers = dict(headers or {})
        self.transport = transport or HTTPTransport(
            base_url or self.base_url,
            headers={**self.auth_headers(), **self.extra_headers},
            timeout=timeout,
            max_retries=max_retries,
            provider=self.provider,
        )

    # -- provider hooks ------------------------------------------------------ #

    def auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def _payload(self, query: str, documents: Sequence[str], top_k: int) -> Dict[str, Any]:
        raise NotImplementedError

    def _scores(self, data: Mapping[str, Any], count: int) -> List[float]:
        raise NotImplementedError

    # -- contract ------------------------------------------------------------ #

    def rerank(
        self, query: str, documents: Sequence[str], *, top_k: Optional[int] = None
    ) -> RerankResult:
        if not query:
            raise AIValidationError("empty query", provider=self.provider)
        documents = list(documents)
        if not documents:
            return RerankResult(items=[])
        k = top_k or self._top_k

        data = self.transport.post_json(
            self.rerank_path,
            self._payload(query, documents, k),
            timeout=self.timeout,
            model=self._model,
        )
        scores = self._scores(data, len(documents))
        items = [
            RerankItem(text=document, score=score)
            for document, score in zip(documents, scores)
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        for rank, item in enumerate(items[:k], start=1):
            item.rank = rank
        return RerankResult(items=items[:k])

    def _score(self, query: str, document: str) -> float:
        result = self.rerank(query, [document], top_k=1)
        best = result.best()
        return best.score if best else 0.0


class CohereReranker(RemoteReranker):
    """Cohere ``/v2/rerank`` cross-encoder."""

    provider = "cohere"
    base_url = "https://api.cohere.com"
    rerank_path = "/v2/rerank"
    default_model = "rerank-v3.5"

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    def _payload(self, query: str, documents: Sequence[str], top_k: int) -> Dict[str, Any]:
        return {
            "model": self._model,
            "query": query,
            "documents": list(documents),
            "top_n": min(int(top_k), len(documents)),
        }

    def _scores(self, data: Mapping[str, Any], count: int) -> List[float]:
        # Results come back ranked and truncated to top_n, keyed by the index of
        # the document they scored; anything not returned scored below the cut.
        scores = [0.0] * count
        for row in data.get("results") or []:
            if not isinstance(row, Mapping):
                continue
            index = int(row.get("index", -1))
            if 0 <= index < count:
                scores[index] = float(row.get("relevance_score", 0.0) or 0.0)
        return scores


RERANK_SYSTEM = (
    "You score how well each document answers a query. "
    "Reply with JSON only, in the form "
    '{"scores": [{"index": <int>, "score": <float between 0 and 1>}]} '
    "with one entry per document and no other text."
)


class LLMReranker(Reranker):
    """Rerank with a language model instead of a dedicated cross-encoder.

    The whole candidate set is scored in one JSON-mode completion. This is for
    deployments that already run an LLM and would rather not add a second
    vendor for ranking; a real cross-encoder is cheaper and faster per call.

    ``provider`` reports the *language model's* provider, so a response is
    attributed to the vendor that actually did the work.
    """

    provider = "llm"

    def __init__(
        self,
        client: Any = None,
        *,
        top_k: int = 5,
        max_documents: int = 50,
        logger: Any = None,
    ) -> None:
        self.client = client if client is not None else create_provider("llm")
        super().__init__(model=self.client.model, top_k=top_k, logger=logger)
        self.provider = self.client.provider
        self.max_documents = int(max_documents)

    def _score(self, query: str, document: str) -> float:
        best = self.rerank(query, [document], top_k=1).best()
        return best.score if best else 0.0

    def rerank(
        self, query: str, documents: Sequence[str], *, top_k: Optional[int] = None
    ) -> RerankResult:
        if not query:
            raise AIValidationError("empty query", provider=self.provider)
        documents = list(documents)
        if not documents:
            return RerankResult(items=[])
        if len(documents) > self.max_documents:
            raise AIValidationError(
                f"{len(documents)} documents exceeds max_documents={self.max_documents}; "
                "retrieve fewer candidates or raise the limit",
                provider=self.provider,
            )
        k = top_k or self._top_k

        scores = self._ask(query, documents)
        items = [
            RerankItem(text=document, score=score, metadata={"index": index})
            for index, (document, score) in enumerate(zip(documents, scores))
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        for rank, item in enumerate(items[:k], start=1):
            item.rank = rank
        return RerankResult(items=items[:k])

    def _ask(self, query: str, documents: Sequence[str]) -> List[float]:
        from .llm import ChatMessage, LLMRequest  # local import: llm may import us

        listing = "\n".join(
            f"[{index}] {document}" for index, document in enumerate(documents)
        )
        prompt = f"Query: {query}\n\nDocuments:\n{listing}"
        request = LLMRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            system=RERANK_SYSTEM,
            temperature=0.0,
            max_tokens=64 + 32 * len(documents),
            json_mode=True,
        )
        response = self.client.execute(request)
        payload = (response.data or {}).get("json_data")
        rows = payload.get("scores") if isinstance(payload, Mapping) else payload
        if not isinstance(rows, (list, tuple)):
            raise AIExecutionError(
                "reranker model did not return a score list",
                provider=self.provider,
                model=self._model,
            )

        scores = [0.0] * len(documents)
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            index = int(row.get("index", -1))
            if 0 <= index < len(documents):
                scores[index] = max(0.0, min(1.0, float(row.get("score", 0.0) or 0.0)))
        return scores


register_provider("reranker", "local", LocalReranker, requires_key=False,
                  replace_existing=True, description="Lexical offline reranking")
register_provider("reranker", "cohere", CohereReranker, replace_existing=True,
                  description="Cohere rerank cross-encoder")
register_provider("reranker", "llm", LLMReranker, requires_key=False,
                  replace_existing=True, description="Rerank with the configured LLM")
