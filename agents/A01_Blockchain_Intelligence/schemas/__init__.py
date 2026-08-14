"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    schemas

Purpose:
    The canonical shapes every chain's data is mapped into, and the value
    objects that keep quantities and identities exact.

Why this package is separate
----------------------------
Sensors return whatever a provider sent. Normalization decides what that means
in one shape. Everything above -- storage, skills, intelligence -- depends only
on this shape, so adding a chain does not touch a detector, and correcting a
provider quirk does not touch storage.

Three decisions here carry most of the weight, each preventing a failure that
would otherwise be silent:

* :class:`Amount` keeps quantities as arbitrary-precision integers and stores
  them zero-padded. A 64-bit column overflows above ~9.22 ETH in wei and a
  float cannot hold wei exactly; both corrupt the largest transfers on the
  chain, which are the ones that matter most.
* :class:`Address` stores one case-folded form per EVM address, because EIP-55
  encodes a checksum in case and a case-sensitive key splits one account into
  several across joins and aggregations.
* :class:`CanonicalBlock` records withdrawal as a flag rather than a delete, so
  a reorg leaves evidence instead of a hole -- and reads must opt in to seeing
  abandoned history.
"""

from __future__ import annotations

from .address import ZERO_ADDRESS, Address, AddressError
from .amount import (
    AMOUNT_WIDTH,
    LAMPORT_DECIMALS,
    MAX_UINT256,
    SATOSHI_DECIMALS,
    WEI_DECIMALS,
    Amount,
    AmountError,
)
from .block import CanonicalBlock, CanonicalTransaction, from_unix, utc_now
from .token import CanonicalNftTransfer, CanonicalTokenTransfer, TokenActivity

__all__ = [
    "AMOUNT_WIDTH",
    "LAMPORT_DECIMALS",
    "MAX_UINT256",
    "SATOSHI_DECIMALS",
    "WEI_DECIMALS",
    "ZERO_ADDRESS",
    "Address",
    "AddressError",
    "Amount",
    "AmountError",
    "CanonicalBlock",
    "CanonicalNftTransfer",
    "CanonicalTokenTransfer",
    "CanonicalTransaction",
    "TokenActivity",
    "from_unix",
    "utc_now",
]
