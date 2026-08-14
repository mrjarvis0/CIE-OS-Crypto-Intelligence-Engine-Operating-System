"""
Tools :: Blockchain Layer
=========================

Multi-chain blockchain intelligence interface.

The Blockchain Layer provides a unified abstraction over blockchain networks,
RPC providers, explorers, smart contracts, wallets, tokens, NFTs, bridges and
DeFi protocols. The Planning Engine never talks to Ethereum nodes, RPC
endpoints or explorers directly; every operation flows through this package.

This package exposes:

* a shared :class:`ChainError` hierarchy (mirroring adapters/ai layers) so
  RPC/explorer failures never leak into the Planner;
* :class:`~.evm.EVMFacade` -- the EVM foundation (addresses, ABI, chains);
* :class:`~.ethereum.EthereumClient` -- network metadata + gas/fee helpers;
* capability clients for explorer, wallet, transaction, token, contract,
  NFT, DeFi and bridge intelligence, each with a deterministic stdlib-only
  local implementation so the layer works offline and in tests.

Two hard rules (mirroring the whole tools tree):

1. Providers may *raise* :class:`ChainError` subclasses; protocol-native
   exceptions never leak to callers.
2. Every capability returns normalized dict/dataclass results; runtime
   failures are reported, not raised, at the operation boundary.

Private keys are never stored in this layer; signing stays outside.
"""

from __future__ import annotations

import abc
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

__all__ = [
    "ChainError",
    "ChainConnectionError",
    "ChainValidationError",
    "ChainTimeoutError",
    "ChainExecutionError",
    "ChainUnsupportedError",
    "ChainRequest",
    "ChainResponse",
    "ChainMetadata",
    "BaseChainClient",
    "EVMFacade",
    "EthereumClient",
    "LocalEthereumClient",
    "ExplorerClient",
    "LocalExplorer",
    "ExplorerProvider",
    "WalletClient",
    "LocalWallet",
    "TransactionClient",
    "LocalTransaction",
    "TokenClient",
    "LocalToken",
    "ContractClient",
    "LocalContract",
    "NFTClient",
    "LocalNFT",
    "DefiClient",
    "LocalDefi",
    "BridgeClient",
    "LocalBridge",
    "NetworkInfo",
    "GasEstimate",
    "FeeHistory",
    "Wallet",
    "AssetBalance",
    "Portfolio",
    "Transaction",
    "TransactionReceipt",
    "TransactionHistory",
    "TokenInfo",
    "TokenTransfer",
    "ContractInterface",
    "ContractFunction",
    "ContractEvent",
    "NFTMetadata",
    "NFTAsset",
    "NFTCollection",
    "ProtocolInfo",
    "LiquidityPosition",
    "LendingPosition",
    "YieldInfo",
    "SwapQuote",
    "BridgeProtocol",
    "BridgeRoute",
    "BridgeTransfer",
    "generate_mnemonic",
    "derive_address",
    "is_valid_hash",
    "classify_transaction",
    "analyze_abi",
    "estimate_gas",
    "token_of",
]

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Shared error model
# --------------------------------------------------------------------------- #


