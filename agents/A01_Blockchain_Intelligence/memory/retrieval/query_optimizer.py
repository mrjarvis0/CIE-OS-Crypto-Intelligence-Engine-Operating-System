"""
Query Optimizer

Normalizes and expands queries, selects the optimal retrieval
strategy, and orchestrates a full retrieval pipeline: query
preparation, strategy dispatch, ranking, reranking, and context
assembly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

from memory.base.memory import (
    EmbeddingProvider,
    MemorySearchResult,
)
from memory.retrieval.context_builder import ContextAssembly, ContextBuilder
from memory.retrieval.hybrid import HybridRetriever
from memory.retrieval.lexical import LexicalRetriever
from memory.retrieval.reranker import CompositeReranker, Reranker
from memory.retrieval.semantic import SemanticRetriever

SEMANTIC_HINTS = {
    "why",
    "how",
    "similar",
    "related",
    "explain",
    "what is",
    "meaning",
    "concept",
    "summarize",
}

KEYWORD_HINTS = {"exact", "prefix", "where is", "who is", "what time"}


@dataclass(slots=True)
class QueryPlan:
    """
    Result of query analysis.
    """

    original: str
    normalized: str
    tokens: list[str]
    strategy: str
    expanded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "tokens": self.tokens,
            "strategy": self.strategy,
            "expanded": self.expanded,
        }


def normalize_query(query: str) -> str:
    """
    Normalize whitespace, case, and punctuation in a query.
    """
    text = query.strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def tokenize_query(query: str) -> list[str]:
    """
    Split a normalized query into lowercase word tokens.
    """
    return [token for token in re.findall(r"[\w-]+", query.lower()) if token]


def detect_semantic_intent(query: str) -> bool:
    """
    Return True when the query expresses semantic intent.
    """
    normalized = query.lower()
    return any(hint in normalized for hint in SEMANTIC_HINTS)


def detect_keyword_intent(query: str) -> bool:
    """
    Return True when the query expresses exact/lexical intent.
    """
    normalized = query.lower()
    return any(hint in normalized for hint in KEYWORD_HINTS)


class StrategySelector:
    """
    Picks a retrieval strategy from a query.
    """

    def __init__(self) -> None:
        pass

    def select(self, query: str) -> str:
        """
        Choose semantic / hybrid / lexical / keyword.
        """
        normalized = normalize_query(query)
        if not normalized:
            return "keyword"
        if detect_keyword_intent(normalized):
            return "keyword"
        if detect_semantic_intent(normalized):
            return "semantic"
        if len(tokenize_query(normalized)) >= 3:
            return "hybrid"
        return "keyword"


class QueryOptimizer:
    """
    Orchestrates the complete retrieval pipeline.

    Responsibilities:
        * Normalize and analyze the incoming query
        * Select the retrieval strategy
        * Dispatch to the appropriate retriever
        * Rank, rerank, and assemble context
    """

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider | None = None,
        semantic: SemanticRetriever | None = None,
        lexical: LexicalRetriever | None = None,
        hybrid: HybridRetriever | None = None,
        reranker: Reranker | None = None,
        context_builder: ContextBuilder | None = None,
        selector: StrategySelector | None = None,
        default_limit: int = 10,
    ) -> None:
        self._embedder = embedder
        self._semantic = semantic or SemanticRetriever(embedder=embedder)
        self._lexical = lexical or LexicalRetriever()
        self._hybrid = hybrid or HybridRetriever(embedder=embedder)
        self._reranker = reranker or CompositeReranker()
        self._context_builder = context_builder or ContextBuilder()
        self._selector = selector or StrategySelector()
        self._default_limit = default_limit

    @property
    def semantic(self) -> SemanticRetriever:
        return self._semantic

    @property
    def lexical(self) -> LexicalRetriever:
        return self._lexical

    @property
    def hybrid(self) -> HybridRetriever:
        return self._hybrid

    @property
    def reranker(self) -> Reranker:
        return self._reranker

    def plan(self, query: str) -> QueryPlan:
        normalized = normalize_query(query)
        tokens = tokenize_query(normalized)
        strategy = self._selector.select(normalized)
        return QueryPlan(
            original=query,
            normalized=normalized,
            tokens=tokens,
            strategy=strategy,
        )

    async def retrieve(
        self,
        query: str,
        *,
        limit: int | None = None,
        strategy: str | None = None,
        source: Any = None,
        memory_source: Any | None = None,
        rerank: bool = True,
    ) -> list[MemorySearchResult[Any]]:
        """
        Execute a full retrieval pass and return ranked results.
        """
        plan = self.plan(query)
        chosen = (strategy or plan.strategy).lower()
        limit_value = self._default_limit if limit is None else limit

        if chosen in {"semantic", "vector"}:
            results = await self._semantic.retrieve(
                query,
                limit=limit_value,
                source=source,
                memory_source=memory_source,
            )
        elif chosen in {"lexical", "exact", "prefix", "keyword"}:
            mode = "exact" if chosen in {"exact", "keyword"} else "prefix"
            results = await self._lexical.retrieve(
                query,
                limit=limit_value,
                source=source,
                memory_source=memory_source,
                mode=mode,
            )
        elif chosen in {"hybrid", "auto"}:
            results = await self._hybrid.retrieve(
                query,
                limit=limit_value,
                source=source,
                memory_source=memory_source,
            )
        else:
            raise ValueError(f"Unknown retrieval strategy '{chosen}'.")

        if rerank:
            results = self._reranker.rerank(results, query)
        return results

    async def retrieve_context(
        self,
        query: str,
        *,
        limit: int | None = None,
        strategy: str | None = None,
        source: Any = None,
        memory_source: Any | None = None,
        format_fn: Any | None = None,
        max_blocks: int | None = None,
    ) -> ContextAssembly:
        """
        Retrieve, rank, and assemble token-bounded context.
        """
        results = await self.retrieve(
            query,
            limit=limit,
            strategy=strategy,
            source=source,
            memory_source=memory_source,
        )
        return self._context_builder.build(
            results,
            format_fn=format_fn,
            max_blocks=max_blocks,
        )
