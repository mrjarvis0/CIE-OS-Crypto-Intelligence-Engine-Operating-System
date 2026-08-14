"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    skills.whale_detection

One skill, one responsibility. See ``skills/README.md`` for the layer rules.
"""

from __future__ import annotations

from .transfers import WhaleTransferSkill

__all__ = ["WhaleTransferSkill"]
