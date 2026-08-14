"""
Tools :: Routing :: Intent
==========================

Extracts execution intent from a request. Intent drives every downstream
routing decision: which tools, agents, models and policies apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["Intent", "INTENT_TYPES", "IntentExtractor"]

INTENT_TYPES = [
    "information_retrieval",
    "blockchain_analysis",
    "smart_contract_audit",
    "news_analysis",
    "social_intelligence",
    "image_analysis",
    "web_search",
    "trading_analysis",
    "multi_step_investigation",
]

_KEYWORDS: Dict[str, List[str]] = {
    "information_retrieval": ["find", "get", "what is", "list", "lookup", "retrieve", "search for", "fetch"],
    "blockchain_analysis": ["blockchain", "chain", "block", "on-chain", "onchain", "address", "transaction", "block explorer", "rpc"],
    "smart_contract_audit": ["audit", "smart contract", "contract review", "vulnerability", "reentrancy", "solidity", "exploit"],
    "news_analysis": ["news", "headline", "press", "announcement", "rumor", "update on"],
    "social_intelligence": ["social", "twitter", "x post", "telegram", "sentiment", "community", "discord"],
    "image_analysis": ["image", "picture", "screenshot", "visual", "ocr", "logo"],
    "web_search": ["web search", "browse", "website", "internet", "google", "html", "webpage"],
    "trading_analysis": ["trade", "trading", "price", "chart", "candle", "signal", "position", "entry", "exit", "pnl"],
    "multi_step_investigation": ["investigate", "trace", "follow the money", "investigate this", "deep dive", "full analysis", "check and", "then"],
}


@dataclass
class Intent:
    """Classified execution intent for a request."""

    request: str
    primary: str = "information_retrieval"
    secondary: List[str] = field(default_factory=list)
    confidence: float = 0.0
    keywords: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request,
            "primary": self.primary,
            "secondary": list(self.secondary),
            "confidence": round(self.confidence, 4),
            "keywords": list(self.keywords),
            "targets": list(self.targets),
        }


class IntentExtractor:
    """Keyword-driven intent classifier (deterministic, stdlib-only)."""

    def classify(self, request: str) -> Intent:
        text = " " + request.lower().strip() + " "
        hits: Dict[str, List[str]] = {}
        for intent, keywords in _KEYWORDS.items():
            found = [kw for kw in keywords if kw in text]
            if found:
                hits[intent] = found

        if not hits:
            return Intent(request=request, primary="information_retrieval", confidence=0.0, targets=["tool"])

        ranked = sorted(hits.items(), key=lambda item: len(item[1]), reverse=True)
        primary = ranked[0][0]
        secondary = [name for name, _ in ranked[1:]]
        confidence = min(0.99, len(ranked[0][1]) * 0.25 + 0.2)
        return Intent(
            request=request,
            primary=primary,
            secondary=secondary,
            confidence=round(confidence, 4),
            keywords=ranked[0][1],
            targets=_default_targets(primary),
        )


def _default_targets(intent: str) -> List[str]:
    if intent == "smart_contract_audit":
        return ["tool", "agent", "workflow"]
    if intent == "multi_step_investigation":
        return ["workflow", "agent", "tool"]
    if intent == "blockchain_analysis":
        return ["adapter", "rpc", "tool"]
    if intent == "image_analysis":
        return ["model", "tool"]
    if intent == "web_search":
        return ["tool", "mcp"]
    return ["tool", "agent"]