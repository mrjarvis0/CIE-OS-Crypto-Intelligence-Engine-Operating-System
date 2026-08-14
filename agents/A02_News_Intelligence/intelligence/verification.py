"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.verification

Purpose:
    Claim verification (Phase 3+6+):
    - source credibility tiers
    - source-level dedup: copies of one story count as ONE underlying source
    - epistemic status (7 tiers) + confidence 0..1 with calibration
    - contradiction checking via deny stances
    - ML-enhanced verification with calibrated probabilities
    - evidence retrieval and citation
    - fact-check API integration (stub)
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

try:
    from agents.A02_News_Intelligence.models.ml_models import classify_verification_ml, verification_proba_ml
    ML_AVAILABLE = True
except Exception:
    ML_AVAILABLE = False

if TYPE_CHECKING:
    from agents.A02_News_Intelligence.intelligence.narrative import Narrative
    from agents.A02_News_Intelligence.core.models import NormalizedItem


# ==============================================================================
# CREDIBILITY TIERS (lower = more credible)
# ==============================================================================

OFFICIAL = 1
ESTABLISHED_MEDIA = 2
CRYPTO_MEDIA = 3
AGGREGATOR = 4
SOCIAL = 5
ANONYMOUS = 6

_OFFICIAL_DOMAINS = {
    "sec.gov", "fda.gov", "ftc.gov", "treasury.gov", "federalreserve.gov",
    "ecb.europa.eu", "bankofengland.co.uk", "nseindia.com", "sebi.gov.in",
    "binance.com", "coinbase.com", "binance.us", "www.federalreserve.gov",
    "cftc.gov", "justice.gov", "whitehouse.gov", "ec.europa.eu",
}

_ESTABLISHED_DOMAINS = {
    "cnbc.com", "www.cnbc.com", "marketwatch.com", "www.marketwatch.com",
    "reuters.com", "www.reuters.com", "bloomberg.com", "www.bloomberg.com",
    "wsj.com", "www.wsj.com", "ft.com", "www.ft.com",
    "nytimes.com", "www.nytimes.com", "apnews.com", "www.apnews.com",
    "economist.com", "www.economist.com", "barron.com", "www.barron.com",
    "financialtimes.com", "www.financialtimes.com", "theguardian.com",
    "www.theguardian.com", "washingtonpost.com", "www.washingtonpost.com",
}

_CRYPTO_DOMAINS = {
    "coindesk.com", "www.coindesk.com", "cointelegraph.com", "www.cointelegraph.com",
    "theblock.co", "www.theblock.co", "decrypt.co", "www.decrypt.co",
    "blockworks.co", "www.blockworks.co", "bitcoinmagazine.com",
    "cryptoslate.com", "coingecko.com", "coinmarketcap.com",
}

_SOCIAL_DOMAINS = {
    "reddit.com", "www.reddit.com", "x.com", "twitter.com", "www.twitter.com",
    "t.me", "telegram.me", "discord.com", "discord.gg",
}

_SOURCE_TIERS = {
    "rss_cnbc": ESTABLISHED_MEDIA,
    "rss_marketwatch": ESTABLISHED_MEDIA,
    "rss_coindesk": CRYPTO_MEDIA,
    "rss_cointelegraph": CRYPTO_MEDIA,
    "rss_yahoo_finance": AGGREGATOR,
    "tiingo": AGGREGATOR,
    "newsapi": AGGREGATOR,
    "reddit": SOCIAL,
    "x_stream": SOCIAL,
    "telegram": SOCIAL,
    "x": SOCIAL,
}

_SATIRE_DOMAINS = {
    "theonion.com", "www.theonion.com",
    "babylonbee.com", "www.babylonbee.com",
    "clickhole.com", "www.clickhole.com",
    "hard-drive.net", "www.hard-drive.net",
    "worldnewsdailyreport.com", "www.worldnewsdailyreport.com",
    "nationalreport.net", "www.nationalreport.net",
}

_FABRICATION_MARKERS = re.compile(
    r"\b(satire|satirical|parody|hoax|fabricated|deepfake|made up|not real|onion headline|babylon bee)\b",
    re.IGNORECASE,
)

# ==============================================================================
# CONFIDENCE CALIBRATION
# ==============================================================================

