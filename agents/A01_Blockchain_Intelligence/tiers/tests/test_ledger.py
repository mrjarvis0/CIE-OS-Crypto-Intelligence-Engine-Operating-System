"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for Tier L: the label ledger.

A label is an external assertion about an address, and the whole value of this
tier is that the assertion cannot lose its provenance on the way in. Most of
what is asserted here protects that: a label with no source is unconstructable,
a category outside the vocabulary is refused, and a reload corrects rather than
duplicates.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from database import Database
from tiers.ledger import (
    CONFIDENCE,
    EVM_SCOPE,
    UNVERIFIED,
    VERIFIED,
    Label,
    LabelRepository,
    chain_scope,
    label_set_from,
)

BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"
COINBASE = "0x71660c4005ba85c37ccec55d0c4493e66fe775d3"
WALLET = "0x5fa36dfe10ce3ee46479790076afe328bef7e2e2"


@pytest.fixture
def repo():
    with Database() as db:
        yield LabelRepository(db)


def label(address: str = BINANCE, **overrides) -> Label:
    fields = {
        "chain": EVM_SCOPE,
        "address": address,
        "label": "Binance 14",
        "entity": "Binance",
        "category": "exchange",
        "source": "gist:xfwil/07dadf39",
        "confidence": CONFIDENCE[UNVERIFIED],
    }
    fields.update(overrides)
    return Label(**fields)


# ==============================================================================
# PROVENANCE IS NOT OPTIONAL
# ==============================================================================

def test_a_label_without_a_source_cannot_be_constructed():
    """
    The design rule, enforced by the type rather than by a reviewer.

    There must be no path from "this address behaves like an exchange" to a row
    in this table, and the cheapest way to guarantee that is to make an
    unsourced label impossible to build at all.
    """
    with pytest.raises(ValueError, match="no source"):
        label(source="")


def test_an_unknown_category_is_refused():
    """
    An open vocabulary accumulates `exchange`, `Exchange` and `cex` for one
    idea, and the gate reading them silently matches a third of the rows.
    """
    with pytest.raises(ValueError, match="unknown label category"):
        label(category="cex")


def test_confidence_outside_zero_to_one_is_refused():
    with pytest.raises(ValueError, match="confidence out of range"):
        label(confidence=1.4)


def test_an_unverified_list_loads_below_certainty():
    """
    A large well-formed community list is evidence of care, not of correctness.
    It must not arrive at a confidence that lets a conclusion rest on it alone.
    """
    assert CONFIDENCE[UNVERIFIED] <= 0.5
    assert CONFIDENCE[UNVERIFIED] < CONFIDENCE[VERIFIED]


# ==============================================================================
# STORAGE
# ==============================================================================

def test_a_label_survives_a_round_trip(repo):
    repo.save(label())

    found = repo.lookup("ethereum", BINANCE)

    assert len(found) == 1
    assert found[0].entity == "Binance"
    assert found[0].label == "Binance 14"
    assert found[0].source == "gist:xfwil/07dadf39"


def test_reloading_the_same_list_updates_rather_than_duplicates(repo):
    """A re-run must be free, and a corrected upstream list must correct here."""
    assert repo.save(label()) is True
    assert repo.save(label(label="Binance 14 (hot)")) is False

    found = repo.lookup(EVM_SCOPE, BINANCE)

    assert len(found) == 1, "one address from one source is one row"
    assert found[0].label == "Binance 14 (hot)"


def test_first_seen_survives_an_update(repo):
    """
    When A01 first learned an address is a fact about A01, and re-reading the
    same file does not change it.
    """
    first = datetime(2026, 1, 1, tzinfo=UTC)
    repo.save(label(first_seen=first))
    repo.save(label(first_seen=datetime(2026, 8, 1, tzinfo=UTC)))

    assert repo.lookup(EVM_SCOPE, BINANCE)[0].first_seen == first


def test_two_sources_labelling_one_address_are_two_rows(repo):
    """
    Disagreement between sources is a fact worth keeping, and corroboration is
    only visible if both assertions survive. Overwriting destroys both.
    """
    repo.save(label(source="gist:xfwil/07dadf39"))
    repo.save(label(source="dune:spellbook", entity="Binance", confidence=0.75))

    found = repo.lookup(EVM_SCOPE, BINANCE)

    assert len(found) == 2
    assert found[0].confidence == 0.75, "most confident first"


def test_save_many_reports_new_against_updated(repo):
    inserted, updated = repo.save_many([label(), label(COINBASE, entity="Coinbase")])
    assert (inserted, updated) == (2, 0)

    inserted, updated = repo.save_many([label(), label(COINBASE, entity="Coinbase")])
    assert (inserted, updated) == (0, 2), "a re-load changes nothing and says so"


def test_a_source_can_be_retracted_in_full(repo):
    """A list that turns out to be wrong has to be removable as a list."""
    repo.save(label(source="bad:list"))
    repo.save(label(COINBASE, entity="Coinbase", source="good:list"))

    assert repo.forget_source("bad:list") == 1
    assert repo.count() == 1


# ==============================================================================
# THE EVM FAMILY SCOPE
# ==============================================================================

def test_an_evm_chain_reads_the_family_scope(repo):
    """
    One EVM address is the same account on every EVM chain. A per-chain copy of
    a 2,858-row list would be nine copies that drift apart.
    """
    repo.save(label(chain=EVM_SCOPE))

    assert BINANCE in repo.label_set("ethereum")
    assert BINANCE in repo.label_set("base")