class ChainError(Exception):
    """Base class for every error raised by the blockchain layer."""

    def __init__(
        self,
        message: str = "",
        *,
        cause: Optional[BaseException] = None,
        chain_id: Optional[int] = None,
        provider: str = "unknown",
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.chain_id = chain_id
        self.provider = provider
        self.request_id = request_id

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        prefix = f"[{self.provider}"
        if self.chain_id is not None:
            prefix += f":{self.chain_id}"
        if self.request_id:
            prefix += f":{self.request_id}"
        return f"{prefix}] {self.message}"


class ChainConnectionError(ChainError):
    """The RPC endpoint / provider could not be reached."""


class ChainValidationError(ChainError):
    """An incoming request failed validation before execution."""


class ChainTimeoutError(ChainError):
    """The request exceeded its time budget."""


class ChainExecutionError(ChainError):
    """The chain executed the request but the operation failed."""


class ChainUnsupportedError(ChainError):
    """The requested chain / capability is not supported."""


# --------------------------------------------------------------------------- #
# Request / Response structures
# --------------------------------------------------------------------------- #


@dataclass
class ChainRequest:
    """A normalized, chain-independent request descriptor."""

    method: str                       # e.g. eth_getBalance, token_metadata
    params: Dict[str, Any] = field(default_factory=dict)
    chain_id: int = 1
    timeout: float = 30.0
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class ChainMetadata:
    """Execution metadata attached to every :class:`ChainResponse`."""

    chain_id: int
    provider: str = "local"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    duration_ms: float = 0.0
    status: str = "success"
    block_number: Optional[int] = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ChainResponse:
    """A normalized, provider-independent chain result."""

    ok: bool
    data: Any = None
    error: Optional[ChainError] = None
    metadata: ChainMetadata = field(default_factory=lambda: ChainMetadata(chain_id=1))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": {"code": type(self.error).__name__, "message": str(self.error)} if self.error else None,
            "metadata": dict(self.metadata.details),
        }


# --------------------------------------------------------------------------- #
# Base client contract
# --------------------------------------------------------------------------- #


class BaseChainClient(abc.ABC):
    """The canonical contract every chain capability client implements."""

    provider: str = "base"
    capability: str = "chain"

    def __init__(self, *, chain_id: int = 1, logger: Optional[logging.Logger] = None) -> None:
        self.log = logger or logging.getLogger(f"{__name__}.{type(self).__name__}")
        self._chain_id = chain_id

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @abc.abstractmethod
    def execute(self, request: ChainRequest) -> ChainResponse:
        """Execute a normalized request and return a normalized response."""
        raise NotImplementedError

    def normalize(
        self,
        ok: bool,
        data: Any = None,
        error: Optional[ChainError] = None,
        *,
        request: Optional[ChainRequest] = None,
        duration_ms: float = 0.0,
        status: str = "success",
        block_number: Optional[int] = None,
        **details: Any,
    ) -> ChainResponse:
        meta = ChainMetadata(
            chain_id=self._chain_id,
            provider=self.provider,
            request_id=(request.request_id if request else uuid.uuid4().hex),
            duration_ms=duration_ms,
            status=status,
            block_number=block_number,
            details=details,
        )
        return ChainResponse(ok=ok, data=data, error=error, metadata=meta)


# --------------------------------------------------------------------------- #
# Imported conveniences
# --------------------------------------------------------------------------- #

from .evm import (  # noqa: E402
    EVMFacade,
    ChainInfo,
    is_address,
    normalize_address,
    validate_address,
    signature_hash,
    function_selector,
    event_topic,
    abi_encode,
    abi_decode,
    build_transaction,
    compute_contract_address,
    parse_block,
    parse_log,
    CHAIN_REGISTRY,
    get_chain,
)
from .ethereum import EthereumClient, LocalEthereumClient, NetworkInfo, GasEstimate, FeeHistory, estimate_gas  # noqa: E402
from .explorer import ExplorerProvider, ExplorerClient, LocalExplorer  # noqa: E402
from .wallet import Wallet, AssetBalance, Portfolio, WalletClient, LocalWallet, derive_address, generate_mnemonic  # noqa: E402
from .transaction import Transaction, TransactionReceipt, TransactionHistory, TransactionClient, LocalTransaction, is_valid_hash, classify_transaction  # noqa: E402
from .token import TokenInfo, TokenTransfer, TokenClient, LocalToken, token_of  # noqa: E402
from .contract import ContractInterface, ContractFunction, ContractEvent, ContractClient, LocalContract, analyze_abi  # noqa: E402
from .nft import NFTMetadata, NFTAsset, NFTCollection, NFTClient, LocalNFT  # noqa: E402
from .defi import ProtocolInfo, LiquidityPosition, LendingPosition, YieldInfo, SwapQuote, DefiClient, LocalDefi  # noqa: E402
from .bridge import BridgeProtocol, BridgeRoute, BridgeTransfer, BridgeClient, LocalBridge  # noqa: E402