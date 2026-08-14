"""
Self-contained tests for memory.retrieval.

Runs without pytest:
    python memory/retrieval/tests/test_retrieval.py

Exits 0 on success, non-zero with a diagnostic on failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from memory.base.memory import (  # noqa: E402
    MemoryEntry,
    MemoryMetadata,
    MemoryPriority,
    MemorySearchResult,
)
from memory.retrieval import (  # noqa: E402
    BoostedReranker,
    CompositeReranker,
    ContextBuilder,
    FilterChain,
    HybridRetriever,
    IdentityReranker,
    LexicalRetriever,
    MemoryQueryFilter,
    MetadataRetriever,
    PriorityReranker,
    QueryOptimizer,
    RankingEngine,
    RecencyReranker,
    ScoreAggregator,
    ScoreBoosterReranker,
    SemanticRetriever,
    StrategySelector,
    normalize_query,
    normalize_scores,
    reciprocal_rank_fusion,
    tokenize_query,
    weighted_merge,
)
from memory.vector.embeddings import LocalHashEmbedder  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def build_entries() -> list[MemoryEntry]:
    now = datetime.now(UTC)
    return [
        MemoryEntry(
            "pref",
            "User prefers gas-free settlement on L2 networks",
            MemoryMetadata(
                tags=["preference"],
                priority=MemoryPriority.HIGH,
                source="chat",
                created_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=1),
            ),
        ),
        MemoryEntry(
            "deploy",
            "Deployed contract on Arbitrum",
            MemoryMetadata(
                tags=["deployment"],
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(days=3),
            ),
        ),
        MemoryEntry(
            "meeting",
            "Meeting at 3pm tomorrow about staking yields",
            MemoryMetadata(
                tags=["event"],
                created_at=now,
                updated_at=now,
            ),
        ),
    ]


def test_scoring() -> None:
    print("scoring")
    check("normalize_query lowercases", normalize_query("  HELLO  World ") == "hello world")
    check("tokenize_query splits words", tokenize_query("L2 gas settlement") == ["l2", "gas", "settlement"])
    check("normalize_scores spans", abs(normalize_scores([1, 3, 5])[1] - 0.5) < 1e-9)
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]])
    check("rrf top is b", fused[0][0] == "b")
    merged = weighted_merge([("a", 0.9)], [("a", 0.5)], weights=[0.5, 0.5])
    check("weighted_merge accumulates", abs(merged[0][1] - 0.7) < 1e-9)
    agg = ScoreAggregator(weights={"relevance": 0.5, "freshness": 0.5})
    composite, breakdown = agg.aggregate({"relevance": 0.8, "freshness": 0.2})
    check("aggregator in range", 0.0 <= composite <= 1.0)
    check("aggregator breakdown keys", set(breakdown) == {"relevance", "freshness"})


def test_filters() -> None:
    print("filters")
    entries = build_entries()
    f = MemoryQueryFilter().with_min_priority(MemoryPriority.HIGH)
    check("priority filter", [e.key for e in f.apply(entries)] == ["pref"])
    f2 = MemoryQueryFilter().with_tags(["deployment"])
    check("tag filter", [e.key for e in f2.apply(entries)] == ["deploy"])
    f3 = MemoryQueryFilter().with_memory_type(MemoryPriority.NORMAL)
    check("memory type duck-typed", isinstance(f3.apply(entries), list))
    chain = FilterChain(lambda e: e.key.startswith("p"))
    check("filter chain", [e.key for e in chain.apply(entries)] == ["pref"])


def test_ranking() -> None:
    print("ranking")
    entries = build_entries()
    results = [MemorySearchResult(entry=e, score=0.9) for e in entries]
    engine = RankingEngine()
    ranked = engine.rank(results)
    check("ranking deterministic order", len(ranked) == 3)
    check("ranked sorted desc", all(
        ranked[i].score >= ranked[i + 1].score for i in range(len(ranked) - 1)
    ))
    check("top_k", len(engine.top_k(results, k=2)) == 2)


async def test_retrievers() -> None:
    print("retrievers")
    entries = build_entries()
    embedder = LocalHashEmbedder()

    sem = SemanticRetriever(embedder=embedder, threshold=0.05)
    results = await sem.retrieve("L2 gas settlement", source=entries)
    check("semantic returns pref first", results[0].entry.key == "pref")

    lex = LexicalRetriever()
    results = await lex.retrieve("meeting staking", source=entries)
    check("lexical returns meeting", results[0].entry.key == "meeting")

    hyb = HybridRetriever(embedder=embedder)
    results = await hyb.retrieve("meeting staking L2", source=entries)
    check("hybrid merged all", {r.entry.key for r in results} == {"pref", "deploy", "meeting"})

    meta = MetadataRetriever()
    results = await meta.retrieve(tags=["preference"], source=entries)
    check("metadata tag match", [r.entry.key for r in results] == ["pref"])

    opt = QueryOptimizer(embedder=embedder)
    plan = opt.plan("explain how L2 gas works")
    check("plan strategy semantic", plan.strategy == "semantic")
    context = await opt.retrieve_context("L2 gas settlement", source=entries)
    check("context non-empty", context.block_count > 0)
    check("context tokens positive", context.total_tokens > 0)
    check("context blocks ordered", all(
        context.blocks[i].score >= context.blocks[i + 1].score
        for i in range(context.block_count - 1)
    ))

    sel = StrategySelector()
    check("selector keyword", sel.select("exact foo") == "keyword")
    check("selector semantic", sel.select("how does this work") == "semantic")


def test_rerankers() -> None:
    print("rerankers")
    now = datetime.now(UTC)
    old = MemoryEntry("old", "c", MemoryMetadata(
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(days=10),
        priority=MemoryPriority.HIGH,
    ))
    new = MemoryEntry("new", "c", MemoryMetadata(
        created_at=now,
        updated_at=now,
        priority=MemoryPriority.LOW,
    ))
    results = [
        MemorySearchResult(entry=old, score=0.9),
        MemorySearchResult(entry=new, score=0.5),
    ]
    check("identity preserves", [r.entry.key for r in IdentityReranker().rerank(results, "q")] == ["old", "new"])
    check("recency first", [r.entry.key for r in RecencyReranker().rerank(results, "q")] == ["new", "old"])
    check("priority first", [r.entry.key for r in PriorityReranker().rerank(results, "q")] == ["old", "new"])
    boosted = BoostedReranker(boost=0.9, predicate=lambda e: e.key == "new").rerank(results, "q")
    check("boosted promotes", boosted[0].entry.key == "new")
    composite = CompositeReranker(steps=[RecencyReranker()]).rerank(results, "q")
    check("composite works", len(composite) == 2)
    booster = ScoreBoosterReranker(scorer=lambda e, q: 0.9).rerank(results, "q")
    check("score booster runs", len(booster) == 2)


def test_context_builder() -> None:
    print("context builder")
    entries = build_entries()
    results = [MemorySearchResult(entry=e, score=1.0 - i * 0.1) for i, e in enumerate(entries)]
    builder = ContextBuilder(max_tokens=20, headroom=0.9)
    assembly = builder.build(results, max_blocks=2)
    check("max_blocks respected", assembly.block_count <= 2)
    check("truncation flagged or full", assembly.block_count == 2)
    text = assembly.to_text()
    check("to_text joined", "pref" in text or "deploy" in text or "meeting" in text)
    check("to_dict serializable", isinstance(assembly.to_dict(), dict))


def main() -> None:
    test_scoring()
    test_filters()
    test_ranking()
    test_rerankers()
    test_context_builder()
    asyncio.run(test_retrievers())
    print(f"\n{PASS} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
