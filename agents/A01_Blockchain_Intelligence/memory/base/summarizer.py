"""
Memory Summarizer — Memory Intelligence Engine for CIE-OS.

A summary is not the goal. Knowledge is the goal.

This engine converts raw conversation into structured, durable memory:
facts, preferences, decisions, tasks, events, topics, intents and entities.
The summarizer is the ingestion + extraction + consolidation + promotion
layer of the memory stack. It does not re-implement long-term or vector
storage; it builds knowledge and delegates persistence to the existing
LongTermMemory / VectorMemory engines.

Pipeline
--------
    conversation
        -> conversation analysis (important / unimportant / noise / duplicate)
        -> message classification (question / answer / code / error / ...)
        -> topic detection
        -> intent detection
        -> entity extraction
        -> fact extraction
        -> preference extraction
        -> decision extraction
        -> task extraction
        -> event extraction
        -> importance scoring
        -> confidence estimation
        -> duplicate detection
        -> chunk management
        -> multi-level summary generation
        -> context compression
        -> knowledge builder
        -> validation & quality scoring
        -> promotion candidates (LongTermMemory / VectorMemory)
        -> events, metrics, diagnostics

Design principles
-----------------
* Deterministic-first: regex + dictionary extraction covers most cases with
  zero LLM calls. An optional generator callable can be supplied for
  high-quality extractive/abstractive summarization.
* Decoupled persistence: promotion only produces candidate records; the
  caller decides where they land.
* Observable: every stage emits events, updates metrics and can be traced
  through diagnostics.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Sequence

from .memory import (
    BaseMemory,
    MemoryEntry,
    MemoryMetadata,
    MemoryPriority,
)

LOGGER = logging.getLogger(__name__)

# ============================================================
# Public Constants
# ============================================================

DEFAULT_NAMESPACE = "default"

DEFAULT_MAX_TOKENS = 4096

DEFAULT_CHUNK_SIZE = 1200

DEFAULT_CHUNK_OVERLAP = 120

DEFAULT_COMPRESSION_RATIO = 0.10

DEFAULT_PROMOTION_THRESHOLD = 55.0

IMPORTANCE_MAX = 100.0

ADDRESS_PATTERN = re.compile(
    r"\b(?:0x[a-fA-F0-9]{40}|"
    r"bc1[ac-hj-np-z02-9]{11,71}|"
    r"[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b"
)

DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?)\b"
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

TOKEN_SPLIT_RE = re.compile(r"\s+")

# ============================================================
# Topic & Intent Knowledge Base
# ============================================================

TOPIC_KEYWORDS: dict[str, set[str]] = {
    "blockchain": {
        "blockchain", "ledger", "block", "consensus", "miner",
        "node", "hash", "immutable", "decentralized", "layer1",
    },
    "crypto": {
        "crypto", "coin", "token", "altcoin", "btc", "eth",
        "defi", "yield", "staking", "airdrop", "mcap", "market cap",
    },
    "stocks": {
        "stock", "stocks", "equity", "shares", "dividend", "nasdaq",
        "nyse", "etf", "ticker", "earnings", "pe ratio",
    },
    "forex": {
        "forex", "fx", "eur/usd", "usd/jpy", "gbp/usd", "pip",
        "spread", "pair", "currency", "fx market",
    },
    "macro": {
        "inflation", "cpi", "interest rate", "fed", "fomc", "gdp",
        "recession", "quantitative", "yield curve", "unemployment",
    },
    "coding": {
        "code", "function", "bug", "debug", "api", "sdk", "syntax",
        "compile", "runtime", "exception", "refactor", "python",
        "javascript", "typescript", "docker", "git",
    },
    "security": {
        "security", "hack", "phishing", "scam", "vulnerability",
        "exploit", "2fa", "private key", "breach", "malware", "cve",
    },
    "wallet": {
        "wallet", "seed phrase", "metamask", "ledger", "trezor",
        "recover", "private key", "address", "balance", "send",
    },
    "trading": {
        "trade", "trading", "long", "short", "leverage", "margin",
        "position", "entry", "exit", "stop loss", "take profit",
        "candle", "chart", "indicator", "futures", "spot",
    },
    "nft": {
        "nft", "nfts", "mint", "collection", "opensea", "metadata",
        "royalty", "reveal", "whitelist",
    },
}

INTENT_PATTERNS: dict[str, list[str]] = {
    "learning": [
        "what is", "how does", "explain", "teach", "learn",
        "understand", "tutorial", "beginner",
    ],
    "research": [
        "research", "compare", "analyze", "investigate", "study",
        "paper", "report", "summary of", "latest", "news",
    ],
    "trading": [
        "buy", "sell", "entry", "exit", "position", "leverage",
        "long", "short", "stop loss", "take profit", "signal",
    ],
    "coding": [
        "code", "implement", "function", "script", "debug",
        "refactor", "fix", "error", "exception", "compile",
    ],
    "investment": [
        "invest", "portfolio", "hold", "dca", "allocation",
        "risk", "diversify", "long-term", "accumulate",
    ],
    "debugging": [
        "bug", "crash", "traceback", "failed", "not working",
        "error message", "exception", "segfault", "stacktrace",
    ],
    "investigation": [
        "investigate", "find out", "track", "recover", "stolen",
        "lost", "scam", "hack", "address", "on-chain", "forensic",
    ],
    "planning": [
        "plan", "roadmap", "next step", "strategy", "schedule",
        "goal", "milestone", "prioritize",
    ],
}

ENTITY_DICTIONARY: dict[str, str] = {
    "bitcoin": "Bitcoin",
    "btc": "Bitcoin",
    "ethereum": "Ethereum",
    "eth": "Ethereum",
    "solana": "Solana",
    "sol": "Solana",
    "binance": "Binance",
    "coinbase": "Coinbase",
    "kraken": "Kraken",
    "bybit": "Bybit",
    "okx": "OKX",
    "vitalik": "Vitalik",
    "vitalik buterin": "Vitalik Buterin",
    "satoshi": "Satoshi Nakamoto",
    "blackrock": "BlackRock",
    "sec": "SEC",
    "uniswap": "Uniswap",
    "aave": "Aave",
    "chainlink": "Chainlink",
    "metamask": "MetaMask",
    "ledger": "Ledger",
    "trezor": "Trezor",
    "usdc": "USDC",
    "usdt": "USDT",
    "tether": "Tether",
}

FACT_PATTERNS: list[tuple[str, list[str]]] = [
    ("favorite_chain", ["favorite chain", "prefer", "only trade"]),
    ("favorite_wallet", ["favorite wallet", "use wallet", "my wallet"]),
    ("favorite_exchange", ["favorite exchange", "use exchange", "on binance", "on coinbase"]),
    ("risk_profile", ["risk profile", "risk tolerance", "low risk", "high risk"]),
    ("trading_style", ["trading style", "day trade", "swing trade", "scalp", "hold long"]),
    ("investment_amount", ["invested", "portfolio size", "position size"]),
    ("location", ["i am in", "based in", "i live in"]),
    ("occupation", ["i work", "i am a", "i am an", "my job"]),
]

PREFERENCE_PATTERNS: dict[str, list[str]] = {
    "language": ["language", "speak", "english", "hindi", "urdu"],
    "risk": ["risk", "risk tolerance", "conservative", "aggressive", "high risk", "low risk"],
    "trading_style": ["trading style", "day trade", "swing", "scalp", "long-term hold"],
    "favorite_wallet": ["favorite wallet", "my wallet", "use wallet", "wallet is"],
    "favorite_chain": ["favorite chain", "only trade", "prefer"],
    "favorite_ide": ["ide", "vscode", "pycharm", "editor"],
    "favorite_model": ["model", "gpt", "claude", "llama", "model name"],
    "timezone": ["timezone", "time zone", "utc", "ist", "gmt"],
}

TASK_PATTERNS: dict[str, list[str]] = {
    "todo": ["todo", "to-do", "task:", "need to", "have to", "should ", "must "],
    "pending": ["pending", "in progress", "working on", "started", "blocked on"],
    "completed": ["done", "completed", "finished", "resolved", "fixed", "shipped"],
    "cancelled": ["cancelled", "canceled", "dropped", "abandoned", "scrapped"],
}

DECISION_PATTERNS: list[str] = [
    "decided", "i will", "going to", "we will", "choice",
    "conclusion", "decided to", "decision", "opted for",
]

EVENT_PATTERNS: list[str] = [
    "hacked", "launched", "released", "announced", "listed",
    "bought", "sold", "invested", "migrated", "upgraded",
    "merged", "acquired", "crashed", "recovered",
]

# ============================================================
# Enumerations
# ============================================================


class SummaryStyle(str, Enum):
    """Supported summary output styles."""

    TINY = "tiny"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    BULLET = "bullet"
    MARKDOWN = "markdown"
    JSON = "json"


class MessageClass(str, Enum):
    """Classification of an individual message."""

    QUESTION = "question"
    ANSWER = "answer"
    INSTRUCTION = "instruction"
    DECISION = "decision"
    CODE = "code"
    ERROR = "error"
    RESEARCH = "research"
    CHAT = "chat"
    GREETING = "greeting"
    WARNING = "warning"


class ContentRank(str, Enum):
    """Conversation-level importance bucket."""

    IMPORTANT = "important"
    UNIMPORTANT = "unimportant"
    NOISE = "noise"
    DUPLICATE = "duplicate"


class TaskState(str, Enum):
    """Lifecycle of an extracted task."""

    TODO = "todo"
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SummarizerState(str, Enum):
    """Async lifecycle state of the engine."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