def test_a_non_evm_chain_does_not_read_the_evm_scope(repo):
    """
    A Solana address and an EVM address are different encodings. Matching one
    list against the other attaches a Binance label to whatever collides.
    """
    repo.save(label(chain=EVM_SCOPE))

    assert chain_scope("solana") == ("solana",)
    assert BINANCE not in repo.label_set("solana")


def test_an_unknown_chain_reads_only_its_own_rows():
    """An unrecognised name fails toward fewer labels, never toward wrong ones."""
    assert chain_scope("testchain") == ("testchain",)


# ==============================================================================
# THE HOT-PATH SET
# ==============================================================================

def test_the_label_set_is_case_insensitive_for_evm(repo):
    """
    EIP-55 encodes a checksum in the case of the hex, so the same account
    legitimately arrives in three different spellings.
    """
    repo.save(label())

    labels = repo.label_set("ethereum")

    assert labels.is_labelled(BINANCE.upper().replace("0X", "0x"))
    assert labels.is_labelled(BINANCE)


def test_an_empty_label_set_is_falsy(repo):
    """
    Callers must be able to tell "no labels" from "labels that did not match".
    A gate handed an empty set would advertise a rule that can never fire.
    """
    labels = repo.label_set("ethereum")

    assert not labels
    assert len(labels) == 0


def test_the_set_resolves_the_operator_not_the_address_label(repo):
    """
    Flow aggregation groups by operator. Keyed on "Binance 14" it would report
    three hundred exchanges where there is one.
    """
    repo.save(label(BINANCE, label="Binance 14", entity="Binance"))
    repo.save(label(COINBASE, label="Coinbase 6", entity="Coinbase"))

    labels = repo.label_set("ethereum")

    assert labels.entity_of(BINANCE) == "Binance"
    assert labels.entities() == ("Binance", "Coinbase")


def test_an_unlabelled_address_resolves_to_nothing(repo):
    repo.save(label())

    labels = repo.label_set("ethereum")

    assert labels.entity_of(WALLET) is None
    assert not labels.is_labelled(WALLET)


def test_the_most_confident_assertion_wins_the_set_entry(repo):
    """
    Two sources, one address, one entry in the hot-path set -- and it is the
    better-supported one. Both rows stay stored and inspectable.
    """
    repo.save(label(source="weak:list", entity="Maybe Binance", confidence=0.3))
    repo.save(label(source="strong:list", entity="Binance", confidence=0.95))

    assert repo.label_set("ethereum").entity_of(BINANCE) == "Binance"
    assert len(repo.lookup("ethereum", BINANCE)) == 2


def test_a_set_can_be_filtered_to_one_category(repo):
    repo.save(label())
    repo.save(label(COINBASE, entity="Hop", category="bridge"))

    exchanges = repo.label_set("ethereum", category="exchange")

    assert len(exchanges) == 1
    assert COINBASE not in exchanges


def test_a_set_can_be_built_without_storage():
    """The seam tests and dry runs use, so a gate can be exercised in memory."""
    labels = label_set_from([label()], chain="ethereum")

    assert labels.is_labelled(BINANCE)


# ==============================================================================
# REPORTING
# ==============================================================================

def test_the_summary_names_every_source(repo):
    """`cli labels` has to answer "where did this come from" without a query."""
    repo.save(label())
    repo.save(label(COINBASE, entity="Coinbase", source="dune:spellbook"))

    summary = repo.summary()

    assert summary["total"] == 2
    assert summary["categories"] == {"exchange": 2}
    assert {entry["source"] for entry in summary["sources"]} == {
        "gist:xfwil/07dadf39",
        "dune:spellbook",
    }


def test_a_pre_entity_database_upgrades_without_losing_labels(tmp_path):
    """
    Forward-only, as every migration here is. A database that already holds
    labels must not have to choose between keeping them and knowing who
    operates them.

    The old row is inserted with v3's own column list rather than through the
    repository, which writes today's schema -- staging an old database with a
    new build's INSERT would test nothing but itself.
    """
    from database import CURRENT_VERSION, Database as Db, migrate

    path = tmp_path / "old.db"
    with Db(path, migrate_on_open=False) as old:
        migrate(old.connection, target=5)
        with old.transaction() as connection:
            connection.execute(
                """
                INSERT INTO labels (
                    key, chain, address, label, category, source,
                    confidence, first_seen, last_verified, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{EVM_SCOPE}:{BINANCE}:legacy",
                    EVM_SCOPE,
                    BINANCE,
                    "Binance 14",
                    "exchange",
                    "legacy",
                    0.5,
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    UNVERIFIED,
                ),
            )

    with Db(path) as upgraded:
        repository = LabelRepository(upgraded)

        assert upgraded.schema_version() == CURRENT_VERSION
        assert repository.count() == 1
        # No operator was recorded, and none is invented. The set falls back to
        # the address's own label rather than grouping under an empty name.
        assert repository.label_set("ethereum").entity_of(BINANCE) == "Binance 14"


def test_entities_rank_operators_by_address_count(repo):
    for index in range(3):
        repo.save(label(f"0x{index:040x}", entity="Binance", label=f"Binance {index}"))
    repo.save(label(COINBASE, entity="Coinbase"))

    top = repo.entities(chain="ethereum")

    assert top[0] == {"entity": "Binance", "addresses": 3}
