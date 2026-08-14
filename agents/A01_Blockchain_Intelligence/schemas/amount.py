"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    schemas.amount

Purpose:
    Represent on-chain token quantities without losing precision, and store
    them in a form that still sorts and compares correctly in SQL.

Design goals:
    - Arbitrary precision; a 256-bit value survives a round trip intact
    - Sortable as text, because the database column cannot hold the integer
    - Decimals carried alongside, so a raw quantity is never shown as a price
    - Human rendering explicitly separate from the stored value
    - No floats anywhere in the path

Notes:
    This module exists because of a specific, silent corruption. EVM values are
    unsigned 256-bit integers denominated in wei. SQLite's INTEGER is a signed
    64-bit type, whose maximum is about 9.22e18 -- which is 9.22 *ether*. Any
    transfer above roughly nine ETH overflows the column. Postgres ``bigint``
    has the same ceiling, and ``numeric`` is unbounded but compares slowly and
    is easy to feed a float by accident.

    Nothing warns you when this happens. The write succeeds, the number comes
    back wrong, and a whale detector reading it concludes the transfer was
    small. A detector that misses the largest transfers on the chain because of
    a column type is worse than no detector.

    So the value is kept as a Python ``int`` -- arbitrary precision -- and
    persisted as a fixed-width, zero-padded decimal string. Zero padding is
    what preserves ordering: ``"10" < "9"`` lexicographically, but
    ``"0000000010" > "0000000009"``. Width is 78 digits, enough for
    ``2**256 - 1``.

    Floats are excluded entirely. A float64 carries 53 bits of mantissa, so it
    cannot represent even a modest wei value exactly, and a rounded balance
    that looks right is the hardest kind of error to notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

#: Digits needed for ``2**256 - 1`` (78 digits). Every stored amount is padded
#: to this width so lexicographic ordering matches numeric ordering.
AMOUNT_WIDTH: Final[int] = 78

#: Largest value an EVM uint256 can hold. Anything above it did not come from
#: the chain.
MAX_UINT256: Final[int] = 2**256 - 1

#: Decimals for the common denominations, so callers stop hardcoding 18.
WEI_DECIMALS: Final[int] = 18
SATOSHI_DECIMALS: Final[int] = 8
LAMPORT_DECIMALS: Final[int] = 9


class AmountError(ValueError):
    """Raised when a value cannot be a valid on-chain quantity."""


@dataclass(frozen=True, slots=True, order=True)
class Amount:
    """
    An exact on-chain quantity in its smallest unit.

    ``raw`` is the integer the chain actually stated -- wei, satoshi, lamports,
    or a token's own base unit. ``decimals`` records how many places to shift
    for display and is never applied to the stored value: converting at the
    boundary and storing the result would bake a token's metadata into the
    record, and that metadata can be wrong or can change.
    """

    raw: int
    decimals: int = WEI_DECIMALS

    def __post_init__(self) -> None:
        if isinstance(self.raw, bool) or not isinstance(self.raw, int):
            raise AmountError(f"amount must be an int, got {type(self.raw).__name__}")
        if self.raw < 0:
            raise AmountError("on-chain quantities cannot be negative")
        if self.raw > MAX_UINT256:
            raise AmountError(
                f"amount exceeds uint256 ({self.raw} > {MAX_UINT256}); "
                "the source is not reporting a chain quantity"
            )
        if self.decimals < 0 or self.decimals > 77:
            raise AmountError(f"decimals out of range: {self.decimals}")

    # -- construction -----------------------------------------------------

    @classmethod
    def zero(cls, decimals: int = WEI_DECIMALS) -> Amount:
        return cls(0, decimals)

    @classmethod
    def from_hex(cls, value: Any, decimals: int = WEI_DECIMALS) -> Amount:
        """
        Parse an RPC hex quantity.

        Refuses anything unreadable rather than defaulting to zero. A failed
        parse recorded as zero is a transfer of nothing, which reads as a fact
        the chain never stated.
        """
        if isinstance(value, bool):
            raise AmountError("boolean is not a quantity")
        if isinstance(value, int):
            return cls(value, decimals)
        if not isinstance(value, str) or not value.strip():
            raise AmountError(f"cannot read quantity from {value!r}")

        text = value.strip()
        try:
            return cls(int(text, 16) if text.lower().startswith("0x") else int(text, 10), decimals)
        except ValueError as exc:
            raise AmountError(f"cannot read quantity from {value!r}") from exc

    @classmethod
    def from_stored(cls, value: str, decimals: int = WEI_DECIMALS) -> Amount:
        """Rebuild from the padded form written by :meth:`stored`."""
        if not isinstance(value, str) or not value.strip():
            raise AmountError("stored amount is empty")
        try:
            return cls(int(value, 10), decimals)
        except ValueError as exc:
            raise AmountError(f"stored amount is not decimal: {value!r}") from exc

    # -- persistence ------------------------------------------------------

    def stored(self) -> str:
        """
        The database form: zero-padded decimal, fixed width.

        Padding is not cosmetic. Without it a text column orders ``"10"``
        before ``"9"``, so ``ORDER BY value DESC`` returns the wrong rows and
        every "largest transfer" query is silently wrong.
        """
        return f"{self.raw:0{AMOUNT_WIDTH}d}"

    # -- presentation -----------------------------------------------------

    def units(self) -> Decimal:
        """
        The value in whole units, exactly.

        ``Decimal``, not ``float``: a float cannot hold a wei value exactly, and
        a balance that is nearly right is harder to catch than one that is
        obviously wrong.
        """
        return Decimal(self.raw).scaleb(-self.decimals)

    def format(self, places: int = 6) -> str:
        """Human-readable rendering, for reports and CLI output only."""
        if places < 0:
            raise AmountError("places must be >= 0")
        quantum = Decimal(1).scaleb(-places)
        return f"{self.units().quantize(quantum)}"

    # -- arithmetic -------------------------------------------------------

    def __add__(self, other: Amount) -> Amount:
        self._require_same_scale(other)
        return Amount(self.raw + other.raw, self.decimals)

    def __sub__(self, other: Amount) -> Amount:
        self._require_same_scale(other)
        if other.raw > self.raw:
            raise AmountError("subtraction would produce a negative quantity")
        return Amount(self.raw - other.raw, self.decimals)

    def _require_same_scale(self, other: Amount) -> None:
        """
        Refuse to combine quantities of different denominations.

        Adding wei to satoshi produces a number with no meaning, and the result
        would look entirely ordinary in a report.
        """
        if not isinstance(other, Amount):
            raise AmountError(f"cannot combine Amount with {type(other).__name__}")
        if other.decimals != self.decimals:
            raise AmountError(
                f"cannot combine amounts with {self.decimals} and "
                f"{other.decimals} decimals"
            )

    # -- interop ----------------------------------------------------------

    def __bool__(self) -> bool:
        return self.raw != 0

    def as_dict(self) -> dict[str, Any]:
        return {"raw": str(self.raw), "decimals": self.decimals}

    def __str__(self) -> str:
        return f"{self.raw} (1e-{self.decimals})"


__all__ = [
    "AMOUNT_WIDTH",
    "LAMPORT_DECIMALS",
    "MAX_UINT256",
    "SATOSHI_DECIMALS",
    "WEI_DECIMALS",
    "Amount",
    "AmountError",
]
