"""
Tools :: Marketplace :: Reviews
===============================

Human feedback: reviews, bug reports, security notes, compatibility
reports and recommendations.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["Review", "ReviewsStore", "REVIEW_KINDS"]

REVIEW_KINDS = ("review", "bug_report", "security_note", "compatibility_report", "recommendation")


@dataclass
class Review:
    """One piece of human feedback."""

    package_id: str
    kind: str = "review"
    author: str = ""
    text: str = ""
    rating: float = 0.0
    review_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in REVIEW_KINDS:
            raise ValueError(f"unknown review kind {self.kind!r}")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "review_id": self.review_id,
            "package_id": self.package_id,
            "kind": self.kind,
            "author": self.author,
            "text": self.text,
            "rating": self.rating,
            "timestamp": self.timestamp,
        }


class ReviewsStore:
    """Append-only store of human feedback."""

    def __init__(self) -> None:
        self._reviews: List[Review] = []

    def add(self, review: Review) -> Review:
        self._reviews.append(review)
        return review

    def by_package(self, package_id: str) -> List[Review]:
        return [review for review in self._reviews if review.package_id == package_id]

    def by_kind(self, kind: str) -> List[Review]:
        return [review for review in self._reviews if review.kind == kind]

    def security_notes(self, package_id: str) -> List[Review]:
        return [review for review in self._reviews if review.package_id == package_id and review.kind == "security_note"]

    def bug_reports(self, package_id: str) -> List[Review]:
        return [review for review in self._reviews if review.package_id == package_id and review.kind == "bug_report"]

    def recommendations(self, package_id: str) -> List[Review]:
        return [review for review in self._reviews if review.package_id == package_id and review.kind == "recommendation"]

    def all(self, limit: int = 200) -> List[Review]:
        return list(self._reviews[-max(1, int(limit)):])