# ============================================================
# Runtime Models
# ============================================================


@dataclass(slots=True)
class Topic:
    """Detected conversation topic."""

    name: str
    confidence: float = 0.0
    mentions: int = 0


@dataclass(slots=True)
class Entity:
    """Extracted named entity."""

    name: str
    kind: str = "organization"
    mentions: int = 1
    confidence: float = 0.0


@dataclass(slots=True)
class Fact:
    """A stable, structured fact extracted from conversation."""

    attribute: str
    value: Any
    confidence: float = 0.6
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass(slots=True)
class Preference:
    """A user preference extracted from conversation."""

    key: str
    value: Any
    confidence: float = 0.6


@dataclass(slots=True)
class Decision:
    """A decision recorded during conversation."""

    statement: str
    confidence: float = 0.6


@dataclass(slots=True)
class TaskItem:
    """An actionable task extracted from conversation."""

    description: str
    state: TaskState = TaskState.TODO
    confidence: float = 0.6


@dataclass(slots=True)
class EventItem:
    """A time-based event extracted from conversation."""

    description: str
    occurred_at: str | None = None
    confidence: float = 0.5


@dataclass(slots=True)
class MessageAnalysis:
    """Analysis of a single message."""

    role: str
    content: str
    classification: MessageClass = MessageClass.CHAT
    rank: ContentRank = ContentRank.IMPORTANT
    importance: float = 50.0
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SummaryResult:
    """Result of the summarization pipeline."""

    text: str
    style: SummaryStyle = SummaryStyle.BULLET
    topics: list[Topic] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    preferences: list[Preference] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    events: list[EventItem] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    importance: float = 0.0
    confidence: float = 0.0
    source_tokens: int = 0
    output_tokens: int = 0
    compression_ratio: float = 0.0
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["style"] = self.style.value
        payload["generated_at"] = self.generated_at.isoformat()
        return payload

    def to_markdown(self) -> str:
        lines = ["## Summary"]
        lines.append("")
        lines.append(self.text)
        if self.facts:
            lines.append("")
            lines.append("### Facts")
            for fact in self.facts:
                lines.append(f"- **{fact.attribute}**: {fact.value}")
        if self.preferences:
            lines.append("")
            lines.append("### Preferences")
            for pref in self.preferences:
                lines.append(f"- **{pref.key}**: {pref.value}")
        if self.tasks:
            lines.append("")
            lines.append("### Tasks")
            for task in self.tasks:
                lines.append(f"- [{task.state.value}] {task.description}")
        if self.entities:
            lines.append("")
            lines.append("### Entities")
            for entity in self.entities:
                lines.append(f"- {entity.name} ({entity.kind})")
        return "\n".join(lines)


@dataclass(slots=True)
class CompressionReport:
    """Result of context compression."""

    compressed: str
    original_tokens: int
    compressed_tokens: int
    ratio: float
    dropped_noise: int = 0
    kept_messages: int = 0


