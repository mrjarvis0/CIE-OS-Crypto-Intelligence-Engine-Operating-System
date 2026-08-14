"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the persistent day/month call ledger.

The per-minute limiter is tested elsewhere and is not the subject here. What
these pin down is the part it cannot do: surviving a restart, tracking two
windows at once, and refusing to invent a limit it was never given.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from database import Database
from pipeline.budget import CallBudget, Pressure, Window

JAN = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


@pytest.fixture
def db():
    with Database() as database:
        yield database


def budget(db, *, day: int | None = 100, month: int | None = 2000) -> CallBudget:
    b = CallBudget(db)
    if day:
        b.set_ceiling("p", Window.DAY, day)
    if month:
        b.set_ceiling("p", Window.MONTH, month)
    return b


# =============================================================================
# WINDOWS
# =============================================================================

def test_day_and_month_are_tracked_separately(db):
    b = budget(db)
    b.spend("p", 40, now=JAN)

    assert b.allowance("p", Window.DAY, now=JAN).spent == 40
    assert b.allowance("p", Window.MONTH, now=JAN).spent == 40


def test_a_new_day_starts_clean_but_the_month_carries(db):
    """
    The distinction that makes both windows worth keeping. A provider can be
    fine today and out of allowance for the month, and only tracking the day
    would let A01 walk into a wall it could see coming.
    """
    b = budget(db)
    b.spend("p", 90, now=JAN)
    tomorrow = JAN + timedelta(days=1)

    assert b.allowance("p", Window.DAY, now=tomorrow).spent == 0
    assert b.allowance("p", Window.MONTH, now=tomorrow).spent == 90


def test_the_worse_window_binds(db):
    b = budget(db, day=10_000, month=100)
    b.spend("p", 100, now=JAN)
    verdict = b.check("p", now=JAN)

    assert not verdict.allowed
    assert verdict.binding is Window.MONTH, "a comfortable day cannot rescue a spent month"


def test_windows_are_utc_not_local(db):
    """
    A ledger on local time double-counts or skips an hour twice a year, and the
    provider is not resetting on the operator's timezone.
    """
    late = datetime(2026, 1, 15, 23, 30, tzinfo=UTC)
    assert Window.DAY.key_for(late) == "2026-01-15"
    assert Window.MONTH.key_for(late) == "2026-01"


# =============================================================================
# PRESSURE
# =============================================================================

def test_pressure_rises_before_the_wall(db):
    """
    Conserving at 85% rather than stopping at 100%. A chain that goes dark at
    23:00 every day is worse than one that stays coarse from 20:00.
    """
    b = budget(db)
    b.spend("p", 86, now=JAN)
    verdict = b.check("p", now=JAN)

    assert verdict.allowed
    assert verdict.pressure is Pressure.TIGHT
    assert verdict.should_degrade
    assert verdict.reason, "a degrade decision must say why"


def test_exhaustion_refuses_and_names_the_window(db):
    b = budget(db)
    b.spend("p", 100, now=JAN)
    verdict = b.check("p", now=JAN)

    assert not verdict.allowed
    assert verdict.binding is Window.DAY
    assert "100" in verdict.reason


def test_a_provider_with_no_ceiling_is_never_throttled(db):
    """
    Unmetered and undocumented providers are real. Inventing a number for one
    produces confident throttling with no basis behind it.
    """
    b = CallBudget(db)
    b.spend("open-node", 50_000, now=JAN)
    verdict = b.check("open-node", now=JAN)

    assert verdict.allowed
    assert verdict.pressure is Pressure.UNKNOWN
    assert not verdict.should_degrade


# =============================================================================
# PERSISTENCE
# =============================================================================

def test_spend_survives_a_new_budget_object(db):
    """
    The whole reason this is not the in-memory bucket. The scheduled task runs
    every ten minutes as a fresh process; a budget that forgets is not one.
    """
    budget(db).spend("p", 70, now=JAN)

    assert budget(db).allowance("p", Window.DAY, now=JAN).spent == 70


def test_spending_is_additive_not_overwriting(db):
    b = budget(db)
    for _ in range(5):
        b.spend("p", 3, now=JAN)

    assert b.allowance("p", Window.DAY, now=JAN).spent == 15


