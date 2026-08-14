"""
Tools :: Blockchain :: Bridge
=============================

Cross-chain bridge abstractions: route discovery, transfer creation,
transfer status and supported bridge protocols.

Local transfers are simulated deterministically; real bridge backends
override client hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import normalize_address

__all__ = [
    "BridgeProtocol",
    "BridgeRoute",
    "BridgeTransfer",
    "BridgeClient",
    "LocalBridge",
]

_BRIDGE_PROTOCOLS = (
    "hop", "arbitrum-bridge", "optimism-bridge", "polygon-bridge",
    "wormhole", "axelar", "layerzero", "across",
)
_BRIDGE_STATES = {"pending", "locked", "finalized", "failed"}


@dataclass
class BridgeProtocol:
    """Descriptor of one bridge service."""

    name: str
    chains: List[int] = field(default_factory=list)
    asset_support: List[str] = field(default_factory=list)
    fee_pct: float = 0.1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "chains": list(self.chains),
            "asset_support": list(self.asset_support),
            "fee_pct": self.fee_pct,
        }


@dataclass
class BridgeRoute:
    """A source->destination route."""

    protocol: str
    from_chain: int
    to_chain: int
    asset: str = "ETH"
    estimated_time_seconds: int = 600
    fee_pct: float = 0.1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "from_chain": self.from_chain,
            "to_chain": self.to_chain,
            "asset": self.asset,
            "estimated_time_seconds": self.estimated_time_seconds,
            "fee_pct": self.fee_pct,
        }


@dataclass
class BridgeTransfer:
    """A cross-chain transfer record."""

    transfer_id: str
    protocol: str
    from_chain: int
    to_chain: int
    asset: str = "ETH"
    amount: float = 0.0
    status: str = "pending"
    from_address: str = ""
    to_address: str = ""
    source_tx: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "protocol": self.protocol,
            "from_chain": self.from_chain,
            "to_chain": self.to_chain,
            "asset": self.asset,
            "amount": self.amount,
            "status": self.status,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "source_tx": self.source_tx,
        }


class BridgeClient(BaseChainClient):
    """Bridge service: protocols, routes, transfers."""

    provider = "bridge"
    capability = "bridge"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)

    # -- provider hooks -------------------------------------------------------- #

    def _protocols(self) -> List[BridgeProtocol]:
        raise NotImplementedError

    def _routes(self, from_chain: int, to_chain: int, asset: str) -> List[BridgeRoute]:
        return []

    def _create(self, route: BridgeRoute, amount: float, from_address: str, to_address: str) -> BridgeTransfer:
        raise NotImplementedError

    def _status(self, transfer_id: str) -> Optional[BridgeTransfer]:
        raise NotImplementedError

    # -- capabilities ---------------------------------------------------------- #

    def protocols(self) -> List[BridgeProtocol]:
        return self._protocols()

    def routes(self, from_chain: int, to_chain: int, asset: str = "ETH") -> List[BridgeRoute]:
        return self._routes(int(from_chain), int(to_chain), asset.upper())

    def create(self, route: BridgeRoute, amount: float, from_address: str, to_address: str) -> BridgeTransfer:
        if route.from_chain == route.to_chain:
            raise ChainValidationError("source and destination chains must differ")
        if float(amount) <= 0:
            raise ChainValidationError("transfer amount must be positive")
        return self._create(route, float(amount), normalize_address(from_address), normalize_address(to_address))

    def status(self, transfer_id: str) -> BridgeTransfer:
        transfer = self._status(transfer_id)
        if transfer is None:
            raise ChainValidationError(f"transfer {transfer_id} not found")
        return transfer

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "protocols":
                data = {"protocols": [proto.as_dict() for proto in self.protocols()]}
            elif method == "routes":
                data = {
                    "routes": [route.as_dict() for route in self.routes(int(params["from_chain"]), int(params["to_chain"]), str(params.get("asset", "ETH")))],
                }
            elif method == "create":
                data = self.create(
                    BridgeRoute(**params.get("route", {})),
                    float(params.get("amount", 0)),
                    str(params.get("from_address", "")),
                    str(params.get("to_address", "")),
                ).as_dict()
            elif method == "status":
                data = self.status(str(params["transfer_id"])).as_dict()
            else:
                raise ChainValidationError(f"unknown bridge method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalBridge(BridgeClient):
    """Deterministic offline bridge simulation."""

    provider = "local-bridge"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._protocol_log: Optional[List[BridgeProtocol]] = None
        self._transfers: Dict[str, BridgeTransfer] = {}
        self._next_id = 0

    def seed_protocols(self, protocols: Sequence[BridgeProtocol]) -> None:
        self._protocol_log = list(protocols)

    def _protocols(self) -> List[BridgeProtocol]:
        if self._protocol_log is not None:
            return list(self._protocol_log)
        return [BridgeProtocol(name=name, chains=[1, 137], asset_support=["ETH", "USDC"]) for name in _BRIDGE_PROTOCOLS]

    def _routes(self, from_chain: int, to_chain: int, asset: str) -> List[BridgeRoute]:
        return [
            BridgeRoute(protocol=name, from_chain=from_chain, to_chain=to_chain, asset=asset)
            for name in ("hop", "wormhole", "across")
        ]

    def _create(self, route: BridgeRoute, amount: float, from_address: str, to_address: str) -> BridgeTransfer:
        self._next_id += 1
        transfer = BridgeTransfer(
            transfer_id=f"bridge-{self._next_id:04d}",
            protocol=route.protocol,
            from_chain=route.from_chain,
            to_chain=route.to_chain,
            asset=route.asset,
            amount=amount,
            status="pending",
            from_address=from_address,
            to_address=to_address,
            source_tx="0x" + f"{self._next_id:064x}",
        )
        self._transfers[transfer.transfer_id] = transfer
        return transfer

    def _status(self, transfer_id: str) -> Optional[BridgeTransfer]:
        transfer = self._transfers.get(transfer_id)
        if transfer is None:
            return None
        transfer.status = "finalized"
        return transfer