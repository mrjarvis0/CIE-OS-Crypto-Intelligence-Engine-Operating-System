"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for normalization -- refusal versus substitution, and completeness
labelling.

DR-08 says raw external data must never be trusted. The tests that matter are
the ones proving the tempting shortcut was not taken: that a missing field
stays missing instead of becoming zero, and that an internally impossible
payload is refused whole rather than mined for the parts that happen to parse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from normalization import (
    Normalizer,
    Severity,
    assess_block,
    normalize_block,
    read_quantity,
)
from schemas.block import CanonicalBlock, from_unix
from sensors.envelope import CaptureGap, Provenance, RawRecord, RecordKind

TIMESTAMP = 1_700_000_000


def raw_block(**overrides) -> dict:
    """A well-formed EVM block payload, with fields overridable per test."""
    payload = {
        "number": "0x64",
        "hash": "0xaaa100",
        "parentHash": "0xaaa099",
        "timestamp": hex(TIMESTAMP),
        "gasUsed": "0x5208",
        "gasLimit": "0x1c9c380",
        "miner": "0x" + "9" * 40,
        "transactions": [],
    }
    payload.update(overrides)
    return payload


def raw_tx(**overrides) -> dict:
    payload = {
        "hash": "0xdead0001",
        "from": "0x" + "1" * 40,
        "to": "0x" + "2" * 40,
        "value": hex(10**18),
        "transactionIndex": "0x0",
        "gas": "0x5208",
        "gasPrice": "0x3b9aca00",
        "nonce": "0x1",
        "input": "0x",
    }
    payload.update(overrides)
    return payload


def record_of(payload: dict, *, chain: str = "ethereum", kind=RecordKind.BLOCK) -> RawRecord:
    return RawRecord(
        chain=chain,
        kind=kind,
        payload=payload,
        height=100 if kind in {RecordKind.BLOCK, RecordKind.LOGS} else None,
        provenance=Provenance("publicnode", chain, "eth_getBlockByNumber", "ok"),
    )


# ==============================================================================
# QUANTITY READING
# ==============================================================================

def test_absent_and_unreadable_both_read_as_none():
    """The caller decides which is fatal; the reader does not guess."""
    assert read_quantity(None) is None
    assert read_quantity("0xzz") is None
    assert read_quantity("") is None
    assert read_quantity(True) is None


def test_quantities_parse_from_hex_and_decimal():
    assert read_quantity("0x64") == 100
    assert read_quantity("100") == 100
    assert read_quantity(100) == 100


# ==============================================================================
# BLOCK — refusal, not substitution
# ==============================================================================

@pytest.mark.parametrize("missing", ["number", "hash", "parentHash", "timestamp"])
def test_a_missing_required_field_rejects_the_block(missing):
    """
    A block that cannot be placed, linked, or dated is not a weaker
    observation. Substituting a default would turn "the provider did not say"
    into a positive claim about the chain.
    """
    payload = raw_block()
    del payload[missing]

    block, issues = normalize_block(payload, chain="ethereum")

    assert block is None
    assert any(issue.field == missing for issue in issues)


def test_unreadable_timestamp_is_not_the_epoch():
    block, issues = normalize_block(raw_block(timestamp="later"), chain="ethereum")

    assert block is None
    assert any(issue.field == "timestamp" for issue in issues)


def test_gas_used_above_gas_limit_rejects_the_whole_block():
    """
    Internally impossible. Whatever produced it is wrong about something, so
    taking the fields that happen to parse imports that wrongness selectively.
    """
    block, issues = normalize_block(
        raw_block(gasUsed="0x1c9c381", gasLimit="0x1c9c380"), chain="ethereum"
    )

    assert block is None
    assert issues[0].field == "gasUsed"


def test_non_object_payload_is_rejected():
    block, issues = normalize_block("not a block", chain="ethereum")
    assert block is None
    assert issues


def test_a_valid_block_maps_completely():
    block, issues = normalize_block(
        raw_block(), chain="ethereum", source_record_id="rec-1", source_provider="publicnode"
    )

    assert block is not None
    assert not issues
    assert block.number == 100
    assert block.block_hash == "0xaaa100"
    assert block.timestamp == from_unix(TIMESTAMP)
    assert block.source_provider == "publicnode"


def test_a_malformed_miner_does_not_reject_the_block():
    """The producer's identity is not needed to place the block."""
    block, _ = normalize_block(raw_block(miner="0xnope"), chain="ethereum")

    assert block is not None
    assert block.miner is None


# ==============================================================================
# TRANSACTIONS
# ==============================================================================

