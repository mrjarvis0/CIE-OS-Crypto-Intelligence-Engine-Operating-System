"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    tiers.ledger

Purpose:
    Tier L. Reference data that outlives every retention sweep: which address
    belongs to whom, who says so, and how much that assertion is worth.

Design goals:
    - Every label carries its source; a label without one is not storable
    - Never inferred from behaviour -- the type has nowhere to put a guess
    - Reloading a list corrects it rather than duplicating it
    - One in-memory set for the capture hot path; no query per transaction
    - No network I/O

Notes:
    A label is an **external assertion**, which is why it lives here rather than
    in ``entities``. An entity row is A01's own observation of an address; a
    label is somebody else's claim about it, with its own provenance and its own
    staleness. Merging them would make an unsourced guess indistinguishable from
    a sourced fact, and the whole reason exchange flow is trustworthy at all is
    that the difference is visible.

    ``source`` is required and enforced in ``__post_init__`` rather than
    documented. ``identity/design_rules.md`` forbids labelling an address from
    behaviour, and the cheapest way to keep that rule is to make an unsourced
    label unconstructable: there is no path from "this address moves like an
    exchange" to a row in this table.

    **Confidence is not a measurement.** It is a policy number attached to a
    verification status, and :data:`CONFIDENCE` states the reasoning for each
    value. A community-maintained list that is large and well-formed is evidence
    of care, not of correctness, so it loads at 0.5 -- usable as a signal,
    never as proof. Nothing here derives a confidence from the data.

    **The ``evm`` chain scope.** One EVM address is the same account on every
    EVM chain, so a per-chain copy of a 2,858-row exchange list would be nine
    copies that drift apart. Labels may therefore be stored against the family
    sentinel :data:`EVM_SCOPE` instead of a chain, and a lookup for an EVM chain
    reads that scope as well as the chain's own rows. A lookup for a non-EVM
    chain never reads it: a Solana address and an EVM address are different
    encodings, and matching one list against the other would attach a Binance
    label to whatever happened to collide.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Iterable, Iterator, Mapping, Sequence

from database.connection import Database

from .retention import Tier

logger = logging.getLogger(__name__)

#: Chain value meaning "every EVM chain". See the module note.
EVM_SCOPE: Final[str] = "evm"

#: The categories a label may carry, matching the schema's own comment.
#:
#: A closed set on purpose. An open one lets ``exchange`` and ``Exchange`` and
#: ``cex`` accumulate into three vocabularies for one idea, and the gate that
#: reads them would silently match a third of the rows it should.
CATEGORIES: Final[frozenset[str]] = frozenset({
    "exchange",
    "bridge",
    "contract",
    "token",
    "mixer",
    "treasury",
    "smart_money",
    "mining_pool",
    "market_maker",
})

#: Verification statuses, weakest first.
UNVERIFIED: Final[str] = "unverified"
CORROBORATED: Final[str] = "corroborated"
VERIFIED: Final[str] = "verified"

#: What a status is worth, and why. Policy, not measurement.
#:
#: ``unverified`` at 0.5 is the load-bearing one: it is what a community address
#: list gets, and it is deliberately below the point where a conclusion could
#: rest on the label alone.
CONFIDENCE: Final[Mapping[str, float]] = {
    # Somebody published it and nothing independent has checked it.
    UNVERIFIED: 0.5,
    # Two independent sources agree on the same address.
    CORROBORATED: 0.75,
    # The operator of the address published it, or an on-chain proof exists.
    VERIFIED: 0.95,
}


def _iso(value: datetime) -> str:
    return value.isoformat()


def _now() -> datetime:
    return datetime.now(UTC)


def _is_evm_chain(chain: str) -> bool:
    """
    Whether a chain name is an EVM chain, per the configured catalog.

    An unknown name reads as non-EVM. The consequence is narrow and safe: the
    family-scoped rows are not consulted, so a lookup returns fewer labels
    rather than the wrong ones.
    """
    if chain == EVM_SCOPE:
        return True
    try:
        from config.rpc.chains import ChainType, get_chain

        return get_chain(chain).chain_type is ChainType.EVM
    except Exception:  # noqa: BLE001 - an unrecognised chain is not an error here
        return False


