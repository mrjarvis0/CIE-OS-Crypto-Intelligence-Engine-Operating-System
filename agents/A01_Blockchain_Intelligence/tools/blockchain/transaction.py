"""
Tools :: Blockchain :: Transaction
==================================

Transaction construction, validation, receipt parsing and history
normalization.

The :class:`Transaction` dataclass mirrors :mod:`tools.blockchain.evm`
transactions plus chain-specific fields (nonce, gas price, chain id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import normalize_address

__all__ = [
    "Transaction",
    "TransactionReceipt",
    "TransactionHistory",
    "TransactionClient",
    "LocalTransaction",
    "classify_transaction",
    "is_valid_hash",
]

_TX_KINDS = {"transfer", "contract", "token_transfer", "swap", "bridge", "stake", "mint", "other"}


def is_valid_hash(value: str) -> bool:
    """A transaction hash is ``0x`` + 64 hex chars."""
    return isinstance(value, str) and value.startswith("0x") and len(value) == 66 and all(ch in "0123456789abcdefABCDEF" for ch in value[2:])


def classify_transaction(tx: Mapping[str, Any]) -> str:
    """Best-effort classification of a raw transaction record."""
    if not isinstance(tx, Mapping):
        return "other"
    method = tx.get("method") or tx.get("function") or tx.get("type") or ""
    if "transfer" in str(method).lower():
        return "transfer"
    if "swap" in str(method).lower() or "swap" in str(tx.get("protocol", "")).lower():
        return "swap"
    if "bridge" in str(method).lower():
        return "bridge"
    if "stake" in str(method).lower():
        return "stake"
    if "mint" in str(method).lower():
        return "mint"
    if "transfer" in str(tx.get("to", "")).lower() or not str(method):
        if tx.get("to"):
            return "transfer"
    return "other"


@dataclass
class Transaction:
    """Normalized transaction record."""

    hash: str
    from_address: str
    to_address: str
    value_wei: int = 0
    gas_used: int = 21000
    gas_price_wei: int = 0
    status: str = "pending"
    block_number: Optional[int] = None
    kind: str = "transfer"
    data: str = "0x"
    timestamp: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hash": self.hash,
            "from": self.from_address,
            "to": self.to_address,
            "value_wei": self.value_wei,
            "gas_used": self.gas_used,
            "gas_price_wei": self.gas_price_wei,
            "status": self.status,
            "block_number": self.block_number,
            "kind": self.kind,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class TransactionReceipt:
    """Execution outcome of a transaction."""

    hash: str
    status: str = "pending"
    gas_used: int = 21000
    effective_gas_price_wei: int = 0
    logs: List[Mapping[str, Any]] = field(default_factory=list)
    block_number: Optional[int] = None

    @property
    def success(self) -> bool:
        return self.status == "success"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hash": self.hash,
            "status": self.status,
            "success": self.success,
            "gas_used": self.gas_used,
            "effective_gas_price_wei": self.effective_gas_price_wei,
            "logs": list(self.logs),
            "block_number": self.block_number,
        }


@dataclass
class TransactionHistory:
    """Recent transactions for an address."""

    address: str
    transactions: List[Transaction] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "count": len(self.transactions),
            "transactions": [tx.as_dict() for tx in self.transactions],
        }


class TransactionClient(BaseChainClient):
    """Transaction service: send, receipt, history."""

    provider = "transaction"
    capability = "transaction"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)

    # -- provider hooks -------------------------------------------------------- #

    def _send(self, tx: Mapping[str, Any]) -> str:
        raise NotImplementedError

    def _receipt(self, tx_hash: str) -> Optional[TransactionReceipt]:
        raise NotImplementedError

    def _history(self, address: str, limit: int) -> List[Transaction]:
        return []

    # -- capabilities ---------------------------------------------------------- #

    def validate_tx(self, tx: Mapping[str, Any]) -> Transaction:
        """Validate and normalize a raw transaction record."""
        tx_hash = str(tx.get("hash", ""))
        if tx_hash and not is_valid_hash(tx_hash):
            raise ChainValidationError(f"invalid transaction hash {tx_hash!r}")
        to_address = str(tx.get("to", "") or "")
        if to_address:
            to_address = normalize_address(to_address)
        return Transaction(
            hash=tx_hash or ("0x" + "0" * 64),
            from_address=normalize_address(str(tx.get("from", ""))),
            to_address=to_address,
            value_wei=int(tx.get("value_wei", tx.get("value", 0)) or 0),
            gas_used=int(tx.get("gas_used", 21000)),
            gas_price_wei=int(tx.get("gas_price_wei", 0)),
            status=str(tx.get("status", "pending")),
            block_number=int(tx["block_number"]) if tx.get("block_number") is not None else None,
            kind=str(tx.get("kind", classify_transaction(tx))),
            data=str(tx.get("data", "0x")),
            timestamp=int(tx.get("timestamp", 0)),
        )

    def send(self, tx: Mapping[str, Any]) -> str:
        normalized = self.validate_tx(tx)
        return self._send(normalized.as_dict())

    def receipt(self, tx_hash: str) -> TransactionReceipt:
        if not is_valid_hash(tx_hash):
            raise ChainValidationError(f"invalid transaction hash {tx_hash!r}")
        receipt = self._receipt(tx_hash)
        if receipt is None:
            raise ChainValidationError(f"transaction {tx_hash} not found")
        return receipt

    def history(self, address: str, limit: int = 25) -> TransactionHistory:
        address = normalize_address(address)
        txs = self._history(address, max(1, min(int(limit), 100)))
        return TransactionHistory(address=address, transactions=txs)

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "send":
                data = {"hash": self.send(params.get("tx", {}))}
            elif method == "receipt":
                data = self.receipt(str(params["hash"])).as_dict()
            elif method == "history":
                data = self.history(str(params["address"]), int(params.get("limit", 25))).as_dict()
            elif method == "validate_tx":
                data = self.validate_tx(params.get("tx", {})).as_dict()
            else:
                raise ChainValidationError(f"unknown transaction method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalTransaction(TransactionClient):
    """Deterministic offline transaction store."""

    provider = "local-transaction"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._store: Dict[str, Transaction] = {}
        self._sent: List[str] = []
        self._by_address: Dict[str, List[Transaction]] = {}

    def seed(self, tx: Transaction) -> None:
        self._store[tx.hash] = tx
        self._by_address.setdefault(tx.from_address, []).append(tx)
        self._by_address.setdefault(tx.to_address, []).append(tx)

    def _send(self, tx: Mapping[str, Any]) -> str:
        tx_hash = "0x" + f"{len(self._sent) + 1:064x}"
        stored = Transaction(
            hash=tx_hash,
            from_address=str(tx.get("from", "")),
            to_address=str(tx.get("to", "")),
            value_wei=int(tx.get("value_wei", 0)),
            gas_used=int(tx.get("gas_used", 21000)),
            gas_price_wei=int(tx.get("gas_price_wei", 0)),
            status="success",
            block_number=int(tx["block_number"]) if tx.get("block_number") is not None else None,
            kind=str(tx.get("kind", "transfer")),
            data=str(tx.get("data", "0x")),
            timestamp=int(tx.get("timestamp", 0)),
        )
        self._store[tx_hash] = stored
        self._sent.append(tx_hash)
        self._by_address.setdefault(stored.from_address, []).append(stored)
        if stored.to_address:
            self._by_address.setdefault(stored.to_address, []).append(stored)
        return tx_hash

    def _receipt(self, tx_hash: str) -> Optional[TransactionReceipt]:
        tx = self._store.get(tx_hash)
        if tx is None:
            return None
        return TransactionReceipt(
            hash=tx.hash,
            status=tx.status,
            gas_used=tx.gas_used,
            effective_gas_price_wei=tx.gas_price_wei,
            block_number=tx.block_number,
        )

    def _history(self, address: str, limit: int) -> List[Transaction]:
        return self._by_address.get(address, [])[-limit:]