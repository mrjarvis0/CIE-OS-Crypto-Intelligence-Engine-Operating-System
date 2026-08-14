"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.monitoring.diagnostics

Purpose:
    Diagnostics for the intelligence system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Diagnostics:
    """
    Collects diagnostic observations.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)

    def log(self, level: str, message: str, **attrs: Any) -> None:
        """
        Record a diagnostic entry.
        """
        self.entries.append({"level": level, "message": message, **attrs})

    def snapshot(self) -> list[dict[str, Any]]:
        """
        Return all diagnostic entries.
        """
        return list(self.entries)

    def clear(self) -> None:
        """
        Clear all diagnostic entries.
        """
        self.entries.clear()
