"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.budget

Purpose:
    Track how much of each provider's daily and monthly call allowance has been
    used, and say what to do when it runs short.

Design goals:
    - Persistent: a budget that resets on restart is not a budget
    - Attempts counted, not successes
    - Day and month tracked separately; either one can be the binding limit
    - Degradation recommended, never applied silently
    - No network I/O

Notes:
    ``blockchain/rpc/rate_limit/bucket.py`` already handles the per-minute
    dimension: token buckets, 429 penalties, per-provider budgets. It is
    correct and stays. What it cannot do is remember anything. Its state is a
    dict in memory, so every restart hands the process a fresh minute — which
    is fine for a minute and useless for a month.

    Free tiers meter per day and per month. Those are the windows that decide
    whether A01 can still read a chain tomorrow, and they have to survive a
    restart, a crash, and a scheduled task that runs every ten minutes as a new
    process. So they live in SQLite next to everything else.

    **Attempts, not successes.** A provider counts the request when it arrives,
    not when it succeeds. Recording only successful calls undercounts precisely
    during retries, timeouts and 429 storms — the periods that burn the most
    allowance and where an accurate figure matters most. So the ledger is
    written before the call goes out, and a failed call still costs.

    **The ceiling is a belief, not a fact.** Documented free-tier limits are
    frequently wrong for a specific key. A 429 observed while the ledger still
    shows headroom is the provider stating its real limit, so
    :meth:`CallBudget.observe_rejection` records it and every later decision
    uses the lower figure. The recorded spend is never rewritten — what was
    used is history, what is allowed is an estimate, and conflating them loses
    the evidence that the estimate was wrong.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable, Final

from database.connection import Database

logger = logging.getLogger(__name__)

#: Fraction of a ceiling that may be spent before A01 starts conserving. Below
#: 1.0 because a budget spent to the last call leaves nothing for the reads an
#: investigation needs, and a chain that goes dark at 23:00 every day is worse
#: than one that stays coarse from 20:00.
DEFAULT_RESERVE: Final[float] = 0.15

#: Pressure above which capture is degraded rather than continued at full rate.
DEGRADE_AT: Final[float] = 1.0 - DEFAULT_RESERVE


class Window(StrEnum):
    """The two windows a free tier meters on."""

    DAY = "day"
    MONTH = "month"

    def key_for(self, moment: datetime) -> str:
        """The window this moment falls in, in UTC."""
        stamp = moment.astimezone(UTC)
        if self is Window.DAY:
            return stamp.strftime("%Y-%m-%d")
        return stamp.strftime("%Y-%m")


class Pressure(StrEnum):
    """How close a provider is to its limit, as an operator-facing word."""

    #: Plenty left; capture at full resolution.
    CLEAR = "clear"
    #: Past the reserve line; conserve.
    TIGHT = "tight"
    #: Nothing left in at least one window.
    EXHAUSTED = "exhausted"
    #: No ceiling is known, so nothing can be said.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Allowance:
    """
    One provider's position in one window.

    ``ceiling`` is nullable on purpose. An unmetered or undocumented provider
    is a real case, and inventing a number for it would produce confident
    throttling with no basis. Its pressure is ``UNKNOWN`` and it is never
    degraded on a guess.
    """

    provider: str
    window: Window
    window_start: str
    spent: int
    ceiling: int | None = None

    @property
    def remaining(self) -> int | None:
        return None if self.ceiling is None else max(self.ceiling - self.spent, 0)

    @property
    def fraction(self) -> float | None:
        if not self.ceiling:
            return None
        return self.spent / self.ceiling

    @property
    def pressure(self) -> Pressure:
        used = self.fraction
        if used is None:
            return Pressure.UNKNOWN
        if used >= 1.0:
            return Pressure.EXHAUSTED
        if used >= DEGRADE_AT:
            return Pressure.TIGHT
        return Pressure.CLEAR

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "window": self.window.value,
            "window_start": self.window_start,
            "spent": self.spent,
            "ceiling": self.ceiling,
            "remaining": self.remaining,
            "fraction": round(self.fraction, 4) if self.fraction is not None else None,
            "pressure": self.pressure.value,
        }


