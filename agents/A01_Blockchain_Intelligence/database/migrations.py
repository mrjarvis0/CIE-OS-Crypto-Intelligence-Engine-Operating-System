"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    database.migrations

Purpose:
    The schema, expressed as an ordered list of versioned steps, and the runner
    that brings a database up to the current version.

Design goals:
    - Forward-only, numbered steps; a database states which it has applied
    - Each step idempotent, so a re-run is harmless
    - Every index justified by a query the system actually issues
    - Amounts stored as padded text, never as an integer column
    - Downgrade deliberately absent

Notes:
    Amount columns are ``TEXT``. This is the schema-level half of the decision
    explained in :mod:`schemas.amount`: SQLite's ``INTEGER`` is signed 64-bit,
    whose ceiling is about 9.22e18 -- roughly nine ether expressed in wei. A
    column of that type silently truncates every transfer above it, which is
    precisely the set of transfers a whale detector exists to find. Zero-padded
    decimal text preserves both the value and its ordering.

    Blocks are keyed by hash, not by height. A reorg produces two different
    blocks at the same height, and a height-keyed table can hold only one of
    them -- so the abandoned block either overwrites the canonical one or is
    dropped, and in both cases the evidence that a reorg occurred is gone. The
    ``canonical`` flag then distinguishes them, and the partial index on it is
    what keeps the common query fast.

    There are no downgrades. A downgrade that drops a column destroys captured
    observations, and one that keeps it is not a downgrade. When a change cannot
    be made forward-only, the answer is a new table and a copy step, not a
    reversal.
