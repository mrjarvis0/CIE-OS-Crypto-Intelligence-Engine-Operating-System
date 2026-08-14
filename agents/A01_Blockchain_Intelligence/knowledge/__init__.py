"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    knowledge

Purpose:
    What A01 knows about the world it observes, as distinct from how it is
    configured to reach it.

The distinction
---------------
`config/rpc/chains.py` says what a chain **is** — its id, native currency,
block time. This package says what A01 can **do** with it, which nothing else
answers. A caller deciding whether to trust an Arbitrum analysis needs to know
that native transfers there are routinely zero and the activity is entirely in
token logs; no chain id conveys that.

The registry is imported here, never restated. Two answers to "what is
Ethereum's chain id" is one answer too many.

Measured, and re-measurable
---------------------------
Every capability fact came from probing the live chain through A01's own sensor
stack, on the date in `MEASURED_ON`. `probe()` re-measures and reports drift, so
the table can be checked rather than trusted — which is the only thing that
makes a dated fact honest as it ages.

The negative facts carry the most weight. `archive_available` is `False` on every
chain not because archive nodes do not exist, but because the free endpoints A01
defaults to do not serve them; Solana and Bitcoin are unobservable not for lack
of endpoints but for lack of a sensor that speaks their dialect.
"""

from __future__ import annotations

from .chains import (
    CAPABILITIES,
    MEASURED_ON,
    ChainCapability,
    Finality,
    ProbeResult,
    capability,
    observable_chains,
    probe,
    registry_only_chains,
    summary,
    token_capable_chains,
)

__all__ = [
    "CAPABILITIES",
    "MEASURED_ON",
    "ChainCapability",
    "Finality",
    "ProbeResult",
    "capability",
    "observable_chains",
    "probe",
    "registry_only_chains",
    "summary",
    "token_capable_chains",
]
