"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.quality

Purpose:
    Data quality improvements:
    - Near-deduplication (SimHash, MinHash)
    - Entity linking to knowledge bases
    - Multilingual support (language detection, translation)
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.A02_News_Intelligence.core.models import NormalizedItem


# ==============================================================================
# SIMHASH (near-deduplication)
# ==============================================================================


class SimHash:
    """SimHash for near-duplicate detection."""
    
    def __init__(self, f: int = 64, seed: int = 42):
        self.f = f
        self.seed = seed
        random.seed(seed)
        # Pre-generate random weights for tokens
        self._token_weights: dict[str, int] = {}
    
    def _get_weight(self, token: str) -> int:
        if token not in self._token_weights:
            self._token_weights[token] = random.getrandbits(self.f)
        return self._token_weights[token]
    
    def hash(self, text: str) -> int:
        """Compute SimHash of text."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0
        
        v = [0] * self.f
        for token in tokens:
            weight = self._get_weight(token)
            for i in range(self.f):
                bit = (weight >> i) & 1
                v[i] += 1 if bit else -1
        
        fingerprint = 0
        for i in range(self.f):
            if v[i] > 0:
                fingerprint |= (1 << i)
        return fingerprint
    
    def _tokenize(self, text: str) -> list[str]:
        """Extract n-gram tokens from text."""
        text = re.sub(r"[^\w\s]", " ", text.lower())
        words = text.split()
        tokens = []
        for i in range(len(words) - 2):
            tokens.append(" ".join(words[i:i+3]))  # 3-grams
        return tokens
    
    @staticmethod
    def hamming_distance(a: int, b: int) -> int:
        """Hamming distance between two fingerprints."""
        return bin(a ^ b).count("1")
    
    @staticmethod
    def similarity(a: int, b: int, f: int = 64) -> float:
        """Similarity between two fingerprints (0-1)."""
        dist = SimHash.hamming_distance(a, b)
        return 1.0 - dist / f


class NearDeduplicator:
    """Near-duplicate detection using SimHash."""
    
    def __init__(self, threshold: float = 0.85, f: int = 64):
        self.threshold = threshold
        self.simhash = SimHash(f=f)
        self._index: dict[int, list[tuple[int, str]]] = defaultdict(list)  # hash -> [(doc_id, fingerprint)]
    
    def add(self, doc_id: int, text: str) -> int:
        """Add document to index. Returns fingerprint."""
        fp = self.simhash.hash(text)
        self._index[fp].append((doc_id, fp))
        return fp
    
    def find_duplicates(self, text: str) -> list[tuple[int, float]]:
        """Find near-duplicates of text. Returns [(doc_id, similarity)]."""
        fp = self.simhash.hash(text)
        duplicates = []
        
        # Check exact fingerprint matches first
        for doc_id, existing_fp in self._index.get(fp, []):
            duplicates.append((doc_id, 1.0))
        
        # Check nearby fingerprints (for small index, check all)
        # For large index, use bucketing/LSH
        for existing_fp, entries in self._index.items():
            if existing_fp == fp:
                continue
            sim = SimHash.similarity(fp, existing_fp, self.simhash.f)
            if sim >= self.threshold:
                for doc_id, _ in entries:
                    duplicates.append((doc_id, sim))
        
        # Sort by similarity descending
        duplicates.sort(key=lambda x: x[1], reverse=True)
        return duplicates
    
    def is_near_duplicate(self, text: str) -> bool:
        """Quick check if text has near-duplicate."""
        return len(self.find_duplicates(text)) > 0


# ==============================================================================
# MINHASH (Jaccard similarity estimation)
# ==============================================================================


class MinHash:
    """MinHash for Jaccard similarity estimation."""
    
    def __init__(self, num_perm: int = 128, seed: int = 42):
        self.num_perm = num_perm
        self.seed = seed
        random.seed(seed)
        self._permutations = [random.randint(1, 2**32 - 1) for _ in range(num_perm)]
    
    def _hash(self, token: str) -> int:
        """Hash a token."""
        return int(hashlib.md5(token.encode()).hexdigest(), 16)
    
    def signature(self, tokens: set[str]) -> list[int]:
        """Compute MinHash signature for a set of tokens."""
        if not tokens:
            return [2**32 - 1] * self.num_perm
        
        sig = [2**32 - 1] * self.num_perm
        for token in tokens:
            h = self._hash(token)
            for i, perm in enumerate(self._permutations):
                # Simple permutation: XOR with random value
                permuted = h ^ perm
                if permuted < sig[i]:
                    sig[i] = permuted
        return sig
    
    @staticmethod
    def jaccard_similarity(sig1: list[int], sig2: list[int]) -> float:
        """Estimate Jaccard similarity from signatures."""
        if len(sig1) != len(sig2):
            return 0.0
        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / len(sig1)


class MinHashLSH:
    """MinHash LSH for scalable near-duplicate detection."""
    
    def __init__(self, threshold: float = 0.8, num_perm: int = 128, num_bands: int = 16):
        self.threshold = threshold
        self.minhash = MinHash(num_perm=num_perm)
        self.num_bands = num_bands
        self.rows_per_band = num_perm // num_bands
        self._buckets: dict[int, dict[tuple, list[int]]] = defaultdict(lambda: defaultdict(list))
        self._signatures: dict[int, list[int]] = {}
    
    def add(self, doc_id: int, tokens: set[str]) -> None:
        """Add document to LSH index."""
        sig = self.minhash.signature(tokens)
        self._signatures[doc_id] = sig
        
        for band in range(self.num_bands):
            start = band * self.rows_per_band
            end = start + self.rows_per_band
            band_key = tuple(sig[start:end])
            self._buckets[band][band_key].append(doc_id)
    
    def query(self, tokens: set[str]) -> list[tuple[int, float]]:
        """Find similar documents."""
        sig = self.minhash.signature(tokens)
        candidates = set()
        
        for band in range(self.num_bands):
            start = band * self.rows_per_band
            end = start + self.rows_per_band
            band_key = tuple(sig[start:end])
            for doc_id in self._buckets[band].get(band_key, []):
                candidates.add(doc_id)
        
        results = []
        for doc_id in candidates:
            if doc_id in self._signatures:
                sim = MinHash.jaccard_similarity(sig, self._signatures[doc_id])
                if sim >= self.threshold:
                    results.append((doc_id, sim))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results


# ==============================================================================
# ENTITY LINKING
# ==============================================================================


@dataclass
class EntityLink:
    """Link between extracted entity and knowledge base entry."""
    entity_text: str
    entity_type: str
    kb_id: str
    kb_name: str
    confidence: float
    kb_url: str | None = None
    aliases: list[str] = field(default_factory=list)


class EntityLinker:
    """Link extracted entities to knowledge base entries (Wikidata, etc.)."""
    
    def __init__(self):
        # In production, this would load from a knowledge base
        # For now, use a small built-in mapping
        self._kb: dict[str, dict] = self._load_builtin_kb()
    
    def _load_builtin_kb(self) -> dict[str, dict]:
        """Load built-in knowledge base for common financial entities."""
        return {
            "BTC": {
                "kb_id": "Q11004",
                "kb_name": "Bitcoin",
                "type": "crypto",
                "url": "https://www.wikidata.org/wiki/Q11004",
                "aliases": ["bitcoin", "btc", "₿"],
            },
            "ETH": {
                "kb_id": "Q13617548",
                "kb_name": "Ethereum",
                "type": "crypto",
                "url": "https://www.wikidata.org/wiki/Q13617548",
                "aliases": ["ethereum", "eth", "Ξ"],
            },
            "AAPL": {
                "kb_id": "Q317521",
                "kb_name": "Apple Inc.",
                "type": "stock",
                "url": "https://www.wikidata.org/wiki/Q317521",
                "aliases": ["apple", "apple inc"],
            },
            "TSLA": {
                "kb_id": "Q40732",
                "kb_name": "Tesla, Inc.",
                "type": "stock",
                "url": "https://www.wikidata.org/wiki/Q40732",
                "aliases": ["tesla", "tesla inc"],
            },
            "SEC": {
                "kb_id": "Q170584",
                "kb_name": "U.S. Securities and Exchange Commission",
                "type": "organization",
                "url": "https://www.wikidata.org/wiki/Q170584",
                "aliases": ["securities and exchange commission", "u.s. sec"],
            },
            "FED": {
                "kb_id": "Q210213",
                "kb_name": "Federal Reserve System",
                "type": "organization",
                "url": "https://www.wikidata.org/wiki/Q210213",
                "aliases": ["federal reserve", "the fed", "central bank"],
            },
            "GOLD": {
                "kb_id": "Q658",
                "kb_name": "Gold",
                "type": "commodity",
                "url": "https://www.wikidata.org/wiki/Q658",
                "aliases": ["gold", "xau"],
            },
            "OIL": {
                "kb_id": "Q177781",
                "kb_name": "Crude oil",
                "type": "commodity",
                "url": "https://www.wikidata.org/wiki/Q177781",
                "aliases": ["crude oil", "wti", "brent"],
            },
        }
    
    def link(self, entity_text: str, entity_type: str | None = None) -> EntityLink | None:
        """Link entity text to knowledge base."""
        text_lower = entity_text.lower().strip()
        
        # Direct symbol match
        if text_lower.upper() in self._kb:
            kb = self._kb[text_lower.upper()]
            return EntityLink(
                entity_text=entity_text,
                entity_type=entity_type or kb["type"],
                kb_id=kb["kb_id"],
                kb_name=kb["kb_name"],
                confidence=1.0,
                kb_url=kb["url"],
                aliases=kb["aliases"],
            )
        
        # Alias match
        for symbol, kb in self._kb.items():
            if text_lower in [a.lower() for a in kb["aliases"]]:
                return EntityLink(
                    entity_text=entity_text,
                    entity_type=entity_type or kb["type"],
                    kb_id=kb["kb_id"],
                    kb_name=kb["kb_name"],
                    confidence=0.9,
                    kb_url=kb["url"],
                    aliases=kb["aliases"],
                )
        
        # Fuzzy match for organization names
        if entity_type == "organization" or "sec" in text_lower or "fed" in text_lower:
            for symbol, kb in self._kb.items():
                if kb["type"] == "organization":
                    for alias in kb["aliases"]:
                        if alias in text_lower or text_lower in alias:
                            return EntityLink(
                                entity_text=entity_text,
                                entity_type="organization",
                                kb_id=kb["kb_id"],
                                kb_name=kb["kb_name"],
                                confidence=0.7,
                                kb_url=kb["url"],
                                aliases=kb["aliases"],
                            )
        
        return None
    
    def link_entities(self, entities: list) -> list[EntityLink]:
        """Link multiple entities."""
        links = []
        for entity in entities:
            link = self.link(entity.symbol if hasattr(entity, 'symbol') else str(entity), 
                           entity.type if hasattr(entity, 'type') else None)
            if link:
                links.append(link)
        return links


# ==============================================================================
# MULTILINGUAL SUPPORT
# ==============================================================================


class LanguageDetector:
    """Simple language detection."""
    
    # Common words per language
    _LANG_MARKERS = {
        "en": {"the", "and", "of", "to", "in", "a", "is", "for", "on", "with", "as", "by", "at", "an", "be", "this", "that", "from", "or", "are"},
        "es": {"el", "la", "de", "que", "y", "en", "un", "es", "se", "no", "te", "lo", "le", "da", "su", "por", "son", "con", "para", "una"},
        "fr": {"le", "la", "de", "et", "à", "un", "il", "être", "et", "en", "avoir", "que", "pour", "dans", "ce", "il", "qui", "ne", "sur", "se"},
        "de": {"der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich", "des", "auf", "für", "ist", "im", "dem", "nicht", "ein", "eine", "als"},
        "zh": {"的", "一", "是", "在", "不", "了", "有", "和", "人", "这", "中", "大", "为", "上", "个", "国", "我", "以", "要", "他"},
        "ja": {"の", "に", "は", "を", "た", "が", "で", "て", "と", "し", "れ", "さ", "ある", "いる", "も", "な", "う", "る", "ん", "か", "よ"},
        "ru": {"и", "в", "не", "на", "я", "что", "то", "он", "но", "да", "ты", "к", "у", "же", "вы", "за", "так", "с", "по", "это"},
        "pt": {"o", "a", "de", "que", "e", "do", "da", "em", "um", "para", "é", "com", "não", "uma", "os", "no", "se", "na", "por", "mais"},
    }
    
    def detect(self, text: str) -> tuple[str, float]:
        """Detect language of text. Returns (lang_code, confidence)."""
        if not text:
            return ("unknown", 0.0)
        
        # Simple word-based detection
        words = set(re.findall(r"\w+", text.lower()))
        if not words:
            return ("unknown", 0.0)
        
        scores = {}
        for lang, markers in self._LANG_MARKERS.items():
            matches = len(words & markers)
            scores[lang] = matches / len(markers)
        
        if not scores:
            return ("unknown", 0.0)
        
        best_lang = max(scores, key=scores.get)
        confidence = scores[best_lang]
        
        # Boost confidence for English (dominant in financial news)
        if best_lang == "en" and confidence > 0.1:
            confidence = min(1.0, confidence * 1.5)
        
        return (best_lang, confidence)


class Translator:
    """Translation stub (integrate with Google Translate, DeepL, etc.)."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.enabled = api_key is not None
    
    def translate(self, text: str, target_lang: str = "en", source_lang: str | None = None) -> str:
        """Translate text to target language."""
        if not self.enabled:
            return text  # Return original if no API
        
        # TODO: Implement actual translation API
        # - Google Translate API
        # - DeepL API
        # - LibreTranslate
        return text
    
    def translate_batch(self, texts: list[str], target_lang: str = "en") -> list[str]:
        return [self.translate(t, target_lang) for t in texts]