def test_expanded_transactions_are_mapped():
    block, issues = normalize_block(
        raw_block(transactions=[raw_tx()]), chain="ethereum"
    )

    assert block is not None
    assert not issues
    assert len(block.transactions) == 1
    assert block.transactions[0].value.raw == 10**18


def test_a_hash_only_transaction_list_counts_without_expanding():
    """Not a defect: the header count stays authoritative."""
    block, issues = normalize_block(
        raw_block(transactions=["0xaa", "0xbb"]), chain="ethereum"
    )

    assert block is not None
    assert not issues
    assert block.transaction_count == 2
    assert not block.transactions_expanded


def test_one_bad_transaction_does_not_discard_the_block():
    """
    The shortfall between the stated count and the stored bodies is what makes
    the loss visible, so the block is worth keeping.
    """
    block, issues = normalize_block(
        raw_block(transactions=[raw_tx(), raw_tx(**{"from": "0xshort"})]),
        chain="ethereum",
    )

    assert block is not None
    assert block.transaction_count == 2
    assert len(block.transactions) == 1
    assert issues


def test_contract_creation_keeps_a_null_recipient():
    block, _ = normalize_block(
        raw_block(transactions=[raw_tx(to=None)]), chain="ethereum"
    )

    assert block is not None
    assert block.transactions[0].is_contract_creation


def test_a_huge_transfer_value_is_carried_exactly():
    """1M ETH in wei is far past a 64-bit column; it must not be reshaped here."""
    value = 10**24
    block, _ = normalize_block(
        raw_block(transactions=[raw_tx(value=hex(value))]), chain="ethereum"
    )

    assert block is not None
    assert block.transactions[0].value.raw == value


def test_input_size_is_measured_in_bytes():
    block, _ = normalize_block(
        raw_block(transactions=[raw_tx(input="0xdeadbeef")]), chain="ethereum"
    )
    assert block is not None
    assert block.transactions[0].input_size == 4


# ==============================================================================
# QUALITY
# ==============================================================================

def canonical_block(**overrides) -> CanonicalBlock:
    fields = {
        "chain": "ethereum",
        "number": 100,
        "block_hash": "0xaaa100",
        "parent_hash": "0xaaa099",
        "timestamp": from_unix(TIMESTAMP),
        "transaction_count": 0,
        "source_record_id": "rec-1",
    }
    fields.update(overrides)
    return CanonicalBlock(**fields)


def test_counted_but_uncaptured_transactions_are_flagged_incomplete():
    """
    The finding a detector must consult before concluding a block was quiet.
    Without it, "no large transfers here" is asserted from a record that never
    contained transfers.
    """
    report = assess_block(canonical_block(transaction_count=200))

    assert not report.complete
    assert report.plausible
    finding = report.by_severity(Severity.INCOMPLETE)[0]
    assert "no transfers occurred" in finding.do_not_infer


def test_a_genuinely_empty_block_is_clean():
    assert assess_block(canonical_block(transaction_count=0)).clean


def test_refused_logs_make_an_otherwise_perfect_block_incomplete():
    """
    The one finding the block cannot produce on its own.

    Everything else here is visible in the block's own fields. Logs arrive as a
    separate record, so a block whose logs were refused looks identical, by
    inspection, to a block that emitted none — which is how an absence gets
    asserted from a fetch that never happened.
    """
    report = assess_block(
        canonical_block(transaction_count=0), capture_gaps=(CaptureGap.LOGS,)
    )

    assert not report.complete
    assert report.plausible, "a refused fetch says nothing about the block's contents"
    finding = report.by_severity(Severity.INCOMPLETE)[0]
    assert finding.check == "logs_captured"
    assert "no token transfers occurred" in finding.do_not_infer


def test_selective_capture_is_not_reported_as_a_fetch_failure():
    """
    The regression for an ordering bug caught on live data.

    A block whose transactions were every one of them below the materiality
    floor arrives with an empty tuple — identical, by inspection, to a block
    fetched without expansion. Reported that way it says "the block was fetched
    without expansion", which sends a reader hunting a transport bug that does
    not exist. The floor is the caller's own statement of intent, so when it is
    present it is the explanation.
    """
    report = assess_block(canonical_block(transaction_count=204), capture_floor=10**18)

    finding = report.by_severity(Severity.INCOMPLETE)[0]
    assert finding.check == "selective_capture"
    assert "materiality floor" in finding.message
    assert "at or above it were all captured" in finding.do_not_infer


def test_without_a_floor_a_thin_block_still_reads_as_a_fetch_shortfall():
    """The non-selective path must be untouched by the branch above it."""
    report = assess_block(canonical_block(transaction_count=204))

    assert report.by_severity(Severity.INCOMPLETE)[0].check == "transactions_expanded"


