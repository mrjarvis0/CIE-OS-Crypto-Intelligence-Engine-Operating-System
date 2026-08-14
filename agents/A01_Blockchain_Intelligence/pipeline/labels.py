"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.labels

Purpose:
    Read an address list off disk and turn it into Tier L labels, without
    losing a row silently and without inventing a fact the file did not state.

Design goals:
    - Take the file's shape as it is; a hand-converted list loses addresses
    - Every rejected row counted and the first few reported with line numbers
    - Provenance supplied by the operator, never guessed from the filename
    - Reloading the same file is free and corrects what changed
    - Pure file I/O; no network, and no lookup of the addresses being loaded

Notes:
    Labels arrive as a **file**, not an API, and that is a design decision
    rather than a limitation. The gate that consumes them asks "is this address
    labelled" of every transaction in every block; an API call on that path
    would burn a rate limit in seconds. Labels also barely move -- an exchange's
    hot wallet does not change daily -- so the freshness an API buys is
    freshness nothing needs.

    **Shape tolerance is deliberate.** Real address lists are a CSV with three
    columns nobody agreed on, a JSON dump, or a text file of addresses. Asking
    an operator to reformat one first is asking for a manual conversion, and a
    manual conversion drops rows quietly. So the column names are matched
    against aliases, the detected mapping is reported back, and anything
    unreadable is counted and shown rather than skipped.

    **Nothing is inferred.** ``category``, ``source`` and ``confidence`` come
    from the caller or from a column that states them. A category guessed from a
    filename would attach a claim nobody made to 2,858 addresses at once, and it
    would be invisible afterwards -- the rows would look exactly like sourced
    ones. The load report names what was applied and where it came from, so an
    operator can see that the file itself said nothing about it.