def chain_scope(chain: str) -> tuple[str, ...]:
    """
    The chain values a lookup for ``chain`` should read.

    ``(chain, "evm")`` for an EVM chain, ``(chain,)`` otherwise.
    """
    if chain == EVM_SCOPE:
        return (EVM_SCOPE,)
    return (chain, EVM_SCOPE) if _is_evm_chain(chain) else (chain,)


@dataclass(frozen=True, slots=True)
class Label:
    """
    One external assertion about one address.

    ``label`` is what this address is called ("Binance 14"); ``entity`` is who
    operates it ("Binance"). Both come from the source. Nothing here derives one
    from the other -- stripping a trailing number works for Binance and invents
    an operator for half the rows of any real list.
    """

    chain: str
    address: str
    label: str
    category: str
    source: str
    confidence: float = CONFIDENCE[UNVERIFIED]
    entity: str = ""
    verification_status: str = UNVERIFIED
    first_seen: datetime | None = None
    last_verified: datetime | None = None

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("a label must name its chain scope")
        if not self.address.strip():
            raise ValueError("a label must name an address")
        if not self.source.strip():
            # The rule, enforced rather than documented: there is no way to
            # construct a label that does not say where it came from.
            raise ValueError(
                f"label for {self.address} has no source; a label with no "
                "source is a guess, and guesses are not storable"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.category not in CATEGORIES:
            raise ValueError(
                f"unknown label category {self.category!r}; "
                f"known: {', '.join(sorted(CATEGORIES))}"
            )

    @property
    def key(self) -> str:
        """
        ``chain:address:source``.

        The source is part of the identity so two sources labelling the same
        address are two rows, not one overwriting the other. Disagreement
        between them is a fact worth keeping -- and corroboration is only
        visible if both assertions survive.
        """
        return f"{self.chain}:{self.address}:{self.source}"

    @property
    def name(self) -> str:
        """The operator where one is known, otherwise the label itself."""
        return self.entity or self.label

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "address": self.address,
            "label": self.label,
            "entity": self.entity,
            "category": self.category,
            "source": self.source,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
        }


@dataclass(frozen=True, slots=True)
class LabelEntry:
    """What the hot path needs to know about one labelled address."""

    entity: str
    category: str
    source: str
    confidence: float


@dataclass(frozen=True, slots=True)
class LabelSet:
    """
    Labels for one chain, resolved once and held in memory.

    The materiality gate asks "is this address labelled" of **every**
    transaction of every block. At 5,000 transactions per block that is 10,000
    questions, and a database round trip per question would put a query between
    every transaction and its verdict. So the set is loaded once per run and
    consulted as a dict.

    Empty is a real state and callers must check for it. A gate handed an empty
    set reports its labelled-address rule as available while it can never fire,
    which is exactly the reassuring lie ``MaterialityGate.limitation`` exists to
    prevent.
    """

    chain: str
    entries: Mapping[str, LabelEntry]
    #: Category the set was filtered to, or empty for all of them.
    category: str = ""

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __contains__(self, address: object) -> bool:
        return isinstance(address, str) and self._key(address) in self.entries

    def __iter__(self) -> Iterator[str]:
        return iter(self.entries)

    def is_labelled(self, address: str) -> bool:
        """The callable :class:`~pipeline.materiality.MaterialityGate` takes."""
        return self._key(address) in self.entries

    def get(self, address: str) -> LabelEntry | None:
        return self.entries.get(self._key(address))

    def entity_of(self, address: str) -> str | None:
        """
        Who operates this address, or None when it is unlabelled.

        Falls back to the address's own label when the source named no
        operator, so a flow aggregate never groups rows under an empty name.
        """
        entry = self.entries.get(self._key(address))
        return entry.entity if entry else None

    def entities(self) -> tuple[str, ...]:
        return tuple(sorted({entry.entity for entry in self.entries.values()}))

    @staticmethod
    def _key(address: str) -> str:
        """
        EVM addresses are case-insensitive; other encodings are not.

        Lowercasing a Solana address produces a different, invalid account, so
        the fold applies only to the ``0x`` form -- which is the same rule
        :class:`schemas.address.Address` follows on the way in.
        """
        return address.lower() if address[:2].lower() == "0x" else address

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "category": self.category or "all",
            "addresses": len(self.entries),
            "entities": len(self.entities()),
        }