"""

from __future__ import annotations

import logging
import sqlite3

from dataclasses import dataclass
from typing import Final, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Migration:
    """One forward schema step."""

    version: int
    name: str
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("migration version must be >= 1")
        if not self.statements:
            raise ValueError(f"migration {self.version} has no statements")


_V1_BLOCKS: Final[str] = """
CREATE TABLE IF NOT EXISTS blocks (
    -- chain:hash. The hash, not the height: a reorg reuses heights, and both
    -- the canonical and the abandoned block must be storable side by side.
    key             TEXT    PRIMARY KEY,
    chain           TEXT    NOT NULL,
    number          INTEGER NOT NULL,
    block_hash      TEXT    NOT NULL,
    parent_hash     TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL,
    tx_count        INTEGER NOT NULL,
    -- 1 while this block is on the chain A01 believes in. Never deleted: the
    -- observation was correct even when the state it described was abandoned.
    canonical       INTEGER NOT NULL DEFAULT 1,
    withdrawn_at    TEXT,
    gas_used        INTEGER,
    gas_limit       INTEGER,
    miner           TEXT,
    -- Links back to the raw capture, so any row can be cited.
    source_record_id TEXT   NOT NULL DEFAULT '',
    source_provider TEXT    NOT NULL DEFAULT '',
    observed_at     TEXT    NOT NULL,
    -- Quality travels with the row. Without it a reader cannot tell a block
    -- with no transfers from a block whose transfers were never fetched.
    complete        INTEGER NOT NULL DEFAULT 1,
    plausible       INTEGER NOT NULL DEFAULT 1
)
"""

_V1_TRANSACTIONS: Final[str] = """
CREATE TABLE IF NOT EXISTS transactions (
    key             TEXT    PRIMARY KEY,
    chain           TEXT    NOT NULL,
    tx_hash         TEXT    NOT NULL,
    block_key       TEXT    NOT NULL,
    block_number    INTEGER NOT NULL,
    tx_index        INTEGER NOT NULL,
    from_address    TEXT    NOT NULL,
    -- NULL for a contract creation. Distinct from the zero address, which is a
    -- real counterparty for mints and burns.
    to_address      TEXT,
    -- Zero-padded decimal, 78 chars. See schemas.amount for why not INTEGER.
    value           TEXT    NOT NULL,
    value_decimals  INTEGER NOT NULL DEFAULT 18,
    gas_limit       INTEGER,
    gas_price       TEXT,
    nonce           INTEGER,
    input_size      INTEGER NOT NULL DEFAULT 0,
    source_record_id TEXT   NOT NULL DEFAULT '',
    FOREIGN KEY (block_key) REFERENCES blocks (key) ON DELETE CASCADE
)
"""

_V1: Final[tuple[Migration, ...]] = (
    Migration(
        version=1,
        name="blocks_and_transactions",
        statements=(
            _V1_BLOCKS,
            _V1_TRANSACTIONS,
            # The hot path: "where is this chain up to". Partial, because a
            # query for chain progress never wants abandoned blocks, and
            # excluding them keeps the index small however many reorgs occur.
            """
            CREATE INDEX IF NOT EXISTS idx_blocks_chain_number
                ON blocks (chain, number DESC) WHERE canonical = 1
            """,
            # Reorg audit: find what was withdrawn, and when.
            """
            CREATE INDEX IF NOT EXISTS idx_blocks_withdrawn
                ON blocks (chain, number) WHERE canonical = 0
            """,
            # Citation lookups from an evidence chain back to the capture.
            """
            CREATE INDEX IF NOT EXISTS idx_blocks_source
                ON blocks (source_record_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tx_block
                ON transactions (block_key)
            """,
            # Address activity, both directions. Two indexes rather than one
            # composite: a counterparty search filters on one side or the
            # other, never on the pair.
            """
            CREATE INDEX IF NOT EXISTS idx_tx_from
                ON transactions (chain, from_address, block_number DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_tx_to
                ON transactions (chain, to_address, block_number DESC)
            """,
            # Largest-transfer queries. Correct only because value is padded:
            # unpadded text would order "9" after "10".
            """
            CREATE INDEX IF NOT EXISTS idx_tx_value
                ON transactions (chain, value DESC)
            """,
        ),
    ),
)

_V2_TOKEN_TRANSFERS: Final[str] = """
CREATE TABLE IF NOT EXISTS token_transfers (
    -- chain:tx_hash:log_index. The log index is part of it because one
    -- transaction routinely emits the same transfer twice -- a swap routed
    -- through two pools -- and keying on the hash alone drops the second as a
    -- duplicate.
    key             TEXT    PRIMARY KEY,
    chain           TEXT    NOT NULL,
    tx_hash         TEXT    NOT NULL,
    log_index       INTEGER NOT NULL,
    block_key       TEXT    NOT NULL,
    block_number    INTEGER NOT NULL,
    -- The token contract that emitted the event, not the sender.
    token           TEXT    NOT NULL,
    from_address    TEXT    NOT NULL,
    to_address      TEXT    NOT NULL,
    -- Zero-padded decimal, 78 chars, exactly as native values are stored.
    value           TEXT    NOT NULL,
    -- 0 while the exponent is unresolved. Reading `value` as a human quantity
    -- while this is 0 is wrong by an unknown power of ten: decimals() needs an
    -- eth_call A01 does not make, and USDC uses 6 where most tokens use 18.
    decimals_known  INTEGER NOT NULL DEFAULT 0,
    is_mint         INTEGER NOT NULL DEFAULT 0,
    is_burn         INTEGER NOT NULL DEFAULT 0,
    source_record_id TEXT   NOT NULL DEFAULT '',
    -- ON DELETE CASCADE is what makes a reorg safe here. Withdrawal marks a
    -- block rather than deleting it, so the cascade is a backstop; a transfer
    -- whose block is gone must not survive it.
    FOREIGN KEY (block_key) REFERENCES blocks (key) ON DELETE CASCADE
)
"""

_V2_NFT_TRANSFERS: Final[str] = """
CREATE TABLE IF NOT EXISTS nft_transfers (
    key             TEXT    PRIMARY KEY,
    chain           TEXT    NOT NULL,
    tx_hash         TEXT    NOT NULL,
    log_index       INTEGER NOT NULL,
    block_key       TEXT    NOT NULL,
    block_number    INTEGER NOT NULL,
    collection      TEXT    NOT NULL,
    from_address    TEXT    NOT NULL,
    to_address      TEXT    NOT NULL,
    -- TEXT, not INTEGER: a tokenId is a uint256 and routinely exceeds 64 bits,
    -- and unlike a value it is an identifier, so a truncated one silently
    -- points at a different NFT rather than at a wrong amount.
    token_id        TEXT    NOT NULL,
    is_mint         INTEGER NOT NULL DEFAULT 0,
    is_burn         INTEGER NOT NULL DEFAULT 0,
    source_record_id TEXT   NOT NULL DEFAULT '',
    FOREIGN KEY (block_key) REFERENCES blocks (key) ON DELETE CASCADE
)
"""

#: Tier H. What a block contained, computed from transactions that were streamed
#: through the materiality gate and then discarded.
#:
#: This table is the reason the transaction mirror can go away. Storing every
#: transaction cost ~0.70 MB per ethereum block -- about 5 GB a day, 150 GB a
#: month, for one chain -- because 334 transactions per block were kept so that
#: a handful of them could later be counted. The counts are computed once, at
#: capture, and the rows they were computed from are dropped.
#:
#: ``materiality_floor`` records the threshold in force when this block was
#: filtered. Without it a later reader cannot tell whether a block has two
#: material transfers because it was quiet or because the gate was raised to
#: protect a rate-limit budget, and those license very different conclusions.
_V3_BLOCK_AGGREGATES: Final[str] = """
CREATE TABLE IF NOT EXISTS block_aggregates (
    -- chain:block_hash, matching blocks. A reorg produces two aggregates at one
    -- height for the same reason it produces two blocks.
    key                  TEXT    PRIMARY KEY,
    chain                TEXT    NOT NULL,
    number               INTEGER NOT NULL,
    block_hash           TEXT    NOT NULL,
    timestamp            TEXT    NOT NULL,

    -- The whole block, including everything discarded.
    tx_count             INTEGER NOT NULL,
    tx_value_total       TEXT    NOT NULL,
    tx_value_max         TEXT    NOT NULL,
    unique_senders       INTEGER NOT NULL DEFAULT 0,
    unique_receivers     INTEGER NOT NULL DEFAULT 0,
    gas_used             INTEGER,

    -- The subset that was kept. material_tx_count is the join back to the
    -- transactions table, which from here on holds material rows only.
    material_tx_count    INTEGER NOT NULL DEFAULT 0,
    material_value_total TEXT    NOT NULL,
    materiality_floor    TEXT    NOT NULL,

    -- Same meaning as blocks.complete: whether the capture obtained everything
    -- it asked for. An aggregate over a block whose logs were refused cannot
    -- license a claim about what that block did not contain.
    complete             INTEGER NOT NULL DEFAULT 1,

    source_provider      TEXT    NOT NULL DEFAULT '',
    source_record_id     TEXT    NOT NULL DEFAULT '',
    observed_at          TEXT    NOT NULL
)
"""

#: Tier W. Per-block aggregates rolled up to the hour, 24x smaller again.
#:
#: This is what a baseline is made of. "Whale transactions: normal 1,200/day,
#: today 4,800" is not answerable from live data at any price -- the comparison
#: needs the history the live call cannot provide. Ninety days of these is a few
#: megabytes per chain.
_V3_HOURLY_AGGREGATES: Final[str] = """
CREATE TABLE IF NOT EXISTS hourly_aggregates (
    -- chain:hour_start, so a re-roll of the same hour is an upsert not a duplicate.
    key                  TEXT    PRIMARY KEY,
    chain                TEXT    NOT NULL,
    hour_start           TEXT    NOT NULL,

    blocks               INTEGER NOT NULL,
    -- Of `blocks`, how many were captured whole. An hour rolled up from partly
    -- incomplete blocks is a floor, not a total, and must say so.
    complete_blocks      INTEGER NOT NULL DEFAULT 0,

    tx_count             INTEGER NOT NULL,
    tx_value_total       TEXT    NOT NULL,
    tx_value_max         TEXT    NOT NULL,
    material_tx_count    INTEGER NOT NULL DEFAULT 0,
    material_value_total TEXT    NOT NULL,
    gas_used             INTEGER,

    first_number         INTEGER NOT NULL,
    last_number          INTEGER NOT NULL,
    rolled_at            TEXT    NOT NULL
)
"""

#: Tier L. One row per address A01 has decided to track. Never expires.
#:
#: Smart money is the reason this table exists. A wallet cannot be called
#: successful from one transaction -- the label is a statement about a track
#: record, so the track record has to survive the retention that everything else
#: is subject to. This grows with tracked entities rather than with chain
#: traffic, which is why it can be kept forever.
#:
#: The classification columns travel together on purpose. Section 12 forbids
#: labelling an address from behaviour alone, so a label with no source, no
#: confidence and no verification status is not storable here.
_V3_ENTITIES: Final[str] = """
CREATE TABLE IF NOT EXISTS entities (
    key                  TEXT    PRIMARY KEY,   -- chain:address
    chain                TEXT    NOT NULL,
    address              TEXT    NOT NULL,

    first_seen_at        TEXT,
    last_seen_at         TEXT,
    first_seen_block     INTEGER,
    last_seen_block      INTEGER,

    sent_count           INTEGER NOT NULL DEFAULT 0,
    received_count       INTEGER NOT NULL DEFAULT 0,
    sent_total           TEXT    NOT NULL,
    received_total       TEXT    NOT NULL,
    counterparty_count   INTEGER NOT NULL DEFAULT 0,
    material_move_count  INTEGER NOT NULL DEFAULT 0,

    classification            TEXT,
    classification_source     TEXT,
    classification_confidence REAL,
    verification_status       TEXT NOT NULL DEFAULT 'unverified',
    classified_at             TEXT,

    updated_at           TEXT    NOT NULL
)
"""

#: Tier L. Reference data: which address is an exchange, a bridge, a token.
#:
#: Separate from `entities` because a label is an external assertion with its own
#: provenance and its own staleness, while an entity row is A01's own
#: observation. Merging them would make an unsourced guess indistinguishable
#: from a sourced fact.
_V3_LABELS: Final[str] = """
CREATE TABLE IF NOT EXISTS labels (
    key             TEXT    PRIMARY KEY,   -- chain:address:source
    chain           TEXT    NOT NULL,
    address         TEXT    NOT NULL,
    label           TEXT    NOT NULL,
    -- exchange | bridge | contract | token | mixer | treasury | smart_money
    category        TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    confidence      REAL    NOT NULL,
    first_seen      TEXT    NOT NULL,
    last_verified   TEXT    NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
)
"""

MIGRATIONS: Final[tuple[Migration, ...]] = _V1 + (
    Migration(
        version=2,
        name="token_and_nft_transfers",
        statements=(
            _V2_TOKEN_TRANSFERS,
            _V2_NFT_TRANSFERS,
            # Withdrawal cascade and per-block reads.
            """
            CREATE INDEX IF NOT EXISTS idx_token_block
                ON token_transfers (block_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_nft_block
                ON nft_transfers (block_key)
            """,
            # "What moved for this token" -- the query a token-flow skill runs.
            """
            CREATE INDEX IF NOT EXISTS idx_token_contract
                ON token_transfers (chain, token, block_number DESC)
            """,
            # Address activity, both directions. Two indexes rather than one
            # composite: a counterparty search filters one side or the other,
            # never the pair.
            """
            CREATE INDEX IF NOT EXISTS idx_token_from
                ON token_transfers (chain, from_address, block_number DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_token_to
                ON token_transfers (chain, to_address, block_number DESC)
            """,
            # Largest-transfer queries, scoped per token. Chain-wide ordering
            # by value is meaningless while decimals are unresolved: one
            # token's raw units are not comparable with another's.
            """
            CREATE INDEX IF NOT EXISTS idx_token_value
                ON token_transfers (chain, token, value DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_nft_collection
                ON nft_transfers (chain, collection, block_number DESC)
            """,
        ),
    ),
    Migration(
        version=3,
        name="tiered_storage",
        statements=(
            _V3_BLOCK_AGGREGATES,
            _V3_HOURLY_AGGREGATES,
            _V3_ENTITIES,
            _V3_LABELS,
            # Chain progress and window queries over aggregates, the same shape
            # the blocks table already serves.
            """
            CREATE INDEX IF NOT EXISTS idx_agg_chain_number
                ON block_aggregates (chain, number DESC)
            """,
            # Retention sweeps and "last N hours" both scan by time.
            """
            CREATE INDEX IF NOT EXISTS idx_agg_time
                ON block_aggregates (chain, timestamp)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_hourly_chain_time
                ON hourly_aggregates (chain, hour_start DESC)
            """,
            # Entity lookups by address, and the "who has A01 been tracking
            # longest" query that smart-money scoring runs.
            """
            CREATE INDEX IF NOT EXISTS idx_entities_address
                ON entities (chain, address)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_entities_activity
                ON entities (chain, material_move_count DESC)
            """,
            # The materiality gate asks "is this address labelled" for every
            # transaction it inspects, so this index is on the hot path.
            """
            CREATE INDEX IF NOT EXISTS idx_labels_address
                ON labels (chain, address)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_labels_category
                ON labels (chain, category)
            """,
        ),
    ),
)

_V4_CALL_LEDGER: Final[str] = """
CREATE TABLE IF NOT EXISTS call_ledger (
    -- provider:window_kind:window_start. One row per provider per window, so a
    -- spend is an UPDATE on a known key rather than an append and a SUM.
    key             TEXT    PRIMARY KEY,
    provider        TEXT    NOT NULL,
    chain           TEXT    NOT NULL DEFAULT '',
    -- 'day' or 'month'. Free tiers meter on both, and exhausting either one
    -- stops the provider answering, so both are tracked separately.
    window_kind     TEXT    NOT NULL,
    -- ISO date for a day window, YYYY-MM for a month. UTC, always: a ledger on
    -- local time double-counts or skips an hour twice a year, and the provider
    -- is not resetting on the operator's timezone.
    window_start    TEXT    NOT NULL,
    -- Attempts, not successes. A provider counts the request whether or not it
    -- answered, so counting successes undercounts exactly during the retries
    -- and timeouts that burn the most budget.
    spent           INTEGER NOT NULL DEFAULT 0,
    -- What the tier is believed to allow. Separate from `spent` so an observed
    -- 429 can lower the belief without touching the record of what was used.
    ceiling         INTEGER,
    -- Set when a 429 proved the documented ceiling wrong for this key.
    observed_limit  INTEGER,
    first_spend_at  TEXT    NOT NULL,
    last_spend_at   TEXT    NOT NULL
)
"""

MIGRATIONS = (
    *MIGRATIONS,
    Migration(
        version=4,
        name="call_budget_ledger",
        statements=(
            _V4_CALL_LEDGER,
            """
            CREATE INDEX IF NOT EXISTS idx_ledger_window
                ON call_ledger (window_kind, window_start)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ledger_provider
                ON call_ledger (provider, window_kind, window_start DESC)
            """,
        ),
    ),
)

#: Why a block is incomplete, and the floor that made it so.
#:
#: ``complete`` alone is a boolean over two failures that mean opposite things. A
#: block whose logs were refused is missing transfers nobody can describe, so it
#: licenses no negative claim at all. A block whose small transfers were dropped
#: at a stated floor is missing only what is below that floor, so it licenses a
#: negative claim above it. Both were stored as ``complete = 0``, and every
#: reader downstream had to assume the worse of the two -- which shut the
#: absence gate permanently the moment selective capture was switched on.
#:
#: ``incomplete_reason`` holds the quality checks that fired, comma-separated,
#: under their own names. ``capture_floor`` is the materiality floor in force for
#: the block, zero-padded exactly as every other amount column is, so ``MAX()``
#: over a window returns the highest floor rather than the longest string. Both
#: are empty for a block that was captured whole.
#:
#: ADD COLUMN, not a rebuild: the existing rows are correct, they are merely
#: silent about a distinction nothing had asked them for yet. SQLite has no
#: ``ADD COLUMN IF NOT EXISTS``, and it does not need one here -- the column and
#: the version bump commit in one transaction, so this step is never seen twice.
_V5_BLOCK_CAPTURE_REASON: Final[tuple[str, ...]] = (
    "ALTER TABLE blocks ADD COLUMN incomplete_reason TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE blocks ADD COLUMN capture_floor TEXT NOT NULL DEFAULT ''",
)

MIGRATIONS = (
    *MIGRATIONS,
    Migration(
        version=5,
        name="block_capture_reason",
        statements=_V5_BLOCK_CAPTURE_REASON,
    ),
)

#: Who operates a labelled address, as distinct from what the address is called.
#:
#: A CEX address list names both and they are different facts. "Binance 14" is
#: this address; "Binance" is the operator that also runs the other 300. A flow
#: aggregate keyed on the first reports three hundred exchanges where there is
#: one, and every per-exchange total it produces is a fragment.
#:
#: Deriving the operator from the label by stripping a trailing number would be
#: a guess dressed as a fact -- it works for "Binance 14" and invents an entity
#: for "Bitfinex: Hot Wallet 2". The source states both, so both are stored.
#:
#: Empty for a label whose source names no operator. That is a real absence: an
#: address labelled "mixer" belongs to nobody in the sense this column means.
_V6_LABEL_ENTITY: Final[tuple[str, ...]] = (
    "ALTER TABLE labels ADD COLUMN entity TEXT NOT NULL DEFAULT ''",
    """
    CREATE INDEX IF NOT EXISTS idx_labels_entity
        ON labels (chain, entity)
    """,
)

MIGRATIONS = (
    *MIGRATIONS,
    Migration(
        version=6,
        name="label_entity",
        statements=_V6_LABEL_ENTITY,
    ),
)

#: Tier W. Exchange deposits and withdrawals, rolled up to the hour per operator.
#:
#: A separate table rather than columns on ``hourly_aggregates``, because the two
#: rollups have different shapes and different lifetimes. An hourly aggregate is
#: one row per chain-hour; this is one row per chain-hour **per exchange**, and
#: folding a per-entity breakdown into a per-chain row would mean either a
#: column per exchange or a total that cannot be attributed. Exchange flow also
#: only exists where labels exist, so an hour with no labelled address produces
#: no row here while still producing an aggregate there.
#:
#: ``internal_count`` is the column that keeps the signal honest. A transfer
#: between two labelled addresses -- Binance hot wallet to Binance cold storage,
#: or Binance to Coinbase -- is not a user depositing. Counting it as inflow is
#: the classic way "exchange inflow" spikes on a rebalance and gets read as
#: incoming sell pressure, so it is tracked apart and excluded from both
#: directions.
#:
#: ``complete_blocks`` and ``capture_floor`` travel with the row for the same
#: reason they travel with a block: an hour rolled up from selectively captured
#: blocks holds only the transfers at or above a stated floor, and a total drawn
#: from it is a floor rather than a total. Without them the row reads as
#: complete, and "Binance took in 4,000 ETH this hour" would be asserted from a
#: capture that dropped everything under one ether.
_V7_EXCHANGE_FLOW_HOURLY: Final[str] = """
CREATE TABLE IF NOT EXISTS exchange_flow_hourly (
    -- chain:hour_start:entity, so re-rolling an hour is an upsert.
    key             TEXT    PRIMARY KEY,
    chain           TEXT    NOT NULL,
    hour_start      TEXT    NOT NULL,
    entity          TEXT    NOT NULL,

    -- Deposits: a transfer into a labelled address from an unlabelled one.
    inflow_count    INTEGER NOT NULL DEFAULT 0,
    inflow_value    TEXT    NOT NULL,
    -- Withdrawals: out of a labelled address to an unlabelled one.
    outflow_count   INTEGER NOT NULL DEFAULT 0,
    outflow_value   TEXT    NOT NULL,
    -- Both sides labelled. Neither a deposit nor a withdrawal.
    internal_count  INTEGER NOT NULL DEFAULT 0,
    internal_value  TEXT    NOT NULL,

    addresses       INTEGER NOT NULL DEFAULT 0,
    blocks          INTEGER NOT NULL DEFAULT 0,
    complete_blocks INTEGER NOT NULL DEFAULT 0,
    capture_floor   TEXT    NOT NULL DEFAULT '',

    first_number    INTEGER NOT NULL,
    last_number     INTEGER NOT NULL,
    -- Which label source attributed these addresses. A flow figure is only as
    -- good as the list behind it, and the list has to be nameable afterwards.
    label_source    TEXT    NOT NULL DEFAULT '',
    rolled_at       TEXT    NOT NULL
)
"""

MIGRATIONS = (
    *MIGRATIONS,
    Migration(
        version=7,
        name="exchange_flow_hourly",
        statements=(
            _V7_EXCHANGE_FLOW_HOURLY,
            # "The last N hours of flow", which is every read this table serves.
            """
            CREATE INDEX IF NOT EXISTS idx_flow_chain_hour
                ON exchange_flow_hourly (chain, hour_start DESC)
            """,
            # One exchange's history, which is the per-entity baseline.
            """
            CREATE INDEX IF NOT EXISTS idx_flow_entity
                ON exchange_flow_hourly (chain, entity, hour_start DESC)
            """,
        ),
    ),
)

#: One decoded approval event, so that approval-risk screening can run against
#: stored data rather than only against a log batch held in memory.
#:
#: A separate table from ``token_transfers``, not a flag on it, because an
#: approval is a different fact with a different shape: it moves nothing, it is
#: replaced rather than accumulated, and each of the three standards keys a
#: grant differently. Folding it into transfer flow is exactly what
#: ``contracts/events.py`` refuses to do -- an approval counted as a transfer
#: inflates every total it touches.
#:
#: ``kind`` is one of ``erc20_approval``, ``erc721_approval``,
#: ``erc721_approval_for_all``. The three do not share a payload: ``allowance``
#: is set for ERC-20 only, ``token_id`` for the per-token ERC-721 form only, and
#: ``approved`` for ``setApprovalForAll`` only. Each is NULL elsewhere rather
#: than defaulted, because a defaulted zero allowance reads as a revocation and
#: would put a live grant on the books as withdrawn.
#:
#: ``allowance`` is zero-padded TEXT for the same reason every amount column is:
#: an ERC-20 allowance is a uint256, routinely ``type(uint256).max``, which no
#: 64-bit INTEGER can hold. ``token_id`` is TEXT because it is a 256-bit
#: identifier, and a truncated one names a different NFT. ``is_revocation`` is
#: derived at decode time and stored so a screen can exclude withdrawals without
#: re-deriving each standard's revocation rule in SQL.
#:
#: Keyed on ``chain:tx_hash:log_index`` and cascaded from ``blocks`` exactly as
#: ``token_transfers`` is: a replayed block re-emits identical logs, so the write
#: is idempotent, and a reorg that withdraws the block removes its approvals with
#: it rather than leaving a grant attached to a history that no longer exists.
_V8_APPROVALS: Final[str] = """
CREATE TABLE IF NOT EXISTS approvals (
    key             TEXT    PRIMARY KEY,   -- chain:tx_hash:log_index
    chain           TEXT    NOT NULL,
    tx_hash         TEXT    NOT NULL,
    log_index       INTEGER NOT NULL,
    block_key       TEXT    NOT NULL,
    block_number    INTEGER NOT NULL,
    -- erc20_approval | erc721_approval | erc721_approval_for_all
    kind            TEXT    NOT NULL,
    -- The token or collection contract that emitted the event.
    token           TEXT    NOT NULL,
    owner           TEXT    NOT NULL,
    -- The spender (ERC-20), the approved address (ERC-721, zero on revoke), or
    -- the operator (ApprovalForAll). Always topic[2], whatever the standard.
    spender         TEXT    NOT NULL,
    -- Zero-padded decimal, ERC-20 only; NULL for the two ERC-721 forms.
    allowance       TEXT,
    -- uint256 as text, ERC-721 per-token only; NULL otherwise.
    token_id        TEXT,
    -- 0/1, setApprovalForAll only; NULL otherwise.
    approved        INTEGER,
    -- Derived at decode time. Each standard revokes differently, so storing the
    -- verdict keeps the exclusion out of every query that reads this table.
    is_revocation   INTEGER NOT NULL DEFAULT 0,
    -- A log carries no timestamp; this is set only when the caller joined the
    -- block, and stays NULL otherwise rather than being filled with read time --
    -- which would make every approval look freshly granted.
    block_timestamp REAL,
    source_record_id TEXT   NOT NULL DEFAULT '',
    FOREIGN KEY (block_key) REFERENCES blocks (key) ON DELETE CASCADE
)
"""

MIGRATIONS = (
    *MIGRATIONS,
    Migration(
        version=8,
        name="approvals",
        statements=(
            _V8_APPROVALS,
            # Withdrawal cascade and per-block reads, as token_transfers has.
            """
            CREATE INDEX IF NOT EXISTS idx_approvals_block
                ON approvals (block_key)
            """,
            # The exposure query: every live grant an owner has, newest first,
            # replayed into current state. This is the read this table exists to
            # serve, so it is the index that has to exist.
            """
            CREATE INDEX IF NOT EXISTS idx_approvals_owner
                ON approvals (chain, owner, block_number DESC, log_index DESC)
            """,
            # "Who did this token grant to", the reverse lookup a token-level
            # screen runs.
            """
            CREATE INDEX IF NOT EXISTS idx_approvals_token
                ON approvals (chain, token, block_number DESC)
            """,
        ),
    ),
)

#: The version a fresh database is brought to.
CURRENT_VERSION: Final[int] = max(m.version for m in MIGRATIONS)


def applied_version(connection: sqlite3.Connection) -> int:
    """
    The highest migration this database has applied; 0 for a fresh one.

    Uses SQLite's own ``user_version`` rather than a bookkeeping table. It is
    written inside the same transaction as the schema change, so the version and
    the schema cannot disagree after a crash -- which a separate table only
    guarantees with care that is easy to get wrong.
    """
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def migrate(connection: sqlite3.Connection, *, target: int | None = None) -> int:
    """
    Apply every pending migration up to ``target``, and return the new version.

    Each migration runs in one transaction together with its version bump, so a
    failure leaves the database at the previous version with none of the step
    applied.
    """
    ceiling = CURRENT_VERSION if target is None else target
    current = applied_version(connection)

    if current > CURRENT_VERSION:
        raise RuntimeError(
            f"database is at version {current}, this build knows "
            f"{CURRENT_VERSION}; refusing to run against a newer schema"
        )

    pending: Sequence[Migration] = tuple(
        m for m in MIGRATIONS if current < m.version <= ceiling
    )
    if not pending:
        return current

    for migration in pending:
        with connection:  # commits on success, rolls back on exception
            for statement in migration.statements:
                connection.execute(statement)
            # Interpolated because PRAGMA does not accept a bound parameter.
            # Safe: the value is an int from a frozen dataclass, never input.
            connection.execute(f"PRAGMA user_version = {int(migration.version)}")
        logger.info("applied migration %d (%s)", migration.version, migration.name)

    return applied_version(connection)


__all__ = [
    "CURRENT_VERSION",
    "MIGRATIONS",
    "Migration",
    "applied_version",
    "migrate",
]
