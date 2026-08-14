"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for event decoding -- and above all for the one confusion that would be
invisible if it happened.

ERC-20 and ERC-721 `Transfer` events share a topic0. A decoder keyed on the
signature alone reads every NFT movement as a token transfer of `tokenId`
units: an enormous, plausible, entirely fabricated amount attached to a real
contract and two real addresses. Most of this file exists to prove that does
not happen.
"""

from __future__ import annotations

from collections import Counter

import pytest

from contracts import (
    APPROVAL_TOPIC,
    ERC1155_SINGLE_TOPIC,
    TRANSFER_TOPIC,
    DecodedTransfer,
    DecodeRefusal,
    EventKind,
    decode_log,
    decode_logs,
    shape_for,
    unsupported_reason,
)
from fixtures.replay import Recording
from schemas.address import ZERO_ADDRESS

CHAIN = "ethereum"
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
TOKEN = "0x" + "c3" * 20


def word(value: str) -> str:
    """An address left-padded into a 32-byte topic, as the chain encodes it."""
    return "0x" + value[2:].rjust(64, "0")


def erc20_log(*, sender=ALICE, recipient=BOB, amount=10**18, **extra) -> dict:
    payload = {
        "address": TOKEN,
        "topics": [TRANSFER_TOPIC, word(sender), word(recipient)],
        "data": "0x" + f"{amount:064x}",
        "transactionHash": "0xtx01",
        "blockNumber": "0x64",
        "logIndex": "0x2",
    }
    payload.update(extra)
    return payload


def erc721_log(*, sender=ALICE, recipient=BOB, token_id=7, **extra) -> dict:
    payload = {
        "address": TOKEN,
        "topics": [
            TRANSFER_TOPIC,
            word(sender),
            word(recipient),
            "0x" + f"{token_id:064x}",
        ],
        "data": "0x",
        "transactionHash": "0xtx02",
        "blockNumber": "0x64",
        "logIndex": "0x3",
    }
    payload.update(extra)
    return payload


# ==============================================================================
# THE SHARED SIGNATURE
# ==============================================================================

def test_erc20_and_erc721_really_do_share_a_topic():
    """
    The premise. If this ever stops being true the whole shape-discrimination
    design is unnecessary — and if it silently became false, the decoder would
    be solving a problem that no longer exists.
    """
    assert erc20_log()["topics"][0] == erc721_log()["topics"][0]


def test_shape_separates_them():
    assert shape_for(TRANSFER_TOPIC, 3, 32).kind is EventKind.ERC20_TRANSFER
    assert shape_for(TRANSFER_TOPIC, 4, 0).kind is EventKind.ERC721_TRANSFER


def test_an_nft_transfer_is_not_read_as_an_amount():
    """
    The failure this package exists to prevent: tokenId 7 becoming a transfer
    of 7 units, or tokenId 99999 becoming a whale-scale movement.
    """
    result = decode_log(erc721_log(token_id=99999), chain=CHAIN)

    assert isinstance(result, DecodedTransfer)
    assert result.is_nft
    assert result.token_id == 99999
    assert result.amount is None


def test_a_token_transfer_is_not_read_as_an_nft():
    result = decode_log(erc20_log(amount=5 * 10**18), chain=CHAIN)

    assert isinstance(result, DecodedTransfer)
    assert not result.is_nft
    assert result.token_id is None
    assert result.amount.raw == 5 * 10**18


# ==============================================================================
# REFUSAL, NOT GUESSWORK
# ==============================================================================

def test_a_transfer_signature_with_an_unknown_shape_is_refused():
    """
    A contract may emit this signature with any layout it likes. Coercing one
    would produce a transfer that never happened, wearing a real address.
    """
    odd = erc20_log()
    odd["data"] = "0x" + "00" * 64  # two words, not one

    result = decode_log(odd, chain=CHAIN)

    assert isinstance(result, DecodeRefusal)
    assert "no known event" in result.reason


def test_a_recognised_but_unsupported_standard_says_so():
    """
    'We saw it and declined' must be distinguishable from 'we never noticed
    it' — the same distinction the rest of A01 draws between an absence and an
    unknown.
    """
    log = {
        "address": TOKEN,
        "topics": [ERC1155_SINGLE_TOPIC, word(ALICE), word(ALICE), word(BOB)],
        "data": "0x" + "00" * 64,
    }
    result = decode_log(log, chain=CHAIN)

    assert isinstance(result, DecodeRefusal)
    assert result.recognised
    assert "ERC-1155" in result.reason


def test_an_unknown_signature_is_refused_without_being_recognised():
    log = {"address": TOKEN, "topics": ["0x" + "ab" * 32], "data": "0x"}
    result = decode_log(log, chain=CHAIN)

    assert isinstance(result, DecodeRefusal)
    assert not result.recognised


def test_an_approval_is_recognised_but_is_not_a_transfer():
    """Approvals must never enter flow analysis as movements."""
    log = {
        "address": TOKEN,
        "topics": [APPROVAL_TOPIC, word(ALICE), word(BOB)],
        "data": "0x" + f"{10**18:064x}",
    }
    result = decode_log(log, chain=CHAIN)

    assert isinstance(result, DecodeRefusal)
    assert result.recognised
    assert "not a transfer" in result.reason


@pytest.mark.parametrize("broken", [None, [], "log", 42, {"topics": []}])
def test_malformed_input_is_refused_not_raised(broken):
    """A parser that throws on hostile input is a denial-of-service surface."""
    assert isinstance(decode_log(broken, chain=CHAIN), DecodeRefusal)


def test_a_truncated_topic_is_refused():
    log = erc20_log()
    log["topics"][1] = "0xdeadbeef"

    assert isinstance(decode_log(log, chain=CHAIN), DecodeRefusal)


# ==============================================================================
# FIELD READING
# ==============================================================================

def test_an_address_is_read_from_the_end_of_its_topic():
    """
    Indexed addresses are left-padded to 32 bytes. Slicing from the front
    yields twelve zero bytes plus half an address — valid-looking, and nobody's.
    """
    result = decode_log(erc20_log(sender=ALICE), chain=CHAIN)

    assert result.sender.value == ALICE


def test_a_256_bit_amount_survives():
    """Token amounts hit the same 64-bit ceiling native values do."""
    huge = 10**30
    result = decode_log(erc20_log(amount=huge), chain=CHAIN)

    assert result.amount.raw == huge


def test_decimals_are_not_assumed():
    """
    The exponent lives in the contract, reachable only by eth_call. Assuming 18
    renders 6-decimal USDC a trillion times too large, and it looks ordinary.
    """
    result = decode_log(erc20_log(amount=140_261_088), chain=CHAIN)

    assert result.amount.raw == 140_261_088
    assert result.amount.decimals == 0, "the scale must be marked unknown, not guessed"


# ==============================================================================
# MINTS AND BURNS
# ==============================================================================

def test_a_mint_is_flagged():
    """
    Counted as an ordinary receipt, a mint inflates a holder's inflows with
    tokens nobody sent them.
    """
    result = decode_log(erc20_log(sender=ZERO_ADDRESS), chain=CHAIN)

    assert result.is_mint
    assert not result.economic


def test_a_burn_is_flagged():
    result = decode_log(erc20_log(recipient=ZERO_ADDRESS), chain=CHAIN)

    assert result.is_burn
    assert not result.economic


def test_an_ordinary_transfer_is_economic():
    assert decode_log(erc20_log(), chain=CHAIN).economic


# ==============================================================================
# BATCHES
# ==============================================================================

def test_a_batch_splits_rather_than_filters():
    """
    Silently dropping what could not be read makes a contract emitting garbage
    look like a contract emitting nothing.
    """
    transfers, refusals = decode_logs(
        [erc20_log(), erc721_log(), {"topics": ["0x" + "ff" * 32]}], chain=CHAIN
    )

    assert len(transfers) == 2
    assert len(refusals) == 1


def test_a_non_list_batch_is_refused():
    transfers, refusals = decode_logs("not a list", chain=CHAIN)

    assert transfers == ()
    assert len(refusals) == 1


# ==============================================================================
# AGAINST REAL MAINNET LOGS
# ==============================================================================

@pytest.fixture(scope="module")
def recorded_logs():
    recording = Recording.named("ethereum_logs")
    return [log for height in recording.logs for log in recording.logs[height]]


def test_the_fixture_carries_real_logs(recorded_logs):
    assert len(recorded_logs) > 1_000


def test_real_logs_decode_into_both_standards(recorded_logs):
    """
    Synthetic logs prove the rules; real ones prove the rules match what chains
    actually emit.
    """
    transfers, _ = decode_logs(recorded_logs, chain=CHAIN)
    kinds = Counter(t.kind.value for t in transfers)

    assert kinds["erc20_transfer"] > 500
    assert kinds["erc721_transfer"] >= 1


def test_no_real_nft_transfer_carries_an_amount(recorded_logs):
    """The confusion, checked against production data rather than fixtures."""
    transfers, _ = decode_logs(recorded_logs, chain=CHAIN)

    for transfer in transfers:
        if transfer.is_nft:
            assert transfer.amount is None
            assert transfer.token_id is not None
        else:
            assert transfer.amount is not None
            assert transfer.token_id is None


def test_every_real_refusal_states_a_reason(recorded_logs):
    _, refusals = decode_logs(recorded_logs, chain=CHAIN)

    assert refusals, "a real block contains events A01 does not decode"
    assert all(r.reason for r in refusals)


def test_decoding_real_logs_is_deterministic(recorded_logs):
    first, _ = decode_logs(recorded_logs, chain=CHAIN)
    second, _ = decode_logs(recorded_logs, chain=CHAIN)

    assert [t.as_dict() for t in first] == [t.as_dict() for t in second]


def test_the_transfer_topic_matches_what_the_chain_emits(recorded_logs):
    """
    Keccak-256 is unavailable on many Python builds, so the constant cannot be
    recomputed. This is the stronger check anyway: it proves the constant
    matches what Ethereum actually emitted.
    """
    topics = Counter(
        log["topics"][0].lower() for log in recorded_logs if log.get("topics")
    )

    assert topics[TRANSFER_TOPIC] > 500
    assert topics[APPROVAL_TOPIC] > 0
