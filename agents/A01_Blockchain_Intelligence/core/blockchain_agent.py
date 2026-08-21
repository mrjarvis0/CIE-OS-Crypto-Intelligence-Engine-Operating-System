"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.blockchain_agent

Purpose:
    The concrete agent that :class:`core.agent.BaseAgent` was written for.

Design goals:
    - One implementation of ``execute()``, so the core runtime is reachable
    - Every answer comes from the same seam the CLI and REST surfaces use
    - Read-only: the agent exposes queries, never ingestion
    - No upward import; the intelligence backend arrives by injection

Notes
-----
``BaseAgent`` is a complete runtime -- lifecycle, middleware, hooks, workers,
statistics, health, audit -- with one deliberate hole in it: ``execute()``
raises, because the base class has no domain. Until something filled that hole
none of the rest of the machine could run, and the file's own docstring named
four concrete agents (``BlockchainAgent``, ``WalletAnalyzer``,
``SmartContractAnalyzer``, ``MEVDetector``) that did not exist. This module is
the first of them, and the one the other three would specialise.

**Why the backend is injected rather than imported.** ``core`` sits at rank 1 of
the layer stack (``tests/test_architecture.py``); ``interfaces`` sits at the
top. An ``import`` from here to :class:`interfaces.service.IntelligenceService`
would be an upward import, and the architecture ratchet asserts there are none.
The dependency-injection container already on ``BaseAgent`` is the seam that was
built for exactly this, so the agent declares the shape it needs
(:class:`IntelligenceBackend`) structurally and is handed an implementation by
:func:`interfaces.agent.build_blockchain_agent`.

Going through that one backend is also what keeps the three surfaces honest.
The CLI and the REST router already share :class:`IntelligenceService` so they
cannot answer the same question differently; an agent that reached past it into
``intelligence`` directly would be a third answer, drifting invisibly from the
other two.

