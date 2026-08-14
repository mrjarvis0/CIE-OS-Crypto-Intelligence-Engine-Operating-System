"""
CIE-OS
A02 News Intelligence Agent

Phase 1 tests — offline (no network, no API keys).
Run directly:
    python agents/A02_News_Intelligence/tests/test_core.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agents.A02_News_Intelligence.core.dedup import (
    content_fingerprint,
    fingerprint,
    looks_duplicate,
    note_seen,
    title_fingerprint,
)
from agents.A02_News_Intelligence.core.entities import extract_entities
from agents.A02_News_Intelligence.core.models import RawItem
from agents.A02_News_Intelligence.core.normalize import clean_text, guess_language, normalize_item, parse_timestamp
from agents.A02_News_Intelligence.core.pipeline import _process_batch
from agents.A02_News_Intelligence.core.symbols import entity_type_for, name_for
from agents.A02_News_Intelligence.core.storage import Storage

PASS = 0
FAIL = 0


def check(label: str, ok: bool) -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def test_normalize() -> None:
    print("normalize:")
    check("strip html", clean_text("<p>Hello <b>world</b> &amp; more</p>") == "Hello world & more")
    check("collapse whitespace", clean_text("a\n\n  b\tc") == "a b c")
    check("junk removal", "sign up" not in clean_text("sign up for our newsletter, read more"))
    parsed = parse_timestamp("2026-01-05T10:00:00Z")
    check("parse iso with Z", parsed is not None and parsed.tzinfo is not None)
    check("parse bad date", parse_timestamp("not-a-date") is None)
    check("language latin", guess_language("This is a financial market update for investors.") == "en")
    check("language devanagari", guess_language("यह एक वित्तीय समाचार है और बाजार में गिरावट आई") == "hi")
    raw = RawItem(source="test", source_key="k1", title="  <b>Bitcoin</b> drops  ", content="", url="http://x/1")
    item = normalize_item(raw)
    check("normalize title", item.title == "Bitcoin drops")
    check("title fingerprint 64 chars", len(item.title_fingerprint) == 64)
    check("empty content fingerprint", item.content_fingerprint == "")
    print()


def test_dedup() -> None:
    print("dedup:")
    t1 = title_fingerprint("Bitcoin drops after ETF news")
    t2 = title_fingerprint("Bitcoin drops after ETF news")  # identical headline
    t3 = title_fingerprint("Bitcoin Drops After ETF News!")  # punctuation/case variants
    check("same title same fp", t1 == t2)
    check("variant title same fp", t1 == t3)
    check("different title different fp", t1 != title_fingerprint("Ethereum rallies"))
    c1 = content_fingerprint("a" * 900)
    c2 = content_fingerprint("a" * 900)
    check("content fp stable", c1 == c2)

    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    seen_contents: set[str] = set()
    check("not dup initially", not looks_duplicate("http://u", t1, c1, seen_urls, seen_titles, seen_contents))
    note_seen("http://u", t1, c1, seen_urls, seen_titles, seen_contents)
    check("dup by url", looks_duplicate("http://u", t2, c2, seen_urls, seen_titles, seen_contents))
    check("dup by title", looks_duplicate("http://u2", t1, c2, seen_urls, seen_titles, seen_contents))
    print()


def test_entities() -> None:
    print("entities:")
    found = extract_entities("Bitcoin falls 5% as $BTC breaks support, while AAPL and EUR/USD react")
    symbols = {e.symbol for e in found}
    check("crypto by name", "BTC" in symbols)
    check("crypto by tag", "BTC" in symbols)
    check("stock by symbol", "AAPL" in symbols)
    check("forex pair", "EURUSD" in symbols)
    found2 = extract_entities("No financial entities mentioned here at all")
    check("no entities", found2 == [])
    found3 = extract_entities("NVIDIA reports earnings, AMD rallies")
    sym3 = {e.symbol for e in found3}
    check("company name alias", "NVDA" in sym3 and "AMD" in sym3)
    check("entity types", entity_type_for("BTC") == "crypto" and entity_type_for("AAPL") == "stock")
    check("entity name", name_for("BTC") == "Bitcoin")
    print()


def test_storage() -> None:
    print("storage:")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        storage = Storage(db)

        async def run() -> None:
            await storage.init()
            raw = RawItem(source="test", source_key="s1", url="http://x/1", title="Bitcoin rally continues")
            items = _process_batch([raw])
            item = items[0]
            check("entity extracted in batch", any(e.symbol == "BTC" for e in item.entities))
            check("not duplicate", not await storage.is_duplicate(item.url, item.title_fingerprint, item.content_fingerprint))
            item_id = await storage.insert_item(item)
            check("insert returns id", item_id >= 1)
            check("now duplicate", await storage.is_duplicate(item.url, item.title_fingerprint, item.content_fingerprint))
            check("count items", await storage.count_items() == 1)
            check("count entities", await storage.count_entities() >= 1)
            recent = await storage.recent_items(5)
            check("recent items", len(recent) == 1 and recent[0]["title"] == "Bitcoin rally continues")
            check("recent entities attached", len(recent[0]["entities"]) >= 1)

        asyncio.run(run())
    print()


def test_pipeline_batch() -> None:
    print("pipeline:")
    now = datetime.now(UTC)
    raw = [
        RawItem(source="rss_cnbc", source_key="a", url="http://x/1", title="Apple beats earnings estimates",
                content="AAPL revenue up, NVDA and TSLA also gained", published_at=now),
        RawItem(source="rss_cnbc", source_key="b", url="http://x/2", title="Apple beats earnings estimates",
                content="same story copy", published_at=now),
        RawItem(source="rss_marketwatch", source_key="c", url="http://x/3", title="Bitcoin ETF approved by SEC",
                content="BTC price reacts", published_at=now),
    ]
    batch = _process_batch(raw)
    check("all normalized", len(batch) == 3)
    check("dup pair shares title fp", batch[0].title_fingerprint == batch[1].title_fingerprint)
    check("entities on story 1", any(e.symbol == "AAPL" for e in batch[0].entities))
    check("entities on story 3", any(e.symbol == "BTC" for e in batch[2].entities))
    check("fingerprint non-empty", all(item.title_fingerprint for item in batch))
    print()


if __name__ == "__main__":
    test_normalize()
    test_dedup()
    test_entities()
    test_storage()
    test_pipeline_batch()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