def test_selective_capture_names_the_boundary_it_cannot_speak_past():
    """
    Still INCOMPLETE, and correctly so — but the boundary is exact. Everything
    at or above the floor was kept, so an absence claim above it is licensed
    and one below it is not, and the number says which side a question is on.
    """
    report = assess_block(canonical_block(transaction_count=10), capture_floor=42)

    assert not report.complete
    assert "42" in report.by_severity(Severity.INCOMPLETE)[0].do_not_infer


def test_the_reason_for_incompleteness_survives_the_boolean():
    """
    `complete` is one bit over two failures that mean opposite things.

    Storing only the bit is how a selectively captured window came to be read as
    a window whose transfers were never fetched — permanently, because the
    reason was gone by the time anything asked.
    """
    refused = assess_block(canonical_block(), capture_gaps=(CaptureGap.LOGS,))
    filtered = assess_block(canonical_block(transaction_count=204), capture_floor=10**18)

    assert refused.complete is filtered.complete is False, "the bit cannot tell them apart"
    assert refused.incomplete_reason == "logs_captured"
    assert filtered.incomplete_reason == "selective_capture"


def test_only_a_deliberate_shortfall_is_bounded():
    """
    What separates the two: a floor states what was dropped, a refused fetch
    states nothing. Only the first can carry a negative claim of any kind.
    """
    assert assess_block(canonical_block(transaction_count=204), capture_floor=1).bounded
    assert not assess_block(canonical_block(), capture_gaps=(CaptureGap.LOGS,)).bounded


def test_a_complete_record_is_not_bounded_because_there_is_nothing_to_bound():
    """`bounded` answers "is the shortfall limited", not "is this record good"."""
    report = assess_block(canonical_block())

    assert report.complete
    assert not report.bounded
    assert report.incomplete_reason == ""


def test_a_filtered_block_whose_logs_were_also_refused_is_not_bounded():
    """
    Both at once, which live capture produces routinely: the floor bounds the
    native transfers, and nothing bounds the token transfers that were never
    fetched. One unbounded reason is enough to void the whole record.
    """
    report = assess_block(
        canonical_block(transaction_count=204),
        capture_gaps=(CaptureGap.LOGS,),
        capture_floor=10**18,
    )

    assert not report.bounded
    assert report.incomplete_reason == "logs_captured,selective_capture"


def test_a_block_with_no_capture_gap_is_unaffected():
    """
    The default has to stay clean. A gap reported against every capture would
    cap every window at "cannot support an absence" permanently.
    """
    assert assess_block(canonical_block(transaction_count=0), capture_gaps=()).clean


def test_a_future_timestamp_is_implausible():
    ahead = datetime.now(UTC) + timedelta(hours=2)
    report = assess_block(canonical_block(timestamp=ahead))

    assert not report.plausible


def test_a_pre_blockchain_timestamp_is_implausible():
    report = assess_block(canonical_block(timestamp=from_unix(1_000_000)))
    assert not report.plausible


def test_gas_burned_with_no_transactions_is_implausible():
    report = assess_block(canonical_block(transaction_count=0, gas_used=21_000))
    assert not report.plausible


def test_a_record_without_provenance_cannot_be_cited():
    report = assess_block(canonical_block(source_record_id=""))

    assert not report.complete
    checks = {f.check for f in report.findings}
    assert "provenance" in checks


def test_quality_is_deterministic():
    block = canonical_block(transaction_count=5)
    now = datetime.now(UTC)
    assert assess_block(block, now=now).as_dict() == assess_block(block, now=now).as_dict()


# ==============================================================================
# NORMALIZER
# ==============================================================================

def test_normalizer_accepts_a_good_record():
    normalizer = Normalizer()
    result = normalizer.normalize(record_of(raw_block(transactions=[raw_tx()])))

    assert result.storable
    assert result.block is not None
    assert normalizer.stats.accepted == 1


def test_normalizer_rejects_and_counts_a_bad_record():
    normalizer = Normalizer()
    payload = raw_block()
    del payload["hash"]

    result = normalizer.normalize(record_of(payload))

    assert not result.storable
    assert normalizer.stats.rejected == 1
    assert result.issues


def test_a_non_evm_chain_is_named_not_parsed_as_evm():
    """
    Sniffing the payload would let a Solana block with a `number` field parse as
    EVM, producing a canonical record that is confidently wrong.
    """
    normalizer = Normalizer()
    result = normalizer.normalize(record_of(raw_block(), chain="solana"))

    assert not result.storable
    assert "solana_like" in result.reason
    assert normalizer.stats.unsupported == 1


