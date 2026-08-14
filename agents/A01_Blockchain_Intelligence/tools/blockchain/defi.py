"""
Tools :: Blockchain :: DeFi
===========================

DeFi primitives: protocol descriptors, liquidity positions, lending
positions, yields and swap quotes.

All local computations are deterministic approximations intended for
analysis; live quotes require a backend hook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import normalize_address

__all__ = [
    "ProtocolInfo",
    "LiquidityPosition",
    "LendingPosition",
    "YieldInfo",
    "SwapQuote",
    "DefiClient",
    "LocalDefi",
]

_KNOWN_PROTOCOLS = {
    "uniswap_v3": "Uniswap V3",
    "uniswap_v2": "Uniswap V2",
    "aave_v3": "Aave V3",
    "curve": "Curve Finance",
    "pancakeswap": "PancakeSwap",
    "lido": "Lido Staking",
    "compound": "Compound",
    "maker": "MakerDAO",
}


@dataclass
class ProtocolInfo:
    """Descriptor of a DeFi protocol."""

    name: str
    kind: str = "dex"
    chain_ids: List[int] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "chain_ids": list(self.chain_ids),
            "categories": list(self.categories),
        }


@dataclass
class LiquidityPosition:
    """A user's LP position."""

    protocol: str
    pool: str
    amount0: float = 0.0
    amount1: float = 0.0
    symbol0: str = "ETH"
    symbol1: str = "USDC"
    fee_tier: int = 3000
    value_usd: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "pool": self.pool,
            "amount0": self.amount0,
            "amount1": self.amount1,
            "symbol0": self.symbol0,
            "symbol1": self.symbol1,
            "fee_tier": self.fee_tier,
            "value_usd": self.value_usd,
        }


@dataclass
class LendingPosition:
    """A user's borrow/supply position."""

    protocol: str
    asset: str = "USDC"
    supplied: float = 0.0
    borrowed: float = 0.0
    apy: float = 0.0
    health_factor: float = 1.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "asset": self.asset,
            "supplied": self.supplied,
            "borrowed": self.borrowed,
            "apy": self.apy,
            "health_factor": self.health_factor,
        }


@dataclass
class YieldInfo:
    """A yield opportunity."""

    protocol: str
    asset: str
    apy: float = 0.0
    tvl_usd: float = 0.0
    risk: str = "low"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "asset": self.asset,
            "apy": self.apy,
            "tvl_usd": self.tvl_usd,
            "risk": self.risk,
        }


@dataclass
class SwapQuote:
    """A swap estimate."""

    from_symbol: str
    to_symbol: str
    amount_in: float = 0.0
    amount_out: float = 0.0
    price_impact_pct: float = 0.0
    fee_pct: float = 0.3
    route: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_symbol,
            "to": self.to_symbol,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "price_impact_pct": self.price_impact_pct,
            "fee_pct": self.fee_pct,
            "route": list(self.route),
        }


class DefiClient(BaseChainClient):
    """DeFi service: protocols, positions, yields, quotes."""

    provider = "defi"
    capability = "defi"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)

    # -- provider hooks -------------------------------------------------------- #

    def _protocols(self) -> List[ProtocolInfo]:
        raise NotImplementedError

    def _liquidity(self, address: str) -> List[LiquidityPosition]:
        return []

    def _lending(self, address: str) -> List[LendingPosition]:
        return []

    def _yields(self) -> List[YieldInfo]:
        return []

    def _quote(self, from_symbol: str, to_symbol: str, amount_in: float) -> Optional[SwapQuote]:
        return None

    # -- capabilities ---------------------------------------------------------- #

    def protocols(self) -> List[ProtocolInfo]:
        return self._protocols()

    def positions(self, address: str) -> Dict[str, List[Any]]:
        address = normalize_address(address)
        return {
            "liquidity": [pos.as_dict() for pos in self._liquidity(address)],
            "lending": [pos.as_dict() for pos in self._lending(address)],
        }

    def yields(self) -> List[YieldInfo]:
        return self._yields()

    def quote(self, from_symbol: str, to_symbol: str, amount_in: float) -> SwapQuote:
        quote = self._quote(from_symbol.upper(), to_symbol.upper(), float(amount_in))
        if quote is None:
            raise ChainValidationError(f"no route for {from_symbol}->{to_symbol}")
        return quote

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "protocols":
                data = {"protocols": [proto.as_dict() for proto in self.protocols()]}
            elif method == "positions":
                data = self.positions(str(params["address"]))
            elif method == "yields":
                data = {"yields": [yield_info.as_dict() for yield_info in self.yields()]}
            elif method == "quote":
                data = self.quote(str(params["from"]), str(params["to"]), float(params.get("amount_in", 1.0))).as_dict()
            else:
                raise ChainValidationError(f"unknown defi method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalDefi(DefiClient):
    """Deterministic offline DeFi snapshot."""

    provider = "local-defi"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._liquidity_log: Dict[str, List[LiquidityPosition]] = {}
        self._lending_log: Dict[str, List[LendingPosition]] = {}
        self._yield_log: List[YieldInfo] = []
        self._rates: Dict[str, Dict[str, float]] = {}

    def seed_liquidity(self, address: str, position: LiquidityPosition) -> None:
        self._liquidity_log.setdefault(normalize_address(address), []).append(position)

    def seed_lending(self, address: str, position: LendingPosition) -> None:
        self._lending_log.setdefault(normalize_address(address), []).append(position)

    def seed_yield(self, yield_info: YieldInfo) -> None:
        self._yield_log.append(yield_info)

    def set_rate(self, symbol: str, price_usd: float) -> None:
        self._rates[symbol.upper()] = float(price_usd)

    def _protocols(self) -> List[ProtocolInfo]:
        return [
            ProtocolInfo(name=name, kind="dex" if "v3" in name or "curve" in name or "swap" in name else "lending", chain_ids=[1, 137])
            for name in _KNOWN_PROTOCOLS.values()
        ]

    def _liquidity(self, address: str) -> List[LiquidityPosition]:
        return self._liquidity_log.get(address, [])

    def _lending(self, address: str) -> List[LendingPosition]:
        return self._lending_log.get(address, [])

    def _yields(self) -> List[YieldInfo]:
        return list(self._yield_log)

    def _quote(self, from_symbol: str, to_symbol: str, amount_in: float) -> Optional[SwapQuote]:
        rate_in = self._rates.get(from_symbol)
        rate_out = self._rates.get(to_symbol)
        if rate_in is None or rate_out is None or rate_in <= 0:
            return None
        amount_out = amount_in * rate_in / rate_out
        price_impact = min(100.0, amount_in * 0.01)
        return SwapQuote(
            from_symbol=from_symbol,
            to_symbol=to_symbol,
            amount_in=amount_in,
            amount_out=round(amount_out, 8),
            price_impact_pct=round(price_impact, 4),
            fee_pct=0.3,
            route=[from_symbol, to_symbol],
        )