"""
Integration tests for the memory vector package.

Each test drives a real ``VectorMemory`` (in-memory SQLite) through the
vector facades: namespace, collection, index, pipeline, retriever,
search, dedup, snapshot, compaction, metrics, batch, adapter, and the
standalone chunker/cache/scoring utilities.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from memory.base.memory import MemoryPriority, SearchMode
from memory.base.vector_memory import (
    VectorMemory,
    VectorMemoryConfig,
)
from memory.storage import SqliteStorage
from memory.vector import (
    BatchOperator,
    ChromaStore,
    CollectionManager,
    Deduplicator,
    EmbeddingCache,
    NamespaceManager,
    ScoreAggregator,
    SearchExecutor,
    SnapshotManager,
    TextChunker,
    VectorAdapter,
    VectorCompactor,
    VectorIndex,
    VectorMetricsCollector,
    VectorRetriever,
    VectorWritePipeline,
    reciprocal_rank_score,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


async def scenario() -> None:
    mem = VectorMemory(config=VectorMemoryConfig(db_path=":memory:"))
    await mem.initialize()

    namespace = NamespaceManager(mem)
    await namespace.create("alpha")
    check("namespace.create", await namespace.exists("alpha"))
    check("namespace.ensure idempotent", not await namespace.ensure("alpha"))

    collection = CollectionManager(mem)
    await collection.create("docs")
    check("collection.exists", await collection.exists("docs"))
    check("collection.snapshot", "docs" in (await collection.snapshot())["collections"])

    pipeline = VectorWritePipeline(mem)
    long_text = " ".join(["l2 rollups settle gas-free"] * 40)
    estimate = pipeline.estimate(long_text)
    check("pipeline.estimate chunks > 1", estimate["chunks"] > 1)
    report = await pipeline.put(
        "k1",
        long_text,
        namespace="alpha",
        collection="docs",
        tags=["l2"],
    )
    check("pipeline.stored >= 1", report.stored >= 1)
    check("pipeline keys non-empty", len(report.keys) >= 1)

    single = await pipeline.put("k2", "rollup gas efficiency", namespace="alpha")
    check("pipeline single stored", single.stored == 1)
    check("pipeline empty skipped", (await pipeline.put("k3", "  ")).skipped == 1)

    retriever = VectorRetriever(mem)
    result = await retriever.retrieve(
        "gas-free settlement",
        namespace="alpha",
        collection="docs",
        limit=5,
    )
    check("retriever.retrieve returns", result.count > 0)
    normalized = retriever.normalize_scores(result)
    check("retriever.normalize range", all(0.0 <= r.score <= 1.0 for r in normalized.results))

    executor = SearchExecutor(mem, default_threshold=0.0)
    plan = executor.plan("query", mode=SearchMode.HYBRID.value)
    check("executor.plan hybrid", plan.mode == "hybrid")
    found = await executor.search("gas-free", namespace="alpha", collection="docs", limit=5)
    check("executor.search non-empty", found.count > 0)
    many = await executor.search_many(["gas", "rollup"], namespace="alpha", collection="docs")
    check("executor.search_many", len(many) == 2)
    flattened = executor.flatten(many)
    check("executor.flatten", len(flattened) >= 1)

    index = VectorIndex(mem)
    rebuilt = await index.rebuild()
    check("index.rebuild count", rebuilt > 0)
    status = await index.status()
    check("index.status namespaces", "alpha" in status.namespaces)
    check("index.health ok", (await index.health())["ok"])

    dedup = Deduplicator(threshold=0.9)
    candidates = [
        (entry.key, mem.embedder.embed(str(entry.value)))
        for entry in await mem.load_all(namespace="alpha", collection="docs")
    ]
    decision = dedup.check_candidates("l2 rollups settle gas-free", candidates)
    check("dedup.candidates finds", decision.is_duplicate)
    source_decision = await dedup.check_source(
        "gas-free settlement",
        mem,
        namespace="alpha",
        collection="docs",
    )
    check("dedup.source runs", source_decision.nearest_key is not None)

    snapshot = SnapshotManager(mem)
    payload = await snapshot.snapshot()
    check("snapshot.capture dict", isinstance(payload, dict))
    check("snapshot.describe", snapshot.describe(payload)["entry_count"] >= 1)

    compactor = VectorCompactor(mem)
    compact_report = await compactor.compact()
    check("compactor.compact", compact_report.compacted)

    metrics = VectorMetricsCollector(mem)
    collected = await metrics.collect()
    check("metrics.entry_count > 0", collected.entry_count > 0)
    check("metrics.namespaces", collected.namespace_count >= 1)
    check("metrics.health", (await metrics.health())["healthy"])

    batch = BatchOperator(mem)
    batch_result = await batch.put_many([("b1", "one"), ("b2", "two")])
    check("batch.put_many", batch_result.succeeded == 2)
    loaded = await batch.get_many(["b1", "b2"])
    check("batch.get_many", len(loaded) == 2)
    deleted = await batch.delete_many(["b1"])
    check("batch.delete_many", deleted.succeeded == 1)

    store = ChromaStore()
    store.upsert(
        ["c1", "c2"],
        ["alpha token", "beta token"],
        metadatas=[{"kind": "x"}, {"kind": "y"}],
    )
    store.upsert(["c3"], ["gamma token"], namespace="other")
    q = store.query("alpha token", n_results=1)
    check("chroma.query top", len(q) == 1 and q[0][0] == "c1")
    check("chroma.count", store.count() == 3)
    check("chroma.delete", store.delete("c3"))

    adapter = VectorAdapter(SqliteStorage(path=":memory:"))
    await adapter.connect()
    await adapter.put("a1", "alpha data", tags=["t"])
    check("adapter.put roundtrip", (await adapter.get("a1")).value == "alpha data")
    check("adapter.count", await adapter.count() == 1)
    search_result = await adapter.search("alpha data", limit=1)
    check("adapter.search returns", len(search_result) >= 1)
    await adapter.disconnect()

    chunker = TextChunker(max_chars=50, overlap_chars=10)
    chunks = chunker.chunk("a b c " * 30)
    check("chunker.chunk splits", len(chunks) > 1)
    check("chunker.single keeps", len(chunker.chunk("short")) == 1)
    check("chunker.stats", chunker.stats("a b c " * 30)["chunk_count"] == len(chunks))

    cache = EmbeddingCache(capacity=5)
    cache.set("x", [1.0, 0.0])
    check("cache.get hit", cache.get("x") == [1.0, 0.0])
    check("cache.miss", cache.get("missing") is None)
    check("cache.stats hit_rate", cache.stats().hit_rate > 0.0)
    small_cache = EmbeddingCache(capacity=2)
    small_cache.set("a", [1.0])
    small_cache.set("b", [1.0])
    small_cache.set("c", [1.0])
    check("cache.evicts", small_cache.stats().evictions == 1)

    aggregator = ScoreAggregator()
    fused = aggregator.weighted_fuse(
        {"s1": [("x", 0.9), ("y", 0.5)], "s2": [("x", 0.4), ("z", 0.8)]},
    )
    check("scoring.weighted_fuse top", fused[0].key == "x")
    rrf = aggregator.rrf_fuse([["x", "y"], ["z", "x"]])
    check("scoring.rrf top x", rrf[0].key == "x")
    check("scoring.rrf score", reciprocal_rank_score(1, k=60) > 0.0)
    check("scoring.dedupe", len(aggregator.dedupe(fused)) == 3)

    await mem.close()
    check("memory.close", True)


def main() -> int:
    print("vector tests")
    asyncio.run(scenario())
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
