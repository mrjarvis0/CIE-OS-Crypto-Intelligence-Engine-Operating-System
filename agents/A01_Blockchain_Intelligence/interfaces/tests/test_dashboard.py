"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the HTML dashboard.

A dashboard is where an honest system most easily turns dishonest: a number
shown large and unqualified is read as a fact. The tests that matter here are
the ones proving the page carries its caveats visually — a thin coverage bar
where the window is thin, raw token amounts never dressed up as quantities, and
nothing loaded from off the page.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from database import (
    Database,
    RecordWriter,
    SqliteAnalyticsRepository,
    SqliteBlockRepository,
    SqliteTokenRepository,
)
from interfaces.dashboard import ABSENCE_THRESHOLD, collect, render
from sensors.envelope import Provenance, RawRecord, RecordKind

CHAIN = "ethereum"
ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
USDC = "0x" + "c6" * 20
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _topic(addr: str) -> str:
    return "0x" + addr[2:].rjust(64, "0")


def block_record(number: int, txs: int = 1) -> RawRecord:
    return RawRecord(
        chain=CHAIN,
        kind=RecordKind.BLOCK,
        height=number,
        provenance=Provenance("fixture", CHAIN, "eth_getBlockByNumber", "ok"),
        payload={
            "number": hex(number),
            "hash": f"0xa{number:06d}",
            "parentHash": f"0xa{number - 1:06d}",
            "timestamp": hex(1_700_000_000 + number * 12),
            "transactions": [
                {
                    "hash": f"0xtx{number:05d}{i:02d}",
                    "from": ALICE,
                    "to": BOB,
                    "value": hex(10**18),
                    "transactionIndex": hex(i),
                    "input": "0x",
                }
                for i in range(txs)
            ],
        },
    )


def logs_record(number: int, count: int = 6) -> RawRecord:
    return RawRecord(
        chain=CHAIN,
        kind=RecordKind.LOGS,
        height=number,
        provenance=Provenance("fixture", CHAIN, "eth_getLogs", "ok"),
        payload=[
            {
                "address": USDC,
                "topics": [TRANSFER, _topic(ALICE), _topic(BOB)],
                "data": "0x" + f"{140_261_088:064x}",  # ~140 USDC at 6 decimals
                "transactionHash": f"0xlt{number:05d}{i:02d}",
                "blockHash": f"0xa{number:06d}",
                "blockNumber": hex(number),
                "logIndex": hex(i),
            }
            for i in range(count)
        ],
    )


@pytest.fixture
def populated():
    with Database() as db:
        writer = RecordWriter(
            SqliteBlockRepository(db), tokens=SqliteTokenRepository(db)
        )
        for number in (100, 101, 102):
            writer.write(block_record(number, txs=2))
            writer.write(logs_record(number))
        yield db


def snap(db, **kw):
    return collect(
        SqliteBlockRepository(db),
        SqliteTokenRepository(db),
        SqliteAnalyticsRepository(db),
        database="test.db",
        **kw,
    )


# ==============================================================================
# SELF-CONTAINED
# ==============================================================================

def test_the_page_loads_nothing_from_off_itself(populated):
    """
    Zero-dependency, like the REST API. An external font or script is a request
    a saved, offline, or air-gapped copy cannot make -- and a supply-chain
    surface on a page that renders financial data.
    """
    html = render(snap(populated))

    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert "<script src" not in html
    assert "@import" not in html


def test_the_page_is_one_document(populated):
    html = render(snap(populated))

    assert html.count("<!DOCTYPE html>") == 1
    assert "<style>" in html and "</style>" in html


def test_rendering_is_deterministic(populated):
    """A photograph of the database must not change between two shots of it."""
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    assert render(snap(populated, now=now)) == render(snap(populated, now=now))


# ==============================================================================
# HONESTY, RENDERED
# ==============================================================================

