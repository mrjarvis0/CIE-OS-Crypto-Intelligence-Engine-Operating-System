"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the agent surface's wiring.

The agent's own routing is tested in `core/tests/test_blockchain_agent.py`
against a fake backend. What is left to prove is the part that only exists
here: that the factory hands it the real service, and that the answers it
returns are the same ones the CLI and the REST router would give -- which is
the entire reason all three go through one object.
"""

from __future__ import annotations

from interfaces import build_blockchain_agent
from interfaces.rest import Router
from interfaces.service import IntelligenceService

ADDRESS = "0x" + "a1" * 20


# ==============================================================================
# WIRING
# ==============================================================================


def test_the_factory_attaches_a_real_service():
    agent = build_blockchain_agent()

    assert isinstance(agent.backend, IntelligenceService)
    assert agent.describe()["backend_registered"] is True


def test_a_supplied_service_is_used_rather_than_rebuilt():
    """
    The seam that lets an agent and another surface share one service -- and
    therefore one alert budget. A rebuilt service would give the agent a fresh
    budget, so an alert already spent elsewhere would fire again here.
    """
    service = IntelligenceService(subscriptions=[])

    agent = build_blockchain_agent(service=service)

    assert agent.backend is service


def test_the_factory_accepts_subscriptions_for_the_decision_engine():
    agent = build_blockchain_agent(subscriptions=())

    assert agent.backend.decisions is not None


def test_no_database_is_not_a_construction_failure():
    """
    A service with no database still answers the catalogue and declines the
    rest with a reason, which is more useful than refusing to build.
    """
    agent = build_blockchain_agent()

    assert agent.backend.has_storage is False


# ==============================================================================
# ONE ANSWER PER QUESTION
# ==============================================================================


async def test_the_agent_and_the_rest_router_answer_alike():
    """
    The claim `interfaces/__init__.py` makes about surfaces not drifting,
    asserted rather than described. Two surfaces reading one service is what
    stops the CLI growing a flag REST lacks, or one applying the maturity gate
    a step earlier than the other.
    """
    service = IntelligenceService()
    agent = build_blockchain_agent(service=service)
    router = Router(service)

    through_agent = await agent.run("detectors")
    through_rest = router.dispatch("/detectors", {})

    assert through_agent["ok"] == through_rest.ok
    assert through_agent["data"] == through_rest.data


async def test_the_catalogue_operations_answer_without_storage():
    agent = build_blockchain_agent()

    async with agent:
        skills = await agent.run("skills")
        detectors = await agent.run("detectors")
        chains = await agent.run("chains")

    assert skills["ok"] and skills["data"]["implemented"]
    assert detectors["ok"] and detectors["data"]["detectors"]
    assert chains["ok"] and chains["data"]["total"] == 15


async def test_an_operation_needing_storage_declines_with_a_reason():
    """
    503 rather than an exception: the database being absent is a fact about
    the deployment, and the status is the one every other surface reports for
    it.
    """
    agent = build_blockchain_agent()

    result = await agent.run("coverage", chain="ethereum")

    assert not result["ok"]
    assert result["status"] == 503
    assert result["error"]


async def test_an_investigation_runs_end_to_end_from_a_supplied_subject():
    """
    Without storage the subject has to come from the caller. The point of the
    case is that the whole path still runs -- engine, decision, narrative --
    rather than the agent short-circuiting when composition has nothing to add.
    """
    agent = build_blockchain_agent()

    result = await agent.investigate(ADDRESS)

    assert result["ok"]
    assert {"package", "decision", "narrative"} <= set(result["data"])


async def test_the_agent_shuts_down_cleanly_after_running():
    agent = build_blockchain_agent()

    async with agent:
        await agent.run("metrics")

    assert agent.status.value == "shutdown"
    assert agent.statistics.successful_executions == 1
