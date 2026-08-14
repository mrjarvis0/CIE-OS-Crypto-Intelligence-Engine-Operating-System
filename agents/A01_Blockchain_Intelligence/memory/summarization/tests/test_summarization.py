"""
Integration tests for the summarization pipeline.

Drives the real ImportanceScorer, MemoryFilter, and ContextCompressor
through the SummarizationPipeline orchestrator.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from memory.summarization import (
    CompressionStrategy,
    SummarizationPipeline,
    count_tokens,
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
    pipeline = SummarizationPipeline()

    entries = [
        {
            "key": "e1",
            "content": "rollup gas efficiency is critical for L2 adoption",
            "tags": ["l2"],
        },
        {
            "key": "e2",
            "content": "settlement is gas-free on optimistic rollups",
            "tags": ["l2"],
        },
        {
            "key": "e3",
            "content": "the weather is nice today",
            "tags": [],
        },
        {
            "key": "e4",
            "content": "rollup gas efficiency is critical for L2 adoption",
            "tags": ["l2"],
        },
    ]

    scored = pipeline.score(entries)
    check("pipeline.score ranks all", len(scored) == 4)
    check("pipeline.score sorted desc", scored[0].score >= scored[-1].score)
    check("pipeline.score in range", all(0.0 <= s.score <= 1.0 for s in scored))

    filter_result = pipeline.filter(scored)
    check("pipeline.filter returns kept", filter_result.kept_count >= 1)
    check("pipeline.filter dropped some", filter_result.dropped_count >= 1)

    long_text = " ".join(
        ["L2 rollups provide secure and scalable scaling while settling on layer one."] * 60
    )
    original_tokens = count_tokens(long_text)
    compressed = await pipeline.compress(
        long_text,
        budget=60,
        strategy=CompressionStrategy.EXTRACT,
    )
    check("pipeline.compress reduces", compressed.compressed_tokens < original_tokens)
    check("pipeline.compress within budget", compressed.compressed_tokens <= 60)
    check("pipeline.compress ratio", compressed.ratio < 1.0)

    result = await pipeline.run(
        entries,
        compress_content=long_text,
        budget=60,
        strategy=CompressionStrategy.SUMMARIZE,
        key="conv-1",
    )
    check("pipeline.run kept non-empty", result.kept_count >= 1)
    check("pipeline.run compression present", result.compression is not None)
    check("pipeline.run stages == 3", len(result.stages) == 3)
    check("pipeline.run stage order", [s.name for s in result.stages] == ["score", "filter", "compress"])
    check("pipeline.run to_dict", result.to_dict()["kept_count"] == result.kept_count)

    anchored = await pipeline.run_content(
        long_text,
        budget=50,
        strategy=CompressionStrategy.ANCHORED,
        key="anchor-1",
    )
    check("pipeline.run_content anchored", anchored.compression is not None)
    check("pipeline.anchored generations", pipeline.compressor.anchor_state("anchor-1").generations >= 1)

    archive_content = " ".join(["archivable segment"] * 20)
    archive = await pipeline.compress(
        archive_content,
        budget=5,
        strategy=CompressionStrategy.ARCHIVE,
    )
    check("pipeline.archive has ref", archive.archive is not None)
    check("pipeline.archive reduces", archive.compressed_tokens < count_tokens(archive_content))

    stats = pipeline.statistics()
    check("pipeline.statistics compressor", "compressor" in stats)
    check("pipeline.statistics filter config", "deduplicate" in stats["memory_filter_config"])


def main() -> int:
    print("summarization tests")
    asyncio.run(scenario())
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
