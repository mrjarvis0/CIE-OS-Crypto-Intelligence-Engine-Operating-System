"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for reading address lists off disk.

The failure this guards against is quiet loss. A list arrives in whatever shape
its author chose, and the two easy mistakes are to reject the whole file over a
column name, or to skip the rows that do not parse and report success. Both end
with an operator believing a label is loaded when it is not, and the second is
worse because nothing about the output shows it.
"""

from __future__ import annotations

import json

import pytest

from database import Database
from pipeline.labels import LabelFileError, load, load_file, parse_file
from tiers.ledger import CONFIDENCE, EVM_SCOPE, UNVERIFIED, VERIFIED, LabelRepository

BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"
COINBASE = "0x71660c4005ba85c37ccec55d0c4493e66fe775d3"
OKX = "0x5041ed759dd4afc3a72b8192c143f72f4724081a"


@pytest.fixture
def repo():
    with Database() as db:
        yield LabelRepository(db)


def write(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ==============================================================================
# SHAPE TOLERANCE
# ==============================================================================

def test_the_real_cex_list_shape_loads(tmp_path):
    """
    The exact header of the list the operator supplied. `cex_name` is the
    operator and `distinct_name` is this address's own label; both are read,
    because collapsing them loses one of two different facts.
    """
    path = write(
        tmp_path,
        "evm_cex.csv",
        "address,cex_name,distinct_name\n"
        f"{BINANCE},Binance,Binance 14\n"
        f"{COINBASE},Coinbase,Coinbase 6\n",
    )

    result = parse_file(path)

    assert result.accepted == 2
    assert result.labels[0].entity == "Binance"
    assert result.labels[0].label == "Binance 14"
    assert result.columns["address"] == "address"


def test_a_file_with_no_header_keeps_its_first_row(tmp_path):
    """
    Header detection is by content. Assuming a header would drop a real address
    on every load, and the file would look one row shorter than it is.
    """
    path = write(tmp_path, "plain.csv", f"{BINANCE},Binance\n{COINBASE},Coinbase\n")

    result = parse_file(path)

    assert result.accepted == 2, "the first row is data, not a header"


def test_column_aliases_are_matched_case_and_underscore_insensitively(tmp_path):
    path = write(
        tmp_path,
        "odd.csv",
        f"Wallet Address,Exchange\n{BINANCE},Binance\n",
    )

    result = parse_file(path)

    assert result.accepted == 1
    assert result.labels[0].entity == "Binance"


def test_a_json_list_of_objects_loads(tmp_path):
    path = write(
        tmp_path,
        "labels.json",
        json.dumps([{"address": BINANCE, "name": "Binance", "category": "exchange"}]),
    )

    result = parse_file(path)

    assert result.accepted == 1


def test_a_json_address_to_name_map_loads(tmp_path):
    path = write(tmp_path, "map.json", json.dumps({BINANCE: "Binance"}))

    result = parse_file(path)

    assert result.accepted == 1
    assert result.labels[0].entity == "Binance"


def test_a_plain_text_list_loads(tmp_path):
    path = write(tmp_path, "list.txt", f"# exchanges\n{BINANCE} Binance\n{COINBASE}\n")

    result = parse_file(path)

    assert result.accepted == 2
    assert result.labels[1].entity == "", "a bare address states no operator"


def test_a_header_with_no_address_column_fails_loudly(tmp_path):
    """
    The one case worth refusing outright. Guessing which column holds addresses
    would load a file of chain ids and report success.
    """
    path = write(tmp_path, "wrong.csv", "id,name\n1,Binance\n")

    with pytest.raises(LabelFileError, match="no address column"):
        parse_file(path)


# ==============================================================================
# NOTHING IS LOST SILENTLY
# ==============================================================================

def test_malformed_rows_are_counted_and_located(tmp_path):
    path = write(
        tmp_path,
        "mixed.csv",
        "address,name\n"
        f"{BINANCE},Binance\n"
        "0xtruncated,Broken\n"
        "not-an-address-at-all,Also broken\n",
    )

    result = parse_file(path)

    assert result.accepted == 1
    assert result.rejected_count == 2
    assert result.rejected[0].line == 3, "the line number identifies the row"


def test_a_non_evm_address_under_an_evm_scope_is_rejected(tmp_path):
    """
    Stored under `evm`, a Solana address can never match anything. It would be
    a row that looks loaded and is inert, which is worse than a refusal.
    """
    path = write(
        tmp_path,
        "mixed_chains.csv",
        f"address,name\n{BINANCE},Binance\nDRpbCBMxVnDK7maPM5tGv6MvB3v1sRMC86PZ8okm21hy,Solana thing\n",
    )

    result = parse_file(path, chain=EVM_SCOPE)

    assert result.accepted == 1
    assert result.rejected_count == 1
    assert "not an EVM address" in result.rejected[0].reason


def test_repeated_addresses_within_a_file_are_counted(tmp_path):
    path = write(tmp_path, "dupes.csv", f"address,name\n{BINANCE},Binance\n{BINANCE},Binance\n")

    result = parse_file(path)

    assert result.accepted == 1
    assert result.duplicates == 1


def test_a_checksummed_address_is_folded_to_the_stored_form(tmp_path):
    """
    Case decides nothing on EVM. Two spellings of one account must not become
    two labels, or a lookup for the true form misses half of them.
    """
    path = write(
        tmp_path,
        "checksum.csv",
        f"address,name\n{BINANCE.upper().replace('0X', '0x')},Binance\n",
    )

    result = parse_file(path)

    assert result.labels[0].address == BINANCE


# ==============================================================================
# PROVENANCE
# ==============================================================================

def test_the_source_defaults_to_the_file_and_says_so(tmp_path):
    """
    `file:<name>` is true and weak: it records where A01 read the list, not who
    published it. A caller that knows the origin should pass it.
    """
    path = write(tmp_path, "evm_cex.csv", f"address,name\n{BINANCE},Binance\n")

    result = parse_file(path)

    assert result.labels[0].source == "file:evm_cex.csv"


def test_a_supplied_source_is_kept_verbatim(tmp_path):
    path = write(tmp_path, "evm_cex.csv", f"address,name\n{BINANCE},Binance\n")

    result = parse_file(path, source="gist:xfwil/07dadf39")

    assert result.labels[0].source == "gist:xfwil/07dadf39"


def test_confidence_follows_the_verification_status(tmp_path):
    path = write(tmp_path, "evm_cex.csv", f"address,name\n{BINANCE},Binance\n")

    unverified = parse_file(path)
    verified = parse_file(path, verification_status=VERIFIED)

    assert unverified.labels[0].confidence == CONFIDENCE[UNVERIFIED]
    assert verified.labels[0].confidence == CONFIDENCE[VERIFIED]
    assert unverified.labels[0].confidence < verified.labels[0].confidence


def test_a_report_says_whether_the_category_came_from_the_file(tmp_path, repo):
    """
    A category applied from the command line is a claim the file never made.
    Applied to 2,858 rows it must not become indistinguishable from a sourced
    one.
    """
    without = write(tmp_path, "a.csv", f"address,name\n{BINANCE},Binance\n")
    with_column = write(
        tmp_path, "b.csv", f"address,name,category\n{COINBASE},Hop,bridge\n"
    )

    assert load_file(without, repo).category_supplied_by_caller is True
    assert load_file(with_column, repo).category_supplied_by_caller is False


def test_a_category_column_overrides_the_default_per_row(tmp_path, repo):
    path = write(
        tmp_path,
        "mixed.csv",
        f"address,name,category\n{BINANCE},Binance,exchange\n{COINBASE},Hop,bridge\n",
    )

    load_file(path, repo, category="exchange")

    assert repo.categories() == {"exchange": 1, "bridge": 1}


def test_an_unknown_category_in_the_file_rejects_the_row_only(tmp_path):
    path = write(
        tmp_path,
        "mixed.csv",
        f"address,name,category\n{BINANCE},Binance,exchange\n{COINBASE},Thing,nonsense\n",
    )

    result = parse_file(path)

    assert result.accepted == 1
    assert result.rejected_count == 1


def test_an_unknown_default_category_is_refused_before_anything_is_read(tmp_path):
    path = write(tmp_path, "a.csv", f"address,name\n{BINANCE},Binance\n")

    with pytest.raises(LabelFileError, match="unknown category"):
        parse_file(path, category="cex")


# ==============================================================================
# LOADING
# ==============================================================================

def test_loading_stores_what_it_parsed(tmp_path, repo):
    path = write(tmp_path, "evm_cex.csv", f"address,name\n{BINANCE},Binance\n{COINBASE},Coinbase\n")

    report = load_file(path, repo)

    assert (report.accepted, report.inserted, report.updated) == (2, 2, 0)
    assert repo.count() == 2


def test_reloading_the_same_file_inserts_nothing(tmp_path, repo):
    """A re-run must be free. The operator sees "0 new" and knows nothing moved."""
    path = write(tmp_path, "evm_cex.csv", f"address,name\n{BINANCE},Binance\n")

    load_file(path, repo)
    report = load_file(path, repo)

    assert (report.inserted, report.updated) == (0, 1)
    assert repo.count() == 1


def test_a_directory_produces_one_report_per_file(tmp_path, repo):
    """
    Not a merged total: a directory holding one good list and one broken list
    must not average into "mostly fine".
    """
    write(tmp_path, "good.csv", f"address,name\n{BINANCE},Binance\n")
    write(tmp_path, "partial.csv", f"address,name\n{OKX},OKX\n0xbad,Broken\n")
    write(tmp_path, "SOURCE.md", "# provenance notes, not data\n")

    reports = load(tmp_path, repo)

    assert len(reports) == 2, "the markdown note is not a label file"
    assert {r.rejected_count for r in reports} == {0, 1}


def test_loading_a_missing_path_fails_with_the_path_named(tmp_path, repo):
    with pytest.raises(LabelFileError, match="no label file"):
        load(tmp_path / "nothing", repo)


# ==============================================================================
# THE POINT OF ALL OF IT: THE GATE CAN FINALLY FIRE
# ==============================================================================

def test_a_loaded_list_keeps_a_small_transfer_into_an_exchange(tmp_path, repo):
    """
    The rule this whole step exists to activate.

    A modest transfer into a known exchange deposit address is a stronger
    signal than a large transfer between two wallets of one owner. That rule
    has been written and inert since selective capture was built, because no
    label source was configured. This is the seam where it starts firing.
    """
    from pipeline.materiality import MaterialityGate, Verdict
    from schemas.amount import Amount

    path = write(tmp_path, "evm_cex.csv", f"address,cex_name\n{BINANCE},Binance\n")
    load_file(path, repo, source="gist:xfwil/07dadf39")

    labels = repo.label_set("ethereum")
    gate = MaterialityGate(floor=Amount(10**18), is_labelled=labels.is_labelled)

    decision = gate.assess(value=10**15, to_address=BINANCE)

    assert decision.material
    assert decision.verdict is Verdict.LABELLED
    assert gate.limitation() == "", "the coverage hole is closed, so nothing to report"


def test_without_labels_the_same_transfer_is_dropped_and_the_gap_is_reported(repo):
    """The state before a load, and it has to name what it cannot see."""
    from pipeline.materiality import MaterialityGate
    from schemas.amount import Amount

    labels = repo.label_set("ethereum")
    gate = MaterialityGate(
        floor=Amount(10**18), is_labelled=labels.is_labelled if labels else None
    )

    assert not gate.assess(value=10**15, to_address=BINANCE).material
    assert "no address labels loaded" in gate.limitation()
