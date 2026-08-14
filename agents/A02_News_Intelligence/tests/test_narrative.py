"""
CIE-OS
A02 News Intelligence Agent

Phase 2 tests — narrative intelligence (offline).
Run directly:
    python agents/A02_News_Intelligence/tests/test_narrative.py
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
from agents.A02_News_Intelligence.intelligence.claims import extract_claim, extract_time_hint, split_sentences
from agents.A02_News_Intelligence.intelligence.cluster import similarity, tokenize
from agents.A02_News_Intelligence.intelligence.narrative import NarrativeEngine, compute_fomo, compute_status
from agents.A02_News_Intelligence.intelligence.stance import classify_stance

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


def make_item(source: str, key: str, title: str, published: datetime, content: str = "", entity_symbols=None) -> NormalizedItem:
    item = NormalizedItem(
        source=source,
        source_key=key,
        url=f"http://x/{key}",
        title=title,
        content=content,
        published_at=published,
        fetched_at=published,
    )
    item.entities = [
        Entity(type="crypto" if s == "BTC" else "stock", symbol=s, name=s, context=None)
        for s in (entity_symbols or [])
    ]
    return item


def test_claims() -> None:
    print("claims:")
    check("split sentences", len(split_sentences("First sentence. Second one! Third?")) == 3)
    claim = extract_claim("SEC will approve XYZ ETF tomorrow.", "", ["XYZ"])
    check("claim text kept", claim.claim_text == "SEC will approve XYZ ETF tomorrow.")
    check("claim entities", claim.entities == ["XYZ"])
    check("time hint", claim.time_hint == "tomorrow")
    check("time hint none", extract_time_hint("Price went up") is None)
    claim2 = extract_claim("Markets mixed today.", "Bitcoin rallied strongly on ETF approval.", ["BTC"])
    check("prefers entity sentence", "Bitcoin" in claim2.claim_text)
    print()


def test_stance() -> None:
    print("stance:")
    check("deny", classify_stance("Binance denies delisting rumors about XYZ") == "deny")
    check("deny word", classify_stance("Company says rumor is not true") == "deny")
    check("support", classify_stance("SEC confirms approval of the ETF") == "support")
    check("support official", classify_stance("Exchange officially announced the listing") == "support")
    check("question", classify_stance("Reportedly, XYZ may be delisted") == "question")
    check("question rumor", classify_stance("Rumor: XYZ is getting delisted?") == "question")
    check("neutral", classify_stance("Markets closed higher on Tuesday") == "neutral")
    print()


def test_similarity() -> None:
    print("similarity:")
    now = datetime.now(UTC)
    a = make_item("rss_a", "a1", "Bitcoin ETF approved by SEC in landmark decision", now, entity_symbols=["BTC"])
    b = make_item("rss_b", "b1", "SEC approves Bitcoin ETF, bitcoin price reacts", now, entity_symbols=["BTC"])
    c = make_item("rss_c", "c1", "Ethereum developer conference announced in Paris", now, entity_symbols=["ETH"])
    check("same story similar", similarity(a, b) >= 0.4)
    check("different story dissimilar", similarity(a, c) < 0.2)
    # pattern headlines about different companies must NOT cluster
    d = make_item("rss_d", "d1", "Equitable Q2 Earnings Call Highlights", now, entity_symbols=["EQH"])
    e = make_item("rss_e", "e1", "ESCO Technologies Q3 Earnings Call Highlights", now, entity_symbols=[])
    check("pattern headlines don't merge", similarity(d, e) < 0.22)
    check("tokenize removes stopwords", "the" not in tokenize("the quick fox"))
    print()


def test_engine() -> None:
    print("engine:")
    now = datetime.now(UTC)

    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "t.db")
            await storage.init()

            # 4 items = same story, 2 items = different story
            items = [
                make_item("rss_a", "s1", "Bitcoin ETF approved by SEC in landmark decision", now - timedelta(hours=5), entity_symbols=["BTC"]),
                make_item("rss_b", "s2", "SEC approves Bitcoin ETF, bitcoin price reacts", now - timedelta(hours=4), entity_symbols=["BTC"]),
                make_item("rss_c", "s3", "Bitcoin ETF approval confirmed by regulators", now - timedelta(hours=3), entity_symbols=["BTC"]),
                make_item("rss_d", "s4", "Bitcoin ETF gets green light", now - timedelta(hours=2), entity_symbols=["BTC"]),
                make_item("rss_e", "s5", "Ethereum developer conference announced in Paris", now - timedelta(hours=2), entity_symbols=["ETH"]),
                make_item("rss_f", "s6", "Ethereum dev conference is happening", now - timedelta(hours=1), entity_symbols=["ETH"]),
            ]
            for item in items:
                await storage.insert_item(item)

            engine = NarrativeEngine()
            narratives = await engine.update(storage, items, now=now)
            by_claim = {n.claim_text: n for n in narratives}
            btc_narratives = [n for n in narratives if "BTC" in n.entities]
            eth_narratives = [n for n in narratives if "ETH" in n.entities]

            check("two narratives", len(narratives) == 2)
            check("btc cluster has 4 mentions", btc_narratives and btc_narratives[0].mention_count == 4)
            check("btc source count 4", btc_narratives and btc_narratives[0].source_count == 4)
            check("eth cluster has 2 mentions", eth_narratives and eth_narratives[0].mention_count == 2)
            check("btc fomo > eth fomo", btc_narratives[0].fomo_score > eth_narratives[0].fomo_score)
            check("btc spreading status", btc_narratives[0].status in ("spreading", "peak_hype"))
            check("fomo in range", all(0 <= n.fomo_score <= 100 for n in narratives))

            # reload from db — metrics persist
            rows = await storage.load_active_narratives("1970-01-01T00:00:00")
            check("persisted narratives", len(rows) == 2)
            check("persisted mentions", sum(r["mention_count"] for r in rows) == 6)
            check("persisted stance", all("stance_counts" in r and r["stance_counts"] for r in rows))
            check("persisted items", all(len(r["items"]) == r["mention_count"] for r in rows))
    asyncio.run(run())
    print()


def test_fomo_and_status() -> None:
    print("fomo/status:")
    now = datetime.now(UTC)

    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "t.db")
            await storage.init()
            engine = NarrativeEngine()
            # fast burst: 8 mentions within ~1.4 hours across 3 sources
            burst = [
                make_item(f"src{i % 3}", f"b{i}", f"Breaking: Bitcoin crash rumor #{i}", now - timedelta(hours=i * 0.2), entity_symbols=["BTC"])
                for i in range(8)
            ]
            quiet = [
                make_item("rss_q", "q1", "Coinbase quietly updates its help center", now - timedelta(hours=1), entity_symbols=["COIN"])
            ]
            for item in burst + quiet:
                await storage.insert_item(item)
            narratives = await engine.update(storage, burst + quiet, now=now)
            fomo_map = {n.entities[0]: n.fomo_score for n in narratives}
            check("burst fomo higher", fomo_map["BTC"] > fomo_map["COIN"])
            check("burst peak_hype", next(n.status for n in narratives if n.entities == ["BTC"]) == "peak_hype")
            check("quiet emerging", next(n.status for n in narratives if n.entities == ["COIN"]) in ("emerging", "spreading"))

            # deny stance -> verifying
            storage2 = Storage(Path(tmp) / "t2.db")
            await storage2.init()
            deny_items = [
                make_item("rss_a", "d1", "SEC denies approval of Bitcoin ETF", now, entity_symbols=["BTC"]),
                make_item("rss_b", "d2", "SEC says Bitcoin ETF report is false", now, entity_symbols=["BTC"]),
            ]
            for item in deny_items:
                await storage2.insert_item(item)
            narratives2 = await engine.update(storage2, deny_items, now=now)
            check("deny -> verifying", narratives2[0].status == "verifying")
            check("stance counts recorded", narratives2[0].stance_counts["deny"] >= 1)
    asyncio.run(run())
    print()


if __name__ == "__main__":
    test_claims()
    test_stance()
    test_similarity()
    test_engine()
    test_fomo_and_status()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
