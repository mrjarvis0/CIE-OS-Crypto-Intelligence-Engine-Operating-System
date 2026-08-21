"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    skills.network_health

One skill, one responsibility. See ``skills/README.md`` for the layer rules.
"""

from __future__ import annotations

from .monitor import NetworkHealthSkill

__all__ = ["NetworkHealthSkill"]
