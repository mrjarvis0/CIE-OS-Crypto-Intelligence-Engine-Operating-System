"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the concrete agent that fills ``BaseAgent.execute()``.

Driven against a fake backend rather than a real service. The question here is
whether the agent routes, parses, and reports correctly -- not whether the
intelligence stack produces good answers, which is tested where that stack
lives. A real service would make every case below depend on a database and
would hide the agent's own behaviour behind the engine's.
"""

from __future__ import annotations

import threading

from dataclasses import dataclass, field
from typing import Any

import pytest

from core.blockchain_agent import (
    DEFAULT_CHAIN,
    OPERATIONS,
    BlockchainAgent,
    blockchain_agent_config,
)
from core.exceptions import AgentRuntimeError

ADDRESS = "0x" + "a1" * 20


# ==============================================================================
# FAKE BACKEND
# ==============================================================================


@dataclass
class FakeResult:
    """Same shape as `interfaces.service.ServiceResult`, structurally."""

    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    status: int = 200


@dataclass
class Call:
    method: str
    kwargs: dict[str, Any]
    thread: int


class FakeBackend:
    """
    Records what it was asked and returns whatever it was told to.

    Every operation lands on ``_record`` so a test can assert the arguments the
    agent built without stubbing nine methods.
    """

    def __init__(self, result: FakeResult | None = None) -> None:
        self.result = result or FakeResult(data={"stub": True})
        self.calls: list[Call] = []

    def _record(self, method: str, **kwargs: Any) -> FakeResult:
        self.calls.append(
            Call(method=method, kwargs=kwargs, thread=threading.get_ident())
        )
        return self.result

    @property
    def last(self) -> Call:
        return self.calls[-1]

    def investigate(
        self,
        *,
        chain: str = DEFAULT_CHAIN,
        address: str | None = None,
        subject: dict[str, Any] | None = None,
    ) -> FakeResult:
        return self._record(
            "investigate", chain=chain, address=address, subject=subject
        )

    def detectors(self) -> FakeResult:
        return self._record("detectors")

    def skills(self) -> FakeResult:
        return self._record("skills")

    def chains(self) -> FakeResult:
        return self._record("chains")

    def labels(self, chain: str = "") -> FakeResult:
        return self._record("labels", chain=chain)

    def flows(self, chain: str = DEFAULT_CHAIN) -> FakeResult:
        return self._record("flows", chain=chain)

    def coverage(self, chain: str = DEFAULT_CHAIN) -> FakeResult:
        return self._record("coverage", chain=chain)

    def metrics(self) -> FakeResult:
        return self._record("metrics")

    def health(self) -> FakeResult:
        return self._record("health")


def agent_with(backend: FakeBackend | None = None) -> BlockchainAgent:
    return BlockchainAgent(backend=backend or FakeBackend())


# ==============================================================================
# EXECUTION
# ==============================================================================


async def test_execute_returns_the_backends_payload():
    backend = FakeBackend(FakeResult(data={"implemented": 19}))
    agent = agent_with(backend)

    result = await agent.run("skills")

    assert result["ok"]
    assert result["operation"] == "skills"
    assert result["status"] == 200
    assert result["data"] == {"implemented": 19}
    assert backend.last.method == "skills"


async def test_every_declared_operation_reaches_the_backend():
    """
    ``OPERATIONS`` is what :meth:`describe` advertises, so an entry with no
    working route would be a documented surface that raises when used.
    """
    backend = FakeBackend()
    agent = agent_with(backend)

    for operation in OPERATIONS:
        result = await agent.run(operation)
        assert result["operation"] == operation
        assert backend.last.method == operation


async def test_a_mapping_task_carries_its_own_parameters():
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.run({"operation": "investigate", "address": ADDRESS})

    assert backend.last.kwargs["address"] == ADDRESS


async def test_keyword_arguments_win_over_mapping_keys():
    """
    Both call styles are accepted, so one has to lose. The keywords win because
    they are written at the call site, while the mapping is usually something
    the caller was handed.
    """
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.run(
        {"operation": "flows", "chain": "polygon"}, chain="arbitrum"
    )

    assert backend.last.kwargs["chain"] == "arbitrum"


async def test_a_none_keyword_does_not_shadow_a_mapping_value():
    """
    The failure this prevents: a caller forwarding ``address=None`` from an
    optional argument, silently erasing the address the mapping carried and
    turning a wallet investigation into a chain-wide one.
    """
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.run(
        {"operation": "investigate", "address": ADDRESS}, address=None
    )

    assert backend.last.kwargs["address"] == ADDRESS


async def test_operations_default_to_ethereum():
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.run("coverage")

    assert backend.last.kwargs["chain"] == DEFAULT_CHAIN


async def test_labels_keeps_an_explicit_empty_chain():
    """
    The backend reads an empty chain as "every chain". Defaulting it to
    Ethereum here would answer a narrower question than the caller asked and
    look like a complete label list while doing it.
    """
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.run("labels", chain="")

    assert backend.last.kwargs["chain"] == ""


async def test_the_backend_runs_off_the_event_loop():
    """
    Every operation may open the database and run the analysis engine. Inline,
    that stalls the loop -- and with it the heartbeat, the workers, and every
    other task on this agent -- for the length of the query.
    """
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.run("metrics")

    assert backend.last.thread != threading.get_ident()


# ==============================================================================
# FAILURE SPLIT
# ==============================================================================


async def test_a_declined_result_is_an_answer_not_a_failure():
    """
    An empty database or a rejected address is a fact about the request, and
    the other surfaces report it as one. Raising here would make the agent
    disagree with the CLI about whether the same call went wrong.
    """
    backend = FakeBackend(
        FakeResult(ok=False, error="no database configured", status=503)
    )
    agent = agent_with(backend)

    result = await agent.run("coverage")

    assert not result["ok"]
    assert result["status"] == 503
    assert result["error"] == "no database configured"
    assert agent.statistics.successful_executions == 1
    assert agent.statistics.failed_executions == 0


async def test_an_unknown_operation_raises_and_names_what_exists():
    agent = agent_with()

    with pytest.raises(AgentRuntimeError) as caught:
        await agent.run("ingest")

    assert "ingest" in str(caught.value)
    assert "investigate" in str(caught.value)


async def test_ingestion_is_not_reachable_through_the_agent():
    """
    A01's ingestion is operator-driven and rate-limited. Behind an agent task
    it would be an unbounded job inside what reads as a lookup -- the same
    reason it is absent from the REST surface.
    """
    assert not {"ingest", "backup", "restore", "write"} & set(OPERATIONS)


async def test_a_task_of_the_wrong_shape_raises():
    agent = agent_with()

    with pytest.raises(AgentRuntimeError):
        await agent.run(42)


async def test_a_mapping_without_an_operation_raises():
    agent = agent_with()

    with pytest.raises(AgentRuntimeError):
        await agent.run({"address": ADDRESS})


async def test_a_missing_backend_raises_rather_than_answering():
    agent = BlockchainAgent()

    with pytest.raises(AgentRuntimeError) as caught:
        await agent.run("skills")

    assert "backend" in str(caught.value)


async def test_a_caller_error_counts_as_a_failed_execution():
    """
    The other half of the split above: the statistics have to tell the two
    apart, or a healthy agent declining bad input looks like a broken one.
    """
    agent = agent_with()

    with pytest.raises(AgentRuntimeError):
        await agent.run("nonsense")

    assert agent.statistics.failed_executions == 1
    assert agent.statistics.successful_executions == 0


# ==============================================================================
# WIRING
# ==============================================================================


async def test_a_swapped_backend_takes_effect():
    """
    The backend is resolved per call, not cached at construction, so pointing
    an agent at a different database does not need a new agent.
    """
    first, second = FakeBackend(), FakeBackend()
    agent = agent_with(first)

    await agent.run("metrics")

    agent.unregister_service("intelligence")
    agent.register_service("intelligence", second)
    await agent.run("metrics")

    assert len(first.calls) == 1
    assert len(second.calls) == 1


def test_the_agent_registers_every_configured_chain():
    agent = agent_with()

    assert agent.get_chain("ethereum") is not None
    assert agent.get_chain("bitcoin") is not None
    assert len(agent.config.supported_chains) == 15


def test_a_chain_without_a_numeric_id_keeps_the_truth_in_metadata():
    """
    ``SupportedChain.chain_id`` is an EVM concept; Bitcoin and Solana have
    none. Zero stands for "not applicable" and the real answer stays readable
    rather than being invented as a number somebody could look up.
    """
    agent = agent_with()

    bitcoin = agent.get_chain("bitcoin")

    assert bitcoin.chain_id == 0
    assert bitcoin.metadata["chain_id"] is None
    assert agent.get_chain("ethereum").metadata["chain_id"] == 1


def test_declared_capabilities_stay_narrower_than_the_enum():
    """
    Every skill behind this agent is LIMITED. Claiming MEV detection, planning
    or multi-agent coordination -- none of which anything here performs --
    would make the capability set a wish list.
    """
    declared = {c.value for c in blockchain_agent_config().capabilities}

    assert "onchain_intelligence" in declared
    assert "mev_detection" not in declared
    assert "planning" not in declared
    assert "multi_agent" not in declared


def test_describe_advertises_the_real_surface():
    agent = agent_with()

    described = agent.describe()

    assert described["operations"] == list(OPERATIONS)
    assert described["read_only"] is True
    assert described["backend_registered"] is True
    assert BlockchainAgent().describe()["backend_registered"] is False


# ==============================================================================
# CONVENIENCE WRAPPERS
# ==============================================================================


async def test_investigate_forwards_the_address_and_chain():
    backend = FakeBackend()
    agent = agent_with(backend)

    await agent.investigate(ADDRESS, chain="polygon")

    assert backend.last.method == "investigate"
    assert backend.last.kwargs["address"] == ADDRESS
    assert backend.last.kwargs["chain"] == "polygon"


async def test_health_report_keeps_agent_and_backend_apart():
    """
    A healthy runtime in front of an unreachable database is the state an
    operator most needs to see, and one flattened status is exactly what would
    hide it.
    """
    backend = FakeBackend(FakeResult(ok=False, error="storage gone", status=503))
    agent = agent_with(backend)

    report = await agent.health_report()

    assert report["agent"]["status"] == "running"
    assert report["backend"]["ok"] is False
    assert report["backend"]["error"] == "storage gone"


async def test_every_operation_is_audited():
    agent = agent_with()

    await agent.run("skills")

    audited = [
        entry
        for entry in agent._audit_log
        if entry["event"] == "operation_executed"
    ]

    assert audited
    assert audited[-1]["data"]["operation"] == "skills"
    assert audited[-1]["data"]["ok"] is True