@dataclass(frozen=True, slots=True)
class Verdict:
    """
    Whether a call may go out, and why not.

    ``reason`` is always populated on refusal. A budget that blocks without
    saying which window ran out sends an operator to check the network.
    """

    allowed: bool
    pressure: Pressure
    binding: Window | None = None
    reason: str = ""
    day: Allowance | None = None
    month: Allowance | None = None

    @property
    def should_degrade(self) -> bool:
        """Whether to keep going at reduced resolution rather than at full rate."""
        return self.pressure is Pressure.TIGHT

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "pressure": self.pressure.value,
            "binding": self.binding.value if self.binding else None,
            "reason": self.reason,
            "day": self.day.as_dict() if self.day else None,
            "month": self.month.as_dict() if self.month else None,
        }


class CallBudget:
    """
    The persistent day/month ledger.

    Complements :class:`~blockchain.rpc.rate_limit.bucket.RateLimiter` rather
    than replacing it: that one answers "may I call in this second", this one
    answers "may I call at all today". Both have to say yes.
    """

    def __init__(
        self,
        database: Database,
        *,
        ceilings: dict[str, dict[Window, int]] | None = None,
    ) -> None:
        self._db = database
        self._ceilings = ceilings or {}

    # -- configuration ----------------------------------------------------

    def set_ceiling(self, provider: str, window: Window, ceiling: int) -> None:
        if ceiling <= 0:
            raise ValueError("ceiling must be > 0")
        self._ceilings.setdefault(provider, {})[window] = ceiling

    def ceiling_for(self, provider: str, window: Window) -> int | None:
        """
        The believed ceiling: the lower of what was configured and what a 429
        proved. An observed limit always wins -- it came from the provider.
        """
        configured = self._ceilings.get(provider, {}).get(window)
        observed = self._observed_limit(provider, window)
        if configured is None:
            return observed
        if observed is None:
            return configured
        return min(configured, observed)

    # -- reading ----------------------------------------------------------

    def allowance(
        self, provider: str, window: Window, *, now: datetime | None = None
    ) -> Allowance:
        moment = now or datetime.now(UTC)
        start = window.key_for(moment)
        row = self._db.connection.execute(
            "SELECT spent FROM call_ledger WHERE key = ?",
            (self._key(provider, window, start),),
        ).fetchone()
        return Allowance(
            provider=provider,
            window=window,
            window_start=start,
            spent=int(row["spent"]) if row else 0,
            ceiling=self.ceiling_for(provider, window),
        )

    def check(self, provider: str, *, now: datetime | None = None) -> Verdict:
        """
        Whether ``provider`` may be called, and how tight it is.

        Both windows are evaluated and the worse one binds. A provider with a
        comfortable day and an exhausted month is exhausted.
        """
        moment = now or datetime.now(UTC)
        day = self.allowance(provider, Window.DAY, now=moment)
        month = self.allowance(provider, Window.MONTH, now=moment)

        worst = max(
            (day, month),
            key=lambda a: (a.fraction if a.fraction is not None else -1.0),
        )

        if worst.pressure is Pressure.EXHAUSTED:
            return Verdict(
                allowed=False,
                pressure=Pressure.EXHAUSTED,
                binding=worst.window,
                reason=(
                    f"{provider}: {worst.spent} of {worst.ceiling} calls used for "
                    f"this {worst.window.value} ({worst.window_start})"
                ),
                day=day,
                month=month,
            )

        return Verdict(
            allowed=True,
            pressure=worst.pressure,
            binding=worst.window if worst.pressure is Pressure.TIGHT else None,
            reason=(
                f"{provider}: {worst.spent} of {worst.ceiling} used this "
                f"{worst.window.value}; conserving"
                if worst.pressure is Pressure.TIGHT
                else ""
            ),
            day=day,
            month=month,
        )

    # -- writing ----------------------------------------------------------

    def spend(
        self,
        provider: str,
        calls: int = 1,
        *,
        chain: str = "",
        now: datetime | None = None,
    ) -> None:
        """
        Record ``calls`` attempts against both windows.

        Attempts, not successes: the transport counts a request when it hands
        it to the adapter, so a call that then times out has still been spent.
        Recording only what came back would lose exactly the calls that failed.

        In practice this is called on ``ChainDispatcher.call``'s return path,
        once per provider per logical read, rather than once before each
        request. See :meth:`recorder` for what that timing costs.
        """
        if calls <= 0:
            raise ValueError("calls must be > 0")

        moment = (now or datetime.now(UTC)).astimezone(UTC)
        stamp = moment.isoformat()

        with self._db.connection as connection:
            for window in (Window.DAY, Window.MONTH):
                start = window.key_for(moment)
                connection.execute(
                    """
                    INSERT INTO call_ledger (
                        key, provider, chain, window_kind, window_start,
                        spent, ceiling, first_spend_at, last_spend_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (key) DO UPDATE SET
                        spent = spent + excluded.spent,
                        last_spend_at = excluded.last_spend_at
                    """,
                    (
                        self._key(provider, window, start),
                        provider,
                        chain,
                        window.value,
                        start,
                        calls,
                        self._ceilings.get(provider, {}).get(window),
                        stamp,
                        stamp,
                    ),
                )

    def recorder(self) -> Callable[[str, str, int], None]:
        """
        A sink the transport can report attempts through.

        ``ChainDispatcher`` counts what it actually sent, per provider, and
        hands the count to a callable. This builds that callable. The signature
        is three primitives on purpose: it is what lets the transport report
        spend without importing storage, and a plain ``(chain, provider,
        calls)`` cannot quietly acquire a dependency later.

        What the timing costs: the dispatcher reports on its return path, so a
        process killed mid-read never records the requests that already reached
        the provider. That undercount is bounded by one logical read. Writing
        the ledger before each attempt instead would bound it at zero and put a
        database write on the hot path of every retry -- including the retry
        storms this ledger exists to survive.

        A zero or negative count is dropped rather than raised on. The
        dispatcher never produces one, and a bookkeeping call is not the place
        to discover it if it ever does.
        """

        def record(chain: str, provider: str, calls: int) -> None:
            if calls <= 0:
                return
            self.spend(provider, calls, chain=chain)

        return record

    def observe_rejection(
        self, provider: str, window: Window = Window.DAY, *, now: datetime | None = None
    ) -> int:
        """
        Record that the provider refused while the ledger still showed room.

        The documented ceiling was wrong for this key. The spend so far becomes
        the new believed limit, because that is the figure the provider just
        demonstrated. Returns the limit now believed.

        The spend itself is never rewritten. What was used is history; what is
        allowed is an estimate. Overwriting the first would destroy the evidence
        that the second was wrong.
        """
        moment = now or datetime.now(UTC)
        current = self.allowance(provider, window, now=moment)
        limit = max(current.spent, 1)

        with self._db.connection as connection:
            connection.execute(
                "UPDATE call_ledger SET observed_limit = ? WHERE key = ?",
                (limit, self._key(provider, window, current.window_start)),
            )

        logger.warning(
            "%s refused at %d calls this %s; documented ceiling was %s",
            provider,
            current.spent,
            window.value,
            current.ceiling,
        )
        return limit

    # -- reporting --------------------------------------------------------

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Every provider with a ledger entry in the current windows."""
        moment = now or datetime.now(UTC)
        providers = {
            row["provider"]
            for row in self._db.connection.execute(
                "SELECT DISTINCT provider FROM call_ledger WHERE window_start IN (?, ?)",
                (Window.DAY.key_for(moment), Window.MONTH.key_for(moment)),
            )
        }
        return {
            provider: self.check(provider, now=moment).as_dict()
            for provider in sorted(providers)
        }

    # -- internals --------------------------------------------------------

    @staticmethod
    def _key(provider: str, window: Window, window_start: str) -> str:
        return f"{provider}:{window.value}:{window_start}"

    def _observed_limit(self, provider: str, window: Window) -> int | None:
        row = self._db.connection.execute(
            """
            SELECT observed_limit FROM call_ledger
             WHERE provider = ? AND window_kind = ? AND observed_limit IS NOT NULL
             ORDER BY window_start DESC LIMIT 1
            """,
            (provider, window.value),
        ).fetchone()
        return int(row["observed_limit"]) if row and row["observed_limit"] else None


__all__ = [
    "DEFAULT_RESERVE",
    "DEGRADE_AT",
    "Allowance",
    "CallBudget",
    "Pressure",
    "Verdict",
    "Window",
]
