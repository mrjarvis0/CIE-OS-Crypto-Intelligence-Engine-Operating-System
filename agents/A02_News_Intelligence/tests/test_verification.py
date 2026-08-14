"""
CIE-OS
A02 News Intelligence Agent

Phase 3 tests — verification + manipulation (offline).
Run directly:
    python agents/A02_News_Intelligence/tests/test_verification.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agents.A02_News_Intelligence.core.models import Entity, NormalizedItem
from agents.A02_News_Intelligence.core.storage import Storage
from agents.A02_News_Intelligence.intelligence.manipulation import coordination_score
from agents.A02_News_Intelligence.intelligence.narrative import Narrative, NarrativeEngine
from agents.A02_News_Intelligence.intelligence.verification import (
    credibility_tier,
    independent_confirmations,
    verify_narrative,
)

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


def make_item(source: str, key: str, title: str, published: datetime, url: str | None = None,
              content: str = "", fp: str | None = None, author: str | None = None,
              platform: str = "web") -> NormalizedItem:
    item = NormalizedItem(
        source=source,
        source_key=key,
        url=url or f"http://x/{key}",
        title=title,
        content=content,
        published_at=published,
        fetched_at=published,
        author=author,
        platform=platform,
        content_fingerprint=fp or title,
    )
    item.entities = [Entity(type="crypto", symbol="BTC", name="Bitcoin", context=None)]
    return item


def test_credibility() -> None:
    print("credibility:")
    check("official domain", credibility_tier("rss_cnbc", "https://www.sec.gov/news/press-release") == 1)
    check("established media", credibility_tier("rss_cnbc", "https://www.cnbc.com/2026/01/01/x") == 2)
    check("crypto media", credibility_tier("rss_cointelegraph", "https://cointelegraph.com/news/x") == 3)
    check("aggregator", credibility_tier("rss_yahoo_finance", "https://finance.yahoo.com/news/x") == 4)
    check("social", credibility_tier("reddit", "https://www.reddit.com/r/x") == 5)
    check("anonymous", credibility_tier("unknown_feed", "https://unknown-blog.example/x") == 6)
    print()


def test_confirmations() -> None:
    print("confirmations:")
    now = datetime.now(UTC)

    # 10 items copying 1 original story -> 1 underlying source
    copies = [
        make_item("rss_a", f"c{i}", f"Bitcoin ETF approved title {i}", now, content="SAME BODY TEXT" * 20)
        for i in range(10)
    ]
    for c in copies:
        c.content_fingerprint = "FINGERPRINT_A"
        c.url = f"https://copy-site-{c.source_key}.com/story"
    tiers = independent_confirmations(copies)
    check("10 copies = 1 source", len(tiers) == 1)

    # 3 genuinely different stories from different domains
    distinct = [
        make_item("rss_a", "d1", "Story one", now, url="https://a.com/s1", content="aaa", fp="FP1"),
        make_item("rss_b", "d2", "Story two", now, url="https://b.com/s2", content="bbb", fp="FP2"),
        make_item("rss_c", "d3", "Story three", now, url="https://c.com/s3", content="ccc", fp="FP3"),
    ]
    tiers3 = independent_confirmations(distinct)
    check("3 distinct = 3 sources", len(tiers3) == 3)
    print()


def _narrative_with(items: list, stances: dict | None = None) -> Narrative:
    now = datetime.now(UTC)
    n = Narrative(claim_text=items[0].title, items=items, first_seen=now, last_seen=now)
    n.stance_counts.update(stances or {})
    return n


def test_verdicts() -> None:
    print("verdicts:")
    now = datetime.now(UTC)

    # official confirmation x2 -> confirmed true
    official = [
        make_item("rss_a", "o1", "SEC approves Bitcoin ETF", now, url="https://www.sec.gov/press", content="x", fp="X1"),
        make_item("rss_b", "o2", "SEC approval official", now, url="https://www.sec.gov/order", content="y", fp="X2"),
    ]
    status, conf, evidence = verify_narrative(_narrative_with(official, {"support": 2}))
    check("official x2 confirmed_true", status == "confirmed_true")
    check("high confidence", conf >= 0.9)
    check("evidence counts", evidence["official_sources"] == 2)

    # 1 official + 0 denies -> confirmed_true
    one_off = [
        make_item("rss_a", "q1", "SEC approves Bitcoin ETF", now, url="https://www.sec.gov/press", content="x", fp="Y1"),
        make_item("rss_b", "q2", "Bitcoin ETF news reaction", now, url="https://www.cnbc.com/news", content="y", fp="Y2"),
    ]
    status2, conf2, _ = verify_narrative(_narrative_with(one_off, {"support": 1}))
    check("1 official confirmed_true", status2 == "confirmed_true")

    # official deny -> confirmed false
    official_deny = [
        make_item("rss_a", "r1", "SEC denies ETF approval", now, url="https://www.sec.gov/statement", content="x", fp="Z1"),
        make_item("rss_b", "r2", "No ETF approval says SEC", now, url="https://www.sec.gov/release", content="y", fp="Z2"),
    ]
    status3, _, _ = verify_narrative(_narrative_with(official_deny, {"deny": 2}))
    check("official deny confirmed_false", status3 == "confirmed_false")

    # 1 deny vs 1 support -> disputed
    disputed_items = [
        make_item("rss_a", "s1", "Bitcoin ETF approved", now, url="https://www.cnbc.com/a", content="x", fp="W1"),
        make_item("rss_b", "s2", "Company denies ETF story", now, url="https://www.marketwatch.com/b", content="y", fp="W2"),
    ]
    status4, _, _ = verify_narrative(_narrative_with(disputed_items, {"support": 1, "deny": 1}))
    check("support+deny disputed", status4 == "disputed")

    # no evidence -> unconfirmed
    lone = [make_item("rss_x", "t1", "Some random tweet about token", now, url="https://www.reddit.com/r/t", content="x", fp="V1")]
    status5, conf5, _ = verify_narrative(_narrative_with(lone, {"question": 1}))
    check("social lone unconfirmed", status5 == "unconfirmed" and conf5 <= 0.5)

    # fabrication markers -> fabricated
    satire = [
        make_item("rss_x", "u1", "Bitcoin to the moon — satirical report", now, url="https://www.reddit.com/r/u", content="x", fp="U1"),
    ]
    status6, _, _ = verify_narrative(_narrative_with(satire, {"question": 1}))
    check("satire marker fabricated", status6 == "fabricated")
    print()


def test_manipulation() -> None:
    print("manipulation:")
    now = datetime.now(UTC)

    # coordinated: identical text, burst timing, one author, one platform
    burst = [
        make_item("rss_x", f"m{i}", f"BREAKING token news {i}", now - timedelta(minutes=i),
                  url=f"https://unknown{i}.net/s", content="IDENTICAL COPY" * 10,
                  fp="SAME_FP", author="bot_1", platform="social")
        for i in range(6)
    ]
    coord, flags = coordination_score(_narrative_with(burst))
    check("coordinated high", coord >= 60)
    check("burst flag", flags["timing_burst"] is True)
    check("identical ratio high", flags["identical_text_ratio"] >= 0.8)

    # organic: diverse text, spread times, many authors, multiple platforms
    organic = [
        make_item("rss_a", f"g{i}", f"Market update number {i} with different words", now - timedelta(hours=i * 3),
                  url=f"https://cnbc.com/s{i}", content=f"story body {i}", fp=f"FP{i}",
                  author=f"reporter_{i}", platform="web")
        for i in range(6)
    ]
    coord2, flags2 = coordination_score(_narrative_with(organic))
    check("organic low", coord2 < 40)
    check("no burst flag", flags2["timing_burst"] is False)

    # single item -> zero
    single = [make_item("rss_a", "h1", "One story", now)]
    coord3, _ = coordination_score(_narrative_with(single))
    check("single item zero", coord3 == 0.0)
    print()


def test_engine_integration() -> None:
    print("engine integration:")
    now = datetime.now(UTC)

    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "t.db")
            await storage.init()

            # verification fields must be persisted through the engine
            items = [
                make_item("rss_a", "e1", "SEC confirms Bitcoin ETF approval", now - timedelta(hours=1),
                          url="https://www.sec.gov/press", content="official", fp="E1"),
                make_item("rss_b", "e2", "Bitcoin ETF gets official green light", now,
                          url="https://www.sec.gov/order", content="also official", fp="E2"),
            ]
            for item in items:
                await storage.insert_item(item)
            engine = NarrativeEngine()
            narratives = await engine.update(storage, items, now=now)
            check("engine sets status", narratives[0].epistemic_status == "confirmed_true")
            check("engine sets confidence", narratives[0].confidence >= 0.9)
            check("engine sets coord", narratives[0].coordination_score >= 0)
            check("engine evidence persisted", narratives[0].evidence.get("underlying_sources", 0) >= 1)

            rows = await storage.load_active_narratives("1970-01-01T00:00:00")
            check("db persists verdict", rows[0]["epistemic_status"] == "confirmed_true")
            check("db persists coord", rows[0]["coordination_score"] >= 0)
    asyncio.run(run())
    print()


if __name__ == "__main__":
    test_credibility()
    test_confirmations()
    test_verdicts()
    test_manipulation()
    test_engine_integration()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