**Why there is no write operation.** A01 is read-only by architecture and its
ingestion is operator-driven and rate-limited. Putting a fetch behind an agent
task would hide an unbounded job inside what callers read as a lookup -- the
same reasoning that keeps ingestion off the REST surface.
"""

from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================

import asyncio
import logging

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

# =============================================================================
# Project Imports
# =============================================================================

from config.rpc.chains import default_registry as chain_registry

from .agent import (
    AgentCapability,
    AgentConfig,
    AgentIdentity,
    AgentMetadata,
    AgentPriority,
    BaseAgent,
    ExecutionMode,
    SupportedChain,
)
from .exceptions import AgentRuntimeError

# =============================================================================
# Logger
# =============================================================================

logger = logging.getLogger(__name__)

# =============================================================================
# Backend Contract
# =============================================================================


@runtime_checkable
class BackendResult(Protocol):
    """
    One backend answer, successful or not.

    Structural on purpose: :class:`interfaces.service.ServiceResult` satisfies
    it without either module knowing about the other, which is what lets the
    agent stay at its own layer.
    """

    ok: bool
    data: dict[str, Any]
    error: str
    status: int


class IntelligenceBackend(Protocol):
    """
    The operations :class:`BlockchainAgent` needs from the layer above it.

    Every method here is synchronous and every one of them may touch the
    database, which is why :meth:`BlockchainAgent.execute` calls them off the
    event loop rather than inline.
    """

    def investigate(
        self,
        *,
        chain: str = ...,
        address: str | None = ...,
        subject: dict[str, Any] | None = ...,
    ) -> BackendResult: ...

    def detectors(self) -> BackendResult: ...

    def skills(self) -> BackendResult: ...

    def chains(self) -> BackendResult: ...

    def labels(self, chain: str = ...) -> BackendResult: ...

    def flows(self, chain: str = ...) -> BackendResult: ...

    def coverage(self, chain: str = ...) -> BackendResult: ...

    def metrics(self) -> BackendResult: ...

    def health(self) -> BackendResult: ...


# =============================================================================
# Constants
# =============================================================================

#: Registry key the backend is stored under, and the name
#: :meth:`BlockchainAgent.execute` resolves at call time.
BACKEND_SERVICE: str = "intelligence"

#: Chain assumed when a task names none. Ethereum is the only chain A01 has
#: ingested at depth, so defaulting anywhere else would answer from an empty
#: window and call it a result.
DEFAULT_CHAIN: str = "ethereum"

#: What the agent can be asked, mapped to the backend call each one makes.
#:
#: Read operations only. The absence of an ``ingest`` entry is the point: see
#: the module docstring.
OPERATIONS: tuple[str, ...] = (
    "investigate",
    "detectors",
    "skills",
    "chains",
    "labels",
    "flows",
    "coverage",
    "metrics",
    "health",
)

#: Capabilities this agent actually backs.
#:
#: Deliberately narrower than :class:`~core.agent.AgentCapability`. Every skill
#: in the registry is ``LIMITED`` -- each answers from transfers, blocks and
#: labels, and states what it cannot see -- so the capabilities claimed here are
#: the ones the skills layer implements, not the ones the enum offers. MEV
#: detection, planning, reasoning and multi-agent coordination are absent
#: because nothing behind this agent performs them.
CAPABILITIES: frozenset[AgentCapability] = frozenset(
    {
        AgentCapability.ANALYZE_TRANSACTIONS,
        AgentCapability.ANALYZE_WALLETS,
        AgentCapability.ANALYZE_CONTRACTS,
        AgentCapability.TOKEN_ANALYSIS,
        AgentCapability.NFT_ANALYSIS,
        AgentCapability.DEFI_ANALYSIS,
        AgentCapability.BRIDGE_ANALYSIS,
        AgentCapability.RISK_SCORING,
        AgentCapability.SCAM_DETECTION,
        AgentCapability.ONCHAIN_INTELLIGENCE,
        AgentCapability.ENTITY_RESOLUTION,
        AgentCapability.AUDIT_LOGGING,
        AgentCapability.OBSERVABILITY,
        AgentCapability.HEALTH_MONITORING,
    }
)


# =============================================================================
# Configuration
# =============================================================================


def supported_chains() -> list[SupportedChain]:
    """
    The chain registry, in the shape ``AgentConfig`` holds.

    ``SupportedChain.chain_id`` is an EVM concept and Bitcoin and Solana have
    none, so ``0`` stands for "not applicable" and the truthful value is kept
    in ``metadata['chain_id']`` rather than invented as a number.
    """
    entries: list[SupportedChain] = []

    for chain in chain_registry():
        entries.append(
            SupportedChain(
                chain_id=chain.chain_id or 0,
                name=chain.name.value,
                symbol=chain.native_currency.symbol,
                ecosystem=chain.chain_type.value,
                explorer_url=(
                    chain.block_explorer_urls[0]
                    if chain.block_explorer_urls
                    else ""
                ),
                native_currency=chain.native_currency.name,
                enabled=chain.is_enabled,
                metadata={
                    "chain_id": chain.chain_id,
                    "confirmations": chain.confirmations,
                    "is_testnet": chain.is_testnet,
                },
            )
        )

    return entries


def blockchain_agent_config(
    *,
    name: str = "A01 Blockchain Intelligence",
    version: str = "1.0.0",
    execution_mode: ExecutionMode = ExecutionMode.INTERACTIVE,
    priority: AgentPriority = AgentPriority.NORMAL,
) -> AgentConfig:
    """A config declaring only what :class:`BlockchainAgent` can back."""
    return AgentConfig(
        identity=AgentIdentity(name=name, version=version),
        metadata=AgentMetadata(
            description=(
                "Reads A01's stored chain history and answers investigations "
                "through the same service the CLI and REST surfaces use."
            ),
            tags=["blockchain", "intelligence", "read-only"],
        ),
        execution_mode=execution_mode,
        priority=priority,
        capabilities=set(CAPABILITIES),
        supported_chains=supported_chains(),
    )


# =============================================================================
# Blockchain Agent
# =============================================================================


class BlockchainAgent(BaseAgent):
    """
    A01's read side, driven through the core runtime.

    A task is either an operation name or a mapping carrying one::

        await agent.run("skills")
        await agent.run({"operation": "investigate", "address": "0xabc..."})
        await agent.run("investigate", address="0xabc...", chain="ethereum")

    Keyword arguments and mapping keys are merged, with the keywords winning,
    so the two call styles can be mixed without one silently shadowing the
    other in the surprising direction.

    Failure is split two ways, deliberately. A backend outcome -- an empty
    database, a rejected address, storage that will not open -- comes back as a
    payload with ``ok`` false and the status the other surfaces would report;
    it is an answer, not a crash, and the CLI already treats it that way. A
    caller error -- an operation that does not exist, a task of the wrong
    shape, a backend that was never registered -- raises
    :class:`~core.exceptions.AgentRuntimeError`, because there is nothing to
    report and retrying will not help.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        backend: IntelligenceBackend | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(config or blockchain_agent_config(), **kwargs)

        for chain in self.config.supported_chains:
            self.register_chain(chain)

        if backend is not None:
            self.register_service(BACKEND_SERVICE, backend)

    # =================================================================
    # Backend Access
    # =================================================================

    @property
    def backend(self) -> IntelligenceBackend:
        """
        The registered intelligence backend.

        Resolved per call rather than cached on the instance so a backend
        swapped through the registry -- a fixture database in a test, a
        different file after a restore -- takes effect immediately instead of
        being shadowed by whatever was bound at construction.
        """
        service = self.get_service(BACKEND_SERVICE)

        if service is None:
            raise AgentRuntimeError(
                f"no {BACKEND_SERVICE!r} backend registered; construct the "
                "agent through interfaces.agent.build_blockchain_agent() or "
                f"call register_service({BACKEND_SERVICE!r}, ...)",
                details={"agent": self.identity.name},
            )

        return service

    def describe(self) -> dict[str, Any]:
        """
        What this agent can be asked, and on what.

        The counterpart of ``cli skills``: a caller should be able to discover
        the surface without reading this module.
        """
        return {
            "agent": self.identity.name,
            "version": self.identity.version,
            "operations": list(OPERATIONS),
            "capabilities": sorted(c.value for c in self.config.capabilities),
            "chains": [chain.name for chain in self.config.supported_chains],
            "default_chain": DEFAULT_CHAIN,
            "read_only": True,
            "backend_registered": self.get_service(BACKEND_SERVICE) is not None,
        }

    # =================================================================
    # Execution
    # =================================================================

    async def execute(
        self,
        task: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Run one read operation and return its payload.

        The backend is synchronous and every operation may open the database
        and run the full analysis engine, so the call is handed to a worker
        thread. Running it inline would stall the event loop -- and with it the
        heartbeat, the workers, and every other task on this agent -- for the
        length of a query.
        """
        operation, params = _parse_task(task, kwargs)

        if operation not in OPERATIONS:
            raise AgentRuntimeError(
                f"unknown operation {operation!r}; supported: "
                + ", ".join(OPERATIONS),
                details={"operation": operation},
            )

        backend = self.backend

        result = await asyncio.to_thread(
            _dispatch, backend, operation, params
        )

        payload = _as_payload(operation, result)

        self._audit(
            "operation_executed",
            operation=operation,
            ok=payload["ok"],
            status=payload["status"],
        )

        if not payload["ok"]:
            logger.info(
                "[%s] %s declined: %s",
                self.identity.name,
                operation,
                payload["error"],
            )

        return payload

    # =================================================================
    # Convenience Wrappers
    # =================================================================

    async def investigate(
        self,
        address: str | None = None,
        *,
        chain: str = DEFAULT_CHAIN,
        subject: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a full investigation; the operation most callers want."""
        return await self.run(
            "investigate", address=address, chain=chain, subject=subject
        )

    async def health_report(self) -> dict[str, Any]:
        """
        Backend health alongside this agent's own.

        Kept apart under two keys rather than merged: a healthy runtime in
        front of an unreachable database is a state an operator has to be able
        to see, and one flattened status would hide exactly that case.
        """
        report = await self.run("health")

        return {
            "agent": self.to_dict(),
            "diagnostics": self.diagnostics(),
            "backend": report,
        }


# =============================================================================
# Task Parsing
# =============================================================================


def _parse_task(
    task: Any,
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """
    Reduce the accepted task shapes to ``(operation, params)``.

    ``None`` values from the keyword form are dropped rather than passed
    through, so ``run("investigate", address=None)`` falls back to the mapping
    or the default instead of overwriting a real value with nothing.
    """
    params: dict[str, Any] = {}

    if isinstance(task, str):
        operation = task.strip().lower()
    elif isinstance(task, Mapping):
        raw = task.get("operation") or task.get("action")
        if not isinstance(raw, str) or not raw.strip():
            raise AgentRuntimeError(
                "task mapping must carry a non-empty 'operation'",
                details={"keys": sorted(str(key) for key in task)},
            )
        operation = raw.strip().lower()
        params = {
            str(key): value
            for key, value in task.items()
            if key not in ("operation", "action")
        }
    else:
        raise AgentRuntimeError(
            "task must be an operation name or a mapping carrying one, "
            f"not {type(task).__name__}",
            details={"task_type": type(task).__name__},
        )

    params.update({k: v for k, v in kwargs.items() if v is not None})

    return operation, params


def _dispatch(
    backend: IntelligenceBackend,
    operation: str,
    params: Mapping[str, Any],
) -> BackendResult:
    """Call the backend method this operation names."""
    chain = str(params.get("chain") or DEFAULT_CHAIN)

    if operation == "investigate":
        address = params.get("address")
        subject = params.get("subject")
        return backend.investigate(
            chain=chain,
            address=str(address) if address else None,
            subject=dict(subject) if isinstance(subject, Mapping) else None,
        )

    if operation == "labels":
        # The backend treats an empty chain as "every chain", so an explicit
        # empty string has to survive rather than being defaulted to Ethereum.
        return backend.labels(str(params.get("chain", "")))

    if operation == "flows":
        return backend.flows(chain)

    if operation == "coverage":
        return backend.coverage(chain)

    return getattr(backend, operation)()


def _as_payload(
    operation: str,
    result: BackendResult,
) -> dict[str, Any]:
    """
    Normalize a backend result into the agent's response shape.

    ``status`` is carried through unchanged. It is HTTP-shaped even here for
    the reason the service gives: a second vocabulary is how a "not found"
    becomes a 500 on one surface and a 404 on another.
    """
    ok = bool(getattr(result, "ok", False))

    return {
        "operation": operation,
        "ok": ok,
        "status": int(getattr(result, "status", 200 if ok else 500)),
        "data": dict(getattr(result, "data", None) or {}),
        "error": str(getattr(result, "error", "") or ""),
    }


# =============================================================================
# Public Exports
# =============================================================================

__all__ = [
    "BACKEND_SERVICE",
    "CAPABILITIES",
    "DEFAULT_CHAIN",
    "OPERATIONS",
    "BackendResult",
    "BlockchainAgent",
    "IntelligenceBackend",
    "blockchain_agent_config",
    "supported_chains",
]
