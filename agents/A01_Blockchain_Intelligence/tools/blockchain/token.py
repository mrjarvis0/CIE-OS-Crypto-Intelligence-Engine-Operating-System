"""
Tools :: Blockchain :: Token
============================

ERC-20 token metadata, balances, transfers and price lookups.

Local implementations resolve a static registry of well-known tokens and
deterministic transfers; RPC backends override client hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import normalize_address

__all__ = [
    "TokenInfo",
    "TokenTransfer",
    "TokenClient",
    "LocalToken",
    "WELL_KNOWN_TOKENS",
    "token_of",
]

_WELL_KNOWN: Dict[str, Dict[str, Any]] = {
    "0x" + "11" * 20: {"symbol": "WETH", "name": "Wrapped Ether", "decimals": 18},
    "0x" + "22" * 20: {"symbol": "USDC", "name": "USD Coin", "decimals": 6},
    "0x" + "33" * 20: {"symbol": "USDT", "name": "Tether USD", "decimals": 6},
    "0x" + "44" * 20: {"symbol": "DAI", "name": "Dai Stablecoin", "decimals": 18},
    "0x" + "55" * 20: {"symbol": "LINK", "name": "Chainlink", "decimals": 18},
    "0x" + "66" * 20: {"symbol": "UNI", "name": "Uniswap", "decimals": 18},
    "0x" + "77" * 20: {"symbol": "AAVE", "name": "Aave", "decimals": 18},
    "0x" + "88" * 20: {"symbol": "WBTC", "name": "Wrapped Bitcoin", "decimals": 8},
}

WELL_KNOWN_TOKENS: Dict[str, Dict[str, Any]] = _WELL_KNOWN


def token_of(address: str) -> Optional[Dict[str, Any]]:
    """Resolve well-known token metadata, or ``None``."""
    return _WELL_KNOWN.get(normalize_address(address))


@dataclass
class TokenInfo:
    """ERC-20 descriptor."""

    address: str
    symbol: str
    name: str = ""
    decimals: int = 18
    total_supply: int = 0
    price_usd: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "symbol": self.symbol,
            "name": self.name,
            "decimals": self.decimals,
            "total_supply": self.total_supply,
            "price_usd": self.price_usd,
        }


@dataclass
class TokenTransfer:
    """One ERC-20 transfer event."""

    token_address: str
    symbol: str
    from_address: str
    to_address: str
    amount: int = 0
    decimals: int = 18
    tx_hash: str = ""
    block_number: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token_address,
            "symbol": self.symbol,
            "from": self.from_address,
            "to": self.to_address,
            "amount": self.amount,
            "decimals": self.decimals,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
        }


class TokenClient(BaseChainClient):
    """Token service: metadata, balances, transfers, prices."""

    provider = "token"
    capability = "token"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)

    # -- provider hooks -------------------------------------------------------- #

    def _info(self, address: str) -> Optional[TokenInfo]:
        raise NotImplementedError

    def _balance(self, address: str, token_address: str) -> int:
        raise NotImplementedError

    def _transfers(self, address: str, limit: int) -> List[TokenTransfer]:
        return []

    def _price(self, symbol: str) -> float:
        return 0.0

    # -- capabilities ---------------------------------------------------------- #

    def info(self, address: str) -> TokenInfo:
        token = self._info(normalize_address(address))
        if token is None:
            raise ChainValidationError(f"token {address} not found")
        return token

    def balance(self, address: str, token_address: str) -> int:
        return int(self._balance(normalize_address(address), normalize_address(token_address)))

    def transfers(self, address: str, limit: int = 25) -> List[TokenTransfer]:
        return self._transfers(normalize_address(address), max(1, min(int(limit), 100)))

    def price(self, symbol: str) -> float:
        return float(self._price(symbol.upper()))

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "info":
                data = self.info(str(params["address"])).as_dict()
            elif method == "balance":
                data = {
                    "address": str(params["address"]),
                    "token": str(params.get("token_address", "")),
                    "balance": self.balance(str(params["address"]), str(params.get("token_address", ""))),
                }
            elif method == "transfers":
                data = {
                    "address": str(params["address"]),
                    "transfers": [tx.as_dict() for tx in self.transfers(str(params["address"]), int(params.get("limit", 25)))],
                }
            elif method == "price":
                data = {"symbol": str(params["symbol"]), "price_usd": self.price(str(params["symbol"]))}
            else:
                raise ChainValidationError(f"unknown token method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalToken(TokenClient):
    """Deterministic offline token service seeded from the well-known registry."""

    provider = "local-token"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._overrides: Dict[str, TokenInfo] = {}
        self._balances: Dict[str, Dict[str, int]] = {}
        self._transfer_log: Dict[str, List[TokenTransfer]] = {}
        self._prices: Dict[str, float] = {}

    def seed(self, address: str, *, symbol: str, name: str = "", decimals: int = 18, total_supply: int = 0, price_usd: float = 0.0) -> None:
        self._overrides[normalize_address(address)] = TokenInfo(
            address=normalize_address(address), symbol=symbol, name=name, decimals=decimals,
            total_supply=total_supply, price_usd=price_usd,
        )

    def seed_balance(self, address: str, token_address: str, amount: int) -> None:
        self._balances.setdefault(normalize_address(address), {})[normalize_address(token_address)] = int(amount)

    def seed_transfer(self, transfer: TokenTransfer) -> None:
        self._transfer_log.setdefault(transfer.from_address, []).append(transfer)
        self._transfer_log.setdefault(transfer.to_address, []).append(transfer)

    def set_price(self, symbol: str, price_usd: float) -> None:
        self._prices[symbol.upper()] = float(price_usd)

    def _info(self, address: str) -> Optional[TokenInfo]:
        address = normalize_address(address)
        known = _WELL_KNOWN.get(address)
        if known is None:
            return self._overrides.get(address)
        override = self._overrides.get(address)
        if override is not None:
            return override
        return TokenInfo(address=address, **known)

    def _balance(self, address: str, token_address: str) -> int:
        return self._balances.get(normalize_address(address), {}).get(normalize_address(token_address), 0)

    def _transfers(self, address: str, limit: int) -> List[TokenTransfer]:
        return self._transfer_log.get(address, [])[-limit:]

    def _price(self, symbol: str) -> float:
        return self._prices.get(symbol.upper(), 0.0)