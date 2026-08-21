"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    interfaces

Purpose:
    How results leave A01. Exposes; does not decide or interpret.

Layer contract
--------------
`decision/` decides what may be said. This layer turns that into bytes for a
particular consumer and does nothing else — no surface applies a threshold, a
confidence ceiling, or a verb of its own.

:class:`IntelligenceService` is the single entry point every surface goes
through. Without it, surfaces drift: the CLI grows a flag REST lacks, one applies
the maturity gate a step earlier than the other, and two callers get two answers
to the same question — invisibly, until somebody compares them.

Surfaces
--------
| Surface | State |
| --- | --- |
| Internal service | :class:`IntelligenceService` — the facade all others use |
| CLI | `python -m cli` |
| REST | :func:`interfaces.rest.serve`, loopback-bound, GET-only |
| WebSocket | Not built — see below |
| Dashboard | Not built |

**Why there is no WebSocket.** A subscription transport needs something to push.
A01's ingestion is stepped and operator-driven — there is no resident process
producing events — so a socket would deliver nothing until an ingestion daemon
exists. Building the transport first would mean testing it against a synthetic
event source and discovering its real shape later. The order is: daemon, then
event stream, then socket.

Security
--------
The REST API has no authentication, so its **bind address is the boundary**. It
defaults to `127.0.0.1` and warns when asked to bind anything else. Only GET is
routed: A01 is read-only by architecture, and the ingestion write path is
deliberately unexposed, since a request-triggered fetch would put an unbounded
rate-limited job behind an HTTP call.
"""

from __future__ import annotations

from .agent import build_blockchain_agent
from .rest import DEFAULT_HOST, DEFAULT_PORT, Router, build_server, serve
from .service import IntelligenceService, ServiceResult

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "IntelligenceService",
    "Router",
    "ServiceResult",
    "build_blockchain_agent",
    "build_server",
    "serve",
]
