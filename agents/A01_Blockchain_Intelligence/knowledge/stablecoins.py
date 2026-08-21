"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    knowledge.stablecoins

Purpose:
    The curated stablecoin reference: which contract at which address is a
    stablecoin, what it is called, and the exponent that turns its raw transfer
    amount into a face quantity.

The problem this closes
-----------------------
A stored ERC-20 ``Transfer`` carries its amount as a raw integer in the token's
own base unit, and ``contracts.events`` refuses to resolve the exponent -- the
``decimals()`` call lives on-chain and this system does not make it during
capture. So ``token_transfers`` holds ``140261088`` with ``decimals_known = 0``,
and that integer is $140.26 of USDC (6 decimals) or a rounding error of an
18-decimal token, with nothing on the row to say which.

For an arbitrary token that ambiguity is unresolvable without a network call.
For the handful of stablecoins that carry the overwhelming majority of dollar
flow, it is answerable from a list -- their addresses and decimals are fixed at
deployment and do not change. This is that list: enough to normalise stablecoin
movement into a comparable face figure without an ``eth_call``, and honest about
being a list rather than an oracle.

What a normalised figure is, and is not
---------------------------------------
``normalize()`` divides a raw amount by ``10 ** decimals``, giving the token's
face quantity. For a coin trading at its peg that face quantity is its dollar
value, and because every entry here targets the same peg, two normalised
amounts **are** comparable and summable -- which raw base units never are.

It is a *face* value, not a market value. A stablecoin that has de-pegged still
normalises to its face quantity; this module reads no price and makes no claim
that the peg is holding. A caller that sums normalised stablecoin flow is
measuring dollars *at par*, and must say so.

Why the decimals are not all six
--------------------------------
USDC and USDT are six-decimal tokens on every chain here **except BNB Chain**,
where both are deployed as eighteen-decimal tokens. Assuming six there would
overstate every BNB-chain stablecoin transfer by a factor of a trillion, which
is exactly the class of error this module exists to prevent -- so the exponent
travels per ``(chain, address)``, never per symbol.

Sourcing
--------
Addresses and decimals are the canonical mainnet deployments, cross-checked
against ``contracts.decimals.WELL_KNOWN``. Chain keys are the registry's own
slugs (:class:`config.rpc.chains.ChainName`) -- ``bnb_chain``, not ``bnb`` or
``bsc`` -- so a lookup keyed on ``request.chain`` actually hits.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


@dataclass(frozen=True, slots=True)
class Stablecoin:
    """One stablecoin deployment, as A01 knows it without asking the chain."""

    symbol: str
    decimals: int
    #: The asset the coin targets. Every entry here is ``USD`` today, but the
    #: field is explicit so a EUR- or gold-pegged coin cannot be summed into a
    #: dollar total by a caller that assumed the peg.
    peg: str = "USD"

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("stablecoin must have a symbol")
        if self.decimals < 0 or self.decimals > 77:
            raise ValueError(f"decimals out of range: {self.decimals}")


#: ``(chain, address_lowercase) -> Stablecoin``.
#:
#: USDC and USDT are 6 decimals everywhere below except ``bnb_chain``, where the
#: canonical deployments are 18. DAI, BUSD and USDP are 18 throughout.
STABLECOINS: Final[dict[tuple[str, str], Stablecoin]] = {
    # -- Ethereum ---------------------------------------------------------
    ("ethereum", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): Stablecoin("USDC", 6),
    ("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7"): Stablecoin("USDT", 6),
    ("ethereum", "0x6b175474e89094c44da98b954eedeac495271d0f"): Stablecoin("DAI", 18),
    ("ethereum", "0x4fabb145d64652a948d72533023f6e7a623c7c53"): Stablecoin("BUSD", 18),
    ("ethereum", "0x8e870d67f660d95d5be530380d0ec0bd388289e1"): Stablecoin("USDP", 18),
    # -- BNB Chain (USDC/USDT are 18 decimals here) -----------------------
    ("bnb_chain", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"): Stablecoin("USDC", 18),
    ("bnb_chain", "0x55d398326f99059ff775485246999027b3197955"): Stablecoin("USDT", 18),
    ("bnb_chain", "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3"): Stablecoin("DAI", 18),
    ("bnb_chain", "0xe9e7cea3dedca5984780bafc599bd69add087d56"): Stablecoin("BUSD", 18),
    # -- Polygon ----------------------------------------------------------
    ("polygon", "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"): Stablecoin("USDC", 6),
    ("polygon", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"): Stablecoin("USDT", 6),
    ("polygon", "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063"): Stablecoin("DAI", 18),
    # -- Arbitrum ---------------------------------------------------------
    ("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"): Stablecoin("USDC", 6),
    ("arbitrum", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"): Stablecoin("USDT", 6),
    ("arbitrum", "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"): Stablecoin("DAI", 18),
    # -- Optimism ---------------------------------------------------------
    ("optimism", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"): Stablecoin("USDC", 6),
    ("optimism", "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58"): Stablecoin("USDT", 6),
    ("optimism", "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"): Stablecoin("DAI", 18),
    # -- Base -------------------------------------------------------------
    ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): Stablecoin("USDC", 6),
    # -- Avalanche (the bridged .e deployments) ---------------------------
    ("avalanche", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"): Stablecoin("USDC", 6),
    ("avalanche", "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7"): Stablecoin("USDT", 6),
    ("avalanche", "0xd586e7f844cea2f87f50152665bcbc2c279d8d70"): Stablecoin("DAI", 18),
}


def lookup(chain: str, address: str) -> Stablecoin | None:
    """
    The stablecoin at this address on this chain, or ``None``.

    Address match is case-insensitive; chains store addresses lowercased, but a
    caller passing a checksummed address must still hit.
    """
    return STABLECOINS.get((chain, address.lower()))


def is_stablecoin(chain: str, address: str) -> bool:
    """Whether this address is a known stablecoin on this chain."""
    return (chain, address.lower()) in STABLECOINS


def symbols(chain: str) -> dict[str, str]:
    """
    ``{address_lowercase: symbol}`` for one chain.

    Empty for a chain with no listed stablecoins, which a caller must treat as
    "none known", never as "none present".
    """
    return {
        address: coin.symbol
        for (coin_chain, address), coin in STABLECOINS.items()
        if coin_chain == chain
    }


def chains() -> frozenset[str]:
    """Every chain this table covers."""
    return frozenset(chain for chain, _ in STABLECOINS)


def normalize(raw: int, decimals: int) -> Decimal:
    """
    A raw base-unit amount as its face quantity.

    Through :class:`~decimal.Decimal` rather than float: a stablecoin transfer
    is routinely larger than a float can hold exactly, and the whole point of
    resolving the exponent is to stop losing the low-order digits.
    """
    return Decimal(raw).scaleb(-decimals)


__all__ = [
    "STABLECOINS",
    "Stablecoin",
    "chains",
    "is_stablecoin",
    "lookup",
    "normalize",
    "symbols",
]
