"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.security.approval_risk.exposure

Purpose:
    Turn a stream of decoded approval events into the set of grants that are
    still live, and measure how much of the owner's position they expose.

Design goals:
    - Replay in chain order, because an approval *replaces* rather than adds
    - A revocation is final until a later event overrides it
    - Report exposure as grants and their breadth, never as a currency figure
    - Pure: no I/O, no balance reads, no labels

Boundary:
    Nothing here decides whether a spender is dangerous. That question needs
    a label source or contract bytecode, and A01 has neither -- see
    :class:`ExposureReport` for exactly what is therefore unanswerable.

Notes:
    **Why replay order is the whole problem.** ``approve(spender, value)``
    sets an allowance; it does not increase one. So the live allowance is
    whatever the *latest* event for that grant said, and "latest" means
    ``(block_number, log_index)`` -- not the order the logs happened to arrive
    in. Providers return logs in block order but batch across ranges, and a
    backfill merged with a live tail can interleave. Replaying two events out
    of order resurrects a revoked approval, and a screen that reports a
    revoked approval as live tells the owner to go and revoke something they
    already revoked. Worse, the reverse ordering hides a live one.

    So :func:`replay` sorts before it folds, every time, and does not trust
    the caller to have done it.

    **What "unlimited" means.** Wallets ask for ``type(uint256).max`` by
    convention, but not universally: some routers request ``2**255``, some
    request a very large round number. Testing for equality with
    ``MAX_UINT256`` therefore misses real unlimited approvals, and the miss is
    silent. The test here is ``allowance >= 2**255``, which no honest
    allowance reaches: it is more than half of every uint256, and no token
    has a supply anywhere near it. Anything above that line is a grant the
    user cannot have meant literally.

    **What this cannot tell you, and why the ceiling is where it is.**

    * *Whether a spender is malicious.* No label source, no bytecode. A
      grant to a well-known router and a grant to a drainer are the same
      record here.
    * *How much value is actually at risk.* An allowance is a ceiling, not a
      holding. Exposure is bounded by ``min(allowance, balance)`` and this
      module reads no balance, so it reports breadth, not a figure.
    * *Whether the token still exists.* A grant on a dead contract is
      harmless and looks identical to a live one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Iterable, Sequence

from .approvals import ApprovalKind, DecodedApproval

__all__ = [
    "DEFAULT_STALE_DAYS",
    "UNLIMITED_THRESHOLD",
    "ExposureReport",
    "LiveApproval",
    "exposure_for_owner",
    "replay",
]

#: At or above this, an allowance is not a considered number. Half of
#: uint256; no token supply approaches it.
UNLIMITED_THRESHOLD: Final[int] = 2**255

#: An approval untouched for this long is reported as stale. Not a risk
#: multiplier -- an old approval to a contract still in daily use is fine --
#: but the ones an owner has forgotten are the ones they never revoke.
DEFAULT_STALE_DAYS: Final[float] = 180.0

#: Seconds per day, so a block timestamp can be aged without importing a
#: calendar into a pure module.
_DAY: Final[float] = 86_400.0