# =============================================================================
# OBSERVED LIMITS
# =============================================================================

def test_a_rejection_lowers_the_believed_ceiling(db):
    """
    A 429 while the ledger still shows headroom is the provider stating its
    real limit. The documented figure was wrong for this key.
    """
    b = budget(db, day=5000)
    b.spend("p", 300, now=JAN)
    assert b.check("p", now=JAN).pressure is Pressure.CLEAR

    b.observe_rejection("p", Window.DAY, now=JAN)

    assert b.ceiling_for("p", Window.DAY) == 300
    assert b.check("p", now=JAN).pressure is Pressure.EXHAUSTED


def test_a_rejection_does_not_rewrite_what_was_spent(db):
    """
    What was used is history; what is allowed is an estimate. Overwriting the
    first destroys the evidence that the second was wrong.
    """
    b = budget(db, day=5000)
    b.spend("p", 300, now=JAN)
    b.observe_rejection("p", Window.DAY, now=JAN)

    assert b.allowance("p", Window.DAY, now=JAN).spent == 300


def test_the_observed_limit_wins_over_a_larger_configured_one(db):
    b = budget(db, day=5000)
    b.spend("p", 120, now=JAN)
    b.observe_rejection("p", Window.DAY, now=JAN)

    b.set_ceiling("p", Window.DAY, 9000)

    assert b.ceiling_for("p", Window.DAY) == 120, "the provider's own answer wins"


# =============================================================================
# THE TRANSPORT SEAM
# =============================================================================

def test_the_recorder_writes_attempts_through_to_the_ledger(db):
    b = budget(db)
    b.recorder()("ethereum", "p", 3)

    assert b.allowance("p", Window.DAY).spent == 3
    assert b.allowance("p", Window.MONTH).spent == 3


def test_the_recorder_keeps_the_chain_that_spent_it(db):
    b = budget(db)
    b.recorder()("base", "p", 1)

    chains = {
        row["chain"]
        for row in db.connection.execute("SELECT chain FROM call_ledger")
    }
    assert chains == {"base"}


def test_the_recorder_drops_a_count_of_nothing(db):
    """
    The dispatcher never produces one, and a bookkeeping call is not where a
    caller should discover it if it ever does.
    """
    b = budget(db)
    b.recorder()("ethereum", "p", 0)

    assert b.allowance("p", Window.DAY).spent == 0


def test_a_real_dispatch_lands_in_the_ledger(db):
    """
    The wiring end to end, with the real dispatcher and the real catalog. Only
    the adapter is scripted, so what is asserted is that a chain read charges
    the provider that answered it -- the thing the ledger was built for and
    then left without a writer.
    """
    from blockchain.rpc import ChainDispatcher, RateLimiter, ResponseCache
    from blockchain.tests.test_transport import FakeClock, FakeResponse, ScriptedAdapter
    from config.rpc.chains import ChainName

    b = CallBudget(db)
    clock = FakeClock()
    dispatcher = ChainDispatcher(
        environ={},
        limiter=RateLimiter(clock=clock),
        cache=ResponseCache(clock=clock),
        on_spend=b.recorder(),
    )
    dispatcher._adapter_for = lambda endpoint, url: ScriptedAdapter(
        [FakeResponse(True, data="0x1")]
    )

    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.ok
    assert b.allowance(result.provider, Window.DAY).spent == 1


# =============================================================================
# GUARDS
# =============================================================================

def test_a_non_positive_spend_is_refused(db):
    with pytest.raises(ValueError):
        budget(db).spend("p", 0, now=JAN)


def test_a_non_positive_ceiling_is_refused(db):
    with pytest.raises(ValueError):
        budget(db).set_ceiling("p", Window.DAY, 0)


def test_snapshot_reports_every_active_provider(db):
    b = budget(db)
    b.spend("p", 5, now=JAN)
    b.spend("q", 5, now=JAN)

    snapshot = b.snapshot(now=JAN)

    assert set(snapshot) == {"p", "q"}
    assert snapshot["p"]["day"]["spent"] == 5