# ==============================================================================
# INTEGRATION HELPERS
# ==============================================================================


def enhance_item_quality(item: "NormalizedItem") -> "NormalizedItem":
    """Enhance a normalized item with quality improvements."""
    from agents.A02_News_Intelligence.core.quality import (
        SimHash,
        NearDeduplicator,
        LanguageDetector,
        EntityLinker,
    )
    
    # Language detection
    detector = LanguageDetector()
    lang, conf = detector.detect(item.title + " " + item.content)
    if not hasattr(item, "language"):
        item.language = lang
    if not hasattr(item, "language_confidence"):
        item.language_confidence = conf
    
    # Translation to English if not English
    if lang != "en" and conf > 0.5:
        translator = Translator()
        item.title = translator.translate(item.title, "en")
        item.content = translator.translate(item.content, "en")
    
    return item


def build_quality_index(items: list["NormalizedItem"]) -> NearDeduplicator:
    """Build near-deduplication index from items."""
    dedup = NearDeduplicator(threshold=0.85)
    for i, item in enumerate(items):
        text = item.title + " " + item.content
        dedup.add(i, text)
    return dedup


__all__ = [
    "SimHash",
    "NearDeduplicator",
    "MinHash",
    "MinHashLSH",
    "EntityLink",
    "EntityLinker",
    "LanguageDetector",
    "Translator",
    "enhance_item_quality",
    "build_quality_index",
]