"""

from __future__ import annotations

import csv
import json
import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

from schemas.address import Address, AddressError
from tiers.ledger import (
    CATEGORIES,
    CONFIDENCE,
    EVM_SCOPE,
    UNVERIFIED,
    Label,
    LabelRepository,
    chain_scope,
)

logger = logging.getLogger(__name__)

#: File suffixes a label directory may hold. `.md` is excluded on purpose:
#: `SOURCE.md` sits beside the data and describes it, and parsing prose into
#: labels would turn a provenance note into rows.
SUFFIXES: Final[frozenset[str]] = frozenset({".csv", ".tsv", ".json", ".txt"})

#: Column aliases, in priority order. Matched case-insensitively against the
#: header after stripping spaces and underscores.
ADDRESS_COLUMNS: Final[tuple[str, ...]] = ("address", "addr", "wallet", "account")
ENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "entity", "cexname", "exchange", "owner", "operator", "organisation",
    "organization", "org", "name",
)
LABEL_COLUMNS: Final[tuple[str, ...]] = (
    "label", "distinctname", "tag", "nametag", "note", "description",
)
CATEGORY_COLUMNS: Final[tuple[str, ...]] = ("category", "type", "kind")
CHAIN_COLUMNS: Final[tuple[str, ...]] = ("chain", "network", "blockchain")

#: Rejected rows kept in full. The count is always exact; this bounds only how
#: many are quoted back, because a broken file produces thousands of identical
#: complaints and the first few are the ones that identify it.
REJECTION_DETAIL: Final[int] = 10


class LabelFileError(ValueError):
    """Raised when a file cannot be read as an address list at all."""


@dataclass(frozen=True, slots=True)
class Rejected:
    """One row that did not become a label, and why."""

    line: int
    value: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"line": self.line, "value": self.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ParseResult:
    """What one file yielded, before anything was stored."""

    labels: tuple[Label, ...] = ()
    rejected: tuple[Rejected, ...] = ()
    rejected_count: int = 0
    duplicates: int = 0
    rows_read: int = 0
    #: Which column each field was read from, so a misdetected header is
    #: visible instead of producing 2,858 labels named after a chain id.
    columns: dict[str, str] = field(default_factory=dict)

    @property
    def accepted(self) -> int:
        return len(self.labels)


@dataclass(frozen=True, slots=True)
class LoadReport:
    """What one file did to the ledger."""

    path: str
    source: str
    chain: str
    category: str
    confidence: float
    verification_status: str
    rows_read: int = 0
    accepted: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    rejected_count: int = 0
    rejected: tuple[Rejected, ...] = ()
    columns: dict[str, str] = field(default_factory=dict)
    #: True when the file named no category and the caller's default was used.
    category_supplied_by_caller: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source": self.source,
            "chain": self.chain,
            "category": self.category,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "rows_read": self.rows_read,
            "accepted": self.accepted,
            "inserted": self.inserted,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "rejected": self.rejected_count,
            "rejected_detail": [r.as_dict() for r in self.rejected],
            "columns": dict(self.columns),
            "category_from": "caller" if self.category_supplied_by_caller else "file",
        }


# ==============================================================================
# DISCOVERY
# ==============================================================================


def discover(path: str | Path) -> tuple[Path, ...]:
    """
    Label files under a path. A file resolves to itself; a directory is scanned.

    Sorted, so a load of the same directory processes files in the same order
    twice -- which matters only because the report should be comparable.
    """
    target = Path(path)
    if target.is_file():
        return (target,)
    if not target.is_dir():
        raise LabelFileError(f"no label file or directory at {target}")
    return tuple(
        sorted(
            child
            for child in target.iterdir()
            if child.is_file() and child.suffix.lower() in SUFFIXES
        )
    )


# ==============================================================================
# PARSING
# ==============================================================================


def _normalise(name: str) -> str:
    return name.strip().lower().replace("_", "").replace("-", "").replace(" ", "")


#: Fields, in the order they claim a column. One column feeds one field: a
#: header where two fields both match is a header where one of them is wrong,
#: and letting both read it copies the same value into two meanings.
FIELDS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("address", ADDRESS_COLUMNS),
    ("entity", ENTITY_COLUMNS),
    ("label", LABEL_COLUMNS),
    ("category", CATEGORY_COLUMNS),
    ("chain", CHAIN_COLUMNS),
)

#: Shortest alias allowed to match as a substring. Real headers say "Wallet
#: Address" and "Token Name", so exact matching alone rejects usable files --
#: but a three-letter alias inside a longer word matches by accident.
MIN_PARTIAL: Final[int] = 4


def _map_columns(names: Sequence[str]) -> dict[str, int]:
    """
    Which column feeds which field.

    Exact matches are resolved for every field **before** any partial one, and
    that ordering is load-bearing. A header of ``address,distinct_name`` has
    ``name`` inside ``distinct_name``: matching field by field would let
    ``entity`` take it on a substring before ``label`` could take it exactly,
    and every address in the file would be attributed to an operator called
    "Binance 14".
    """
    normalised = [_normalise(name) for name in names]
    indexes: dict[str, int] = {}
    claimed: set[int] = set()

    for exact in (True, False):
        for field_name, aliases in FIELDS:
            if field_name in indexes:
                continue
            for alias in aliases:
                if not exact and len(alias) < MIN_PARTIAL:
                    continue
                for index, column in enumerate(normalised):
                    if index in claimed:
                        continue
                    if column == alias if exact else alias in column:
                        indexes[field_name] = index
                        claimed.add(index)
                        break
                if field_name in indexes:
                    break

    return indexes


def _looks_like_address(value: str) -> bool:
    try:
        Address.parse(value, "evm")
        return True
    except AddressError:
        return False


def _read_rows(path: Path) -> tuple[list[list[str]], list[str] | None]:
    """
    A file as rows plus its header, if it has one.

    Header detection is by content, not by convention: if the first row's first
    cell is itself an address, the file has no header and treating it as one
    would drop a real address on every load.
    """
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = [
        row
        for row in csv.reader(text.splitlines(), delimiter=delimiter)
        if row and any(cell.strip() for cell in row)
    ]
    if not rows:
        return [], None

    if any(_looks_like_address(cell) for cell in rows[0]):
        return rows, None
    return rows[1:], rows[0]


def parse_file(
    path: str | Path,
    *,
    chain: str = EVM_SCOPE,
    category: str = "exchange",
    source: str = "",
    confidence: float | None = None,
    verification_status: str = UNVERIFIED,
) -> ParseResult:
    """
    Read one file into labels, counting everything it could not read.

    ``source`` defaults to ``file:<name>``, which is true and weak: it records
    where A01 got the list, not who published it. A caller that knows the
    upstream origin should pass it -- the difference is whether a later reader
    can check the claim.
    """
    target = Path(path)
    if category not in CATEGORIES:
        raise LabelFileError(
            f"unknown category {category!r}; known: {', '.join(sorted(CATEGORIES))}"
        )

    origin = source or f"file:{target.name}"
    weight = CONFIDENCE.get(verification_status, CONFIDENCE[UNVERIFIED])
    if confidence is not None:
        weight = confidence

    if target.suffix.lower() == ".json":
        raw, columns = _rows_from_json(target)
    elif target.suffix.lower() == ".txt":
        raw, columns = _rows_from_text(target)
    else:
        raw, columns = _rows_from_table(target)

    labels: list[Label] = []
    rejected: list[Rejected] = []
    rejected_count = 0
    duplicates = 0
    seen: set[str] = set()

    for line, record in raw:
        value = record.get("address", "")
        row_chain = record.get("chain") or chain
        try:
            address = Address.parse(value, row_chain)
        except AddressError as exc:
            rejected_count += 1
            if len(rejected) < REJECTION_DETAIL:
                rejected.append(Rejected(line=line, value=value[:80], reason=str(exc)))
            continue

        # An address stored under an EVM scope that is not EVM-shaped can never
        # match anything, so it would be a row that looks loaded and is inert.
        if _is_evm_scope(row_chain) and not address.is_evm:
            rejected_count += 1
            if len(rejected) < REJECTION_DETAIL:
                rejected.append(
                    Rejected(
                        line=line,
                        value=value[:80],
                        reason="not an EVM address, and the chain scope is EVM",
                    )
                )
            continue

        if address.value in seen:
            duplicates += 1
            continue
        seen.add(address.value)

        entity = record.get("entity", "").strip()
        name = record.get("label", "").strip() or entity
        row_category = (record.get("category") or category).strip().lower()
        if row_category not in CATEGORIES:
            rejected_count += 1
            if len(rejected) < REJECTION_DETAIL:
                rejected.append(
                    Rejected(
                        line=line,
                        value=row_category[:80],
                        reason="unknown category in the file",
                    )
                )
            continue

        labels.append(
            Label(
                chain=row_chain,
                address=address.value,
                label=name or address.short(),
                entity=entity or name,
                category=row_category,
                source=origin,
                confidence=weight,
                verification_status=verification_status,
                first_seen=datetime.now(UTC),
            )
        )

    return ParseResult(
        labels=tuple(labels),
        rejected=tuple(rejected),
        rejected_count=rejected_count,
        duplicates=duplicates,
        rows_read=len(raw),
        columns=columns,
    )


def _is_evm_scope(chain: str) -> bool:
    return EVM_SCOPE in chain_scope(chain)


def _rows_from_table(path: Path) -> tuple[list[tuple[int, dict[str, str]]], dict[str, str]]:
    """CSV or TSV, header optional."""
    rows, header = _read_rows(path)
    if not rows:
        return [], {}

    if header is None:
        # Positional, and only the first two positions are claimed: column three
        # of an unlabelled file could be anything, and guessing would attach it
        # to a field.
        columns = {"address": "column 1", "entity": "column 2"}
        indexes = {"address": 0, "entity": 1}
        offset = 1
    else:
        indexes = _map_columns(header)
        columns = {name: header[index].strip() for name, index in indexes.items()}
        offset = 2

        if "address" not in indexes:
            raise LabelFileError(
                f"{path.name} has a header with no address column; "
                f"looked for {', '.join(ADDRESS_COLUMNS)}, found "
                f"{', '.join(header) or '(nothing)'}"
            )

    out: list[tuple[int, dict[str, str]]] = []
    for number, row in enumerate(rows, start=offset):
        record = {
            name: (row[index].strip() if index < len(row) else "")
            for name, index in indexes.items()
        }
        out.append((number, record))
    return out, columns


def _rows_from_json(path: Path) -> tuple[list[tuple[int, dict[str, str]]], dict[str, str]]:
    """
    A JSON list of objects, a list of addresses, or an ``{address: name}`` map.

    Line numbers are element indexes here. A JSON file has lines, but the
    element index is what a reader can act on.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise LabelFileError(f"{path.name} is not valid JSON: {exc}") from exc

    out: list[tuple[int, dict[str, str]]] = []
    columns: dict[str, str] = {}

    if isinstance(payload, dict):
        columns = {"address": "object key", "entity": "object value"}
        for index, (address, name) in enumerate(payload.items(), start=1):
            out.append((index, {"address": str(address), "entity": str(name)}))
        return out, columns

    if not isinstance(payload, list):
        raise LabelFileError(
            f"{path.name} holds a {type(payload).__name__}; expected a list or an object"
        )

    for index, item in enumerate(payload, start=1):
        if isinstance(item, str):
            out.append((index, {"address": item}))
            columns.setdefault("address", "list element")
            continue
        if not isinstance(item, dict):
            continue
        keys = list(item)
        record: dict[str, str] = {}
        for field_name, position in _map_columns(keys).items():
            record[field_name] = str(item[keys[position]] or "")
            columns.setdefault(field_name, keys[position])
        out.append((index, record))

    return out, columns


