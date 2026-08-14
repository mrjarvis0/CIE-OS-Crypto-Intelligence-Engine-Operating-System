"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    schemas.address

Purpose:
    A chain address in one canonical form, so two references to the same
    account are the same key.

Design goals:
    - One stored form per address; case never decides identity on EVM
    - The form the user typed preserved for display
    - Chain carried with the address, since the same bytes mean different
      accounts on different chains
    - Validation refuses malformed input rather than normalising it into
      something plausible

Notes:
    EVM addresses are hex, and EIP-55 encodes a checksum in the *case* of that
    hex. So the same account legitimately appears as ``0xAbC...``, ``0xabc...``
    and ``0xABC...`` depending on who wrote it down. If the stored form
    preserves case, an equality join misses most of its matches, a balance
    aggregation splits one account into three, and a cluster analysis reports
    three participants where there is one. None of that raises an error --
    it just produces quietly wrong intelligence.

    Storage is therefore lowercase, always. The checksummed form is a
    presentation concern and is reconstructed on the way out.

    Chain is part of identity. The same twenty bytes are a different account on
    Ethereum and on BNB Chain, and contracts deployed by the same deployer at
    the same nonce genuinely collide across EVM chains. Keying on the address
    alone merges them.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any, Final

#: An EVM address: 20 bytes of hex with the 0x prefix.
_EVM_PATTERN: Final[re.Pattern[str]] = re.compile(r"^0x[0-9a-f]{40}$")

#: Length bounds for non-EVM addresses (base58 Solana, bech32/base58 Bitcoin).
#: Deliberately permissive: this layer establishes identity, not chain-specific
#: encoding rules, and rejecting a valid future format would drop real data.
_MIN_LENGTH: Final[int] = 16
_MAX_LENGTH: Final[int] = 128

#: The EVM zero address. Appears as the counterparty of every mint and burn, so
#: it is recognised rather than treated as an ordinary account.
ZERO_ADDRESS: Final[str] = "0x" + "0" * 40


class AddressError(ValueError):
    """Raised when a value cannot be a chain address."""


@dataclass(frozen=True, slots=True)
class Address:
    """
    A canonical address reference.

    ``value`` is the stored form and the join key. ``original`` keeps what the
    source supplied, so a checksummed address can be shown back to a user
    exactly as they would recognise it without that form ever reaching a
    comparison.
    """

    value: str
    chain: str
    original: str = ""

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise AddressError("address must name its chain")
        if not self.value:
            raise AddressError("address value cannot be empty")
        if not self.original:
            object.__setattr__(self, "original", self.value)

    # -- construction -----------------------------------------------------

    @classmethod
    def parse(cls, value: Any, chain: str) -> Address:
        """
        Build a canonical address, refusing anything malformed.

        Refusal matters more than it looks. A truncated address that is
        accepted becomes a real key in storage, and every query for the true
        account silently misses those rows.
        """
        if not isinstance(value, str):
            raise AddressError(f"address must be a string, got {type(value).__name__}")

        text = value.strip()
        if not text:
            raise AddressError("address is empty")

        if text.lower().startswith("0x"):
            lowered = text.lower()
            if not _EVM_PATTERN.match(lowered):
                raise AddressError(
                    f"{text!r} starts 0x but is not a 20-byte hex address"
                )
            return cls(value=lowered, chain=chain, original=text)

        # Non-EVM: no case folding. Base58 and bech32 are case-sensitive, and
        # lowercasing a Solana address produces a different, invalid account.
        if not (_MIN_LENGTH <= len(text) <= _MAX_LENGTH):
            raise AddressError(
                f"address length {len(text)} outside {_MIN_LENGTH}-{_MAX_LENGTH}"
            )
        if not text.isalnum():
            raise AddressError(f"{text!r} contains characters no address encoding uses")
        return cls(value=text, chain=chain, original=text)

    @classmethod
    def parse_optional(cls, value: Any, chain: str) -> Address | None:
        """
        Parse, or None when the field is genuinely absent.

        Contract-creation transactions have no ``to``. That is a real absence,
        not a malformed value, and it must stay distinguishable from one.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return cls.parse(value, chain)

    # -- properties -------------------------------------------------------

    @property
    def is_evm(self) -> bool:
        return bool(_EVM_PATTERN.match(self.value))

    @property
    def is_zero(self) -> bool:
        """The mint/burn counterparty, not an account anyone controls."""
        return self.value == ZERO_ADDRESS

    @property
    def key(self) -> str:
        """The storage key: chain-scoped, because addresses collide across chains."""
        return f"{self.chain}:{self.value}"

    def short(self) -> str:
        """Abbreviated form for display."""
        if len(self.value) <= 12:
            return self.value
        return f"{self.value[:6]}…{self.value[-4:]}"

    def as_dict(self) -> dict[str, Any]:
        return {"address": self.value, "chain": self.chain}

    def __str__(self) -> str:
        return self.value


__all__ = ["ZERO_ADDRESS", "Address", "AddressError"]
