"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    interfaces.agent

Purpose:
    Wire :class:`core.blockchain_agent.BlockchainAgent` to
    :class:`~interfaces.service.IntelligenceService`, so the agent surface
    answers from the same place the CLI and the REST router do.

Notes
-----
The wiring lives here rather than in ``core`` because the dependency only runs
one way. ``core`` is rank 1 of the layer stack and ``interfaces`` is the top, so
the agent declares the shape it needs and this module -- which is allowed to see
both -- supplies it. Nothing else about the agent is decided here: the factory
constructs, injects, and returns.

A01 has three surfaces now, and this is the third. The CLI renders for a
terminal, REST serializes for a socket, and the agent exposes the same
operations to the core runtime -- lifecycle, middleware, hooks, statistics --
for callers that want an investigation to run inside that machinery rather than
as a one-shot call. All three go through one service, which is the only reason
they cannot answer the same question differently.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.blockchain_agent import BlockchainAgent, blockchain_agent_config
from decision import Subscription

from .service import IntelligenceService

__all__ = ["build_blockchain_agent"]


def build_blockchain_agent(
    *,
    database_path: str | Path | None = None,
    subscriptions: Iterable[Subscription] = (),
    service: IntelligenceService | None = None,
    **agent_kwargs: Any,
) -> BlockchainAgent:
    """
    A :class:`BlockchainAgent` with an intelligence backend already attached.

    ``service`` takes an already-built one; it is the seam tests use to pass a
    service pointed at a fixture database, and the way a caller shares one
    service -- and therefore one alert budget -- between an agent and another
    surface. When it is omitted a service is constructed from
    ``database_path``.

    Passing neither is allowed and is not a misconfiguration: a service with no
    database still answers the catalogue operations (``skills``, ``detectors``,
    ``chains``) and declines the rest with a reason, which is more useful than
    refusing to construct.
    """
    if service is None:
        service = IntelligenceService(
            database_path=database_path, subscriptions=subscriptions
        )

    config = agent_kwargs.pop("config", None) or blockchain_agent_config()

    return BlockchainAgent(config, backend=service, **agent_kwargs)
