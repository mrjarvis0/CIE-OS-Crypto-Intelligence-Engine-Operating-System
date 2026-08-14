"""
Tools :: Blockchain :: NFT
==========================

ERC-721 / ERC-1155 NFT metadata, ownership, transfers and collections.

Local resolution uses deterministic token URI and metadata generation;
backends override client hooks for on-chain data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import normalize_address

__all__ = [
    "NFTMetadata",
    "NFTAsset",
    "NFTCollection",
    "NFTClient",
    "LocalNFT",
]

_ERC_STANDARDS = {"ERC721", "ERC1155"}


@dataclass
class NFTMetadata:
    """Token metadata (tokenURI payload)."""

    name: str
    description: str = ""
    image: str = ""
    attributes: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "image": self.image,
            "attributes": list(self.attributes),
        }


@dataclass
class NFTAsset:
    """One owned NFT."""

    token_id: int
    contract_address: str
    standard: str = "ERC721"
    metadata: Optional[NFTMetadata] = None
    balance: int = 1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "contract": self.contract_address,
            "standard": self.standard,
            "metadata": self.metadata.as_dict() if self.metadata else None,
            "balance": self.balance,
        }


@dataclass
class NFTCollection:
    """Descriptor for an NFT contract."""

    address: str
    name: str
    symbol: str = ""
    standard: str = "ERC721"
    total_supply: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "name": self.name,
            "symbol": self.symbol,
            "standard": self.standard,
            "total_supply": self.total_supply,
        }


class NFTClient(BaseChainClient):
    """NFT service: collections, assets, metadata."""

    provider = "nft"
    capability = "nft"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)

    # -- provider hooks -------------------------------------------------------- #

    def _collection(self, address: str) -> Optional[NFTCollection]:
        raise NotImplementedError

    def _assets(self, address: str, limit: int) -> List[NFTAsset]:
        return []

    def _metadata(self, collection: NFTCollection, token_id: int) -> Optional[NFTMetadata]:
        return None

    # -- capabilities ---------------------------------------------------------- #

    def collection(self, address: str) -> NFTCollection:
        collection = self._collection(normalize_address(address))
        if collection is None:
            raise ChainValidationError(f"collection {address} not found")
        return collection

    def assets(self, address: str, limit: int = 25) -> List[NFTAsset]:
        return self._assets(normalize_address(address), max(1, min(int(limit), 100)))

    def metadata(self, collection_address: str, token_id: int) -> NFTMetadata:
        collection = self.collection(collection_address)
        metadata = self._metadata(collection, int(token_id))
        if metadata is None:
            raise ChainValidationError(f"metadata for token {token_id} not found")
        return metadata

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "collection":
                data = self.collection(str(params["address"])).as_dict()
            elif method == "assets":
                data = {
                    "address": str(params["address"]),
                    "assets": [asset.as_dict() for asset in self.assets(str(params["address"]), int(params.get("limit", 25)))],
                }
            elif method == "metadata":
                data = self.metadata(str(params["address"]), int(params["token_id"])).as_dict()
            else:
                raise ChainValidationError(f"unknown nft method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalNFT(NFTClient):
    """Deterministic offline NFT registry."""

    provider = "local-nft"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._collections: Dict[str, NFTCollection] = {}
        self._owned: Dict[str, List[NFTAsset]] = {}
        self._meta: Dict[str, Dict[int, NFTMetadata]] = {}

    def seed_collection(self, address: str, *, name: str, symbol: str = "", standard: str = "ERC721", total_supply: int = 0) -> None:
        if standard not in _ERC_STANDARDS:
            raise ChainValidationError(f"unsupported NFT standard {standard!r}")
        self._collections[normalize_address(address)] = NFTCollection(
            address=normalize_address(address), name=name, symbol=symbol, standard=standard, total_supply=total_supply,
        )

    def seed_asset(self, owner: str, asset: NFTAsset) -> None:
        self._owned.setdefault(normalize_address(owner), []).append(asset)
        self._meta.setdefault(normalize_address(asset.contract_address), {})[asset.token_id] = asset.metadata

    def _collection(self, address: str) -> Optional[NFTCollection]:
        return self._collections.get(normalize_address(address))

    def _assets(self, address: str, limit: int) -> List[NFTAsset]:
        return self._owned.get(address, [])[-limit:]

    def _metadata(self, collection: NFTCollection, token_id: int) -> Optional[NFTMetadata]:
        return self._meta.get(normalize_address(collection.address), {}).get(token_id)