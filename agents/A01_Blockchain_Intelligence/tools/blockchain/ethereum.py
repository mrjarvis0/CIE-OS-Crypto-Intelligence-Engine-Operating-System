"""
Tools :: Blockchain :: Ethereum
===============================

Ethereum-specific implementation over the EVM foundation.

Provides network metadata (mainnet/sepolia/holesky), deterministic gas and
fee estimation, fee history normalization and block information. A local
client ships an in-memory ledger so wallet/transaction analysis works
offline; RPC-backed clients subclass and override ``_call``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainExecutionError, ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import get_chain, normalize_address, parse_block, CHAIN_REGISTRY, ChainInfo

__all__ = [
    "NetworkInfo",
    "GasEstimate",
    "FeeHistory",
    "EthereumClient",
    "LocalEthereumClient",
    "estimate_gas",
]

# Deterministic per-block base-fee bump when a block is full.
_TARGET_GAS = 30_000_000


@dataclass
class NetworkInfo:
    """Normalized network snapshot."""

    chain: ChainInfo
    block_number: int = 0
    block_time_seconds: float = 12.0
    status: str = "ok"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "chain": self.chain.as_dict(),
            "block_number": self.block_number,
            "block_time_seconds": self.block_time_seconds,
            "status": self.status,
        }


@dataclass
class GasEstimate:
    """Gas and fee estimate for a transaction."""

    gas_units: int = 21000
    base_fee: int = 0
    priority_fee: int = 0
    max_fee: int = 0
    estimated_cost_wei: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gas_units": self.gas_units,
            "base_fee": self.base_fee,
            "priority_fee": self.priority_fee,
            "max_fee": self.max_fee,
            "estimated_cost_wei": self.estimated_cost_wei,
        }


@dataclass
class FeeHistory:
    """Recent block fee data."""

    blocks: List[Mapping[str, Any]] = field(default_factory=list)
    suggested_base_fee: int = 0
    suggested_priority_fee: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "blocks": list(self.blocks),
            "suggested_base_fee": self.suggested_base_fee,
            "suggested_priority_fee": self.suggested_priority_fee,
        }


def estimate_gas(
    *,
    base_fee: int = 10_000_000_000,
    priority_fee: int = 2_000_000_000,
    gas_units: int = 21000,
    is_contract_call: bool = False,
    payload_bytes: int = 0,
) -> GasEstimate:
    """Deterministic local gas estimation.

    ``is_contract_call`` raises the floor; each payload byte adds a flat
    16-gas data cost (matching EVM calldata pricing).
    """
    if is_contract_call:
        gas_units = max(gas_units, 50_000)
    gas_units = gas_units + payload_bytes * 16
    max_fee = base_fee * 2 + priority_fee
    return GasEstimate(
        gas_units=gas_units,
        base_fee=base_fee,
        priority_fee=priority_fee,
        max_fee=max_fee,
        estimated_cost_wei=gas_units * max_fee,
    )


class EthereumClient(BaseChainClient):
    """Ethereum network client: metadata, gas, fees, blocks.

    ``_call`` is the provider hook; the local subclass overrides it with an
    in-memory ledger. All responses are normalized.
    """

    provider = "ethereum"
    capability = "ethereum"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self.chain = get_chain(chain_id)

    # -- provider hook -------------------------------------------------------- #

    def _call(self, method: str, params: Mapping[str, Any]) -> Any:
        raise NotImplementedError

    # -- capabilities --------------------------------------------------------- #

    def network_info(self) -> NetworkInfo:
        block = self._call("eth_blockNumber", {}) or {}
        return NetworkInfo(chain=self.chain, block_number=int(block.get("number", 0)))

    def gas_estimate(
        self,
        *,
        to: str = "",
        data: str = "0x",
        gas_units: Optional[int] = None,
    ) -> GasEstimate:
        to_addr = normalize_address(to) if to else ""
        is_contract = bool(to_addr)  # best-effort local heuristic
        payload_bytes = max(0, (len(data) - 2) // 2) if data.startswith("0x") else len(data)
        base_fee = self._fee_snapshot().get("base_fee", 10_000_000_000)
        return estimate_gas(
            base_fee=int(base_fee),
            gas_units=gas_units or 21000,
            is_contract_call=is_contract,
            payload_bytes=payload_bytes,
        )

    def fee_history(self, *, blocks: int = 10) -> FeeHistory:
        return self._fee_history(blocks)

    def block_info(self, number: Optional[int] = None) -> Mapping[str, Any]:
        block = self._call("eth_getBlockByNumber", {"number": number} if number is not None else {})
        if block is None:
            raise ChainExecutionError(f"block {number} not found", chain_id=self._chain_id)
        return parse_block(block)

    # -- defaults overridden by subclasses ------------------------------------ #

    def _fee_snapshot(self) -> Mapping[str, Any]:
        return {"base_fee": 10_000_000_000, "priority_fee": 2_000_000_000}

    def _fee_history(self, blocks: int) -> FeeHistory:
        snapshot = self._fee_snapshot()
        entries = []
        for index in range(blocks):
            entries.append(
                {
                    "number": index,
                    "base_fee": snapshot.get("base_fee"),
                    "gas_used_ratio": 0.5,
                }
            )
        return FeeHistory(
            blocks=entries,
            suggested_base_fee=int(snapshot.get("base_fee", 0)),
            suggested_priority_fee=int(snapshot.get("priority_fee", 0)),
        )

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "network_info":
                data = self.network_info().as_dict()
            elif method == "gas_estimate":
                data = self.gas_estimate(**params).as_dict()
            elif method == "fee_history":
                data = self.fee_history(blocks=int(params.get("blocks", 10))).as_dict()
            elif method == "block_info":
                data = self.block_info(int(params["number"]) if "number" in params else None)
            elif method == "get_chain":
                data = self.chain.as_dict()
            else:
                raise ChainValidationError(f"unknown ethereum method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalEthereumClient(EthereumClient):
    """In-memory Ethereum client for offline analysis and tests.

    Holds a deterministic ledger: block height, base fee, account balances
    and a small transaction pool. Seed state with :meth:`seed`.
    """

    provider = "local-ethereum"

    def __init__(self, *, chain_id: int = 1, block_number: int = 20_000_000, base_fee: int = 12_000_000_000, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._block_number = block_number
        self._base_fee = base_fee
        self._balances: Dict[str, int] = {}

    def seed_balance(self, address: str, wei: int) -> None:
        self._balances[normalize_address(address)] = int(wei)

    def _call(self, method: str, params: Mapping[str, Any]) -> Any:
        if method == "eth_blockNumber":
            return {"number": self._block_number}
        if method == "eth_getBlockByNumber":
            number = params.get("number", self._block_number)
            return {
                "number": number,
                "hash": "0x" + ("ab" * 32),
                "parent_hash": "0x" + ("cd" * 32),
                "timestamp": 1_700_000_000 + number,
                "transactions": [],
                "gas_used": 15_000_000,
                "gas_limit": _TARGET_GAS,
                "base_fee": self._base_fee,
            }
        if method == "eth_getBalance":
            address = normalize_address(str(params.get("address", "")))
            return {"balance": self._balances.get(address, 0)}
        raise ChainValidationError(f"local client cannot serve {method!r}")

    def _fee_snapshot(self) -> Mapping[str, Any]:
        return {"base_fee": self._base_fee, "priority_fee": 1_500_000_000}

    def balance(self, address: str) -> int:
        response = self._call("eth_getBalance", {"address": address})
        return int(response.get("balance", 0))