def _rows_from_text(path: Path) -> tuple[list[tuple[int, dict[str, str]]], dict[str, str]]:
    """One address per line, with anything after it taken as the name."""
    out: list[tuple[int, dict[str, str]]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace("\t", " ").replace(",", " ").split(None, 1)
        out.append(
            (
                number,
                {
                    "address": parts[0],
                    "entity": parts[1].strip() if len(parts) > 1 else "",
                },
            )
        )
    return out, {"address": "first token", "entity": "rest of line"}


# ==============================================================================
# LOADING
# ==============================================================================


def load_file(
    path: str | Path,
    repository: LabelRepository,
    *,
    chain: str = EVM_SCOPE,
    category: str = "exchange",
    source: str = "",
    confidence: float | None = None,
    verification_status: str = UNVERIFIED,
) -> LoadReport:
    """Parse one file and store what it yielded."""
    target = Path(path)
    parsed = parse_file(
        target,
        chain=chain,
        category=category,
        source=source,
        confidence=confidence,
        verification_status=verification_status,
    )

    inserted, updated = repository.save_many(parsed.labels)
    weight = CONFIDENCE.get(verification_status, CONFIDENCE[UNVERIFIED])

    return LoadReport(
        path=str(target),
        source=source or f"file:{target.name}",
        chain=chain,
        category=category,
        confidence=confidence if confidence is not None else weight,
        verification_status=verification_status,
        rows_read=parsed.rows_read,
        accepted=parsed.accepted,
        inserted=inserted,
        updated=updated,
        duplicates=parsed.duplicates,
        rejected_count=parsed.rejected_count,
        rejected=parsed.rejected,
        columns=parsed.columns,
        category_supplied_by_caller="category" not in parsed.columns,
    )


def load(
    path: str | Path,
    repository: LabelRepository,
    *,
    chain: str = EVM_SCOPE,
    category: str = "exchange",
    source: str = "",
    confidence: float | None = None,
    verification_status: str = UNVERIFIED,
) -> tuple[LoadReport, ...]:
    """
    Load a file, or every label file in a directory.

    One report per file rather than a merged total: a directory holding a good
    list and a broken one should not average into "mostly fine".
    """
    return tuple(
        load_file(
            found,
            repository,
            chain=chain,
            category=category,
            source=source,
            confidence=confidence,
            verification_status=verification_status,
        )
        for found in discover(path)
    )


def describe(reports: Iterable[LoadReport]) -> str:
    """One operator-facing block summarising a load."""
    lines: list[str] = []
    for report in reports:
        lines.append(
            f"{Path(report.path).name}: {report.accepted} label(s) "
            f"({report.inserted} new, {report.updated} updated), "
            f"{report.duplicates} duplicate(s), {report.rejected_count} rejected"
        )
        for rejection in report.rejected:
            lines.append(f"    line {rejection.line}: {rejection.reason}")
    return "\n".join(lines)


__all__ = [
    "REJECTION_DETAIL",
    "SUFFIXES",
    "LabelFileError",
    "LoadReport",
    "ParseResult",
    "Rejected",
    "describe",
    "discover",
    "load",
    "load_file",
    "parse_file",
]
