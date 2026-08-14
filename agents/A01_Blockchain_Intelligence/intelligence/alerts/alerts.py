"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.alerts.alerts

Purpose:
    Alert model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class Alert:
    """
    An intelligence alert event.
    """

    alert_id: str
    title: str
    severity: str = "info"
    trigger: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "title": self.title,
            "severity": self.severity,
            "trigger": self.trigger,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }
