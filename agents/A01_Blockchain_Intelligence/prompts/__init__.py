"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    prompts

Purpose:
    Safe handling of untrusted text on its way to a language model.

A01 is an autonomous agent that ingests attacker-controlled data by design.
Token names, contract metadata, ENS records, NFT metadata, calldata, IPFS
documents and social content are all cheap and permanent to write, and all of
them flow into the reasoning layer. That makes indirect prompt injection A01's
most serious novel risk -- more serious than the analytical-evasion threats a
conventional analytics platform models.

Modules
-------
sanitize   Structural neutralisation and injection-pattern detection.
fencing    Explicit data boundaries with a standing never-obey directive.

Usage
-----
    from prompts import fence_subject

    cleaned, fenced = fence_subject(subject)
    # `cleaned` is safe for deterministic analysis.
    # `fenced.text` is what goes into the model prompt.
    if fenced.suspicious:
        ...  # record an adversarial indicator for this subject

An injection attempt is itself intelligence. A contract whose metadata
contains a payload is a strong adversarial signal, so it is logged and
attributed rather than quietly filtered away.

See docs/intelligence/threat-model.md section 3.1.
"""

from __future__ import annotations

from .fencing import FENCE_DIRECTIVE, FencedContent, fence, fence_subject
from .sanitize import (
    DEFAULT_MAX_LENGTH,
    INJECTION_PATTERNS,
    SanitizationReport,
    SanitizedText,
    detect_injection,
    sanitize,
    sanitize_mapping,
)

__all__ = [
    "FENCE_DIRECTIVE",
    "FencedContent",
    "fence",
    "fence_subject",
    "DEFAULT_MAX_LENGTH",
    "INJECTION_PATTERNS",
    "SanitizationReport",
    "SanitizedText",
    "detect_injection",
    "sanitize",
    "sanitize_mapping",
]
