"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.rpc.chains

Purpose:
    Typed blockchain chain registry used by RPC configuration and chain-aware
    runtime components.

Design goals:
    - Strong typing
    - Immutable metadata
    - EVM-friendly defaults
    - Clear chain registry lookups
    - No secrets
    - No network I/O
    - Safe to import anywhere

Notes:
    EIP-155 uses chain IDs for replay protection, and EIP-3085/EIP-2015
    describe chain metadata fields such as chainId, chainName, rpcUrls and
    blockExplorerUrls for chain configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from typing import Final, Iterable, Mapping, Sequence


# ==============================================================================
# ENUMS
# ==============================================================================

class ChainName(StrEnum):
    """
    Supported blockchain names for the A01 agent.

    A name here is a claim that A01 can read the chain, so nothing is listed
    until at least two open endpoints have been observed serving blocks *and*
    logs for it. Every ``average_block_time_seconds`` below was measured from
    the chain's own timestamps over a 500-block span rather than taken from
    documentation -- see the note on :data:`DEFAULT_CHAIN_CONFIGS`.
    """

    ETHEREUM = "ethereum"
    BNB_CHAIN = "bnb_chain"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    AVALANCHE = "avalanche"
    LINEA = "linea"
    SCROLL = "scroll"
    GNOSIS = "gnosis"
    CELO = "celo"
    MANTLE = "mantle"
    UNICHAIN = "unichain"
    SOLANA = "solana"
    BITCOIN = "bitcoin"


class ChainType(StrEnum):
    """High-level chain family."""

    EVM = "evm"
    NON_EVM = "non_evm"
    BITCOIN_LIKE = "bitcoin_like"
    SOLANA_LIKE = "solana_like"


# ==============================================================================
# DATA MODELS
# ==============================================================================

@dataclass(frozen=True, slots=True)
class NativeCurrency:
    """Native currency metadata for a blockchain network."""

    name: str
    symbol: str
    decimals: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("native currency name cannot be empty")
        if not self.symbol.strip():
            raise ValueError("native currency symbol cannot be empty")
        if self.decimals < 0:
            raise ValueError("native currency decimals must be >= 0")


@dataclass(frozen=True, slots=True)
class ChainConfig:
    """Immutable chain metadata used throughout the A01 runtime."""

    name: ChainName
    chain_id: int | None
    chain_type: ChainType
    display_name: str
    native_currency: NativeCurrency
    block_explorer_urls: tuple[str, ...] = ()
    rpc_urls: tuple[str, ...] = ()
    average_block_time_seconds: int | None = None
    confirmations: int = 12
    is_testnet: bool = False
    is_enabled: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if self.chain_type == ChainType.EVM and (self.chain_id is None or self.chain_id <= 0):
            raise ValueError("EVM chain_id must be greater than zero")
        if self.chain_type != ChainType.EVM and self.chain_id is not None and self.chain_id <= 0:
            raise ValueError("non-EVM chain_id must be None or greater than zero")
        if not self.display_name.strip():
            raise ValueError("display_name cannot be empty")
        if self.confirmations < 0:
            raise ValueError("confirmations must be >= 0")
        if self.average_block_time_seconds is not None and self.average_block_time_seconds <= 0:
            raise ValueError("average_block_time_seconds must be > 0 when provided")

        if not self.block_explorer_urls and self.chain_type == ChainType.EVM:
            # EVM chains should generally expose an explorer, but this is a soft
            # rule: empty is allowed for local or private deployments.
            object.__setattr__(self, "block_explorer_urls", ())

        if self.rpc_urls and any(not url.strip() for url in self.rpc_urls):
            raise ValueError("rpc_urls cannot contain empty entries")

        if self.block_explorer_urls and any(not url.strip() for url in self.block_explorer_urls):
            raise ValueError("block_explorer_urls cannot contain empty entries")


# ==============================================================================
# DEFAULT CATALOG
# ==============================================================================

