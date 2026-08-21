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

Status: wired to stored data
----------------------------
The decoding and the replay were finished and tested before any of this was
reachable, and they were not changed to make it reachable -- the wiring was
built around them, not into them. Three pieces close the loop that this
docstring once named as still open:

* ``database/migrations.py`` v8 adds an ``approvals`` table, keyed and
  cascaded exactly as ``token_transfers`` is, so a replayed block is
  idempotent and a reorg withdrawal removes a grant with its block.
* ``normalization/approvals.py`` binds each decoded grant to the block that
  emitted it, the sibling of the transfer path. ``contracts/events.py`` still
  refuses approvals as non-transfers -- correctly, since an approval moves
  nothing -- and this is the separate path that keeps them.
* ``database/writer.py`` captures approvals from the same log batch through an
  optional repository, and ``cli approvals`` replays the stored log for one
  owner into :func:`exposure_for_owner`. The capture is opt-in: a writer with
  no approval repository behaves exactly as it did before the schema existed.

Every entry point here still takes its logs from the caller, which is what
keeps the decoding and the replay testable without a database.
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