def test_a_thin_window_shows_a_thin_coverage_bar(populated):
    """
    Three blocks against a 3,600 threshold is a nearly empty bar and a 'thin'
    state, so a reader sees why negatives are withheld rather than reading their
    absence as their falsehood.
    """
    html = render(snap(populated))

    # The applied class on the card div, not the stylesheet (which defines both).
    assert '"coverage coverage-thin"' in html
    assert '"coverage coverage-ok"' not in html
    assert str(ABSENCE_THRESHOLD) in html or "3,600" in html


def test_token_amounts_are_never_shown_as_scaled_quantities(populated):
    """
    The raw value is 140,261,088 base units — ~140 USDC at six decimals. The
    page must never render it as 140,261,088 of anything, because decimals are
    unresolved and the figure would be wrong by a million.
    """
    html = render(snap(populated))

    # The token panel shows transfer *counts*, not amounts. The raw integer
    # must not appear as a displayed quantity anywhere on the page.
    assert "140,261,088" not in html
    assert "140261088" not in html


def test_the_flow_note_states_the_decimals_caveat(populated):
    html = render(snap(populated))

    assert "raw base units" in html or "decimals are unresolved" in html


def test_the_footer_states_the_evidence_stance(populated):
    html = render(snap(populated))

    assert "evidence, not decisions" in html


def test_a_deep_contiguous_window_reads_as_ok(populated):
    """The bar flips to 'ok' only when the window can actually license absence."""
    # Rebuild the snapshot with a threshold the fixture clears, by monkeypatching
    # nothing — instead assert the state machine via a fabricated deep window.
    from interfaces.dashboard import ChainCard, Snapshot

    card = ChainCard(
        chain=CHAIN, display="Ethereum", accent="#7b8cff",
        blocks=ABSENCE_THRESHOLD + 10, from_height=1, to_height=ABSENCE_THRESHOLD + 10,
        contiguous=True, supports_absence=True, coverage_limitation="",
        transactions=5, token_transfers=5, nft_transfers=0,
        largest_native="1.0 ETH", native_symbol="ETH", freshness="1m ago",
    )
    html = render(Snapshot(generated_at=datetime.now(UTC), database="x", chains=(card,)))

    assert '"coverage coverage-ok"' in html


# ==============================================================================
# CONTENT
# ==============================================================================

def test_the_snapshot_counts_what_was_stored(populated):
    s = snap(populated)

    assert s.total_blocks == 3
    assert s.total_transactions == 6
    assert s.total_token_transfers == 18  # 6 logs x 3 blocks
    assert len(s.chains) == 1


def test_the_flow_graph_is_scoped_to_one_token(populated):
    """Cross-token value is meaningless; the graph is drawn for one contract."""
    s = snap(populated)

    assert s.flow is not None
    assert s.flow.token == USDC


def test_an_empty_database_renders_a_prompt_not_a_blank_page():
    with Database() as db:
        html = render(snap(db))

    assert "No chain data stored yet" in html
    assert "ingest" in html


def test_addresses_are_abbreviated_not_dropped(populated):
    """A reader needs to recognise an address; the full string is unreadable."""
    html = render(snap(populated))

    assert "…" in html  # abbreviation marker
    assert ALICE not in html  # never the full 42-char form in the token panels


def test_html_special_characters_would_be_escaped():
    """A chain or token label is data; it must not become markup."""
    from interfaces.dashboard import _e

    assert _e("<script>") == "&lt;script&gt;"


# ==============================================================================
# REACH — registered chains against ingested ones
# ==============================================================================

def test_the_reach_panel_lists_every_registered_chain(populated):
    """
    The page used to show only chains with stored history, which made "A01 has
    one chain" and "A01 can read thirteen and one is ingested" render
    identically. They are different facts.
    """
    from config.rpc.chains import supported_chain_names

    snapshot = snap(populated)

    assert len(snapshot.reach) == len(supported_chain_names())
    assert {r.chain for r in snapshot.reach} >= {"linea", "scroll", "gnosis", "unichain"}