@dataclass(frozen=True, slots=True)
class LiveApproval:
    """
    One grant that is still standing, and the event that last set it.

    ``granted_at`` is the timestamp of that event when the caller supplied
    one, and ``None`` otherwise. It is never defaulted to "now": an approval
    of unknown age would then look freshly granted, which is the opposite of
    what staleness is trying to surface.
    """

    kind: ApprovalKind
    chain: str
    token: str
    owner: str
    spender: str
    allowance: int | None = None
    token_id: int | None = None
    block_number: int | None = None
    granted_at: float | None = None

    @property
    def unlimited(self) -> bool:
        """
        True when the grant has no practical ceiling.

        ``ERC721_ALL`` is unconditionally unlimited: ``setApprovalForAll``
        covers every token in the collection the owner holds now *and every
        one they acquire later*, which is a broader grant than any numeric
        allowance can express.
        """
        if self.kind is ApprovalKind.ERC721_ALL:
            return True
        return self.allowance is not None and self.allowance >= UNLIMITED_THRESHOLD

    def age_days(self, as_of: float | None) -> float | None:
        if self.granted_at is None or as_of is None:
            return None
        return max(0.0, (as_of - self.granted_at) / _DAY)

    def stale(self, as_of: float | None, *, stale_days: float = DEFAULT_STALE_DAYS) -> bool:
        age = self.age_days(as_of)
        return age is not None and age >= stale_days

    def as_dict(self, as_of: float | None = None) -> dict[str, Any]:
        age = self.age_days(as_of)
        return {
            "kind": str(self.kind),
            "chain": self.chain,
            "token": self.token,
            "owner": self.owner,
            "spender": self.spender,
            # A 256-bit allowance is not a JSON number.
            "allowance": str(self.allowance) if self.allowance is not None else None,
            "token_id": self.token_id,
            "unlimited": self.unlimited,
            "block_number": self.block_number,
            "age_days": round(age, 2) if age is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ExposureReport:
    """
    What an owner has left standing, and what cannot be said about it.

    ``unanswerable`` is part of the report rather than a docstring, because
    the reader of a screen needs the limits next to the numbers. A report
    listing three unlimited approvals and not saying "whether any of these
    spenders is dangerous is not determined here" reads as an alarm.
    """

    owner: str
    chain: str
    live: tuple[LiveApproval, ...] = ()
    revoked: int = 0
    events_replayed: int = 0
    undecodable: int = 0
    as_of: float | None = None
    stale_days: float = DEFAULT_STALE_DAYS
    unanswerable: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.live)

    @property
    def unlimited(self) -> tuple[LiveApproval, ...]:
        return tuple(grant for grant in self.live if grant.unlimited)

    @property
    def collection_wide(self) -> tuple[LiveApproval, ...]:
        return tuple(
            grant for grant in self.live if grant.kind is ApprovalKind.ERC721_ALL
        )

    @property
    def stale(self) -> tuple[LiveApproval, ...]:
        return tuple(
            grant for grant in self.live if grant.stale(self.as_of, stale_days=self.stale_days)
        )

    @property
    def spenders(self) -> tuple[str, ...]:
        return tuple(sorted({grant.spender for grant in self.live}))

    @property
    def tokens(self) -> tuple[str, ...]:
        return tuple(sorted({grant.token for grant in self.live}))

    @property
    def ageable(self) -> bool:
        """
        True when at least one live grant carries a timestamp.

        Staleness is only a finding when ages are known. Without it, an empty
        ``stale`` tuple means "not measured", and the two must not read alike.
        """
        return any(grant.granted_at is not None for grant in self.live)

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "chain": self.chain,
            "total": self.total,
            "unlimited": len(self.unlimited),
            "collection_wide": len(self.collection_wide),
            "stale": len(self.stale) if self.ageable else None,
            "stale_measurable": self.ageable,
            "distinct_spenders": len(self.spenders),
            "distinct_tokens": len(self.tokens),
            "revoked": self.revoked,
            "events_replayed": self.events_replayed,
            "undecodable": self.undecodable,
            "stale_days": self.stale_days,
            "approvals": [grant.as_dict(self.as_of) for grant in self.live],
            "unanswerable": list(self.unanswerable),
        }


#: Stated once, attached to every report. These are properties of the
#: available data, not gaps in this module, and they do not vary per call.
UNANSWERABLE: Final[tuple[str, ...]] = (
    "whether any spender is malicious -- no label source and no bytecode analysis",
    "how much value is at risk -- an allowance is a ceiling, not a holding, "
    "and no balance is read here",
    "whether the token contract is still live",
)


def replay(
    approvals: Iterable[DecodedApproval],
) -> tuple[dict[tuple[str, str, str, str], DecodedApproval], int]:
    """
    Fold approval events into the latest state of each grant.

    Returns ``(latest_by_key, revocations)``. Sorting happens here rather
    than being required of the caller: the failure mode of an unsorted replay
    is a revoked approval reported as live, which is silent, plausible and
    exactly backwards.
    """
    ordered = sorted(approvals, key=lambda approval: approval.order)

    latest: dict[tuple[str, str, str, str], DecodedApproval] = {}
    for approval in ordered:
        latest[approval.key] = approval

    revocations = sum(1 for approval in latest.values() if approval.is_revocation)
    return latest, revocations


def exposure_for_owner(
    approvals: Sequence[DecodedApproval],
    *,
    owner: str,
    chain: str,
    as_of: float | None = None,
    stale_days: float = DEFAULT_STALE_DAYS,
    undecodable: int = 0,
) -> ExposureReport:
    """
    Live approval exposure for one owner.

    ``owner`` is matched case-insensitively against the canonical address
    each event carries. Events for other owners are ignored rather than
    rejected: a caller screening one address from a shared log batch is the
    ordinary case, not an error.
    """
    normalized_owner = owner.lower()
    mine = [
        approval
        for approval in approvals
        if approval.owner.value.lower() == normalized_owner
    ]

    latest, revocations = replay(mine)

    live: list[LiveApproval] = []
    for approval in latest.values():
        if approval.is_revocation:
            continue
        live.append(
            LiveApproval(
                kind=approval.kind,
                chain=approval.chain,
                token=approval.token.value,
                owner=approval.owner.value,
                spender=approval.spender.value,
                allowance=approval.allowance.raw if approval.allowance else None,
                token_id=approval.token_id,
                block_number=approval.block_number,
                granted_at=approval.block_timestamp,
            )
        )

    live.sort(key=lambda grant: (grant.token, grant.spender, grant.token_id or -1))

    return ExposureReport(
        owner=owner,
        chain=chain,
        live=tuple(live),
        revoked=revocations,
        events_replayed=len(mine),
        undecodable=undecodable,
        as_of=as_of,
        stale_days=stale_days,
        unanswerable=UNANSWERABLE,
    )