@dataclass(slots=True)
class KnowledgeReport:
    """Structured knowledge extracted from a conversation."""

    conversation_id: str = ""
    topics: list[Topic] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    preferences: list[Preference] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    events: list[EventItem] = field(default_factory=list)
    importance: float = 0.0
    confidence: float = 0.0
    summary: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "conversation_id": self.conversation_id,
            "topics": [
                asdict(topic) for topic in self.topics
            ],
            "intents": self.intents,
            "entities": [
                asdict(entity) for entity in self.entities
            ],
            "facts": [
                fact.to_dict() for fact in self.facts
            ],
            "preferences": [
                asdict(pref) for pref in self.preferences
            ],
            "goals": self.goals,
            "decisions": [
                asdict(decision) for decision in self.decisions
            ],
            "tasks": [
                {
                    "description": task.description,
                    "state": task.state.value,
                    "confidence": task.confidence,
                }
                for task in self.tasks
            ],
            "events": [
                asdict(event) for event in self.events
            ],
            "importance": self.importance,
            "confidence": self.confidence,
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
        }
        return payload

    def promotion_candidates(self) -> list[dict[str, Any]]:
        """Return durable, type-tagged candidate records."""
        candidates: list[dict[str, Any]] = []

        for fact in self.facts:
            candidates.append({
                "key": f"fact:{fact.attribute}",
                "value": fact.to_dict(),
                "memory_type": "knowledge",
                "tags": ["fact", "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": fact.confidence,
            })

        for pref in self.preferences:
            candidates.append({
                "key": f"preference:{pref.key}",
                "value": asdict(pref),
                "memory_type": "knowledge",
                "tags": ["preference", "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": pref.confidence,
            })

        for decision in self.decisions:
            candidates.append({
                "key": f"decision:{hashlib.sha1(decision.statement.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]}",
                "value": asdict(decision),
                "memory_type": "episodic",
                "tags": ["decision", "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": decision.confidence,
            })

        for task in self.tasks:
            candidates.append({
                "key": f"task:{task.state.value}:{hashlib.sha1(task.description.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]}",
                "value": {
                    "description": task.description,
                    "state": task.state.value,
                },
                "memory_type": "procedural",
                "tags": ["task", task.state.value, "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": task.confidence,
            })

        for event in self.events:
            candidates.append({
                "key": f"event:{hashlib.sha1(event.description.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]}",
                "value": asdict(event),
                "memory_type": "episodic",
                "tags": ["event", "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": event.confidence,
            })

        for entity in self.entities:
            candidates.append({
                "key": f"entity:{entity.name.lower().replace(' ', '_')}",
                "value": asdict(entity),
                "memory_type": "knowledge",
                "tags": ["entity", entity.kind, "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": entity.confidence,
            })

        for topic in self.topics:
            candidates.append({
                "key": f"topic:{topic.name}",
                "value": asdict(topic),
                "memory_type": "semantic",
                "tags": ["topic", "summarizer"],
                "importance": self.importance / 100.0,
                "confidence": topic.confidence,
            })

        return candidates


# ============================================================
# Configuration
# ============================================================


@dataclass(slots=True)
class SummarizerConfig:
    """Configuration for the memory intelligence engine."""

    namespace: str = DEFAULT_NAMESPACE
    model: str | None = None
    temperature: float = 0.3
    max_tokens: int = DEFAULT_MAX_TOKENS
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    language: str = "en"
    compression_ratio: float = DEFAULT_COMPRESSION_RATIO
    summary_style: SummaryStyle = SummaryStyle.BULLET
    retry_attempts: int = 3
    retry_delay: float = 0.5
    timeout: float = 30.0
    parallel_workers: int = 2
    promotion_threshold: float = DEFAULT_PROMOTION_THRESHOLD
    minimum_messages: int = 2
    generator: Callable[..., Any] | None = None
    enable_events: bool = True
    enable_metrics: bool = True


# ============================================================
# Summarizer — Memory Intelligence Engine
# ============================================================


class MemorySummarizer:
    """
    Ingests conversations, extracts structured knowledge and produces
    durable memory candidates.

    The engine satisfies the MemoryManager summarizer contract:
        * summarize(content, **kwargs) -> SummaryResult
        * compress(content, **kwargs) -> CompressionReport
        * importance_score(content) -> float (0.0 - 1.0)

    And additionally exposes:
        * analyze(content, **kwargs) -> KnowledgeReport
        * promote(report, long_term, vector) -> dict[str, int]
        * lifecycle: start / pause / resume / stop / restart
        * observability: events, metrics, diagnostics, statistics
    """

    # ============================================================
    # Foundation
    # ============================================================

    def __init__(
        self,
        config: SummarizerConfig | None = None,
    ) -> None:
        self._config = config or SummarizerConfig()
        self._validate_configuration()
        self._state = SummarizerState.STOPPED
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._worker_task: asyncio.Task[Any] | None = None
        self._listeners: dict[str, list[Callable[..., Any]]] = {}
        self._metrics: dict[str, float] = {
            "summaries": 0.0,
            "analyses": 0.0,
            "compressions": 0.0,
            "promotions": 0.0,
            "errors": 0.0,
            "tokens_in": 0.0,
            "tokens_out": 0.0,
            "total_latency_ms": 0.0,
        }
        self._started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Configuration & Properties
    # ------------------------------------------------------------------

    def _validate_configuration(self) -> None:
        config = self._config
        if not config.namespace.strip():
            raise ValueError("namespace must not be empty")
        if config.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if config.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0.0 < config.compression_ratio <= 1.0:
            raise ValueError("compression_ratio must be in (0, 1]")
        if not 0.0 <= config.promotion_threshold <= IMPORTANCE_MAX:
            raise ValueError("promotion_threshold must be in [0, 100]")

    @property
    def config(self) -> SummarizerConfig:
        return self._config

    @property
    def state(self) -> SummarizerState:
        return self._state

    @property
    def metrics(self) -> dict[str, float]:
        return dict(self._metrics)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def _record(self, name: str, value: float = 1.0) -> None:
        if self._config.enable_metrics:
            self._metrics[name] = self._metrics.get(name, 0.0) + value

    # ============================================================
    # Events
    # ============================================================

    def on(self, event: str, listener: Callable[..., Any]) -> None:
        if not callable(listener):
            raise TypeError("listener must be callable")
        self._listeners.setdefault(event, []).append(listener)

    def off(self, event: str, listener: Callable[..., Any]) -> bool:
        listeners = self._listeners.get(event, [])
        if listener not in listeners:
            return False
        listeners.remove(listener)
        return True

    def clear_listeners(self, event: str | None = None) -> None:
        if event is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event, None)

    def listener_count(self) -> int:
        return sum(len(v) for v in self._listeners.values())

    async def emit(self, event: str, **kwargs: Any) -> None:
        if not self._config.enable_events:
            return
        for listener in self._listeners.get(event, []):
            try:
                result = listener(event, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                LOGGER.exception("listener error on event '%s'", event)

    # ============================================================
    # Async Lifecycle
    # ============================================================

    async def start(self) -> None:
        async with self._lock:
            if self._state in (SummarizerState.RUNNING, SummarizerState.STARTING):
                return
            self._state = SummarizerState.STARTING
            if self._worker_task is None:
                self._worker_task = asyncio.create_task(
                    self._worker_loop(),
                    name="memory_summarizer_worker",
                )
            self._state = SummarizerState.RUNNING
        await self.emit("started", state=self._state.value)

    async def pause(self) -> None:
        async with self._lock:
            if self._state != SummarizerState.RUNNING:
                return
            self._state = SummarizerState.PAUSED
        await self.emit("paused")

    async def resume(self) -> None:
        async with self._lock:
            if self._state != SummarizerState.PAUSED:
                return
            self._state = SummarizerState.RUNNING
        await self.emit("resumed")

    async def stop(self) -> None:
        async with self._lock:
            if self._state == SummarizerState.STOPPED:
                return
            self._state = SummarizerState.STOPPING
            task, self._worker_task = self._worker_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                LOGGER.exception("worker stopped with error")
        self._state = SummarizerState.STOPPED
        await self.emit("stopped")

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _worker_loop(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if self._state == SummarizerState.PAUSED:
                    self._queue.task_done()
                    continue
                content = job.get("content")
                kwargs = job.get("kwargs", {})
                future = job.get("future")
                result = await self.analyze(content, **kwargs)
                if future is not None and not future.done():
                    future.set_result(result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record("errors")
                if job.get("future") is not None and not job["future"].done():
                    job["future"].set_exception(exc)
            finally:
                self._queue.task_done()

    async def enqueue(
        self,
        content: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Enqueue content for asynchronous analysis and await the result.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put(
            {"content": content, "kwargs": kwargs, "future": future}
        )
        return await future

    # ============================================================
    # Text Utilities
    # ============================================================

    @staticmethod
    def token_count(text: str) -> int:
        if not text:
            return 0
        return len(TOKEN_SPLIT_RE.split(text.strip()))

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _split_sentences(cls, text: str) -> list[str]:
        return [
            sent.strip()
            for sent in SENTENCE_SPLIT_RE.split(text)
            if sent.strip()
        ]

    @classmethod
    def _content_to_messages(
        cls,
        content: Any,
    ) -> list[tuple[str, str]]:
        """
        Normalize arbitrary content into (role, text) message tuples.

        Accepts:
            * str (single message, role "user")
            * list[str]
            * list[dict] with 'role'/'content'
            * list of objects exposing .role/.content
            * Mapping of {role: content}
        """
        messages: list[tuple[str, str]] = []

        if isinstance(content, str):
            if content.strip():
                messages.append(("user", content.strip()))
            return messages

        if isinstance(content, Mapping):
            for role, text in content.items():
                messages.append((str(role), cls._normalize(str(text))))
            return messages

        if isinstance(content, Iterable):
            for item in content:
                if isinstance(item, str):
                    if item.strip():
                        messages.append(("user", item.strip()))
                    continue
                if isinstance(item, (tuple, list)) and len(item) == 2 and all(
                    isinstance(part, str) for part in item
                ):
                    role, text = item
                    if text.strip():
                        messages.append((role, cls._normalize(text)))
                    continue
                if isinstance(item, Mapping):
                    role = str(item.get("role", "user"))
                    text = str(item.get("content", item.get("text", "")))
                elif isinstance(item, MemoryEntry):
                    role = item.metadata.source or "user"
                    text = str(item.value)
                else:
                    role = str(getattr(item, "role", "user"))
                    text = str(getattr(item, "content", getattr(item, "text", str(item))))
                if text.strip():
                    messages.append((role, cls._normalize(text)))

        return messages

    # ============================================================
    # Conversation Analyzer
    # ============================================================

    def analyze_message(
        self,
        role: str,
        content: str,
    ) -> MessageAnalysis:
        lower = content.lower()
        topics = self.detect_topics(content)
        entities = self.extract_entities(content)
        classification = self.classify_message(content)
        importance = self.score_message_importance(
            role, content, classification
        )

        rank = ContentRank.IMPORTANT
        if classification in (
            MessageClass.GREETING,
            MessageClass.CHAT,
        ) and importance < 40:
            rank = ContentRank.NOISE
        elif importance < 30:
            rank = ContentRank.UNIMPORTANT

        return MessageAnalysis(
            role=role,
            content=content,
            classification=classification,
            rank=rank,
            importance=importance,
            topics=[topic.name for topic in topics],
            entities=[entity.name for entity in entities],
        )

    # ============================================================
    # Message Classifier
    # ============================================================

    def classify_message(self, content: str) -> MessageClass:
        stripped = content.strip()
        lower = stripped.lower()

        if not stripped:
            return MessageClass.CHAT

        if any(
            stripped.startswith(prefix)
            for prefix in ("import ", "from ", "def ", "class ", "async ", "await ")
        ) or re.search(r"[{};()]\s*$", stripped) or "```" in stripped:
            return MessageClass.CODE

        if re.search(
            r"\b(traceback|exception|error|failed|crash|bug)\b",
            lower,
        ):
            return MessageClass.ERROR

        if re.search(r"\b(warning|beware|danger|scam|phishing|do not)\b", lower):
            return MessageClass.WARNING

        if re.search(
            r"\b(how|what|why|when|where|which|can you|explain)\b",
            lower,
        ) and "?" in stripped:
            return MessageClass.QUESTION

        if lower.startswith(("please ", "can you ", "could you ", "do this", "go ahead")):
            return MessageClass.INSTRUCTION

        if any(token in lower for token in ("decided", "decision", "i will", "going to")):
            return MessageClass.DECISION

        if any(token in lower for token in ("research", "analy", "report", "investigate")):
            return MessageClass.RESEARCH

        if re.match(r"^(hi|hello|hey|yo|thanks|thank you|ok|okay)\b", lower):
            return MessageClass.GREETING

        return MessageClass.ANSWER

    # ============================================================
    # Topic Detection
    # ============================================================

    def detect_topics(self, content: str) -> list[Topic]:
        lower = content.lower()
        tokens = set(TOKEN_SPLIT_RE.split(lower))
        detected: list[Topic] = []

        for topic, keywords in TOPIC_KEYWORDS.items():
            mentions = 0
            for keyword in keywords:
                if keyword in tokens:
                    mentions += 1
                elif " " in keyword and keyword in lower:
                    mentions += 1
            if mentions:
                confidence = min(1.0, mentions / max(2, len(tokens)) * 4 + 0.2)
                detected.append(
                    Topic(
                        name=topic,
                        confidence=round(confidence, 3),
                        mentions=mentions,
                    )
                )

        detected.sort(key=lambda t: (t.mentions, t.confidence), reverse=True)
        return detected

    # ============================================================
    # Intent Detection
    # ============================================================

    def detect_intents(self, content: str) -> list[str]:
        lower = content.lower()
        intents: list[str] = []
        for intent, patterns in INTENT_PATTERNS.items():
            if any(pattern in lower for pattern in patterns):
                intents.append(intent)
        return intents

    # ============================================================
    # Entity Extraction
    # ============================================================

    def extract_entities(self, content: str) -> list[Entity]:
        lower = content.lower()
        counts: dict[str, int] = {}
        kinds: dict[str, str] = {}

        for alias, canonical in ENTITY_DICTIONARY.items():
            count = len(re.findall(rf"\b{re.escape(alias)}\b", lower))
            if count:
                counts[canonical] = counts.get(canonical, 0) + count
                kind = "person" if canonical in (
                    "Vitalik Buterin", "Satoshi Nakamoto",
                ) else "organization"
                kinds[canonical] = kind

        for match in ADDRESS_PATTERN.finditer(content):
            address = match.group(0)
            short = f"{address[:6]}...{address[-4:]}"
            counts[short] = counts.get(short, 0) + 1
            kinds[short] = "address"

        entities = [
            Entity(
                name=name,
                kind=kinds.get(name, "organization"),
                mentions=count,
                confidence=min(0.95, 0.5 + 0.1 * count),
            )
            for name, count in counts.items()
        ]
        entities.sort(key=lambda e: e.mentions, reverse=True)
        return entities

    # ============================================================
    # Fact Extraction
    # ============================================================

    def extract_facts(self, content: str) -> list[Fact]:
        lower = content.lower()
        facts: list[Fact] = []

        for attribute, markers in FACT_PATTERNS:
            if any(marker in lower for marker in markers):
                sentences = self._split_sentences(content)
                for sentence in sentences:
                    sentence_lower = sentence.lower()
                    if not any(marker in sentence_lower for marker in markers):
                        continue
                    value = self._fact_value(sentence, attribute)
                    if value:
                        facts.append(
                            Fact(
                                attribute=attribute,
                                value=value,
                                confidence=0.7,
                                source=sentence,
                            )
                        )
                        break

        if "only trade" in lower:
            facts.append(
                Fact(
                    attribute="favorite_chain",
                    value=self._extract_chain(lower),
                    confidence=0.8,
                    source=content,
                )
            )

        return facts

    def _fact_value(self, sentence: str, attribute: str) -> str | None:
        lower = sentence.lower()
        for marker in ("favorite", "prefer", "use", "only trade"):
            if marker in lower:
                idx = lower.find(marker) + len(marker)
                rest = sentence[idx:].strip(" :,.")
                rest = self._clean_value(rest)
                if rest:
                    return rest[:120]
        return None

    def _clean_value(self, value: str) -> str:
        """Trim connective prefixes that leak into extracted values."""
        cleaned = re.sub(
            r"^(?:is|are|to|the|a|an|my|on|in|with|of|and|then)\s+",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^(?:wallet|chain|exchange|ide|language|risk|timezone|favorite|preferred)\s+is\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.split(r"[\n\r]", cleaned)[0].strip(" :,.;!?")
        return cleaned

    def _merge_facts(self, facts: Iterable[Fact]) -> list[Fact]:
        merged: dict[str, Fact] = {}
        for fact in facts:
            if fact.attribute in merged:
                existing = merged[fact.attribute]
                existing.confidence = max(existing.confidence, fact.confidence)
            else:
                merged[fact.attribute] = fact
        return list(merged.values())

    def _merge_preferences(self, preferences: Iterable[Preference]) -> list[Preference]:
        merged: dict[str, Preference] = {}
        for preference in preferences:
            if preference.key in merged:
                existing = merged[preference.key]
                existing.confidence = max(existing.confidence, preference.confidence)
            else:
                merged[preference.key] = preference
        return list(merged.values())

    def _extract_chain(self, lower: str) -> str:
        for alias, canonical in (
            ("ethereum", "Ethereum"),
            ("eth", "Ethereum"),
            ("bitcoin", "Bitcoin"),
            ("solana", "Solana"),
        ):
            if alias in lower:
                return canonical
        return "unknown"

    # ============================================================
    # Preference Extraction
    # ============================================================

    def extract_preferences(self, content: str) -> list[Preference]:
        lower = content.lower()
        preferences: list[Preference] = []
        sentences = self._split_sentences(content)

        for key, markers in PREFERENCE_PATTERNS.items():
            if not any(marker in lower for marker in markers):
                continue
            for sentence in sentences:
                sentence_lower = sentence.lower()
                if not any(marker in sentence_lower for marker in markers):
                    continue
                value = self._preference_value(sentence, sentence_lower)
                if value:
                    preferences.append(
                        Preference(key=key, value=value, confidence=0.6)
                    )
                    break

        return preferences

    def _preference_value(self, sentence: str, lower: str) -> str | None:
        for marker in ("is", "use", "prefer", "only trade", "speak", "my"):
            idx = lower.find(marker)
            if idx == -1:
                continue
            tail = sentence[idx + len(marker):].strip(" :,.")
            tail = self._clean_value(tail)
            if tail:
                return tail[:120]
        return None

    # ============================================================
    # Goal / Decision / Task / Event Extraction
    # ============================================================

    def extract_goals(self, content: str) -> list[str]:
        lower = content.lower()
        goals: list[str] = []
        markers = ("i want to build", "goal is", "aim is", "i plan to")
        for sentence in self._split_sentences(content):
            sentence_lower = sentence.lower()
            for marker in markers:
                if marker in sentence_lower:
                    goals.append(sentence.strip()[:160])
                    break
        return goals

    def extract_decisions(self, content: str) -> list[Decision]:
        decisions: list[Decision] = []
        for sentence in self._split_sentences(content):
            if any(pattern in sentence.lower() for pattern in DECISION_PATTERNS):
                decisions.append(
                    Decision(statement=sentence.strip(), confidence=0.6)
                )
        return decisions

    def extract_tasks(self, content: str) -> list[TaskItem]:
        tasks: list[TaskItem] = []
        for sentence in self._split_sentences(content):
            lower = sentence.lower()
            state = None
            for candidate, markers in TASK_PATTERNS.items():
                if any(marker in lower for marker in markers):
                    state = candidate
                    break
            if state is None:
                continue
            description = sentence.strip()
            if description:
                tasks.append(
                    TaskItem(
                        description=description,
                        state=TaskState(state),
                        confidence=0.6,
                    )
                )
        return tasks

    def extract_events(self, content: str) -> list[EventItem]:
        events: list[EventItem] = []
        for sentence in self._split_sentences(content):
            if any(token in sentence.lower() for token in EVENT_PATTERNS):
                occurred_at = None
                date_match = DATE_PATTERN.search(sentence)
                if date_match:
                    occurred_at = date_match.group(0)
                events.append(
                    EventItem(
                        description=sentence.strip(),
                        occurred_at=occurred_at,
                        confidence=0.5,
                    )
                )
        return events

    # ============================================================
    # Importance Scoring
    # ============================================================

    def score_importance(
        self,
        content: str,
        *,
        analysis: list[MessageAnalysis] | None = None,
    ) -> float:
        """
        Return an importance score in [0, 100].
        """
        if analysis:
            if not analysis:
                return 0.0
            base = sum(message.importance for message in analysis) / len(analysis)
            base += min(20.0, len(analysis) * 2.0)
            return min(IMPORTANCE_MAX, base)

        lower = content.lower()
        score = 30.0

        urgent = ("urgent", "critical", "important", "must", "immediately", "asap")
        score += 15.0 * sum(1 for token in urgent if token in lower)

        emotional = ("!!", "love", "hate", "excited", "worried", "scared", "panic")
        score += 5.0 * sum(1 for token in emotional if token in lower)

        monetary = ("money", "funds", "usd", "btc", "eth", "invest", "loss", "gain", "stolen")
        score += 5.0 * sum(1 for token in monetary if token in lower)

        decisions = self.extract_decisions(content)
        if decisions:
            score += min(20.0, len(decisions) * 5.0)

        tasks = self.extract_tasks(content)
        if tasks:
            score += min(15.0, len(tasks) * 3.0)

        topics = self.detect_topics(content)
        if topics:
            score += min(15.0, len(topics) * 3.0)

        score = min(IMPORTANCE_MAX, score)
        return round(score, 2)

    def score_message_importance(
        self,
        role: str,
        content: str,
        classification: MessageClass | None = None,
    ) -> float:
        lower = content.lower()
        score = 35.0

        if classification is None:
            classification = self.classify_message(content)

        role_bonus = {
            "user": 10.0,
            "assistant": 2.0,
            "system": -5.0,
        }
        score += role_bonus.get(role.lower(), 0.0)

        if classification == MessageClass.ERROR:
            score += 20.0
        elif classification == MessageClass.DECISION:
            score += 15.0
        elif classification == MessageClass.INSTRUCTION:
            score += 10.0
        elif classification in (MessageClass.CHAT, MessageClass.GREETING):
            score -= 10.0

        topics = self.detect_topics(content)
        score += min(15.0, len(topics) * 3.0)

        entities = self.extract_entities(content)
        score += min(10.0, len(entities) * 2.0)

        if "?" in content:
            score += 3.0

        return round(max(0.0, min(IMPORTANCE_MAX, score)), 2)

    # ============================================================
    # Confidence Estimation
    # ============================================================

    def estimate_confidence(self, content: str) -> float:
        lower = content.lower()
        confidence = 0.5

        explicit = ("i use", "i trade", "my", "i am", "i want", "i will", "decided")
        confidence += 0.15 * sum(1 for token in explicit if token in lower)

        facts = self.extract_facts(content)
        confidence += min(0.2, len(facts) * 0.08)

        length_factor = min(0.15, self.token_count(content) / 1000.0)
        confidence += length_factor

        hedged = ("maybe", "perhaps", "i think", "not sure", "possibly")
        confidence -= 0.1 * sum(1 for token in hedged if token in lower)

        return round(max(0.0, min(1.0, confidence)), 3)

    # ============================================================
    # Duplicate Detection
    # ============================================================

    @staticmethod
    def similarity(left: str, right: str) -> float:
        """Token-overlap similarity in [0, 1]."""
        tokens_left = set(TOKEN_SPLIT_RE.split(left.lower()))
        tokens_right = set(TOKEN_SPLIT_RE.split(right.lower()))
        if not tokens_left or not tokens_right:
            return 0.0
        return len(tokens_left & tokens_right) / len(tokens_left | tokens_right)

    def find_duplicates(
        self,
        messages: list[tuple[str, str]],
        *,
        threshold: float = 0.75,
    ) -> list[tuple[int, int, float]]:
        duplicates: list[tuple[int, int, float]] = []
        texts = [text for _, text in messages]
        for i in range(len(texts)):
            for j in range(i + 1, len(texts)):
                sim = self.similarity(texts[i], texts[j])
                if sim >= threshold:
                    duplicates.append((i, j, round(sim, 3)))
        return duplicates

    # ============================================================
    # Chunk Manager
    # ============================================================

    def chunk_text(
        self,
        text: str,
        *,
        max_tokens: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        max_size = max_tokens or self._config.chunk_size
        overlap_size = overlap if overlap is not None else self._config.chunk_overlap

        sentences = self._split_sentences(text)
        chunks: list[str] = []
        current: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            tokens = self.token_count(sentence)
            if current and current_tokens + tokens > max_size:
                chunks.append(" ".join(current))
                carry = current[-overlap_size:] if overlap_size else []
                current = list(carry)
                current_tokens = sum(self.token_count(s) for s in carry)
            current.append(sentence)
            current_tokens += tokens

        if current:
            chunks.append(" ".join(current))

        return chunks or [text]

    # ============================================================
    # Multi-Level Summary Generation
    # ============================================================

    async def generate_summary(
        self,
        content: str,
        *,
        style: SummaryStyle | str = SummaryStyle.BULLET,
        max_tokens: int | None = None,
    ) -> str:
        style = SummaryStyle(style) if isinstance(style, str) else style
        budget = max_tokens or self._config.max_tokens

        generator = self._config.generator
        if generator is not None:
            try:
                return await self._invoke_generator(content, style, budget)
            except Exception:
                LOGGER.exception("generator failed, falling back to extractive")

        return self._extractive_summary(content, style=style, budget=budget)

    async def _invoke_generator(
        self,
        content: str,
        style: SummaryStyle,
        budget: int,
    ) -> str:
        generator = self._config.generator
        result = generator(
            content=content,
            style=style.value,
            max_tokens=budget,
            model=self._config.model,
            temperature=self._config.temperature,
        )
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)

    def _extractive_summary(
        self,
        content: str,
        *,
        style: SummaryStyle,
        budget: int,
    ) -> str:
        sentences = self._split_sentences(content)
        if not sentences:
            return ""

        topics = self.detect_topics(content)
        entities = self.extract_entities(content)
        keywords = {
            topic.name
            for topic in topics
        } | {entity.name.lower() for entity in entities}

        scored: list[tuple[float, str]] = []
        for index, sentence in enumerate(sentences):
            lower = sentence.lower()
            score = 0.0
            for keyword in keywords:
                if keyword in lower:
                    score += 2.0
            if any(token in lower for token in ("decided", "important", "must", "todo")):
                score += 3.0
            if "?" in sentence:
                score += 1.0
            score += 0.5 / (index + 1)
            scored.append((score, sentence))

        scored.sort(key=lambda item: item[0], reverse=True)

        limit = {
            SummaryStyle.TINY: 1,
            SummaryStyle.SHORT: 2,
            SummaryStyle.MEDIUM: 3,
            SummaryStyle.LONG: 6,
            SummaryStyle.EXECUTIVE: 3,
            SummaryStyle.TECHNICAL: 5,
            SummaryStyle.BULLET: 5,
            SummaryStyle.MARKDOWN: 6,
            SummaryStyle.JSON: 3,
        }.get(style, 3)

        selected = scored[:limit]

        if style == SummaryStyle.TINY:
            text = " ".join(s for _, s in selected)
        elif style in (SummaryStyle.BULLET, SummaryStyle.MARKDOWN):
            text = "\n".join(f"- {s}" for _, s in selected)
        elif style == SummaryStyle.TECHNICAL:
            text = "\n".join(
                f"[{idx + 1}] {sentence}"
                for idx, (_, sentence) in enumerate(selected)
            )
        elif style == SummaryStyle.EXECUTIVE:
            lead = selected[0][1] if selected else ""
            supporting = [s for _, s in selected[1:]]
            text = "Executive summary: " + lead
            if supporting:
                text += "\nKey points: " + " ".join(supporting)
        elif style == SummaryStyle.JSON:
            payload = {
                "summary": [s for _, s in selected],
                "topics": [t.name for t in topics],
                "entities": [e.name for e in entities],
            }
            text = json.dumps(payload, ensure_ascii=False)
        else:
            text = " ".join(s for _, s in selected)

        return self._truncate_to_tokens(text, budget)

    def _truncate_to_tokens(self, text: str, budget: int) -> str:
        tokens = TOKEN_SPLIT_RE.split(text.strip())
        if len(tokens) <= budget:
            return text.strip()
        return " ".join(tokens[:budget])

    # ============================================================
    # Context Compression
    # ============================================================

    def compress_text(
        self,
        content: str,
        *,
        ratio: float | None = None,
        keep_important: bool = True,
    ) -> CompressionReport:
        ratio = ratio if ratio is not None else self._config.compression_ratio
        original_tokens = self.token_count(content)
        target_tokens = max(1, int(original_tokens * ratio))

        messages = self._content_to_messages(content)
        analyses = [
            self.analyze_message(role, text)
            for role, text in messages
        ]

        kept: list[tuple[str, str]] = []
        dropped_noise = 0
        for analysis, (role, text) in zip(analyses, messages):
            if keep_important and analysis.rank == ContentRank.NOISE:
                dropped_noise += 1
                continue
            kept.append((role, text))

        if not kept:
            kept = [("user", content)]

        def _score_role_weight(role: str) -> float:
            return {"user": 1.0, "assistant": 0.4}.get(role.lower(), 0.5)

        selected: list[str] = []
        selected_tokens = 0
        for analysis, (role, text) in sorted(
            zip(
                [self.analyze_message(r, t) for r, t in kept],
                kept,
            ),
            key=lambda pair: (
                pair[0].importance * _score_role_weight(pair[1][0]),
                -len(pair[1][1]),
            ),
            reverse=True,
        ):
            tokens = self.token_count(text)
            if selected_tokens + tokens > target_tokens and selected:
                continue
            selected.append(text)
            selected_tokens += tokens

        compressed = self._truncate_to_tokens(" ".join(selected), target_tokens)
        return CompressionReport(
            compressed=compressed,
            original_tokens=original_tokens,
            compressed_tokens=self.token_count(compressed),
            ratio=round(self.token_count(compressed) / max(1, original_tokens), 4),
            dropped_noise=dropped_noise,
            kept_messages=len(selected),
        )

    # ============================================================
    # Knowledge Builder
    # ============================================================

    async def build_knowledge(
        self,
        content: Any,
        *,
        conversation_id: str = "",
        style: SummaryStyle | str = SummaryStyle.BULLET,
        max_tokens: int | None = None,
    ) -> KnowledgeReport:
        messages = self._content_to_messages(content)
        if not messages:
            raise ValueError("content contains no messages")

        text = "\n".join(f"{role}: {payload}" for role, payload in messages)
        plain_text = " ".join(payload for _, payload in messages)

        analyses = [
            self.analyze_message(role, payload)
            for role, payload in messages
        ]

        topics: dict[str, Topic] = {}
        for analysis in analyses:
            for topic in self.detect_topics(analysis.content):
                if topic.name not in topics:
                    topics[topic.name] = topic
                else:
                    topics[topic.name].mentions += topic.mentions
                    topics[topic.name].confidence = max(
                        topics[topic.name].confidence,
                        topic.confidence,
                    )
        topic_list = sorted(
            topics.values(),
            key=lambda t: (t.mentions, t.confidence),
            reverse=True,
        )

        intents: list[str] = []
        for _, payload in messages:
            for intent in self.detect_intents(payload):
                if intent not in intents:
                    intents.append(intent)

        entities: dict[str, Entity] = {}
        for _, payload in messages:
            for entity in self.extract_entities(payload):
                if entity.name not in entities:
                    entities[entity.name] = entity
                else:
                    entities[entity.name].mentions += entity.mentions
        entity_list = sorted(
            entities.values(),
            key=lambda e: e.mentions,
            reverse=True,
        )

        facts = self._merge_facts(
            fact
            for _, payload in messages
            for fact in self.extract_facts(payload)
        )
        preferences = self._merge_preferences(
            pref
            for _, payload in messages
            for pref in self.extract_preferences(payload)
        )
        goals: list[str] = []
        for _, payload in messages:
            for goal in self.extract_goals(payload):
                if goal not in goals:
                    goals.append(goal)
        decisions: list[Decision] = []
        for _, payload in messages:
            for decision in self.extract_decisions(payload):
                if decision.statement not in {d.statement for d in decisions}:
                    decisions.append(decision)
        tasks: list[TaskItem] = []
        for _, payload in messages:
            for task in self.extract_tasks(payload):
                if task.description not in {t.description for t in tasks}:
                    tasks.append(task)
        events: list[EventItem] = []
        for _, payload in messages:
            for event in self.extract_events(payload):
                if event.description not in {e.description for e in events}:
                    events.append(event)

        importance = self.score_importance(text, analysis=analyses)
        confidence = self.estimate_confidence(text)

        summary = await self.generate_summary(
            plain_text,
            style=style,
            max_tokens=max_tokens,
        )

        return KnowledgeReport(
            conversation_id=conversation_id,
            topics=topic_list,
            intents=intents,
            entities=entity_list,
            facts=facts,
            preferences=preferences,
            goals=goals,
            decisions=decisions,
            tasks=tasks,
            events=events,
            importance=importance,
            confidence=confidence,
            summary=summary,
        )

    # ============================================================
    # Validation & Quality Scoring
    # ============================================================

    def validate_report(self, report: KnowledgeReport) -> dict[str, Any]:
        issues: list[str] = []

        if report.importance < 30:
            issues.append("low overall importance")
        if report.confidence < 0.3:
            issues.append("low extraction confidence")
        if not report.summary.strip():
            issues.append("empty summary")
        if not report.topics and not report.facts and not report.tasks:
            issues.append("no knowledge extracted")

        return {
            "valid": not issues,
            "issues": issues,
            "coverage": {
                "topics": len(report.topics),
                "intents": len(report.intents),
                "entities": len(report.entities),
                "facts": len(report.facts),
                "preferences": len(report.preferences),
                "goals": len(report.goals),
                "decisions": len(report.decisions),
                "tasks": len(report.tasks),
                "events": len(report.events),
            },
        }

    def quality_score(self, report: KnowledgeReport) -> float:
        score = 0.0
        score += min(20.0, len(report.topics) * 4.0)
        score += min(15.0, len(report.facts) * 5.0)
        score += min(15.0, len(report.tasks) * 3.0)
        score += min(10.0, len(report.decisions) * 3.0)
        score += min(10.0, len(report.preferences) * 3.0)
        score += min(10.0, len(report.entities) * 2.0)
        score += report.confidence * 10.0
        return round(min(100.0, score), 2)

    # ============================================================
    # Hallucination / Coherence Check
    # ============================================================

    def coherence_check(self, content: str, summary: str) -> float:
        """Estimate how much of the summary is supported by the source."""
        source_tokens = set(TOKEN_SPLIT_RE.split(content.lower()))
        summary_tokens = set(TOKEN_SPLIT_RE.split(summary.lower()))
        if not summary_tokens:
            return 0.0
        overlap = summary_tokens & source_tokens
        return round(len(overlap) / len(summary_tokens), 3)

    # ============================================================
    # Promotion Engine (delegates to existing memory engines)
    # ============================================================

    async def promote(
        self,
        report: KnowledgeReport,
        *,
        long_term_memory: BaseMemory[Any] | None = None,
        vector_memory: BaseMemory[Any] | None = None,
        threshold: float | None = None,
    ) -> dict[str, int]:
        """
        Promote structured knowledge into durable memory.

        Candidates that clear the importance threshold are written to
        LongTermMemory (type-tagged) and indexed in VectorMemory.
        No storage logic is duplicated here; both engines expose save/put.
        """
        threshold = threshold if threshold is not None else self._config.promotion_threshold
        if report.importance < threshold:
            await self.emit(
                "promotion_skipped",
                conversation_id=report.conversation_id,
                importance=report.importance,
                threshold=threshold,
            )
            return {"long_term": 0, "vector": 0}

        candidates = report.promotion_candidates()
        if report.summary:
            candidates.insert(0, {
                "key": f"summary:{report.conversation_id or 'latest'}",
                "value": report.summary,
                "memory_type": "semantic",
                "tags": ["summary", "summarizer"],
                "importance": report.importance / 100.0,
                "confidence": report.confidence,
            })

        lt_count = 0
        vec_count = 0

        await self.emit(
            "before_promotion",
            conversation_id=report.conversation_id,
            candidates=len(candidates),
        )

        if long_term_memory is not None:
            save = getattr(long_term_memory, "save", None)
            if callable(save):
                for candidate in candidates:
                    try:
                        await save(
                            candidate["key"],
                            candidate["value"],
                            memory_type=candidate["memory_type"],
                            tags=candidate["tags"],
                            importance=candidate["importance"],
                            confidence=candidate["confidence"],
                            source="summarizer",
                        )
                        lt_count += 1
                    except Exception:
                        LOGGER.exception("long-term promotion failed for %s", candidate["key"])
                        self._record("errors")

        if vector_memory is not None:
            put = getattr(vector_memory, "put", None)
            if callable(put):
                for candidate in candidates:
                    try:
                        await put(
                            candidate["key"],
                            candidate["value"],
                            tags=candidate["tags"],
                            importance=candidate["importance"],
                            source="summarizer",
                        )
                        vec_count += 1
                    except Exception:
                        LOGGER.exception("vector promotion failed for %s", candidate["key"])
                        self._record("errors")

        self._record("promotions", lt_count + vec_count)
        await self.emit(
            "after_promotion",
            conversation_id=report.conversation_id,
            long_term=lt_count,
            vector=vec_count,
        )
        return {"long_term": lt_count, "vector": vec_count}

    # ============================================================
    # Manager Contract: summarize
    # ============================================================

    async def summarize(
        self,
        content: Any,
        **kwargs: Any,
    ) -> SummaryResult:
        """
        Summarize arbitrary content into a structured SummaryResult.

        Satisfies MemoryManager.summarize() contract.
        """
        start = time.perf_counter()
        await self.emit("before_summary", content=content)

        messages = self._content_to_messages(content)
        if not messages:
            raise ValueError("content contains no messages")

        text = "\n".join(f"{role}: {payload}" for role, payload in messages)
        style = kwargs.get("style", self._config.summary_style)
        max_tokens = kwargs.get("max_tokens")
        conversation_id = kwargs.get("conversation_id", "")

        report = await self.build_knowledge(
            messages,
            conversation_id=conversation_id,
            style=style,
            max_tokens=max_tokens,
        )

        source_tokens = self.token_count(text)
        output_tokens = self.token_count(report.summary)

        result = SummaryResult(
            text=report.summary,
            style=SummaryStyle(style) if isinstance(style, str) else style,
            topics=report.topics,
            facts=report.facts,
            preferences=report.preferences,
            decisions=report.decisions,
            tasks=report.tasks,
            events=report.events,
            entities=report.entities,
            importance=report.importance,
            confidence=report.confidence,
            source_tokens=source_tokens,
            output_tokens=output_tokens,
            compression_ratio=round(output_tokens / max(1, source_tokens), 4),
        )

        latency = (time.perf_counter() - start) * 1000.0
        self._record("summaries")
        self._record("tokens_in", source_tokens)
        self._record("tokens_out", output_tokens)
        self._record("total_latency_ms", latency)

        await self.emit(
            "after_summary",
            result=result,
            latency_ms=latency,
        )
        return result

    # ============================================================
    # Manager Contract: compress
    # ============================================================

    async def compress(
        self,
        content: Any,
        **kwargs: Any,
    ) -> CompressionReport:
        """
        Compress content to fit a token budget.

        Satisfies MemoryManager.compress() contract.
        """
        text = self._content_to_text(content)
        ratio = kwargs.get("ratio")
        keep_important = kwargs.get("keep_important", True)

        await self.emit("before_compress", content=content)
        report = self.compress_text(
            text,
            ratio=ratio,
            keep_important=keep_important,
        )
        self._record("compressions")
        await self.emit("after_compress", report=report)
        return report

    # ============================================================
    # Manager Contract: importance_score
    # ============================================================

    async def importance_score(self, content: Any) -> float:
        """
        Return an importance score in [0, 1].

        Satisfies MemoryManager.importance_score() contract.
        """
        if isinstance(content, SummaryResult):
            return round(content.importance / IMPORTANCE_MAX, 4)
        if isinstance(content, KnowledgeReport):
            return round(content.importance / IMPORTANCE_MAX, 4)
        if isinstance(content, CompressionReport):
            return round(min(1.0, content.compressed_tokens / max(1, content.original_tokens)), 4)

        messages = self._content_to_messages(content)
        if not messages:
            raise ValueError("content contains no messages")

        text = "\n".join(f"{role}: {payload}" for role, payload in messages)
        analyses = [
            self.analyze_message(role, payload)
            for role, payload in messages
        ]
        importance = self.score_importance(text, analysis=analyses)
        return round(importance / IMPORTANCE_MAX, 4)

    # ============================================================
    # High-Level API
    # ============================================================

    async def analyze(
        self,
        content: Any,
        **kwargs: Any,
    ) -> KnowledgeReport:
        """Extract structured knowledge from a conversation."""
        start = time.perf_counter()
        await self.emit("before_analysis", content=content)

        messages = self._content_to_messages(content)
        if not messages:
            raise ValueError("content contains no messages")

        report = await self.build_knowledge(
            messages,
            conversation_id=kwargs.get("conversation_id", ""),
            style=kwargs.get("style", self._config.summary_style),
            max_tokens=kwargs.get("max_tokens"),
        )

        self._record("analyses")
        self._record("total_latency_ms", (time.perf_counter() - start) * 1000.0)
        await self.emit("after_analysis", report=report)
        return report

    def _content_to_text(self, content: Any) -> str:
        messages = self._content_to_messages(content)
        if not messages:
            return str(content)
        return "\n".join(f"{role}: {payload}" for role, payload in messages)

    # ============================================================
    # Export / Import
    # ============================================================

    def export_report(
        self,
        report: KnowledgeReport,
        *,
        format: str = "json",
    ) -> str:
        if format == "json":
            return json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        if format == "markdown":
            lines = [f"# Knowledge Report: {report.conversation_id}", ""]
            lines.append(f"**Importance**: {report.importance:.1f}/100  ")
            lines.append(f"**Confidence**: {report.confidence:.2f}  ")
            lines.append("")
            lines.append("## Summary")
            lines.append(report.summary)
            if report.facts:
                lines += ["", "## Facts"]
                lines += [f"- **{f.attribute}**: {f.value}" for f in report.facts]
            if report.preferences:
                lines += ["", "## Preferences"]
                lines += [f"- **{p.key}**: {p.value}" for p in report.preferences]
            if report.tasks:
                lines += ["", "## Tasks"]
                lines += [f"- [{t.state.value}] {t.description}" for t in report.tasks]
            if report.entities:
                lines += ["", "## Entities"]
                lines += [f"- {e.name} ({e.kind})" for e in report.entities]
            return "\n".join(lines)
        if format == "html":
            body = self.export_report(report, format="markdown")
            escaped = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<html><body><pre>{escaped}</pre></body></html>"
        raise ValueError(f"unsupported export format '{format}'")

    def export_state(self) -> dict[str, Any]:
        return {
            "namespace": self._config.namespace,
            "state": self._state.value,
            "config": asdict(self._config) if not isinstance(self._config.summary_style, str) else {
                **asdict(self._config),
                "summary_style": self._config.summary_style.value,
            },
            "metrics": self.metrics,
            "queue_size": self.queue_size,
            "started_at": self._started_at.isoformat(),
        }

    # ============================================================
    # Diagnostics
    # ============================================================

    def statistics(self) -> dict[str, Any]:
        return self.metrics

    def health(self) -> dict[str, Any]:
        status = "healthy"
        issues: list[str] = []
        if self._metrics["errors"] > 0:
            status = "degraded"
            issues.append(f"{int(self._metrics['errors'])} errors recorded")
        return {
            "status": status,
            "state": self._state.value,
            "queue_size": self.queue_size,
            "issues": issues,
            "metrics": self.metrics,
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "health": self.health(),
            "state": self.export_state(),
            "config": self.export_state()["config"],
            "listeners": self.listener_count(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def benchmark(self, text: str, *, rounds: int = 20) -> dict[str, float]:
        import time as _time

        latencies: list[float] = []
        for _ in range(rounds):
            start = _time.perf_counter()
            messages = self._content_to_messages(text)
            analysis = [
                self.analyze_message(role, payload)
                for role, payload in messages
            ]
            self.score_importance(text, analysis=analysis)
            latencies.append((_time.perf_counter() - start) * 1000.0)

        return {
            "rounds": rounds,
            "mean_ms": round(sum(latencies) / len(latencies), 3),
            "min_ms": round(min(latencies), 3),
            "max_ms": round(max(latencies), 3),
        }

    async def reset(self) -> None:
        """Reset metrics and queue state while preserving configuration."""
        self._metrics = {
            "summaries": 0.0,
            "analyses": 0.0,
            "compressions": 0.0,
            "promotions": 0.0,
            "errors": 0.0,
            "tokens_in": 0.0,
            "tokens_out": 0.0,
            "total_latency_ms": 0.0,
        }
        while not self._queue.empty():
            self._queue.get_nowait()
        self._started_at = datetime.now(timezone.utc)
        await self.emit("reset")

    # ============================================================
    # Context Manager
    # ============================================================

    async def __aenter__(self) -> "MemorySummarizer":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        await self.stop()
