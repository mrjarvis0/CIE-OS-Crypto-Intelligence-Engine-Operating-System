"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.security.approval_risk

Approval exposure screening: which spending grants an address still has
standing, and how broad each one is.

Two modules, split along the line the rest of the system uses:
``approvals`` turns logs into records and refuses what it cannot read;
``exposure`` replays those records into the live set and measures it.

Neither judges a spender. That needs a label source or contract bytecode,
and A01 ingests neither -- ``exposure.UNANSWERABLE`` carries that limit into
every report rather than leaving it in a docstring.

Status: complete, and not yet reachable from stored data
-------------------------------------------------------
The decoding and the replay are finished and tested. What is missing is
upstream of both: **A01 stores no approval logs.**

``database/migrations.py`` declares ``blocks``, ``transactions``,
``token_transfers``, ``nft_transfers``, the aggregates, ``entities``,
``labels``, ``call_ledger`` and ``exchange_flow_hourly``. There is no logs
table and no approvals table, and ``contracts/events.py`` refuses approval
logs before they could reach one -- correctly, since an approval moves
nothing and would corrupt flow totals.

So this package answers a question about a log stream nobody is capturing.
That is a deliberate order of work, not an oversight: the decoder has to
exist before capturing the logs is worth doing, and it is the half that can
be written and proven without touching the schema. Wiring it to live data
needs an approvals table, an ingestion path that keeps approval logs instead
of discarding them, and a migration -- schema work with its own review, and
the operator's call.

Until then, every entry point here takes its logs from the caller, which is
also what makes the whole package testable without a database.
"""

from .approvals import (
    ApprovalKind,
    ApprovalRefusal,
    DecodedApproval,
    decode_approval,
    decode_approvals,
    is_approval_topic,
)
from .exposure import (
    DEFAULT_STALE_DAYS,
    UNANSWERABLE,
    UNLIMITED_THRESHOLD,
    ExposureReport,
    LiveApproval,
    exposure_for_owner,
    replay,
)

__all__ = [
    "DEFAULT_STALE_DAYS",
    "UNANSWERABLE",
    "UNLIMITED_THRESHOLD",
    "ApprovalKind",
    "ApprovalRefusal",
    "DecodedApproval",
    "ExposureReport",
    "LiveApproval",
    "decode_approval",
    "decode_approvals",
    "exposure_for_owner",
    "is_approval_topic",
    "replay",
]
