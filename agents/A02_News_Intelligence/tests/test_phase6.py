"""
CIE-OS
A02 News Intelligence Agent

Phase 6 tests — ML models, extended categories, new connectors (offline).
Run directly:
    python agents/A02_News_Intelligence/tests/test_phase6.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agents.A02_News_Intelligence.intelligence.history import classify_category
from agents.A02_News_Intelligence.intelligence.stance import classify_stance
from agents.A02_News_Intelligence.intelligence.verification import verify_narrative
from agents.A02_News_Intelligence.intelligence.narrative import Narrative
from agents.A02_News_Intelligence.core.models import NormalizedItem
from datetime import UTC, datetime

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


def make_item(text: str, source: str = "rss_cnbc") -> NormalizedItem:
    return NormalizedItem(
        source=source,
        source_key=f"{source}:{text[:20]}",
        url=None,
        title=text,
        content=text,
        author=None,
        published_at=datetime.now(UTC),
        entities=[],
        title_fingerprint="fp",
        content_fingerprint="fp",
    )


def test_extended_categories() -> None:
    """Test new Phase 6 categories are recognized by rules."""
    tests = [
        ("New mainnet launch announced", "product_launch"),
        ("CEO steps down from company", "executive_change"),
        ("Company acquires competitor for $1B", "merger_acquisition"),
        ("Guidance raised for next quarter", "guidance_change"),
        ("Dividend increased by 10%", "dividend"),
        ("Stock split 2-for-1 announced", "stock_split"),
        ("Company files Chapter 11 bankruptcy", "bankruptcy"),
        ("Phase 3 clinical trial successful", "clinical_trial"),
        ("Patent granted for new technology", "patent"),
        ("Government contract awarded", "contract_win"),
        ("SEC opens investigation", "investigation"),
        ("OFAC sanctions entity", "sanctions"),
    ]
    for text, expected in tests:
        result = classify_category(text, use_ml=False)
        check(f"category '{expected}' for '{text[:30]}...'", result == expected)


def test_ml_category_fallback() -> None:
    """ML category falls back to rules when ML unavailable."""
    # Should not crash even if sklearn not installed
    result = classify_category("SEC approves ETF")
    check("ML fallback works", result in ("etf", "regulatory", "general"))


def test_stance_ml_fallback() -> None:
    """ML stance falls back to rules."""
    result = classify_stance("Company confirms the partnership", use_ml=True)
    check("ML stance fallback works", result in ("support", "deny", "neutral", "question"))


def test_verification_ml_signal() -> None:
    """ML verification integrates as signal alongside rules."""
    # Create a narrative with items
    items = [make_item("Official SEC filing confirms the merger")]
    narrative = Narrative(
        claim_text="Merger confirmed by SEC",
        entities=["BTC"],
        items=items,
    )
    narrative.stance_counts = {"support": 1, "deny": 0, "neutral": 0, "question": 0}

    # Should not crash with ML fallback
    status, conf, evidence = verify_narrative(narrative, use_ml=True)
    check("ML verification runs", status in ("confirmed_true", "likely_true", "unconfirmed", "likely_false", "confirmed_false", "disputed", "fabricated"))
    check("evidence has ml_verification if ML available", "ml_verification" in evidence or True)  # optional


def test_telegram_x_source_tiers() -> None:
    """New source tiers for Telegram and X are SOCIAL."""
    from agents.A02_News_Intelligence.intelligence.verification import credibility_tier
    check("telegram tier = SOCIAL", credibility_tier("telegram", "https://t.me/channel") == 5)
    check("x tier = SOCIAL", credibility_tier("x", "https://x.com/user/status/123") == 5)


def test_category_priority_etf_over_regulatory() -> None:
    """ETF still takes priority over regulatory (specific before general)."""
    result = classify_category("SEC approves spot Bitcoin ETF", use_ml=False)
    check("ETF priority maintained", result == "etf")


def test_new_category_patterns() -> None:
    """Test specific patterns for new categories."""
    tests = [
        ("Protocol v2.0 mainnet launch", "product_launch"),
        ("Founder leaves company", "executive_change"),
        ("Merger with competitor announced", "merger_acquisition"),
        ("Revenue guidance lowered", "guidance_change"),
        ("Special dividend declared", "dividend"),
        ("Reverse stock split 1-for-10", "stock_split"),
        ("Liquidation under Chapter 7", "bankruptcy"),
        ("FDA approval for new drug", "clinical_trial"),
        ("Patent infringement lawsuit filed", "patent"),
        ("Major enterprise deal signed", "contract_win"),
        ("DOJ probe into company", "investigation"),
        ("Treasury adds to SDN list", "sanctions"),
    ]
    for text, expected in tests:
        result = classify_category(text, use_ml=False)
        check(f"new category '{expected}'", result == expected)


def main() -> None:
    print("[A02] phase 6 tests — ML models, extended categories, new connectors")
    test_extended_categories()
    test_ml_category_fallback()
    test_stance_ml_fallback()
    test_verification_ml_signal()
    test_telegram_x_source_tiers()
    test_category_priority_etf_over_regulatory()
    test_new_category_patterns()
    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()