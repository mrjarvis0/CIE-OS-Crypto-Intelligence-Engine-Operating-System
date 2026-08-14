"""
Chain adapter base class.

A chain adapter is the per-chain contract that tells A01's runtime which
sensor family to use, whether the chain is account-based or UTXO, and
any chain-specific behaviour that the generic EVM path cannot handle.

It does not restate metadata from ``config.rpc.chains`` or capabilities
from ``knowledge.chains``. It answers the question those two do not:
*how should A01 interact with this particular chain?*
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from config.rpc.chains import ChainName, ChainType


class ChainAdapter(ABC):
    """Per-chain adapter providing chain-specific configuration."""

    @property
    @abstractmethod
    def chain(self) -> ChainName:
        """Which chain this adapter serves."""

    @property
    @abstractmethod
    def chain_type(self) -> ChainType:
        """The chain's type family."""

    @property
    def sensor_family(self) -> str:
        """Which sensor implementation reads this chain."""
        if self.chain_type == ChainType.EVM:
            return "evm"
        if self.chain_type == ChainType.SOLANA_LIKE:
            return "solana"
        if self.chain_type == ChainType.BITCOIN_LIKE:
            return "utxo"
        return "unknown"

    @property
    def is_account_based(self) -> bool:
        return self.chain_type != ChainType.BITCOIN_LIKE

    @property
    def is_utxo(self) -> bool:
        return self.chain_type == ChainType.BITCOIN_LIKE

    @property
    def has_sensor(self) -> bool:
        return self.chain_type == ChainType.EVM

    def __repr__(self) -> str:
        return f"{type(self).__name__}(chain={self.chain.value!r})"


class EvmAdapter(ChainAdapter):
    """Adapter for EVM-compatible chains. Used by 13 of 15 chains."""

    _chain: ChainName

    def __init__(self, chain: ChainName) -> None:
        if ChainType.EVM != ChainType.EVM:
            raise ValueError(f"{chain} is not an EVM chain")
        object.__setattr__(self, "_chain", chain)

    @property
    def chain(self) -> ChainName:
        return self._chain

    @property
    def chain_type(self) -> ChainType:
        return ChainType.EVM


class UtxoAdapter(ChainAdapter):
    """
    Adapter for UTXO-based chains (Bitcoin).

    UTXO chains have no accounts with balances. A transaction spends
    previous outputs and creates new ones. Forcing the EVM account model
    onto UTXO produces confidently wrong output:

    - "address balance" has no direct meaning
    - transaction inputs reference previous outputs, not account state
    - change addresses mean one user appears as many addresses
    - common-input-ownership heuristics are probabilistic
    - there are no event logs and no smart contracts
    """

    _chain: ChainName

    def __init__(self, chain: ChainName) -> None:
        object.__setattr__(self, "_chain", chain)

    @property
    def chain(self) -> ChainName:
        return self._chain

    @property
    def chain_type(self) -> ChainType:
        return ChainType.BITCOIN_LIKE

    @property
    def has_sensor(self) -> bool:
        return False


class SolanaAdapter(ChainAdapter):
    """
    Adapter for Solana-like chains.

    Solana uses slots, not blocks. Slots can be skipped. The RPC dialect
    is JSON-RPC but with entirely different methods from EVM. A01's EVM
    sensor cannot parse Solana responses.
    """

    _chain: ChainName

    def __init__(self, chain: ChainName) -> None:
        object.__setattr__(self, "_chain", chain)

    @property
    def chain(self) -> ChainName:
        return self._chain

    @property
    def chain_type(self) -> ChainType:
        return ChainType.SOLANA_LIKE

    @property
    def has_sensor(self) -> bool:
        return False


__all__ = [
    "ChainAdapter",
    "EvmAdapter",
    "SolanaAdapter",
    "UtxoAdapter",
]
