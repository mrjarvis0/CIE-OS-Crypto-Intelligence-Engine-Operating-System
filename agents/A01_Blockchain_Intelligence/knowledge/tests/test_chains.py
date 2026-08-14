"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for chain knowledge.

Two properties matter. The first is that this package **imports** the registry
rather than restating it — two answers to "what is Ethereum's chain id" is one
too many, and nothing would report the divergence. The second is that the
negative facts are present and specific: a capability table that only lists what
works is a sales sheet.
"""

from __future__ import annotations

import pytest

from config.rpc.chains import get_chain, supported_chain_names
from knowledge import (
    CAPABILITIES,
    MEASURED_ON,
    Finality,
    capability,
    observable_chains,
    registry_only_chains,
    summary,
    token_capable_chains,
)


# ==============================================================================
# THE REGISTRY IS IMPORTED, NOT RESTATED
# ==============================================================================

def test_chain_ids_come_from_the_registry():
    """
    Not copied. A second copy would drift from `config/rpc/chains.py` and
    nothing would notice.
    """
    arbitrum = capability("arbitrum")

    assert arbitrum.config.chain_id == get_chain("arbitrum").chain_id
    assert arbitrum.config.chain_id == 42161


def test_every_registered_chain_has_a_capability_record():
    """
    A chain in the registry with no capability record is a chain an operator
    would assume is fully supported.
    """
    registered = {str(c) for c in supported_chain_names()}
    known = {c.chain for c in CAPABILITIES}

    assert registered <= known, f"missing capability records: {registered - known}"


def test_no_capability_record_invents_a_chain():
    registered = {str(c) for c in supported_chain_names()}

    for entry in CAPABILITIES:
        assert entry.chain in registered, f"{entry.chain} is not in the registry"


def test_native_currency_is_not_duplicated():
    for entry in CAPABILITIES:
        registry = get_chain(entry.chain)
        assert entry.config.native_currency is registry.native_currency


# ==============================================================================
# THE NEGATIVE FACTS
# ==============================================================================

def test_solana_and_bitcoin_are_reachable_but_unobservable():
    """
    The distinction that matters: endpoints exist, a sensor does not. That is a
    different problem from an unsupported chain, and it has a different fix.
    """
    assert set(registry_only_chains()) == {"solana", "bitcoin"}

    for name in ("solana", "bitcoin"):
        entry = capability(name)
        assert not entry.observable
        assert any("no sensor" in limit for limit in entry.limits)


def test_every_chain_says_where_its_archive_position_comes_from():
    """
    This test used to assert that *no* chain claims archive access, which was
    true while A01 ran on open endpoints alone and stopped being true the moment
    a keyed provider was configured. Pinning the measurement made the test a
    snapshot; the rule underneath it is what is worth asserting.

    The rule: a claim of archive access must say it rests on a credential, and
    an absence of it must say so too. Either way a caller learns whether
    historical state will arrive, and what would change that.
    """
    for entry in CAPABILITIES:
        if not entry.observable:
            continue
        if entry.archive_available:
            assert any(
                "keyed provider" in limit for limit in entry.limits
            ), f"{entry.chain} claims archive without saying the key grants it"
        else:
            assert any(
                "archive" in limit for limit in entry.limits
            ), f"{entry.chain} lacks archive and does not say so"


def test_a_chain_without_a_keyed_route_says_what_that_costs():
    """
    The six chains added on 2026-08-14 have open endpoints and no keyed one, so
    there is no upgrade path to archive at all. That is a different position
    from "not keyed yet" and it disables a named detector.
    """
    for name in ("linea", "scroll", "gnosis", "celo", "mantle", "unichain"):
        entry = capability(name)
        assert not entry.archive_available
        assert any("DET-DORMANT-01" in limit for limit in entry.limits), name


def test_layer_twos_warn_that_native_transfers_are_empty():
    """
    Measured on live blocks: the largest native transfer on Arbitrum and
    Optimism was 0.0000. Without this warning a reader takes an idle-looking
    chain at face value.
    """
    for name in ("arbitrum", "optimism", "base"):
        entry = capability(name)
        assert entry.finality is Finality.ROLLUP
        assert any("routinely 0" in limit for limit in entry.limits), name


def test_every_chain_states_at_least_one_limit():
    """A capability record with no limits is a claim of completeness."""
    for entry in CAPABILITIES:
        assert entry.limits, f"{entry.chain} states no limits"


def test_token_capable_chains_are_the_observable_evm_ones():
    assert set(token_capable_chains()) == set(observable_chains())
    # Every registered chain except the two with no EVM sensor.
    assert len(token_capable_chains()) == len(supported_chain_names()) - 2
    assert len(token_capable_chains()) == 13


# ==============================================================================
# LOOKUP
# ==============================================================================

def test_an_unknown_chain_raises_rather_than_defaulting():
    """
    A permissive default would have a caller analyse nothing and report it as
    an absence.
    """
    with pytest.raises(KeyError) as excinfo:
        capability("notachain")

    assert "ethereum" in str(excinfo.value)


def test_summary_is_serialisable_and_dated():
    s = summary()

    assert s["measured_on"] == MEASURED_ON.isoformat()
    assert s["total"] == len(CAPABILITIES)
    assert s["observable"] == 13
    assert len(s["chains"]) == len(CAPABILITIES)


def test_reorg_depth_reflects_the_chain_not_a_constant():
    """
    Polygon needs a far deeper wait than Avalanche. A single constant would be
    wrong in both directions.
    """
    assert capability("polygon").reorg_depth > capability("ethereum").reorg_depth
    assert capability("avalanche").reorg_depth < capability("ethereum").reorg_depth


def test_finality_models_are_distinguished():
    assert capability("ethereum").finality is Finality.CHECKPOINT
    assert capability("bitcoin").finality is Finality.PROBABILISTIC
    assert capability("avalanche").finality is Finality.INSTANT
    assert capability("arbitrum").finality is Finality.ROLLUP


# ==============================================================================
# THE TABLE CAN BE RE-CHECKED
# ==============================================================================

def test_probe_returns_a_result_for_an_unsupported_chain_rather_than_raising():
    """
    Probing a chain with no sensor is a measurement, not a fault — and the
    result is what proves the table's "no sensor" claim.
    """
    from knowledge import probe

    result = probe("bitcoin")

    assert result.chain == "bitcoin"
    assert not result.has_sensor
    assert not result.disagrees_with_table()


def test_a_probe_of_an_unknown_chain_reports_the_gap():
    from knowledge import ProbeResult

    stray = ProbeResult(
        chain="notachain",
        reachable=True,
        has_sensor=True,
        supports_logs=True,
        archive_available=False,
    )

    assert "not in the capability table" in stray.disagrees_with_table()[0]


def test_a_probe_that_matches_the_table_reports_no_drift():
    from knowledge import ProbeResult

    known = capability("ethereum")
    matching = ProbeResult(
        chain="ethereum",
        reachable=True,
        has_sensor=known.has_sensor,
        supports_logs=known.supports_logs,
        archive_available=known.archive_available,
        head=1,
    )

    assert matching.disagrees_with_table() == ()


def test_a_probe_that_contradicts_the_table_says_which_field():
    """
    Drift means the record is stale, and a stale dated fact is only honest if
    something can catch it.
    """
    from knowledge import ProbeResult

    contradicting = ProbeResult(
        chain="linea",
        reachable=True,
        has_sensor=True,
        supports_logs=True,
        archive_available=True,  # the table says False: no keyed route exists
        head=1,
    )
    drift = contradicting.disagrees_with_table()

    assert len(drift) == 1
    assert "archive_available" in drift[0]