class LabelRepository:
    """
    Reads and writes Tier L labels.

    Writes are upserts keyed on ``chain:address:source``: re-running a load of
    the same list is free, and a list that has been corrected upstream corrects
    the rows here. ``first_seen`` survives the update because it records when
    A01 first learned the address, which a re-read does not change.
    """

    tier = Tier.LEDGER

    def __init__(self, database: Database) -> None:
        self._db = database

    @property
    def database(self) -> Database:
        return self._db

    # -- writing ----------------------------------------------------------

    def save(self, label: Label) -> bool:
        """Store one label. Returns True when the row is new."""
        with self._db.transaction() as connection:
            return self._save(connection, label, _now())

    def save_many(self, labels: Sequence[Label]) -> tuple[int, int]:
        """
        Store a batch in one transaction. Returns ``(inserted, updated)``.

        One transaction for the batch rather than one per row: a 2,858-address
        list is a single load, and committing each row separately turns it into
        2,858 fsyncs for no atomicity anyone wants.
        """
        observed = _now()
        inserted = 0
        with self._db.transaction() as connection:
            for label in labels:
                if self._save(connection, label, observed):
                    inserted += 1
        return inserted, len(labels) - inserted

    @staticmethod
    def _save(connection: Any, label: Label, observed: datetime) -> bool:
        first_seen = label.first_seen or observed
        verified = label.last_verified or observed

        # Read before write, because SQLite reports rowcount 1 for both branches
        # of an upsert and the caller's report depends on the difference: "2,858
        # loaded, 0 new" is how an operator sees that a re-run changed nothing.
        # One indexed primary-key lookup per row, inside a transaction that is
        # already open.
        existed = connection.execute(
            "SELECT 1 FROM labels WHERE key = ?", (label.key,)
        ).fetchone() is not None

        connection.execute(
            """
            INSERT INTO labels (
                key, chain, address, label, entity, category, source,
                confidence, first_seen, last_verified, verification_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                label               = excluded.label,
                entity              = excluded.entity,
                category            = excluded.category,
                confidence          = excluded.confidence,
                last_verified       = excluded.last_verified,
                verification_status = excluded.verification_status
            """,
            (
                label.key,
                label.chain,
                label.address,
                label.label,
                label.entity,
                label.category,
                label.source,
                label.confidence,
                _iso(first_seen),
                _iso(verified),
                label.verification_status,
            ),
        )
        return not existed

    def forget_source(self, source: str) -> int:
        """
        Remove every label from one source. Returns rows deleted.

        The only deletion this tier allows, and it is scoped to a source for a
        reason: a list that turns out to be wrong has to be retractable in
        full, and retracting it by address would leave the ones nobody checked.
        """
        with self._db.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM labels WHERE source = ?", (source,)
            )
            return cursor.rowcount

    # -- reading ----------------------------------------------------------

    def label_set(self, chain: str, *, category: str = "") -> LabelSet:
        """
        Every label that applies to ``chain``, as one in-memory set.

        Where two sources label the same address, the more confident assertion
        wins the entry. That is a display choice, not a merge: both rows remain
        stored, and disagreement stays inspectable through :meth:`lookup`.
        """
        scope = chain_scope(chain)
        sql = [
            """
            SELECT address, label, entity, category, source, confidence
              FROM labels
             WHERE chain IN ({placeholders})
            """.format(placeholders=", ".join("?" * len(scope)))
        ]
        params: list[Any] = list(scope)
        if category:
            sql.append(" AND category = ?")
            params.append(category)
        sql.append(" ORDER BY confidence ASC")

        entries: dict[str, LabelEntry] = {}
        for row in self._db.connection.execute("".join(sql), params):
            entries[row["address"]] = LabelEntry(
                entity=row["entity"] or row["label"],
                category=row["category"],
                source=row["source"],
                confidence=float(row["confidence"]),
            )

        return LabelSet(chain=chain, entries=entries, category=category)

    def lookup(self, chain: str, address: str) -> tuple[Label, ...]:
        """Every assertion about one address, most confident first."""
        scope = chain_scope(chain)
        rows = self._db.connection.execute(
            """
            SELECT * FROM labels
             WHERE chain IN ({placeholders}) AND address = ?
             ORDER BY confidence DESC
            """.format(placeholders=", ".join("?" * len(scope))),
            (*scope, address.lower() if address[:2].lower() == "0x" else address),
        )
        return tuple(self._hydrate(row) for row in rows)

    def count(self, *, chain: str = "", category: str = "", source: str = "") -> int:
        sql = ["SELECT COUNT(*) AS n FROM labels WHERE 1 = 1"]
        params: list[Any] = []
        if chain:
            scope = chain_scope(chain)
            sql.append(" AND chain IN ({})".format(", ".join("?" * len(scope))))
            params.extend(scope)
        if category:
            sql.append(" AND category = ?")
            params.append(category)
        if source:
            sql.append(" AND source = ?")
            params.append(source)

        row = self._db.connection.execute("".join(sql), params).fetchone()
        return int(row["n"]) if row else 0

    def sources(self) -> tuple[dict[str, Any], ...]:
        """What has been loaded, per source, for `cli labels`."""
        rows = self._db.connection.execute(
            """
            SELECT source,
                   COUNT(*)            AS rows,
                   COUNT(DISTINCT entity) AS entities,
                   MIN(confidence)     AS confidence,
                   MAX(last_verified)  AS last_verified,
                   verification_status AS status
              FROM labels
             GROUP BY source, verification_status
             ORDER BY rows DESC
            """
        )
        return tuple(
            {
                "source": row["source"],
                "rows": int(row["rows"]),
                "entities": int(row["entities"]),
                "confidence": float(row["confidence"]),
                "verification_status": row["status"],
                "last_verified": row["last_verified"],
            }
            for row in rows
        )

    def categories(self) -> dict[str, int]:
        rows = self._db.connection.execute(
            "SELECT category, COUNT(*) AS n FROM labels GROUP BY category ORDER BY n DESC"
        )
        return {row["category"]: int(row["n"]) for row in rows}

    def entities(self, *, chain: str = "", category: str = "", limit: int = 25) -> tuple[dict[str, Any], ...]:
        """The operators with the most labelled addresses."""
        sql = [
            """
            SELECT COALESCE(NULLIF(entity, ''), label) AS name,
                   COUNT(*) AS addresses
              FROM labels
             WHERE 1 = 1
            """
        ]
        params: list[Any] = []
        if chain:
            scope = chain_scope(chain)
            sql.append(" AND chain IN ({})".format(", ".join("?" * len(scope))))
            params.extend(scope)
        if category:
            sql.append(" AND category = ?")
            params.append(category)
        sql.append(" GROUP BY name ORDER BY addresses DESC, name ASC LIMIT ?")
        params.append(limit)

        rows = self._db.connection.execute("".join(sql), params)
        return tuple(
            {"entity": row["name"], "addresses": int(row["addresses"])} for row in rows
        )

    def summary(self) -> dict[str, Any]:
        """Everything `cli labels` and `cli doctor` need, in one read."""
        return {
            "total": self.count(),
            "categories": self.categories(),
            "sources": list(self.sources()),
        }

    @staticmethod
    def _hydrate(row: Any) -> Label:
        return Label(
            chain=row["chain"],
            address=row["address"],
            label=row["label"],
            entity=row["entity"],
            category=row["category"],
            source=row["source"],
            confidence=float(row["confidence"]),
            verification_status=row["verification_status"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_verified=datetime.fromisoformat(row["last_verified"]),
        )

    def __repr__(self) -> str:
        return f"LabelRepository(labels={self.count()})"


def label_set_from(labels: Iterable[Label], chain: str) -> LabelSet:
    """An in-memory set built without storage. The seam for tests and dry runs."""
    entries = {
        label.address: LabelEntry(
            entity=label.name,
            category=label.category,
            source=label.source,
            confidence=label.confidence,
        )
        for label in labels
    }
    return LabelSet(chain=chain, entries=entries)


__all__ = [
    "CATEGORIES",
    "CONFIDENCE",
    "CORROBORATED",
    "EVM_SCOPE",
    "UNVERIFIED",
    "VERIFIED",
    "Label",
    "LabelEntry",
    "LabelRepository",
    "LabelSet",
    "chain_scope",
    "label_set_from",
]