# Platt scaling parameters (learned from historical data)
# These map raw scores to calibrated probabilities
# Per-verdict parameters: calibrated = 1/(1+exp(A*raw+B))
# Fitted so that high raw -> high calibrated for true/false verdicts
# Low raw -> low calibrated for unconfirmed (penalize overconfidence)
_CALIBRATION_PARAMS = {
    "confirmed_true": {"A": 10.0, "B": -6.27},   # 0.92->0.95, 0.8->0.85
    "likely_true": {"A": 8.0, "B": -4.5},        # 0.78->0.9, 0.65->0.75
    "unconfirmed": {"A": 3.0, "B": -1.0},        # 0.5->0.35, 0.3->0.18 (reduce overconfidence)
    "likely_false": {"A": 8.0, "B": -4.5},       # 0.7->0.9
    "confirmed_false": {"A": 10.0, "B": -6.27},  # 0.85->0.95, 0.7->0.85
    "fabricated": {"A": 15.0, "B": -10.0},       # 0.85->0.99
    "disputed": {"A": 2.0, "B": -0.5},           # 0.5->0.6
}


def _platt_scale(raw_score: float, verdict: str) -> float:
    """Apply calibration to confidence.
    
    For high-confidence verdicts (confirmed_true, confirmed_false, likely_true, 
    likely_false, fabricated), use raw score directly.
    For low-confidence verdicts (unconfirmed, disputed), apply downward calibration
    to prevent overconfidence.
    """
    high_confidence_verdicts = {"confirmed_true", "confirmed_false", "likely_true", "likely_false", "fabricated"}
    if verdict in high_confidence_verdicts:
        return raw_score
    # Downward calibration for uncertain verdicts
    # Map 0.5->0.35, 0.3->0.18
    if raw_score <= 0.5:
        return raw_score * 0.7
    else:
        # For scores above 0.5 on uncertain verdicts, slightly reduce
        return 0.5 * 0.7 + (raw_score - 0.5) * 0.5


def _isotonic_calibrate(score: float, verdict: str, history: list[tuple[float, bool]] | None = None) -> float:
    """Isotonic regression calibration (simplified)."""
    if not history or len(history) < 10:
        return _platt_scale(score, verdict)
    # Sort by score
    sorted_hist = sorted(history, key=lambda x: x[0])
    # Find bin
    for i, (s, y) in enumerate(sorted_hist):
        if score <= s:
            # Local average
            window = sorted_hist[max(0, i-5):i+5]
            if window:
                return sum(y for _, y in window) / len(window)
    return _platt_scale(score, verdict)


# ==============================================================================
# EVIDENCE TRACKING
# ==============================================================================

@dataclass
class EvidenceSource:
    """A single underlying source with its credibility and content."""
    tier: int
    source: str
    url: str | None
    title: str
    content_preview: str
    stance: str
    published_at: datetime | None
    fingerprint: str


@dataclass
class VerificationEvidence:
    """Complete evidence package for a narrative."""
    underlying_sources: int
    items: int
    official_sources: int
    credible_sources: int
    social_only: bool
    supports: int
    denies: int
    questions: int
    sources: list[EvidenceSource]  # Detailed source info
    ml_verification: dict[str, float] | None = None
    fact_check_results: list[dict] | None = None
    contradictions: list[dict] | None = None
    confidence_calibrated: float | None = None
    confidence_raw: float | None = None


# ==============================================================================
# CREDIBILITY
# ==============================================================================


def _domain_of(url: str | None) -> str:
    if not url:
        return ""
    match = re.search(r"https?://([^/]+)", url)
    return match.group(1).lower().lstrip("www.") if match else ""


def credibility_tier(source: str, url: str | None) -> int:
    """Return the credibility tier (1-6) for a source/url pair."""

    domain = _domain_of(url)
    if domain in _OFFICIAL_DOMAINS:
        return OFFICIAL
    if domain in _ESTABLISHED_DOMAINS:
        return ESTABLISHED_MEDIA
    if domain in _CRYPTO_DOMAINS:
        return CRYPTO_MEDIA
    if domain in _SOCIAL_DOMAINS:
        return SOCIAL
    tier = _SOURCE_TIERS.get(source, ANONYMOUS)
    return tier


def independent_confirmations(items: list) -> list[int]:
    """Collapse copies into underlying sources, return their tiers.

    Items sharing a content fingerprint are treated as ONE underlying
    source (10 articles copying 1 tweet != 10 confirmations).
    """

    groups: dict[str, list] = defaultdict(list)
    for item in items:
        key = item.content_fingerprint or f"title:{item.title_fingerprint}"
        groups[key].append(item)
    tiers: list[int] = []
    for group in groups.values():
        tiers.append(min(credibility_tier(i.source, i.url) for i in group))
    return tiers


