"""
Tools :: Blockchain :: Explorer
===============================

Explorer abstraction over Etherscan, Blockscout, OKLink, Routescan and
chain explorers.

A provider describes base URL and API conventions; a client normalizes
address, transaction, contract, token and block lookups into one shape.
:class:`LocalExplorer` resolves deterministic records for offline use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import normalize_address

__all__ = [
    "ExplorerProvider",
    "EXPLORER_PROVIDERS",
    "ExplorerClient",
    "LocalExplorer",
]


@dataclass(frozen=True)
class ExplorerProvider:
    """Static descriptor of one explorer service."""

    name: str
    base_url: str
    api_path: str = "/api"
    supports_contract: bool = True
    supports_token: bool = True

    def url_for(self, kind: str, identifier: str) -> str:
        """Human-readable page URL for an entity."""
        routes = {
            "address": "address",
            "transaction": "tx",
            "block": "block",
            "token": "token",
        }
        route = routes.get(kind, kind)
        return f"{self.base_url}/{route}/{identifier}"

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "api_path": self.api_path,
            "supports_contract": self.supports_contract,
            "supports_token": self.supports_token,
        }


EXPLORER_PROVIDERS = {
    "etherscan": ExplorerProvider("etherscan", "https://etherscan.io"),
    "bscscan": ExplorerProvider("bscscan", "https://bscscan.com"),
    "polygonscan": ExplorerProvider("polygonscan", "https://polygonscan.com"),
    "arbiscan": ExplorerProvider("arbiscan", "https://arbiscan.io"),
    "basescan": ExplorerProvider("basescan", "https://basescan.org"),
    "blockscout": ExplorerProvider("blockscout", "https://blockscout.com"),
    "oklink": ExplorerProvider("oklink", "https://www.oklink.com"),
    "routescan": ExplorerProvider("routescan", "https://routescan.io"),
}


class ExplorerClient(BaseChainClient):
    """Normalized lookup client over any explorer provider."""

    provider = "explorer"
    capability = "explorer"

    def __init__(self, *, provider: str = "etherscan", chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self.explorer = EXPLORER_PROVIDERS.get(provider)
        if self.explorer is None:
            raise ChainValidationError(f"unknown explorer provider {provider!r}")

    # -- provider hook -------------------------------------------------------- #

    def _lookup(self, kind: str, identifier: str) -> Mapping[str, Any]:
        raise NotImplementedError

    # -- capabilities --------------------------------------------------------- #

    def lookup(self, kind: str, identifier: str) -> Dict[str, Any]:
        """Look up ``address|transaction|contract|token|block``."""
        if kind not in ("address", "transaction", "contract", "token", "block"):
            raise ChainValidationError(f"unknown lookup kind {kind!r}")
        if kind in ("address", "contract", "token"):
            identifier = normalize_address(identifier) if identifier.startswith("0x") else identifier
        record = self._lookup(kind, identifier)
        return {
            "kind": kind,
            "identifier": identifier,
            "provider": self.explorer.name,
            "url": self.explorer.url_for(kind, identifier),
            "record": dict(record),
        }

    def address_lookup(self, address: str) -> Dict[str, Any]:
        return self.lookup("address", address)

    def transaction_lookup(self, tx_hash: str) -> Dict[str, Any]:
        return self.lookup("transaction", tx_hash)

    def contract_lookup(self, address: str) -> Dict[str, Any]:
        return self.lookup("contract", address)

    def token_lookup(self, address: str) -> Dict[str, Any]:
        return self.lookup("token", address)

    def block_lookup(self, number: int) -> Dict[str, Any]:
        return self.lookup("block", str(number))

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method in ("lookup", "address_lookup", "transaction_lookup", "contract_lookup", "token_lookup", "block_lookup"):
                if method == "lookup":
                    data = self.lookup(str(params.get("kind", "")), str(params.get("identifier", "")))
                else:
                    field_name = params.get("address") or params.get("hash") or params.get("number") or params.get("identifier")
                    data = getattr(self, method)(field_name if field_name is not None else "")
            else:
                raise ChainValidationError(f"unknown explorer method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalExplorer(ExplorerClient):
    """Deterministic offline explorer: known entities resolve to stable records."""

    provider = "local-explorer"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(provider="etherscan", chain_id=chain_id, logger=logger)
        self._records: Dict[str, Dict[str, Any]] = {}
        self._tx: Dict[str, Dict[str, Any]] = {}

    def seed_address(self, address: str, *, label: str = "", balance_wei: int = 0, tx_count: int = 0) -> None:
        self._records[normalize_address(address)] = {
            "address": normalize_address(address),
            "label": label,
            "balance_wei": balance_wei,
            "transaction_count": tx_count,
        }

    def seed_transaction(self, tx_hash: str, **fields: Any) -> None:
        self._tx[tx_hash] = dict(fields)

    def _lookup(self, kind: str, identifier: str) -> Mapping[str, Any]:
        if kind == "transaction":
            record = self._tx.get(identifier)
            return record or {"status": "not_found", "hash": identifier}
        if kind in ("address", "contract", "token"):
            address = normalize_address(identifier)
            if kind == "contract":
                record = self._records.get(address) or {"address": address}
                return {**record, "is_contract": True}
            if kind == "token":
                record = self._records.get(address) or {"address": address}
                return {**record, "token": True}
            return self._records.get(address) or {"address": address, "label": "", "balance_wei": 0, "transaction_count": 0}
        if kind == "block":
            return {"number": int(identifier), "status": "ok"}
        raise ChainValidationError(f"unknown lookup kind {kind!r}")