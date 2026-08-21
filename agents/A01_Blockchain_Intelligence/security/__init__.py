"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    security

Security has two canonical homes and they are not interchangeable, so they
are bound under distinct names rather than merged.

``configuration`` is :mod:`config.security` -- secret resolution, API-key
specs, input validation. ``runtime`` is :mod:`tools.security` --
authentication, authorization, rate limiting, sandbox isolation.

Why they are not merged
-----------------------
Every other redirect package in this tree forwards unknown names to its one
canonical module. This one deliberately does not, because there are two and
their surfaces collide: both define a secret wrapper.
``config.security.SecretValue`` refuses pickling, copying and
``dataclasses.asdict``; ``tools.security.Secret`` is a lighter in-memory
holder. A caller reaching for ``security.Secret`` through a merged namespace
could not tell which hardening they were getting, and would have no reason
to suspect there was a choice.

That is the drift this package exists to prevent, in its most dangerous
form -- so the ambiguity is preserved as two names instead of hidden behind
one.

On-chain security *screening* is a third thing entirely and lives at
:mod:`blockchain.security`. It measures other people's contracts; these two
protect this process. They share a word and nothing else.
"""

from __future__ import annotations

from config import security as configuration
from tools import security as runtime

__all__ = ["configuration", "runtime"]