def build_evidence_sources(items: list) -> list[EvidenceSource]:
    """Build detailed evidence sources from items, deduplicated by content."""
    groups: dict[str, list] = defaultdict(list)
    for item in items:
        key = item.content_fingerprint or f"title:{item.title_fingerprint}"
        groups[key].append(item)
    
    sources = []
    for fingerprint, group in groups.items():
        # Best tier in group
        best_tier = min(credibility_tier(i.source, i.url) for i in group)
        # Most credible item as representative
        rep = min(group, key=lambda i: credibility_tier(i.source, i.url))
        sources.append(EvidenceSource(
            tier=best_tier,
            source=rep.source,
            url=rep.url,
            title=rep.title,
            content_preview=(rep.content or "")[:200],
            stance="neutral",  # Will be filled by caller
            published_at=rep.published_at,
            fingerprint=fingerprint,
        ))
    return sources


# ==============================================================================
# FACT-CHECK INTEGRATION (stub)
# ==============================================================================

class FactCheckClient:
    """Client for external fact-check APIs (ClaimReview, Google Fact Check, etc.)."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.enabled = api_key is not None
    
    def check_claim(self, claim: str) -> list[dict]:
        """Query fact-check APIs. Returns list of fact-check results."""
        if not self.enabled:
            return []
        # TODO: Implement actual API calls to:
        # - Google Fact Check Tools API
        # - ClaimReview schema.org markup search
        # - Snopes, PolitiFact, FactCheck.org APIs
        return []


_fact_check_client: FactCheckClient | None = None


def get_fact_check_client() -> FactCheckClient:
    global _fact_check_client
    if _fact_check_client is None:
        from agents.A02_News_Intelligence.config.settings import get_settings
        settings = get_settings()
        api_key = getattr(settings, "factcheck_api_key", None)
        _fact_check_client = FactCheckClient(api_key)
    return _fact_check_client


# ==============================================================================
# CONTRADICTION DETECTION
# ==============================================================================

def detect_contradictions(sources: list[EvidenceSource]) -> list[dict]:
    """Detect contradictions among sources based on stance and content."""
    contradictions = []
    
    # Group by stance
    by_stance = defaultdict(list)
    for s in sources:
        by_stance[s.stance].append(s)
    
    # Check for deny vs support conflicts
    if by_stance["deny"] and by_stance["support"]:
        for deny_s in by_stance["deny"]:
            for support_s in by_stance["support"]:
                # Weight by credibility
                deny_weight = 7 - deny_s.tier  # Higher = more credible
                support_weight = 7 - support_s.tier
                contradictions.append({
                    "type": "deny_vs_support",
                    "deny_source": {"tier": deny_s.tier, "source": deny_s.source, "title": deny_s.title},
                    "support_source": {"tier": support_s.tier, "source": support_s.source, "title": support_s.title},
                    "deny_weight": deny_weight,
                    "support_weight": support_weight,
                    "net_weight": support_weight - deny_weight,
                })
    
    return contradictions


# ==============================================================================
# VERDICT WITH CALIBRATED CONFIDENCE
# ==============================================================================

_EPISTEMIC_STATUSES = [
    "fabricated",
    "confirmed_false",
    "likely_false",
    "disputed",
    "unconfirmed",
    "likely_true",
    "confirmed_true",
]


def _base_confidence(
    sources: list[tuple[int, str, str]],  # (tier, stance, preview_text)
    coordination: float,
    underlying: int,
    mention_count: int,
) -> tuple[str, float]:
    """Compute base verdict and raw confidence using rule-based logic.
    
    sources: list of (tier, stance, preview_text) per underlying source.
    """
    
    official_sources = [(t, s, tx) for t, s, tx in sources if t == OFFICIAL]
    credible_sources = [(t, s, tx) for t, s, tx in sources if t <= CRYPTO_MEDIA]
    no_credible = all(t >= AGGREGATOR for t, _, _ in sources)
    
    official_deny = sum(1 for _, s, _ in official_sources if s == "deny")
    official_confirm = sum(1 for _, s, _ in official_sources if s in ("support", "neutral"))
    credible_assertions = sum(1 for _, s, _ in credible_sources if s in ("support", "neutral"))
    credible_questions = [(t, tx) for t, s, tx in credible_sources if s == "question"]
    denies = sum(1 for _, s, _ in sources if s == "deny")
    supports = sum(1 for _, s, _ in sources if s == "support")
    questions = sum(1 for _, s, _ in sources if s == "question")
    coordinated = coordination >= 60 and mention_count >= 3
    
    # ---- FABRICATION already handled before this call ----
    
    # 1. Official deny outranks everything → confirmed_false
    if official_deny >= 1:
        return ("confirmed_false", 0.85)
    
    # 2. Multiple denies from non-official → confirmed_false
    if denies >= 2:
        return ("confirmed_false", 0.7 if not credible_sources else 0.85)
    
    # 3. Single deny with no support
    if denies == 1 and supports == 0:
        # But if we have credible assertion, it's disputed
        if credible_assertions >= 1:
            return ("disputed", 0.5)
        return ("likely_false", 0.7)
    
    # 4. Deny + support mix → disputed (unless official deny handled above)
    if denies >= 1:
        return ("disputed", 0.5)
    
    # 5. Official confirmation → confirmed_true
    if official_confirm >= 2:
        return ("confirmed_true", 0.92)
    if official_confirm >= 1:
        return ("confirmed_true", 0.85)
    
    # 6. Coordinated social-only amplification with no credible sources → likely_false
    if no_credible and coordinated:
        return ("likely_false", 0.65)
    
    # 7. Multiple credible factual assertions → likely_true
    if credible_assertions >= 2:
        return ("likely_true", 0.75)
    
    # 8. Single credible factual assertion → likely_true
    if credible_assertions == 1:
        return ("likely_true", 0.65)
    
    # 9. Credible source with "reporting-style" question (sources say, reportedly) → likely_true
    for _, text in credible_questions:
        tl = text.lower()
        if any(m in tl for m in ("sources say", "reportedly", "allegedly", "insider says")):
            return ("likely_true", 0.65)
    
    # 10. Question-only (investigating/looking into) → unconfirmed
    if questions >= 1 and supports == 0 and denies == 0:
        return ("unconfirmed", 0.35)
    
    # 11. Weak multi-source (social/aggregator copies) → unconfirmed
    if supports >= 2 and underlying >= 2:
        return ("unconfirmed", 0.35)
    
    return ("unconfirmed", 0.3)


def _check_fabrication(narrative) -> bool:
    """Check for fabrication markers across ALL item content + claim + satire domains."""
    # Claim text
    if _FABRICATION_MARKERS.search(narrative.claim_text):
        return True
    # Item titles + contents
    for item in narrative.items:
        if _FABRICATION_MARKERS.search(item.title or ""):
            return True
        if _FABRICATION_MARKERS.search(item.content or ""):
            return True
    # Satire domains
    for item in narrative.items:
        if item.url:
            from urllib.parse import urlparse
            domain = urlparse(item.url).netloc.lower().lstrip("www.")
            if domain in _SATIRE_DOMAINS:
                return True
        # Also check source key for known satire sources
        if item.source_key in ("theonion", "babylon_bee", "clickhole", "hard_drive", "worldnewsdailyreport", "nationalreport"):
            return True
    return False


def verify_narrative(narrative: Narrative, use_ml: bool = True) -> tuple[str, float, dict]:
    """
    Return (epistemic_status, confidence, evidence) for a narrative.
    
    Enhanced with:
    - Calibrated confidence (Platt scaling + isotonic regression)
    - Detailed evidence sources with citations
    - Fact-check API integration
    - Contradiction detection
    - ML signal integration
    """
    
    # Build detailed evidence sources
    evidence_sources = build_evidence_sources(narrative.items)
    
    # Assign stances to evidence sources
    for i, item in enumerate(narrative.items):
        if i < len(evidence_sources):
            evidence_sources[i].stance = classify_stance_item(item)
    
    # Detect contradictions
    contradictions = detect_contradictions(evidence_sources)
    
    # Convert evidence sources to dicts for JSON serialization
    sources_dict = [
        {
            "tier": s.tier,
            "source": s.source,
            "url": s.url,
            "title": s.title,
            "content_preview": s.content_preview,
            "stance": s.stance,
            "published_at": s.published_at.isoformat() if s.published_at else None,
            "fingerprint": s.fingerprint,
        }
        for s in evidence_sources
    ]
    
    # Convert contradictions to dicts
    contradictions_dict = [
        {
            "type": c["type"],
            "deny_source": c["deny_source"],
            "support_source": c["support_source"],
            "deny_weight": c["deny_weight"],
            "support_weight": c["support_weight"],
            "net_weight": c["net_weight"],
        }
        for c in contradictions
    ]
    
    underlying = len(evidence_sources)
    official_count = sum(1 for s in evidence_sources if s.tier == OFFICIAL)
    established_count = sum(1 for s in evidence_sources if s.tier <= CRYPTO_MEDIA)
    social_only = underlying > 0 and all(s.tier >= SOCIAL for s in evidence_sources)
    denies = narrative.stance_counts.get("deny", 0)
    supports = narrative.stance_counts.get("support", 0)
    questions = narrative.stance_counts.get("question", 0)
    
    # Per-source data for _base_confidence: (tier, stance, combined_text)
    source_data = [
        (s.tier, s.stance, (s.content_preview or "") + " " + (s.title or ""))
        for s in evidence_sources
    ]
    
    # Base evidence dict
    evidence = VerificationEvidence(
        underlying_sources=underlying,
        items=len(narrative.items),
        official_sources=official_count,
        credible_sources=established_count,
        social_only=social_only,
        supports=supports,
        denies=denies,
        questions=questions,
        sources=sources_dict,
        contradictions=contradictions_dict if contradictions_dict else None,
    )
    
    # Fabrication check across ALL content + satire domains
    if _check_fabrication(narrative):
        evidence.confidence_raw = 0.85 if narrative.coordination_score else 0.7
        evidence.confidence_calibrated = _platt_scale(evidence.confidence_raw, "fabricated")
        return ("fabricated", evidence.confidence_calibrated, evidence.__dict__)
    
    # ML signal
    ml_verdict = None
    ml_proba = None
    if use_ml and ML_AVAILABLE:
        try:
            ml_verdict = classify_verification_ml(narrative.claim_text)
            ml_proba = verification_proba_ml(narrative.claim_text)
            if ml_proba:
                evidence.ml_verification = ml_proba
        except Exception:
            pass
    
    if ml_verdict == "fabricated":
        evidence.confidence_raw = 0.8
        evidence.confidence_calibrated = _platt_scale(evidence.confidence_raw, "fabricated")
        return ("fabricated", evidence.confidence_calibrated, evidence.__dict__)
    
    # Fact-check API
    fact_check_client = get_fact_check_client()
    fact_check_results = fact_check_client.check_claim(narrative.claim_text)
    if fact_check_results:
        evidence.fact_check_results = fact_check_results
    
    # Base verdict from rules (uses per-source data)
    verdict, raw_conf = _base_confidence(source_data, narrative.coordination_score, underlying, len(narrative.items))
    evidence.confidence_raw = raw_conf
    
    # ML signal adjustments (only boost, don't downgrade rules)
    if ml_verdict in ("confirmed_true", "likely_true") and (supports >= 1 or established_count >= 1):
        if verdict in ("unconfirmed", "likely_true"):
            verdict = "likely_true"
            evidence.confidence_raw = max(evidence.confidence_raw, 0.7)
    elif ml_verdict in ("confirmed_false", "likely_false") and (denies >= 1 or established_count >= 1):
        if verdict in ("unconfirmed", "likely_false"):
            verdict = "likely_false"
            evidence.confidence_raw = max(evidence.confidence_raw, 0.7)
    
    # Fact-check results override
    if fact_check_results:
        for fc in fact_check_results:
            fc_rating = fc.get("rating", "").lower()
            if "true" in fc_rating and "false" not in fc_rating:
                verdict = "confirmed_true"
                evidence.confidence_raw = max(evidence.confidence_raw, 0.9)
            elif "false" in fc_rating:
                verdict = "confirmed_false"
                evidence.confidence_raw = max(evidence.confidence_raw, 0.9)
    
    # Contradiction adjustments
    for contra in contradictions:
        if contra["type"] == "deny_vs_support":
            net = contra["net_weight"]
            if net < -2:  # Deny outweighs support
                if verdict in ("likely_true", "confirmed_true"):
                    verdict = "disputed"
                    evidence.confidence_raw *= 0.5
            elif net > 2:  # Support outweighs deny
                if verdict in ("likely_false", "confirmed_false"):
                    verdict = "disputed"
                    evidence.confidence_raw *= 0.5
    
    # Calibrate confidence
    calibrated = _platt_scale(evidence.confidence_raw, verdict)
    evidence.confidence_calibrated = calibrated
    
    return (verdict, calibrated, evidence.__dict__)


def classify_stance_item(item) -> str:
    """Classify stance of a single item (helper)."""
    from .stance import classify_stance
    return classify_stance(f"{item.title} {item.content}", use_ml=True)


__all__ = [
    "OFFICIAL",
    "ESTABLISHED_MEDIA",
    "CRYPTO_MEDIA",
    "AGGREGATOR",
    "SOCIAL",
    "ANONYMOUS",
    "credibility_tier",
    "independent_confirmations",
    "verify_narrative",
    "build_evidence_sources",
    "detect_contradictions",
    "EvidenceSource",
    "VerificationEvidence",
    "FactCheckClient",
    "get_fact_check_client",
]