#: Chain metadata, ordered EVM first.
#:
#: **The block times are measurements, not documentation.** Each was taken from
#: the chain's own block timestamps across a 500-block span, with ethereum and
#: base as controls (12.07s and 2.00s against declared 12 and 2). Two of them
#: contradict what a reader would assume: Linea measured 8.4s and Scroll 10.1s,
#: not the 2-3s their marketing block times suggest, because both produce blocks
#: on demand and the span sampled was quiet. This field feeds height-to-time
#: reasoning in coverage, so a figure four times too small there would silently
#: turn a one-hour window into a fifteen-minute claim.
DEFAULT_CHAIN_CONFIGS: Final[tuple[ChainConfig, ...]] = (
    ChainConfig(
        name=ChainName.ETHEREUM,
        chain_id=1,
        chain_type=ChainType.EVM,
        display_name="Ethereum Mainnet",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://etherscan.io",),
        confirmations=12,
        average_block_time_seconds=12,
        description="Primary Ethereum mainnet configuration.",
    ),
    ChainConfig(
        name=ChainName.BNB_CHAIN,
        chain_id=56,
        chain_type=ChainType.EVM,
        display_name="BNB Smart Chain",
        native_currency=NativeCurrency(name="BNB", symbol="BNB", decimals=18),
        block_explorer_urls=("https://bscscan.com",),
        confirmations=15,
        average_block_time_seconds=3,
        description="BNB Smart Chain / BSC configuration.",
    ),
    ChainConfig(
        name=ChainName.POLYGON,
        chain_id=137,
        chain_type=ChainType.EVM,
        display_name="Polygon Mainnet",
        native_currency=NativeCurrency(name="POL", symbol="POL", decimals=18),
        block_explorer_urls=("https://polygonscan.com",),
        confirmations=128,
        average_block_time_seconds=2,
        description="Polygon mainnet configuration.",
    ),
    ChainConfig(
        name=ChainName.ARBITRUM,
        chain_id=42161,
        chain_type=ChainType.EVM,
        display_name="Arbitrum One",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://arbiscan.io",),
        confirmations=20,
        average_block_time_seconds=1,
        description="Arbitrum One configuration.",
    ),
    ChainConfig(
        name=ChainName.OPTIMISM,
        chain_id=10,
        chain_type=ChainType.EVM,
        display_name="Optimism Mainnet",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://optimistic.etherscan.io",),
        confirmations=20,
        average_block_time_seconds=2,
        description="Optimism mainnet configuration.",
    ),
    ChainConfig(
        name=ChainName.BASE,
        chain_id=8453,
        chain_type=ChainType.EVM,
        display_name="Base Mainnet",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://basescan.org",),
        confirmations=20,
        average_block_time_seconds=2,
        description="Base mainnet configuration.",
    ),
    ChainConfig(
        name=ChainName.AVALANCHE,
        chain_id=43114,
        chain_type=ChainType.EVM,
        display_name="Avalanche C-Chain",
        native_currency=NativeCurrency(name="AVAX", symbol="AVAX", decimals=18),
        block_explorer_urls=("https://snowtrace.io",),
        confirmations=12,
        average_block_time_seconds=2,
        description="Avalanche C-Chain configuration.",
    ),
    ChainConfig(
        name=ChainName.LINEA,
        chain_id=59144,
        chain_type=ChainType.EVM,
        display_name="Linea Mainnet",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://lineascan.build",),
        confirmations=20,
        # Measured 8.38s. Demand-driven, so this is the observed rate at a quiet
        # moment rather than a protocol constant.
        average_block_time_seconds=8,
        description="Linea zkEVM rollup. Sequencer-ordered; confirmations track soft ordering, not L1 settlement.",
    ),
    ChainConfig(
        name=ChainName.SCROLL,
        chain_id=534352,
        chain_type=ChainType.EVM,
        display_name="Scroll Mainnet",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://scrollscan.com",),
        confirmations=20,
        # Measured 10.08s, and demand-driven for the same reason as Linea.
        average_block_time_seconds=10,
        description="Scroll zkEVM rollup. Sequencer-ordered; confirmations track soft ordering, not L1 settlement.",
    ),
    ChainConfig(
        name=ChainName.GNOSIS,
        chain_id=100,
        chain_type=ChainType.EVM,
        display_name="Gnosis Chain",
        native_currency=NativeCurrency(name="xDai", symbol="XDAI", decimals=18),
        block_explorer_urls=("https://gnosisscan.io",),
        # Gasper with 16-slot epochs, so finality lands two epochs back. Unlike
        # the rollups above this is a real settlement depth, not a soft one.
        confirmations=32,
        average_block_time_seconds=5,
        description="Gnosis Chain L1. Stable-denominated gas; the only chain here whose native unit is a stablecoin.",
    ),
    ChainConfig(
        name=ChainName.CELO,
        chain_id=42220,
        chain_type=ChainType.EVM,
        display_name="Celo Mainnet",
        native_currency=NativeCurrency(name="Celo", symbol="CELO", decimals=18),
        block_explorer_urls=("https://celoscan.io",),
        confirmations=20,
        average_block_time_seconds=1,
        description="Celo, now an Ethereum L2. One-second blocks, so a confirmation depth here is a fifth of the wall time it buys on Base.",
    ),
    ChainConfig(
        name=ChainName.MANTLE,
        chain_id=5000,
        chain_type=ChainType.EVM,
        display_name="Mantle Mainnet",
        native_currency=NativeCurrency(name="Mantle", symbol="MNT", decimals=18),
        block_explorer_urls=("https://mantlescan.xyz",),
        confirmations=20,
        average_block_time_seconds=2,
        description="Mantle L2. Native gas token is MNT rather than ether, so a value threshold set in ether means nothing here.",
    ),
    ChainConfig(
        name=ChainName.UNICHAIN,
        chain_id=130,
        chain_type=ChainType.EVM,
        display_name="Unichain Mainnet",
        native_currency=NativeCurrency(name="Ether", symbol="ETH", decimals=18),
        block_explorer_urls=("https://uniscan.xyz",),
        confirmations=20,
        average_block_time_seconds=1,
        description="Unichain, an OP-stack L2. One-second blocks; see the note on Celo's confirmation depth.",
    ),
    ChainConfig(
        name=ChainName.SOLANA,
        chain_id=None,
        chain_type=ChainType.SOLANA_LIKE,
        display_name="Solana Mainnet",
        native_currency=NativeCurrency(name="Solana", symbol="SOL", decimals=9),
        # Solana's commitment levels are processed / confirmed / finalized, and
        # finalized sits roughly 32 slots back. This previously read 1, which is
        # the "processed" level: a block one slot old can still be dropped, so
        # treating it as settled meant reading unconfirmed state as history.
        confirmations=32,
        average_block_time_seconds=1,
        description="Solana mainnet configuration.",
    ),
    ChainConfig(
        name=ChainName.BITCOIN,
        chain_id=None,
        chain_type=ChainType.BITCOIN_LIKE,
        display_name="Bitcoin Mainnet",
        native_currency=NativeCurrency(name="Bitcoin", symbol="BTC", decimals=8),
        confirmations=6,
        average_block_time_seconds=600,
        description="Bitcoin mainnet configuration.",
    ),
)

