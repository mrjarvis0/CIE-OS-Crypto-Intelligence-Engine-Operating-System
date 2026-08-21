"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for approval decoding and exposure replay.

Three of these earn the file on their own.

``test_an_approval_for_all_is_never_read_as_an_erc20_approval`` guards the one
place this decoder can be quietly wrong. The two events share a layout --
three topics, one data word -- so a decoder that checks shape before
signature reads a boolean ``true`` as an allowance of one base unit, and a
grant over an entire NFT collection is filed as dust.

``test_a_revocation_survives_an_out_of_order_replay`` guards the one place
the fold can be quietly wrong. Approvals replace rather than accumulate, so
replaying two events in the wrong order resurrects a revoked grant.

``test_a_second_erc20_spender_does_not_displace_the_first`` guards the grant
identity. The three standards key a grant differently, and using one key for
all three loses live approvals in one direction and keeps dead ones in the
other.
"""

from __future__ import annotations

import pytest

from blockchain.security.approval_risk import (
    UNLIMITED_THRESHOLD,
    ApprovalKind,
    ApprovalRefusal,
    DecodedApproval,
    decode_approval,
    decode_approvals,
    exposure_for_owner,
    is_approval_topic,
    replay,
)
from contracts.signatures import (
    APPROVAL_FOR_ALL_TOPIC,
    APPROVAL_TOPIC,
    TRANSFER_TOPIC,
)

OWNER = "0x" + "11" * 20
SPENDER = "0x" + "22" * 20
OTHER_SPENDER = "0x" + "33" * 20
TOKEN = "0x" + "44" * 20
ZERO = "0x" + "00" * 20

MAX_UINT256 = 2**256 - 1
DAY = 86_400.0


def word(address: str) -> str:
    return "0x" + address[2:].rjust(64, "0")


def data_word(value: int) -> str:
    return "0x" + format(value, "064x")


def erc20_log(spender: str = SPENDER, value: int = 1000, block: int = 100, index: int = 0, **extra):
    log = {
        "address": TOKEN,
        "topics": [APPROVAL_TOPIC, word(OWNER), word(spender)],
        "data": data_word(value),
        "blockNumber": block,
        "logIndex": index,
    }
    log.update(extra)
    return log


def erc721_log(to: str = SPENDER, token_id: int = 7, block: int = 100, index: int = 0):
    return {
        "address": TOKEN,
        "topics": [APPROVAL_TOPIC, word(OWNER), word(to), data_word(token_id)],
        "data": "0x",
        "blockNumber": block,
        "logIndex": index,
    }


def for_all_log(operator: str = SPENDER, approved: bool = True, block: int = 100, index: int = 0):
    return {
        "address": TOKEN,
        "topics": [APPROVAL_FOR_ALL_TOPIC, word(OWNER), word(operator)],
        "data": data_word(1 if approved else 0),
        "blockNumber": block,
        "logIndex": index,
    }


def decoded(logs) -> list[DecodedApproval]:
    approvals, refusals = decode_approvals(logs, chain="ethereum")
    assert refusals == (), [r.reason for r in refusals]
    return list(approvals)


# ==============================================================================
# THE SHARED-LAYOUT TRAP
# ==============================================================================

def test_an_approval_for_all_is_never_read_as_an_erc20_approval():
    """
    Both are three topics and one data word. Confusing them files a grant
    over an entire collection as an allowance of one base unit.
    """
    approval = decode_approval(for_all_log(approved=True), chain="ethereum")

    assert isinstance(approval, DecodedApproval)
    assert approval.kind is ApprovalKind.ERC721_ALL
    assert approval.approved is True
    assert approval.allowance is None
    assert approval.is_revocation is False


def test_an_erc20_approval_is_never_read_as_a_collection_grant():
    approval = decode_approval(erc20_log(value=1), chain="ethereum")

    assert approval.kind is ApprovalKind.ERC20
    assert approval.allowance.raw == 1
    assert approval.approved is None


def test_the_three_standards_decode_to_their_own_kinds():
    erc20, erc721, for_all = decoded([erc20_log(), erc721_log(), for_all_log()])

    assert erc20.kind is ApprovalKind.ERC20
    assert erc721.kind is ApprovalKind.ERC721_TOKEN
    assert erc721.token_id == 7
    assert for_all.kind is ApprovalKind.ERC721_ALL


def test_a_non_boolean_encoding_of_true_is_still_true():
    """A bool is a full ABI word: zero is false, anything else is true."""
    approval = decode_approval(
        {
            "address": TOKEN,
            "topics": [APPROVAL_FOR_ALL_TOPIC, word(OWNER), word(SPENDER)],
            "data": data_word(42),
        },
        chain="ethereum",
    )

    assert approval.approved is True


# ==============================================================================
# REFUSALS
# ==============================================================================

def test_a_transfer_log_is_not_an_approval():
    outcome = decode_approval(
        {
            "address": TOKEN,
            "topics": [TRANSFER_TOPIC, word(OWNER), word(SPENDER)],
            "data": data_word(1),
        },
        chain="ethereum",
    )

    assert isinstance(outcome, ApprovalRefusal)
    assert outcome.recognised is False
    assert "not an approval signature" in outcome.reason


def test_an_approval_with_the_wrong_layout_is_refused_as_recognised():
    """
    Recognised-but-wrong and never-seen are different states, and an operator
    needs to tell a declined log from an unnoticed one.
    """
    outcome = decode_approval(
        {
            "address": TOKEN,
            "topics": [APPROVAL_TOPIC, word(OWNER), word(SPENDER)],
            "data": "0x",  # ERC-20 approval needs a data word
        },
        chain="ethereum",
    )

    assert isinstance(outcome, ApprovalRefusal)
    assert outcome.recognised is True
    assert "byte(s) of data" in outcome.reason


def test_a_malformed_address_is_refused_not_truncated():
    outcome = decode_approval(
        {
            "address": TOKEN,
            "topics": [APPROVAL_TOPIC, "0xdeadbeef", word(SPENDER)],
            "data": data_word(1),
        },
        chain="ethereum",
    )

    assert isinstance(outcome, ApprovalRefusal)
    assert "address field unreadable" in outcome.reason


@pytest.mark.parametrize("log", [None, "a string", 42, {}, {"topics": []}])
def test_junk_is_refused_without_raising(log):
    assert isinstance(decode_approval(log, chain="ethereum"), ApprovalRefusal)


def test_refusals_are_returned_rather_than_dropped():
    """
    A silently discarded log is indistinguishable from one that was never
    there, and the count of what could not be read is part of the answer.
    """
    approvals, refusals = decode_approvals(
        [erc20_log(), {"topics": [TRANSFER_TOPIC]}, "junk"], chain="ethereum"
    )

    assert len(approvals) == 1
    assert len(refusals) == 2


def test_is_approval_topic_accepts_both_signatures_and_nothing_else():
    assert is_approval_topic(APPROVAL_TOPIC)
    assert is_approval_topic(APPROVAL_FOR_ALL_TOPIC.upper())
    assert not is_approval_topic(TRANSFER_TOPIC)
    assert not is_approval_topic(None)


# ==============================================================================
# REVOCATION, PER STANDARD
# ==============================================================================

def test_each_standard_revokes_in_its_own_way():
    """
    Reading one revocation form as another is how a revoked approval stays on
    the books.
    """
    erc20_zero = decode_approval(erc20_log(value=0), chain="ethereum")
    erc721_zero = decode_approval(erc721_log(to=ZERO), chain="ethereum")
    for_all_false = decode_approval(for_all_log(approved=False), chain="ethereum")

    assert erc20_zero.is_revocation is True
    assert erc721_zero.is_revocation is True
    assert for_all_false.is_revocation is True


def test_a_grant_is_not_a_revocation():
    assert decode_approval(erc20_log(value=1), chain="ethereum").is_revocation is False
    assert decode_approval(erc721_log(), chain="ethereum").is_revocation is False
    assert decode_approval(for_all_log(), chain="ethereum").is_revocation is False


# ==============================================================================
# REPLAY ORDER
# ==============================================================================

def test_a_revocation_survives_an_out_of_order_replay():
    """
    Providers batch across ranges and a backfill merged with a live tail can
    interleave. Folding in arrival order resurrects the revoked grant.
    """
    grant = erc20_log(value=MAX_UINT256, block=100)
    revoke = erc20_log(value=0, block=200)

    forwards = exposure_for_owner(decoded([grant, revoke]), owner=OWNER, chain="ethereum")
    backwards = exposure_for_owner(decoded([revoke, grant]), owner=OWNER, chain="ethereum")

    assert forwards.total == 0
    assert backwards.total == 0
    assert backwards.revoked == 1


def test_log_index_breaks_ties_within_a_block():
    grant = erc20_log(value=MAX_UINT256, block=100, index=0)
    revoke = erc20_log(value=0, block=100, index=1)

    report = exposure_for_owner(decoded([revoke, grant]), owner=OWNER, chain="ethereum")

    assert report.total == 0


def test_a_regrant_after_a_revocation_is_live_again():
    events = decoded(
        [
            erc20_log(value=MAX_UINT256, block=100),
            erc20_log(value=0, block=200),
            erc20_log(value=500, block=300),
        ]
    )
    report = exposure_for_owner(events, owner=OWNER, chain="ethereum")

    assert report.total == 1
    assert report.live[0].allowance == 500
    assert report.live[0].unlimited is False


def test_an_approval_replaces_rather_than_accumulates():
    """``approve`` sets an allowance. Two grants are not 1,500."""
    events = decoded([erc20_log(value=1000, block=100), erc20_log(value=500, block=200)])
    report = exposure_for_owner(events, owner=OWNER, chain="ethereum")

    assert report.total == 1
    assert report.live[0].allowance == 500


# ==============================================================================
# GRANT IDENTITY
# ==============================================================================

def test_a_second_erc20_spender_does_not_displace_the_first():
    """An owner may hold many simultaneous ERC-20 allowances on one token."""
    events = decoded(
        [
            erc20_log(spender=SPENDER, value=MAX_UINT256, block=100),
            erc20_log(spender=OTHER_SPENDER, value=250, block=101),
        ]
    )
    report = exposure_for_owner(events, owner=OWNER, chain="ethereum")

    assert report.total == 2
    assert set(report.spenders) == {SPENDER.lower(), OTHER_SPENDER.lower()}


def test_an_erc721_approval_to_a_new_address_replaces_the_old_one():
    """
    ERC-721 allows exactly one approved address per token id. Keying it by
    spender would leave the previous address on the books as though live.
    """
    events = decoded(
        [
            erc721_log(to=SPENDER, token_id=7, block=100),
            erc721_log(to=OTHER_SPENDER, token_id=7, block=200),
        ]
    )
    report = exposure_for_owner(events, owner=OWNER, chain="ethereum")

    assert report.total == 1
    assert report.live[0].spender == OTHER_SPENDER.lower()


def test_different_token_ids_are_different_grants():
    events = decoded([erc721_log(token_id=7), erc721_log(token_id=8, index=1)])

    assert exposure_for_owner(events, owner=OWNER, chain="ethereum").total == 2


def test_a_collection_grant_and_a_single_token_grant_coexist():
    """Revoking one must not appear to revoke the other."""
    events = decoded([for_all_log(block=100), erc721_log(block=101)])
    report = exposure_for_owner(events, owner=OWNER, chain="ethereum")

    assert report.total == 2

    revoked = decoded([for_all_log(block=100), erc721_log(block=101), for_all_log(approved=False, block=102)])
    after = exposure_for_owner(revoked, owner=OWNER, chain="ethereum")

    assert after.total == 1
    assert after.live[0].kind is ApprovalKind.ERC721_TOKEN


def test_another_owners_events_are_ignored_not_rejected():
    other_owner = "0x" + "99" * 20
    theirs = {
        "address": TOKEN,
        "topics": [APPROVAL_TOPIC, word(other_owner), word(SPENDER)],
        "data": data_word(MAX_UINT256),
        "blockNumber": 100,
    }
    report = exposure_for_owner(
        decoded([erc20_log(), theirs]), owner=OWNER, chain="ethereum"
    )

    assert report.total == 1
    assert report.events_replayed == 1


# ==============================================================================
# BREADTH
# ==============================================================================

@pytest.mark.parametrize(
    "value,unlimited",
    [
        (MAX_UINT256, True),
        (UNLIMITED_THRESHOLD, True),
        (UNLIMITED_THRESHOLD - 1, False),
        (10**24, False),
        (1, False),
    ],
)
def test_unlimited_is_a_threshold_not_an_equality(value: int, unlimited: bool):
    """
    Not every wallet asks for ``type(uint256).max``. Testing for equality
    with it misses real unlimited approvals, and the miss is silent.
    """
    report = exposure_for_owner(
        decoded([erc20_log(value=value)]), owner=OWNER, chain="ethereum"
    )

    assert report.live[0].unlimited is unlimited


def test_a_collection_grant_is_unconditionally_unlimited():
    """It covers tokens the owner does not hold yet, which no number expresses."""
    report = exposure_for_owner(
        decoded([for_all_log()]), owner=OWNER, chain="ethereum"
    )

    assert report.live[0].unlimited is True
    assert len(report.collection_wide) == 1


# ==============================================================================
# STALENESS
# ==============================================================================

def test_staleness_is_measured_when_timestamps_are_supplied():
    events = decoded([erc20_log(value=MAX_UINT256, blockTimestamp=1_000_000.0)])
    report = exposure_for_owner(
        events, owner=OWNER, chain="ethereum", as_of=1_000_000.0 + 200 * DAY
    )

    assert report.ageable is True
    assert len(report.stale) == 1
    assert report.live[0].age_days(report.as_of) == pytest.approx(200.0)


def test_a_recent_grant_is_not_stale():
    events = decoded([erc20_log(value=MAX_UINT256, blockTimestamp=1_000_000.0)])
    report = exposure_for_owner(
        events, owner=OWNER, chain="ethereum", as_of=1_000_000.0 + 10 * DAY
    )

    assert report.stale == ()


def test_an_ageless_grant_is_reported_as_unmeasured_not_as_fresh():
    """
    Without timestamps an empty `stale` tuple means "not measured", and that
    must not read like "nothing is stale".
    """
    report = exposure_for_owner(decoded([erc20_log()]), owner=OWNER, chain="ethereum")

    assert report.ageable is False
    assert report.as_dict()["stale"] is None
    assert report.as_dict()["stale_measurable"] is False


# ==============================================================================
# THE REPORT
# ==============================================================================

def test_every_report_carries_what_it_cannot_answer():
    """
    A report listing three unlimited approvals without saying "whether any of
    these spenders is dangerous is not determined here" reads as an alarm.
    """
    report = exposure_for_owner(decoded([erc20_log()]), owner=OWNER, chain="ethereum")
    rendered = " ".join(report.unanswerable)

    assert "malicious" in rendered
    assert "ceiling, not a holding" in rendered
    assert report.as_dict()["unanswerable"]


def test_the_report_counts_what_could_not_be_decoded():
    report = exposure_for_owner(
        decoded([erc20_log()]), owner=OWNER, chain="ethereum", undecodable=4
    )

    assert report.as_dict()["undecodable"] == 4


def test_an_allowance_serializes_as_a_string():
    """A 256-bit allowance is not a JSON number."""
    report = exposure_for_owner(
        decoded([erc20_log(value=MAX_UINT256)]), owner=OWNER, chain="ethereum"
    )
    payload = report.as_dict()

    assert payload["approvals"][0]["allowance"] == str(MAX_UINT256)
    assert int(payload["approvals"][0]["allowance"]) == MAX_UINT256


def test_an_empty_history_is_an_empty_report_not_an_error():
    report = exposure_for_owner([], owner=OWNER, chain="ethereum")

    assert report.total == 0
    assert report.revoked == 0
    assert report.as_dict()["distinct_spenders"] == 0


def test_replay_returns_the_latest_event_per_grant():
    events = decoded([erc20_log(value=1000, block=100), erc20_log(value=0, block=200)])
    latest, revocations = replay(events)

    assert len(latest) == 1
    assert revocations == 1
