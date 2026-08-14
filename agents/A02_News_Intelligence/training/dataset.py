"""
CIE-OS
A02 News Intelligence Agent

Module:
    training.dataset

Purpose:
    Curated, labeled training dataset for the verification engine.
    Three groups:
      - real    : genuine news stories (taken from live RSS data) -> true-leaning verdicts
      - fake    : satire, fabricated claims, coordinated rumor spam -> false-leaning verdicts
      - complex : ambiguous propagation patterns (deny/support, question-only, aggregator copies)

    Each sample builds a Narrative the same way the live pipeline does,
    and carries the EXPECTED epistemic verdict a human fact-checker would give.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from agents.A02_News_Intelligence.core.dedup import content_fingerprint, title_fingerprint
from agents.A02_News_Intelligence.intelligence.claims import extract_claim
from agents.A02_News_Intelligence.intelligence.narrative import Narrative
from agents.A02_News_Intelligence.intelligence.stance import classify_stance

# True-leaning verdicts that satisfy an expected true outcome
TRUE_LEANING = {"confirmed_true", "likely_true"}
# False-leaning verdicts that satisfy an expected false outcome
FALSE_LEANING = {"confirmed_false", "likely_false", "fabricated"}
# Indecisive verdicts (honest "we don't know")
UNCERTAIN = {"unconfirmed", "disputed", "unverifiable"}

_TRUE_EXPECTED = {"likely_true", "confirmed_true"}
_FALSE_EXPECTED = {"likely_false", "confirmed_false", "fabricated"}
_UNCERTAIN_EXPECTED = {"unconfirmed", "disputed", "unverifiable"}


@dataclass
class TrainingSample:
    name: str
    group: str  # real | fake | complex
    expected: str  # expected epistemic verdict
    items: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "group": self.group, "expected": self.expected}


def _item(
    title: str,
    source: str,
    source_key: str,
    url: str,
    content: str = "",
    author: str | None = None,
    minutes_ago: int = 60,
    platform: str = "web",
) -> dict:
    """Build an item dict with fingerprints, ready for NormalizedItem."""
    published = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {
        "source": source,
        "source_key": source_key,
        "url": url,
        "title": title,
        "content": content,
        "author": author,
        "published_at": published,
        "platform": platform,
        "title_fingerprint": title_fingerprint(title),
        "content_fingerprint": content_fingerprint(content or title),
    }


def build_narrative(sample: TrainingSample) -> Narrative:
    """Reconstruct a Narrative exactly like the live engine does.

    Stance is classified with rules (use_ml=False) so the harness is
    deterministic; the verdict itself may still use ML signals.
    """
    from agents.A02_News_Intelligence.core.models import NormalizedItem

    items: list[NormalizedItem] = []
    for d in sample.items:
        item = NormalizedItem(
            source=d["source"],
            source_key=d["source_key"],
            url=d["url"],
            title=d["title"],
            content=d["content"],
            author=d.get("author"),
            published_at=d["published_at"],
            platform=d.get("platform", "web"),
            title_fingerprint=d["title_fingerprint"],
            content_fingerprint=d["content_fingerprint"],
        )
        items.append(item)

    first = items[0]
    claim = extract_claim(first.title, first.content, [])
    stance_counts = {"support": 0, "deny": 0, "neutral": 0, "question": 0}
    for item in items:
        stance = classify_stance(f"{item.title} {item.content}", use_ml=False)
        stance_counts[stance] += 1

    sources = {i.source for i in items}
    platforms = {i.platform for i in items}
    published_times = [i.published_at for i in items]
    first_seen = min(p for p in published_times if p)
    last_seen = max(p for p in published_times if p)

    return Narrative(
        claim_text=claim.claim_text,
        entities=claim.entities,
        first_seen=first_seen,
        last_seen=last_seen,
        mention_count=len(items),
        source_count=len(sources),
        platforms=sorted(platforms),
        stance_counts=stance_counts,
        items=items,
    )


def export_training_json(samples: list[TrainingSample], path: str) -> int:
    """Export verification labels as JSON for ML retraining."""
    import json

    rows = []
    for s in samples:
        if s.expected in _TRUE_EXPECTED | _FALSE_EXPECTED:
            claim = build_narrative(s).claim_text
            rows.append({"text": claim, "verification": s.expected})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return len(rows)


# ==============================================================================
# DATASET
# ==============================================================================

SAMPLES: list[TrainingSample] = [
    # ------------------------------------------------------------------ REAL
    TrainingSample(
        "real_btc_65k_coindesk", "real", "likely_true",
        items=[_item(
            "Bitcoin hovers below $65,000 as Middle East tensions escalate further",
            "rss_coindesk", "rss_coindesk",
            "https://www.coindesk.com/markets/2026/08/08/bitcoin-hovers-below-65000/",
            content="Bitcoin traded below $65,000 on Friday as geopolitical tensions in the Middle East kept risk appetite muted. The largest cryptocurrency fell 2.1% in the last 24 hours, tracking equity markets lower.",
            author="Helene Braun", minutes_ago=55,
        )],
    ),
    TrainingSample(
        "real_sec_etf_two_crypto", "real", "likely_true",
        items=[
            _item(
                "SEC officially approves Bitcoin ETF",
                "rss_coindesk", "rss_coindesk",
                "https://www.coindesk.com/policy/2026/01/10/sec-approves-bitcoin-etf/",
                content="The Securities and Exchange Commission has officially approved the first spot Bitcoin exchange-traded fund, the agency announced. Trading is expected to begin next week.",
                author="Nikhilesh De", minutes_ago=240,
            ),
            _item(
                "SEC gives green light to spot Bitcoin ETF after years of rejections",
                "rss_cointelegraph", "rss_cointelegraph",
                "https://cointelegraph.com/news/sec-approves-spot-bitcoin-etf",
                content="The SEC has approved spot Bitcoin ETF applications, a watershed moment for the industry after a decade of applications and rejections.",
                author="Tom Mitchelhill", minutes_ago=230,
            ),
        ],
    ),
    TrainingSample(
        "real_sec_etf_cnbc_marketwatch", "real", "likely_true",
        items=[
            _item(
                "SEC approves spot bitcoin ETFs, paving the way for new wave of investors",
                "rss_cnbc", "rss_cnbc",
                "https://www.cnbc.com/2026/01/10/sec-approves-spot-bitcoin-etfs.html",
                content="The SEC approved 11 spot bitcoin exchange-traded funds, a landmark decision that opens the asset class to mainstream investors.",
                author="Jesse Pound", minutes_ago=200,
            ),
            _item(
                "SEC approves Bitcoin ETFs: What it means for investors",
                "rss_marketwatch", "rss_marketwatch",
                "https://www.marketwatch.com/story/sec-approves-bitcoin-etfs",
                content="Regulators have approved spot bitcoin ETFs, ending a 10-year quest and potentially unlocking billions in new demand.",
                author="Frances Yue", minutes_ago=195,
            ),
        ],
    ),
    TrainingSample(
        "real_etf_official_sec_gov", "real", "confirmed_true",
        items=[_item(
            "SEC Approves Spot Bitcoin Exchange-Traded Products",
            "sec_gov", "rss_yahoo_finance",
            "https://www.sec.gov/news/press-release/2026-4",
            content="The Securities and Exchange Commission today approved the listing and trading of spot bitcoin exchange-traded products on national securities exchanges. This approval follows the Commission's prior determinations regarding exchange-traded products holding bitcoin futures.",
            author="SEC Press Office", minutes_ago=300,
        )],
    ),
    TrainingSample(
        "real_bybit_lazarus_coindesk", "real", "likely_true",
        items=[_item(
            "Bybit sues North Korea and Lazarus Group over $1.5 billion hack, secures asset freeze",
            "rss_coindesk", "rss_coindesk",
            "https://www.coindesk.com/business/2026/08/08/bybit-sues-lazarus-group/",
            content="Bybit has filed suit against North Korea and the Lazarus Group over the $1.5 billion hack of its exchange, and secured an asset freeze order against the group's addresses, the exchange said Thursday.",
            author="Amanda Allison", minutes_ago=90,
        )],
    ),
    TrainingSample(
        "real_japan_fsa_cointelegraph", "real", "likely_true",
        items=[_item(
            "Japan FSA asks crypto exchanges to impose withdrawal delays to fight scams",
            "rss_cointelegraph", "rss_cointelegraph",
            "https://cointelegraph.com/news/japan-fsa-withdrawal-delays-scams",
            content="Japan's Financial Services Agency has asked domestic crypto exchanges to introduce withdrawal delays to curb fraud, according to a document seen by the publication.",
            author="Ezra Reguerra", minutes_ago=75,
        )],
    ),
    TrainingSample(
        "real_imf_stablecoin_cointelegraph", "real", "likely_true",
        items=[_item(
            "Domestic stablecoins could boost demand for dollar-backed tokens: IMF",
            "rss_cointelegraph", "rss_cointelegraph",
            "https://cointelegraph.com/news/imf-domestic-stablecoins-demand",
            content="Domestic stablecoins could strengthen demand for dollar-backed tokens globally, the International Monetary Fund said in a working paper published Wednesday.",
            author="Arijit Sarkar", minutes_ago=70,
        )],
    ),
    TrainingSample(
        "real_reuters_exclusive", "real", "likely_true",
        items=[_item(
            "BlackRock in talks to launch tokenized money market fund, sources say",
            "reuters", "rss_yahoo_finance",
            "https://www.reuters.com/technology/blackrock-tokenized-money-market-fund-2026-08-08/",
            content="BlackRock is in talks with partners to launch a tokenized money market fund, two people familiar with the matter told Reuters. A deal has not been finalized.",
            author="Hannah Lang", minutes_ago=120,
        )],
    ),
    TrainingSample(
        "real_binance_official_blog", "real", "confirmed_true",
        items=[_item(
            "Binance Announces BNB Auto-Burn Update for Q3 2026",
            "binance", "rss_cointelegraph",
            "https://www.binance.com/en/blog/ecosystem/bnb-auto-burn-q3-2026",
            content="Binance is pleased to announce the completion of the 29th quarterly BNB burn, removing 1,944,900 BNB from circulation, per the BNB auto-burn mechanism.",
            author="Binance Team", minutes_ago=45,
        )],
    ),
    TrainingSample(
        "real_etf_official_plus_reuters", "real", "confirmed_true",
        items=[
            _item(
                "SEC Approves Spot Bitcoin Exchange-Traded Products",
                "sec_gov", "rss_yahoo_finance",
                "https://www.sec.gov/news/press-release/2026-4",
                content="The Securities and Exchange Commission today approved the listing and trading of spot bitcoin exchange-traded products on national securities exchanges.",
                author="SEC Press Office", minutes_ago=310,
            ),
            _item(
                "SEC approves first spot bitcoin ETFs in landmark ruling",
                "reuters", "rss_yahoo_finance",
                "https://www.reuters.com/business/finance/sec-approves-first-spot-bitcoin-etfs-2026-01-10/",
                content="The U.S. securities regulator approved the first spot bitcoin exchange-traded funds, a landmark decision for the crypto industry. SEC Chair said the move reflects the maturation of the market.",
                author="Hannah Lang", minutes_ago=305,
            ),
        ],
    ),
    TrainingSample(
        "real_trump_media_coindesk", "real", "likely_true",
        items=[_item(
            "Trump Media pulls back from crypto, scraps Crypto.com's CRO token treasury deal",
            "rss_coindesk", "rss_coindesk",
            "https://www.coindesk.com/business/2026/08/08/trump-media-scraps-cro-treasury-deal/",
            content="Trump Media has walked back its crypto ambitions, terminating a planned treasury arrangement with Crypto.com that would have added CRO tokens to its balance sheet, according to a regulatory filing.",
            author="Sander Lutz", minutes_ago=85,
        )],
    ),
    TrainingSample(
        "real_coldcard_coindesk", "real", "likely_true",
        items=[_item(
            "Coldcard fallout shows up onchain as 210,000 bitcoin leaves old wallets",
            "rss_coindesk", "rss_coindesk",
            "https://www.coindesk.com/tech/2026/08/08/coldcard-fallout-onchain/",
            content="Onchain data shows 210,000 bitcoin moving from wallets that had been dormant since the early era, an analyst said, coinciding with concerns around a popular hardware wallet's security advisory.",
            author="Oliver Knight", minutes_ago=65,
        )],
    ),
    TrainingSample(
        "real_russia_crackdown_coindesk", "real", "likely_true",
        items=[_item(
            "Russia cracks down on unlicensed crypto exchanges it claims are linked to Ukraine",
            "rss_coindesk", "rss_coindesk",
            "https://www.coindesk.com/policy/2026/08/07/russia-crackdown-unlicensed-exchanges/",
            content="Russian authorities are blocking unlicensed crypto exchanges they say are used to fund Ukraine, a senior central bank official said, escalating enforcement against cross-border crypto transfers.",
            author="Sandali Handagama", minutes_ago=300,
        )],
    ),
    # ------------------------------------------------------------------ FAKE
    TrainingSample(
        "fake_onion_btc_barbecue", "fake", "fabricated",
        items=[_item(
            "Bitcoin Reaches $1 Million After All Remaining Coins Burned in Barbecue Accident",
            "theonion", "rss_yahoo_finance",
            "https://www.theonion.com/bitcoin-reaches-1-million-barbecue-accident",
            content="The global economy was thrown into chaos Friday after a backyard barbecue accident in suburban New Jersey destroyed the private keys to 99% of all bitcoin, sending the price of the remaining coins to $1 million.",
            author="The Onion Staff", minutes_ago=30,
        )],
    ),
    TrainingSample(
        "fake_babylon_bee_ripple", "fake", "fabricated",
        items=[_item(
            "Ripple Announces Purchase of Coinbase for $68 Billion in a Transaction Totally Made Up",
            "babylon_bee", "rss_yahoo_finance",
            "https://babylonbee.com/news/ripple-purchases-coinbase-68-billion",
            content="In a move that surprised absolutely no one who read the headline closely, Ripple announced it has purchased Coinbase for $68 billion. The bee reports on this fabricated transaction exclusively.",
            author="Babylon Bee Staff", minutes_ago=40,
        )],
    ),
    TrainingSample(
        "fake_satire_elon_doge", "fake", "fabricated",
        items=[_item(
            "Elon Musk announces Tesla will accept DOGE for car purchases (satire)",
            "x_stream", "x_stream",
            "https://x.com/dogefan2026/status/1",
            content="SATIRE: Elon Musk announces Tesla will accept DOGE for car purchases, effective immediately. This is a satirical post.",
            author="dogefan2026", minutes_ago=20, platform="x",
        )],
    ),
    TrainingSample(
        "fake_deepfake_powell", "fake", "fabricated",
        items=[_item(
            "Video shows Fed Chair Powell announcing CBDC replacing the dollar",
            "x_stream", "x_stream",
            "https://x.com/crypto_alertzz/status/2",
            content="VIDEO: Fed Chair Powell announces the dollar is replaced by a CBDC in 2027. Warning: this is a deepfake circulating on social media.",
            author="crypto_alertzz", minutes_ago=15, platform="x",
        )],
    ),
    TrainingSample(
        "fake_etf_tweet_coordination", "fake", "likely_false",
        items=[
            _item(
                "BREAKING: SEC just approved Bitcoin ETF!!!",
                "x_stream", "x_stream",
                "https://x.com/acct%02d/status/1" % i,
                content="BREAKING: SEC just approved Bitcoin ETF!!! Get in before it moons!!!",
                author=f"cryptoacct{i}", minutes_ago=8 - i // 8, platform="x",
            )
            for i in range(25)
        ],
    ),
    TrainingSample(
        "fake_binance_insolvent_social", "fake", "likely_false",
        items=[
            _item(
                "URGENT: Binance is insolvent, $9B gone, withdraw everything NOW",
                "x_stream", "x_stream",
                "https://x.com/whalealert_fake/status/3",
                content="URGENT: Binance is insolvent, $9B gone, withdraw everything NOW before it collapses!!",
                author="whalealert_fake", minutes_ago=12, platform="x",
            )
            for _ in range(6)
        ],
    ),
    TrainingSample(
        "fake_binance_insolvent_denied", "fake", "confirmed_false",
        items=[
            _item(
                "URGENT: Binance is insolvent, withdraw everything NOW",
                "x_stream", "x_stream",
                "https://x.com/whalealert_fake/status/3",
                content="URGENT: Binance is insolvent, withdraw everything NOW before it collapses!!",
                author="whalealert_fake", minutes_ago=12, platform="x",
            ),
            _item(
                "Binance denies insolvency rumors: 'Our balance sheet is fully audited'",
                "binance", "rss_cointelegraph",
                "https://www.binance.com/en/blog/company/binance-denies-insolvency-rumors",
                content="Binance has denied rumors of insolvency circulating on social media, saying the claims are baseless and its balance sheet has been audited by independent third parties. The company said user funds are fully backed 1:1.",
                author="Binance Team", minutes_ago=8,
            ),
        ],
    ),
    TrainingSample(
        "fake_sec_ban_denied", "fake", "confirmed_false",
        items=[
            _item(
                "SEC is banning ALL crypto in the US, effective tomorrow",
                "telegram", "telegram",
                "https://t.me/crypto_panic/77",
                content="SEC is banning ALL crypto in the US, effective tomorrow. Exchanges must halt operations within 48 hours!!",
                author="crypto_panic", minutes_ago=10, platform="telegram",
            ),
            _item(
                "SEC refutes false claims of an immediate crypto ban",
                "sec_gov", "rss_yahoo_finance",
                "https://www.sec.gov/news/statement/2026-08-08",
                content="The Securities and Exchange Commission issued a statement today refuting claims circulating online that it plans to ban cryptocurrencies. 'These reports are false,' the statement read. 'No such action is under consideration.'",
                author="SEC Press Office", minutes_ago=5,
            ),
        ],
    ),
    TrainingSample(
        "complex_ripple_coinbase_social", "complex", "unconfirmed",
        items=[
            _item(
                "Ripple acquires Coinbase for $68 billion in all-stock deal",
                "x_stream", "x_stream",
                "https://x.com/insider_crypto/status/4",
                content="Ripple acquires Coinbase for $68 billion in an all-stock deal. Sources close to the deal confirm. TO THE MOON.",
                author="insider_crypto", minutes_ago=60, platform="x",
            ),
            _item(
                "Ripple acquires Coinbase for $68 billion in all-stock deal",
                "rss_yahoo_finance", "rss_yahoo_finance",
                "https://finance.yahoo.com/quote/ripple-coinbase-deal/",
                content="Ripple acquires Coinbase for $68 billion in an all-stock deal, according to sources close to the deal.",
                author="Yahoo Staff", minutes_ago=55,
            ),
        ],
    ),
    TrainingSample(
        "fake_exchange_drained_telegram", "fake", "likely_false",
        items=[
            _item(
                "BREAKING: OKX drained, $3B stolen by hackers",
                "telegram", "telegram",
                "https://t.me/crypto_alerts_999/12",
                content="BREAKING: OKX drained, $3B stolen by hackers. All withdrawals frozen. Stay safe.",
                author="crypto_alerts_999", minutes_ago=9, platform="telegram",
            )
            for _ in range(5)
        ],
    ),
    TrainingSample(
        "fake_onion_reposted_yahoo", "fake", "fabricated",
        items=[
            _item(
                "Bitcoin Reaches $1 Million After All Remaining Coins Burned in Barbecue Accident",
                "rss_yahoo_finance", "rss_yahoo_finance",
                "https://finance.yahoo.com/news/bitcoin-1-million-barbecue/",
                content="In a satirical report originally published by The Onion, bitcoin reached $1 million after a barbecue accident destroyed 99% of all private keys. The satirical piece was widely shared on social media.",
                author="Yahoo Staff", minutes_ago=35,
            ),
            _item(
                "Bitcoin Reaches $1 Million After All Remaining Coins Burned in Barbecue Accident",
                "rss_yahoo_finance", "rss_yahoo_finance",
                "https://finance.yahoo.com/news/bitcoin-1-million-barbecue-2/",
                content="In a satirical report originally published by The Onion, bitcoin reached $1 million after a barbecue accident destroyed 99% of all private keys. The satirical piece was widely shared on social media.",
                author="Yahoo Staff", minutes_ago=34,
            ),
        ],
    ),
    TrainingSample(
        "fake_airdrop_phishing_social", "fake", "likely_false",
        items=[
            _item(
                "Claim your free BTC airdrop now - link in bio!!",
                "x_stream", "x_stream",
                "https://x.com/btc_giveaway_100/status/5",
                content="Claim your free BTC airdrop now - link in bio!! Limited time only!! 2x your deposit instantly!!",
                author="btc_giveaway_100", minutes_ago=11, platform="x",
            )
            for _ in range(10)
        ],
    ),
    TrainingSample(
        "fake_ai_press_release", "fake", "fabricated",
        items=[_item(
            "Ethereum Foundation liquidates entire treasury after 'strategic review'",
            "rss_yahoo_finance", "rss_yahoo_finance",
            "https://finance.yahoo.com/news/ethereum-foundation-liquidates-treasury/",
            content="A fabricated press release circulating online claims the Ethereum Foundation liquidated its entire treasury. The document contains obvious AI-generated language and was confirmed to be fake by the Foundation.",
            author="Yahoo Staff", minutes_ago=50,
        )],
    ),
    TrainingSample(
        "fake_celeb_endorse_scam", "fake", "likely_false",
        items=[
            _item(
                "Elon Musk endorses this new token - it will 100x",
                "telegram", "telegram",
                "https://t.me/elon_fan_club/3",
                content="Elon Musk endorses this new token - it will 100x. He tweeted about it (look at the screenshot, totally real).",
                author="elon_fan_club", minutes_ago=18, platform="telegram",
            )
            for _ in range(8)
        ],
    ),
    TrainingSample(
        "fake_hoax_btc_death", "fake", "fabricated",
        items=[_item(
            "Bitcoin officially declared dead by German regulator - hoax article debunked",
            "rss_yahoo_finance", "rss_yahoo_finance",
            "https://finance.yahoo.com/news/bitcoin-dead-hoax/",
            content="A hoax article claiming German regulators declared bitcoin legally dead spread briefly this morning. The hoax was debunked within hours, and no such declaration exists.",
            author="Yahoo Staff", minutes_ago=22,
        )],
    ),
    TrainingSample(
        "fake_exchange_freeze_reddit", "fake", "likely_false",
        items=[
            _item(
                "Gemini froze ALL withdrawals - users locked out",
                "reddit", "reddit",
                "https://www.reddit.com/r/cryptocurrency/comments/gemini_freeze/",
                content="Gemini froze ALL withdrawals - users locked out. Screenshots inside. Trust me bro.",
                author="u/anon_crypto_guy", minutes_ago=7, platform="reddit",
            )
            for _ in range(4)
        ],
    ),
    # -------------------------------------------------------------- COMPLEX
    TrainingSample(
        "complex_bloomberg_sources_say", "complex", "likely_true",
        items=[_item(
            "BlackRock in talks to launch tokenized money market fund, sources say",
            "bloomberg", "rss_yahoo_finance",
            "https://www.bloomberg.com/news/articles/2026-08-08/blackrock-tokenized-fund",
            content="BlackRock is in talks with partners to launch a tokenized money market fund, people familiar with the matter said. The talks are ongoing and no final decision has been made.",
            author="Emily Nicolle", minutes_ago=100,
        )],
    ),
    TrainingSample(
        "complex_reddit_question_bitstamp", "complex", "unconfirmed",
        items=[_item(
            "Is Bitstamp insolvent? Reddit thread asks after delayed withdrawals",
            "reddit", "reddit",
            "https://www.reddit.com/r/Bitstamp/comments/insolvency/",
            content="Is Bitstamp insolvent? A Reddit thread asks whether delayed withdrawals are a sign of trouble, citing only personal anecdote.",
            author="u/concerned_trader", minutes_ago=25, platform="reddit",
        )],
    ),
    TrainingSample(
        "complex_deny_vs_support", "complex", "disputed",
        items=[
            _item(
                "Coinbase confirms it is in talks to buy bankrupt exchange",
                "x_stream", "x_stream",
                "https://x.com/cointalk_official/status/6",
                content="Coinbase confirms it is in talks to buy bankrupt exchange FTX Europe. Sources confirm.",
                author="cointalk_official", minutes_ago=80, platform="x",
            ),
            _item(
                "Coinbase denies acquisition talks with any bankrupt exchange",
                "rss_cointelegraph", "rss_cointelegraph",
                "https://cointelegraph.com/news/coinbase-denies-acquisition-talks",
                content="Coinbase has denied reports of acquisition talks with a bankrupt exchange, calling the claims baseless in a statement to Cointelegraph.",
                author="Ana Paula Pereira", minutes_ago=60,
            ),
        ],
    ),
    TrainingSample(
        "complex_single_yahoo", "complex", "unconfirmed",
        items=[_item(
            "Wayfair Q2 Earnings Call Highlights",
            "rss_yahoo_finance", "rss_yahoo_finance",
            "https://finance.yahoo.com/news/wayfair-q2-earnings-call-highlights/",
            content="Wayfair's Q2 earnings call highlighted improving gross margins and a cautious outlook for home goods demand.",
            author="Yahoo Staff", minutes_ago=140,
        )],
    ),
    TrainingSample(
        "complex_official_plus_established", "complex", "confirmed_true",
        items=[
            _item(
                "Treasury Sanctions Mixin Network for North Korean Money Laundering",
                "sec_gov", "rss_yahoo_finance",
                "https://home.treasury.gov/news/press-releases/treasury-sanctions-mixin",
                content="The U.S. Department of the Treasury's OFAC sanctioned Mixin Network today for laundering funds for North Korean cyber actors, freezing its assets in U.S. jurisdictions.",
                author="Treasury Press Office", minutes_ago=400,
            ),
            _item(
                "Treasury sanctions crypto mixer Mixin Network for North Korea links",
                "reuters", "rss_yahoo_finance",
                "https://www.reuters.com/technology/treasury-sanctions-mixin-network-2026-08-07/",
                content="The U.S. Treasury sanctioned crypto mixing service Mixin Network for its role in laundering proceeds for North Korean hackers, the department said Wednesday.",
                author="Raphael Satter", minutes_ago=395,
            ),
        ],
    ),
    TrainingSample(
        "complex_social_plus_coindesk_investigating", "complex", "unconfirmed",
        items=[
            _item(
                "Circle is insolvent and Tether is next - insider leak",
                "x_stream", "x_stream",
                "https://x.com/circle_watch/status/7",
                content="Circle is insolvent and Tether is next - insider leak from ex-employee. USDC depeg incoming!!",
                author="circle_watch", minutes_ago=90, platform="x",
            ),
            _item(
                "Coindesk is investigating social media claims about Circle's finances",
                "rss_coindesk", "rss_coindesk",
                "https://www.coindesk.com/business/2026/08/08/circle-insolvency-claims/",
                content="Coindesk is looking into social media claims that stablecoin issuer Circle is insolvent. Circle has not commented.",
                author="Cheyenne Ligon", minutes_ago=70,
            ),
        ],
    ),
    TrainingSample(
        "complex_coindesk_report_binance_deny", "complex", "disputed",
        items=[
            _item(
                "Binance may exit several European markets after license review",
                "rss_coindesk", "rss_coindesk",
                "https://www.coindesk.com/policy/2026/08/08/binance-europe-license-review/",
                content="Binance may exit several European markets after a license review, Coindesk reports, citing two people familiar with internal deliberations.",
                author="Jack Schickler", minutes_ago=95,
            ),
            _item(
                "Binance says reports of European exit are baseless",
                "rss_cointelegraph", "rss_cointelegraph",
                "https://cointelegraph.com/news/binance-denies-european-exit",
                content="Binance has rejected reports it plans to exit European markets, calling them baseless and reaffirming its commitment to EU compliance.",
                author="Ana Paula Pereira", minutes_ago=75,
            ),
        ],
    ),
    TrainingSample(
        "complex_aggregator_copies_social", "complex", "unconfirmed",
        items=[
            _item(
                "PayPal to launch its own stablecoin next month - report",
                "x_stream", "x_stream",
                "https://x.com/fintech_rumors/status/8",
                content="PayPal to launch its own stablecoin next month - report. Details scarce.",
                author="fintech_rumors", minutes_ago=110, platform="x",
            ),
            _item(
                "PayPal to launch its own stablecoin next month - report",
                "rss_yahoo_finance", "rss_yahoo_finance",
                "https://finance.yahoo.com/news/paypal-stablecoin-report/",
                content="PayPal to launch its own stablecoin next month, according to a report circulating on social media. PayPal has not commented.",
                author="Yahoo Staff", minutes_ago=105,
            ),
        ],
    ),
    TrainingSample(
        "complex_official_plus_social_cheer", "complex", "confirmed_true",
        items=[
            _item(
                "SEC Approves Spot Bitcoin Exchange-Traded Products",
                "sec_gov", "rss_yahoo_finance",
                "https://www.sec.gov/news/press-release/2026-4",
                content="The Securities and Exchange Commission today approved the listing and trading of spot bitcoin exchange-traded products on national securities exchanges.",
                author="SEC Press Office", minutes_ago=320,
            ),
            _item(
                "LETS GOOOO!!! Bitcoin ETF APPROVED!!!",
                "x_stream", "x_stream",
                "https://x.com/bitcoin_army/status/9",
                content="LETS GOOOO!!! Bitcoin ETF APPROVED!!! Bullish forever!!!",
                author="bitcoin_army", minutes_ago=315, platform="x",
            ),
        ],
    ),
    TrainingSample(
        "complex_two_official", "complex", "confirmed_true",
        items=[
            _item(
                "Fed Chair Powell: 'No CBDC issuance under consideration without Congress'",
                "sec_gov", "rss_yahoo_finance",
                "https://www.federalreserve.gov/newsevents/speech/powell-cbdc-2026-08-06.htm",
                content="In testimony before the Senate Banking Committee, Federal Reserve Chair Jerome Powell said the Fed would not issue a CBDC without clear congressional authorization.",
                author="Federal Reserve", minutes_ago=500,
            ),
            _item(
                "Treasury Secretary: Administration has 'no plans' to restrict self-custody wallets",
                "sec_gov", "rss_yahoo_finance",
                "https://home.treasury.gov/news/press-releases/treasury-self-custody",
                content="Treasury Secretary said the administration has no plans to restrict self-custody crypto wallets, addressing rumors circulating in the community.",
                author="Treasury Press Office", minutes_ago=450,
            ),
        ],
    ),
    TrainingSample(
        "complex_x_rumor_crypto_confirm", "complex", "likely_true",
        items=[
            _item(
                "Samsung to add crypto wallet to Galaxy phones - insider",
                "x_stream", "x_stream",
                "https://x.com/tech_leaks_daily/status/10",
                content="Samsung to add crypto wallet to Galaxy phones - insider leak from supply chain source.",
                author="tech_leaks_daily", minutes_ago=130, platform="x",
            ),
            _item(
                "Samsung confirms native crypto wallet for Galaxy S series",
                "rss_coindesk", "rss_coindesk",
                "https://www.coindesk.com/tech/2026/08/08/samsung-crypto-wallet-galaxy/",
                content="Samsung confirmed Thursday that its next Galaxy flagship will ship with a native crypto wallet, following months of speculation.",
                author="Nelson Wang", minutes_ago=115,
            ),
        ],
    ),
    TrainingSample(
        "complex_opinion_quote", "complex", "unconfirmed",
        items=[_item(
            "Bitcoin will never fall below $60K again: Nansen founder",
            "rss_cointelegraph", "rss_cointelegraph",
            "https://cointelegraph.com/news/bitcoin-never-below-60k-nansen",
            content="The founder of analytics firm Nansen said bitcoin will never fall below $60,000 again, citing institutional adoption as a structural floor. The claim is a personal forecast, not an established fact.",
            author="Brayden Lindrea", minutes_ago=150,
        )],
    ),
]


def by_name(name: str) -> TrainingSample:
    return next(s for s in SAMPLES if s.name == name)


def groups() -> dict[str, list[TrainingSample]]:
    out: dict[str, list[TrainingSample]] = {"real": [], "fake": [], "complex": []}
    for s in SAMPLES:
        out[s.group].append(s)
    return out