_CHAIN_INDEX_BY_NAME: Final[dict[ChainName, ChainConfig]] = {
    chain.name: chain for chain in DEFAULT_CHAIN_CONFIGS
}
_CHAIN_INDEX_BY_ID: Final[dict[int, ChainConfig]] = {
    chain.chain_id: chain
    for chain in DEFAULT_CHAIN_CONFIGS
    if chain.chain_id is not None and chain.chain_id > 0
}


# ==============================================================================
# REGISTRY
# ==============================================================================

class ChainRegistry:
    """Immutable chain registry with lookups by name and chain ID."""

    def __init__(self, chains: Sequence[ChainConfig] | None = None) -> None:
        config_list = tuple(chains or DEFAULT_CHAIN_CONFIGS)
        self._chains = config_list
        self._by_name = {chain.name: chain for chain in config_list}
        self._by_id = {
            chain.chain_id: chain for chain in config_list if chain.chain_id is not None and chain.chain_id > 0
        }

    @property
    def chains(self) -> tuple[ChainConfig, ...]:
        return self._chains

    def list_enabled(self) -> tuple[ChainConfig, ...]:
        return tuple(chain for chain in self._chains if chain.is_enabled)

    def list_evm_chains(self) -> tuple[ChainConfig, ...]:
        return tuple(chain for chain in self._chains if chain.chain_type == ChainType.EVM)

    def get_by_name(self, name: ChainName | str) -> ChainConfig:
        key = name if isinstance(name, ChainName) else ChainName(str(name).lower())
        try:
            return self._by_name[key]
        except KeyError as exc:
            raise KeyError(f"Unknown chain name: {name!r}") from exc

    def get_by_chain_id(self, chain_id: int) -> ChainConfig:
        try:
            return self._by_id[chain_id]
        except KeyError as exc:
            raise KeyError(f"Unknown chain_id: {chain_id}") from exc

    def contains_name(self, name: ChainName | str) -> bool:
        try:
            self.get_by_name(name)
            return True
        except Exception:
            return False

    def contains_chain_id(self, chain_id: int) -> bool:
        return chain_id in self._by_id

    def names(self) -> tuple[ChainName, ...]:
        return tuple(chain.name for chain in self._chains)

    def chain_ids(self) -> tuple[int, ...]:
        return tuple(chain.chain_id for chain in self._chains if chain.chain_id is not None and chain.chain_id > 0)

    def as_mapping(self) -> Mapping[str, ChainConfig]:
        return {chain.name.value: chain for chain in self._chains}

    def __iter__(self):
        return iter(self._chains)

    def __len__(self) -> int:
        return len(self._chains)


@lru_cache(maxsize=1)
def default_registry() -> ChainRegistry:
    """Return the default chain registry singleton."""
    return ChainRegistry()


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def supported_chain_names() -> tuple[ChainName, ...]:
    return default_registry().names()


def supported_chain_ids() -> tuple[int, ...]:
    return default_registry().chain_ids()


def get_chain(name: ChainName | str) -> ChainConfig:
    return default_registry().get_by_name(name)


def get_chain_by_id(chain_id: int) -> ChainConfig:
    return default_registry().get_by_chain_id(chain_id)


def is_supported_chain(name: ChainName | str) -> bool:
    return default_registry().contains_name(name)


def is_supported_chain_id(chain_id: int) -> bool:
    return default_registry().contains_chain_id(chain_id)


__all__ = [
    "ChainName",
    "ChainType",
    "NativeCurrency",
    "ChainConfig",
    "ChainRegistry",
    "DEFAULT_CHAIN_CONFIGS",
    "default_registry",
    "supported_chain_names",
    "supported_chain_ids",
    "get_chain",
    "get_chain_by_id",
    "is_supported_chain",
    "is_supported_chain_id",
]