def test_reach_separates_ingested_from_merely_readable(populated):
    snapshot = snap(populated)
    states = {r.chain: r.state for r in snapshot.reach}

    assert states["ethereum"] == "stored"
    assert states["linea"] == "idle"
    # A missing sensor is a different problem from an unsupported chain, and it
    # keeps its own state rather than collapsing into "not ingested".
    assert states["solana"] == "unobservable"


def test_reach_renders_the_three_states_distinguishably(populated):
    html = render(snap(populated))

    assert "ingested" in html
    assert "readable, nothing captured" in html
    assert "no sensor" in html


def test_every_new_chain_has_its_own_accent():
    """Six chains sharing the default grey are six chains a reader cannot tell apart."""
    from interfaces.dashboard import _DEFAULT_ACCENT, _accent

    for chain in ("linea", "scroll", "gnosis", "celo", "mantle", "unichain"):
        assert _accent(chain) != _DEFAULT_ACCENT, chain


# ==============================================================================
# EXCHANGE FLOW
# ==============================================================================

def _label(db, address: str, entity: str = "Binance") -> None:
    from tiers.ledger import EVM_SCOPE, Label, LabelRepository

    LabelRepository(db).save(
        Label(
            chain=EVM_SCOPE,
            address=address,
            label=f"{entity} hot",
            entity=entity,
            category="exchange",
            source="test:fixture-list",
            confidence=0.5,
        )
    )


def test_without_labels_the_flow_panel_states_why_rather_than_showing_zero(populated):
    """
    A zero here with no labels loaded would be a confident figure produced by a
    rule that never ran.
    """
    html = render(snap(populated))

    assert "no exchange address labels loaded" in html
    # Asserted in two parts: the sentence wraps in the template, so the whole
    # phrase is not a contiguous substring of the rendered page.
    assert "never infers" in html
    assert "from behaviour" in html


def test_with_labels_the_panel_attributes_and_names_its_source(populated):
    _label(populated, BOB)
    snapshot = snap(populated)

    assert snapshot.exchange is not None
    assert snapshot.exchange.determined
    assert snapshot.exchange.attributed == 6
    assert snapshot.exchange.label_source == "test:fixture-list"

    html = render(snapshot)
    assert "test:fixture-list" in html
    assert "Binance" in html


def test_an_unverified_list_is_flagged_on_the_panel(populated):
    """
    The figures are only worth what the list behind them is worth, and the page
    has to say so where the figures are, not in a footnote.
    """
    _label(populated, BOB)
    html = render(snap(populated))

    assert "unverified" in html
    assert "external claim rather than an established fact" in html


def test_the_panel_carries_the_skill_s_own_bounds(populated):
    _label(populated, BOB)
    html = render(snap(populated))

    assert "native value only" in html
    assert "no exchange list is complete" in html


def test_a_net_outflow_renders_as_a_signed_magnitude(populated):
    """
    ``Amount`` refuses a negative, correctly: a net flow is the difference of
    two quantities rather than a quantity. The sign travels beside the
    magnitude instead of inside it.
    """
    from interfaces.dashboard import _operator_row

    outbound = _operator_row(
        "Kraken", {"inflow_count": 0, "outflow_count": 3, "net_value": -2 * 10**18}
    )
    inbound = _operator_row(
        "Binance", {"inflow_count": 3, "outflow_count": 0, "net_value": 2 * 10**18}
    )

    assert outbound.direction == "out"
    assert outbound.net.startswith("−")
    assert "2.0000" in outbound.net
    assert inbound.direction == "in"
    assert inbound.net.startswith("+")


def test_the_panel_never_interprets_direction(populated):
    """Direction is what moved. Whether it is sell pressure is not decidable here."""
    _label(populated, BOB)
    html = render(snap(populated)).lower()

    for forbidden in ("sell pressure is", "bullish", "bearish", "dumping"):
        assert forbidden not in html, forbidden