def test_an_unregistered_chain_is_refused():
    normalizer = Normalizer()
    record = RawRecord(
        chain="notachain",
        kind=RecordKind.BLOCK,
        payload=raw_block(),
        provenance=Provenance("p", "notachain", "m", "ok"),
    )

    assert not normalizer.normalize(record).storable


def test_a_record_kind_without_a_mapping_is_refused():
    """
    RECEIPT has no normalizer. LOGS used to be here too and now maps to token
    activity; a kind gaining a mapping should move out of this test, not have
    the assertion loosened around it.
    """
    normalizer = Normalizer()
    result = normalizer.normalize(record_of({"status": "0x1"}, kind=RecordKind.RECEIPT))

    assert not result.storable
    assert "record kind" in result.reason


def topic_word(address: str) -> str:
    """An address left-padded into a 32-byte topic, as the chain encodes it."""
    return "0x" + address[2:].rjust(64, "0")


def transfer_log(**overrides) -> dict:
    payload = {
        "address": "0x" + "c3" * 20,
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
            topic_word("0x" + "a1" * 20),
            topic_word("0x" + "b2" * 20),
        ],
        "data": "0x" + f"{10**18:064x}",
        "transactionHash": "0xtx01",
        "blockHash": "0xaaa100",
        "blockNumber": "0x64",
        "logIndex": "0x0",
    }
    payload.update(overrides)
    return payload


def test_logs_now_map_to_token_activity():
    """
    The gap this closed: the sensor was already fetching logs and the pipeline
    was throwing them away. On L2s, where the largest native transfer in a real
    block is 0.0000, that meant seeing essentially nothing.
    """
    normalizer = Normalizer()
    result = normalizer.normalize(record_of([transfer_log()], kind=RecordKind.LOGS))

    assert result.storable
    assert result.is_token_activity
    assert len(result.activity.transfers) == 1
    assert normalizer.stats.token_transfers == 1


def test_a_transfer_binds_to_the_block_that_emitted_it():
    """
    Storage cascades token transfers from the block row, so the linkage is what
    lets a reorg withdrawal take them with it. Bound to a height instead, an
    abandoned transfer would read exactly like a live one.
    """
    normalizer = Normalizer()
    result = normalizer.normalize(record_of([transfer_log()], kind=RecordKind.LOGS))

    assert result.activity.transfers[0].block_hash == "0xaaa100"


def test_a_log_without_block_linkage_is_not_filed():
    normalizer = Normalizer()
    orphan = transfer_log()
    del orphan["blockHash"]

    result = normalizer.normalize(record_of([orphan], kind=RecordKind.LOGS))

    assert result.activity.transfers == ()
    assert any("blockHash" in i.field for i in result.issues)


def test_token_amounts_are_never_scaled_by_a_guessed_exponent():
    """
    decimals() needs an eth_call this layer does not make. Assuming 18 renders
    6-decimal USDC a trillion times too large, and the figure looks ordinary.
    """
    normalizer = Normalizer()
    result = normalizer.normalize(
        record_of([transfer_log(data="0x" + f"{140_261_088:064x}")], kind=RecordKind.LOGS)
    )
    transfer = result.activity.transfers[0]

    assert transfer.value.raw == 140_261_088
    assert transfer.decimals_known is False


def test_undecoded_logs_are_counted_as_the_denominator():
    """
    "300 transfers in this block" invites reading 300 as the total. Most logs
    are protocol events A01 has no opinion about, and the ratio says so.
    """
    normalizer = Normalizer()
    unknown = {"address": "0x" + "d4" * 20, "topics": ["0x" + "ee" * 32], "data": "0x"}

    result = normalizer.normalize(
        record_of([transfer_log(), unknown], kind=RecordKind.LOGS)
    )
    activity = result.activity

    assert activity.undecoded == 1
    assert activity.total_logs == 2
    assert activity.decoded_fraction == 0.5


def test_normalize_all_splits_instead_of_filtering():
    """
    A batch writer that silently drops rejections makes a provider serving junk
    look like a chain with no activity.
    """
    normalizer = Normalizer()
    good = record_of(raw_block())
    bad_payload = raw_block(number=None)
    bad = record_of(bad_payload)

    accepted, rejected = normalizer.normalize_all([good, bad])

    assert len(accepted) == 1
    assert len(rejected) == 1


def test_incomplete_records_are_counted_separately_from_rejections():
    normalizer = Normalizer()
    normalizer.normalize(record_of(raw_block(transactions=["0xaa"])))

    assert normalizer.stats.accepted == 1
    assert normalizer.stats.rejected == 0
    assert normalizer.stats.incomplete == 1
