"""
Tools :: Blockchain :: EVM
==========================

Shared implementation for every EVM-compatible chain.

This is the foundation module of the blockchain layer: address validation,
ABI encoding/decoding, function/event signature derivation, transaction
building, block/log parsing and the built-in chain registry.

All hashing here is deterministic and stdlib-only (SHA-256 based). A real
provider-facing implementation must substitute Keccak-256 for
``signature_hash``; the local approximation is sufficient for offline
analysis, tests and selector bookkeeping.
"""

from __future__ import annotations

import hashlib
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient

__all__ = [
    "is_address",
    "normalize_address",
    "validate_address",
    "signature_hash",
    "function_selector",
    "event_topic",
    "abi_encode",
    "abi_decode",
    "decode_types",
    "build_transaction",
    "compute_contract_address",
    "parse_block",
    "parse_log",
    "CHAIN_REGISTRY",
    "get_chain",
    "ChainInfo",
    "EVMFacade",
    "sha3_256",
]

_HEX_RE = frozenset("0123456789abcdefABCDEF")


# --------------------------------------------------------------------------- #
# Hashing (deterministic local approximation of Keccak-256)
# --------------------------------------------------------------------------- #


def sha3_256(data: bytes) -> bytes:
    """Deterministic 32-byte digest.

    The real EVM uses Keccak-256; this local substitute uses SHA-256 so the
    layer runs stdlib-only. Provider implementations must override this with
    the true Keccak-256.
    """
    return hashlib.sha256(data).digest()


def signature_hash(signature: str) -> str:
    """32-byte hex topic/selector base for an ABI signature string."""
    return "0x" + sha3_256(signature.encode("utf-8")).hex()


def function_selector(signature: str) -> str:
    """4-byte function selector (``0x`` + 8 hex chars)."""
    return signature_hash(signature)[:10]


def event_topic(signature: str) -> str:
    """32-byte event topic for a log signature."""
    return signature_hash(signature)


# --------------------------------------------------------------------------- #
# Addresses
# --------------------------------------------------------------------------- #


def normalize_address(address: str) -> str:
    """Lower-case, 0x-prefixed 40-hex canonical form."""
    value = (address or "").strip()
    if value.startswith("0x") or value.startswith("0X"):
        value = value[2:]
    if len(value) != 40 or any(ch not in _HEX_RE for ch in value):
        raise ChainValidationError(f"invalid EVM address length: {address!r}")
    return "0x" + value.lower()


def is_address(address: str) -> bool:
    try:
        normalize_address(address)
        return True
    except ChainValidationError:
        return False


def validate_address(address: str) -> str:
    """Normalize or raise :class:`ChainValidationError`."""
    return normalize_address(address)


# --------------------------------------------------------------------------- #
# ABI encoding (subset sufficient for common read/write calls)
# --------------------------------------------------------------------------- #

_BOOL_OPCODES = "01"


def _encode_single(type_name: str, value: Any) -> bytes:
    type_name = type_name.strip()
    if type_name == "bool":
        return (b"\x00" * 31) + (b"\x01" if value else b"\x00")
    if type_name == "address":
        return b"\x00" * 12 + bytes.fromhex(normalize_address(str(value))[2:])
    if type_name == "bytes32":
        raw = str(value)
        if raw.startswith("0x"):
            payload = bytes.fromhex(raw[2:].zfill(64)[:64] if len(raw[2:]) <= 64 else raw[2:])
        else:
            payload = raw.encode("utf-8")
        return payload[:32].ljust(32, b"\x00")
    if type_name == "string":
        payload = str(value).encode("utf-8")
        head = struct.pack(">I", 32)  # static offset placeholder (single arg)
        return head + struct.pack(">I", len(payload)) + payload + b"\x00" * ((32 - len(payload) % 32) % 32)
    if type_name.startswith("uint") or type_name == "int":
        bits = int(type_name[4:]) if type_name.startswith("uint") else 256
        if bits > 256:
            raise ChainValidationError(f"unsupported width: {type_name}")
        return int(value).to_bytes(32, "big", signed=type_name.startswith("int"))
    if type_name.startswith("int"):
        bits = int(type_name[3:])
        return int(value).to_bytes(32, "big", signed=True)
    raise ChainValidationError(f"unsupported abi type: {type_name!r}")


def abi_encode(types: Sequence[str], values: Sequence[Any]) -> str:
    """ABI-encode a call argument list to a hex string."""
    if len(types) != len(values):
        raise ChainValidationError("types/values length mismatch")
    encoded = b""
    for type_name, value in zip(types, values):
        encoded += _encode_single(type_name, value)
    return "0x" + encoded.hex()


def abi_decode(types: Sequence[str], data: str) -> List[Any]:
    """Decode a hex payload into typed values (static subset)."""
    raw = data[2:] if data.startswith("0x") else data
    if len(raw) % 64 != 0:
        raise ChainValidationError("abi payload must be a multiple of 32 bytes")
    body = bytes.fromhex(raw)
    offset = 0
    decoded: List[Any] = []
    for type_name in types:
        type_name = type_name.strip()
        chunk = body[offset : offset + 32]
        if len(chunk) < 32:
            raise ChainValidationError("truncated abi payload")
        if type_name == "bool":
            decoded.append(chunk[31] != 0)
        elif type_name == "address":
            decoded.append("0x" + chunk[12:].hex())
        elif type_name == "bytes32":
            decoded.append("0x" + chunk.hex())
        elif type_name == "string":
            length = struct.unpack(">I", body[offset + 32 : offset + 64])[0] if len(body) >= offset + 64 else 0
            decoded.append(body[offset + 64 : offset + 64 + length].decode("utf-8", errors="replace"))
            offset += (length + 31) // 32  # advance past the dynamic payload
        elif type_name.startswith("uint") or type_name.startswith("int"):
            decoded.append(int.from_bytes(chunk, "big", signed=type_name.startswith("int")))
        else:
            raise ChainValidationError(f"unsupported abi type: {type_name!r}")
        offset += 32
    return decoded


def decode_types(types: Sequence[str], data: str) -> List[Any]:
    return abi_decode(types, data)


# --------------------------------------------------------------------------- #
# Transactions / contracts
# --------------------------------------------------------------------------- #


@dataclass
class Transaction:
    """Normalized EVM transaction."""

    hash: str = ""
    from_addr: str = ""
    to_addr: str = ""
    value: int = 0
    data: str = "0x"
    nonce: int = 0
    gas: int = 21000
    gas_price: int = 0
    chain_id: int = 1
    input_decoded: Optional[List[Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hash": self.hash,
            "from": self.from_addr,
            "to": self.to_addr,
            "value": self.value,
            "data": self.data,
            "nonce": self.nonce,
            "gas": self.gas,
            "gas_price": self.gas_price,
            "chain_id": self.chain_id,
            "input_decoded": self.input_decoded,
        }


def build_transaction(
    *,
    to: str,
    value: int = 0,
    data: str = "0x",
    nonce: int = 0,
    gas: int = 21000,
    gas_price: int = 0,
    chain_id: int = 1,
    from_addr: str = "",
) -> Transaction:
    """Build a normalized transaction (no signing)."""
    return Transaction(
        from_addr=normalize_address(from_addr) if from_addr else "",
        to_addr=normalize_address(to),
        value=int(value),
        data=data if data.startswith("0x") else "0x" + data,
        nonce=int(nonce),
        gas=int(gas),
        gas_price=int(gas_price),
        chain_id=int(chain_id),
    )


def compute_contract_address(deployer: str, nonce: int) -> str:
    """CREATE-address derivation (keccak approximation)."""
    deployer_bytes = bytes.fromhex(normalize_address(deployer)[2:])
    rlp_like = b"\xd6\x94" + deployer_bytes + bytes([nonce])
    digest = sha3_256(rlp_like)[12:]
    return "0x" + digest.hex()


# --------------------------------------------------------------------------- #
# Blocks / logs
# --------------------------------------------------------------------------- #


def parse_block(block: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a raw block mapping into a stable shape."""
    return {
        "number": int(block.get("number", 0)),
        "hash": str(block.get("hash", "")),
        "parent_hash": str(block.get("parent_hash", "")),
        "timestamp": int(block.get("timestamp", 0)),
        "transactions": list(block.get("transactions", [])),
        "gas_used": int(block.get("gas_used", 0)),
        "gas_limit": int(block.get("gas_limit", 0)),
        "base_fee": int(block.get("base_fee", 0)),
    }


def parse_log(log: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a raw event log into a stable shape."""
    return {
        "address": str(log.get("address", "")),
        "topics": list(log.get("topics", [])),
        "data": str(log.get("data", "0x")),
        "block_number": int(log.get("block_number", 0)),
        "transaction_hash": str(log.get("transaction_hash", "")),
        "log_index": int(log.get("log_index", 0)),
    }


# --------------------------------------------------------------------------- #
# Chain registry
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChainInfo:
    """Static metadata about a supported chain."""

    chain_id: int
    name: str
    symbol: str
    native_decimals: int = 18
    explorer: str = ""
    rpc: str = ""
    testnet: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "symbol": self.symbol,
            "native_decimals": self.native_decimals,
            "explorer": self.explorer,
            "rpc": self.rpc,
            "testnet": self.testnet,
        }


CHAIN_REGISTRY: Dict[int, ChainInfo] = {
    1: ChainInfo(1, "Ethereum Mainnet", "ETH", explorer="https://etherscan.io", rpc="https://eth.llamarpc.com"),
    10: ChainInfo(10, "Optimism", "ETH", explorer="https://optimistic.etherscan.io", rpc="https://mainnet.optimism.io"),
    56: ChainInfo(56, "BNB Chain", "BNB", explorer="https://bscscan.com", rpc="https://bsc-dataseed.binance.org"),
    137: ChainInfo(137, "Polygon", "POL", explorer="https://polygonscan.com", rpc="https://polygon-rpc.com"),
    42161: ChainInfo(42161, "Arbitrum One", "ETH", explorer="https://arbiscan.io", rpc="https://arb1.arbitrum.io/rpc"),
    8453: ChainInfo(8453, "Base", "ETH", explorer="https://basescan.org", rpc="https://mainnet.base.org"),
    43114: ChainInfo(43114, "Avalanche C-Chain", "AVAX", explorer="https://snowtrace.io", rpc="https://api.avax.network/ext/bc/C/rpc"),
    59144: ChainInfo(59144, "Linea", "ETH", explorer="https://lineascan.build", rpc="https://rpc.linea.build"),
    534352: ChainInfo(534352, "Scroll", "ETH", explorer="https://scrollscan.com", rpc="https://rpc.scroll.io"),
    324: ChainInfo(324, "zkSync Era", "ETH", explorer="https://explorer.zksync.io", rpc="https://mainnet.era.zksync.io"),
    11155111: ChainInfo(11155111, "Sepolia", "ETH", explorer="https://sepolia.etherscan.io", rpc="https://rpc.sepolia.org", testnet=True),
    17000: ChainInfo(17000, "Holesky", "ETH", explorer="https://holesky.etherscan.io", rpc="https://ethereum-holesky.publicnode.com", testnet=True),
    5: ChainInfo(5, "Goerli", "ETH", explorer="https://goerli.etherscan.io", rpc="https://rpc.ankr.com/eth_goerli", testnet=True),
}


def get_chain(chain_id: int) -> ChainInfo:
    """Look up chain metadata; raises :class:`ChainUnsupportedError`."""
    chain = CHAIN_REGISTRY.get(int(chain_id))
    if chain is None:
        from . import ChainUnsupportedError

        raise ChainUnsupportedError(f"unsupported chain id {chain_id}", chain_id=int(chain_id))
    return chain


# --------------------------------------------------------------------------- #
# Facade
# --------------------------------------------------------------------------- #


class EVMFacade(BaseChainClient):
    """EVM foundation client: chains, addresses, ABI and transaction building."""

    provider = "evm"
    capability = "evm"

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "is_address":
                data = is_address(str(params.get("address", "")))
            elif method == "normalize_address":
                data = normalize_address(str(params.get("address", "")))
            elif method == "get_chain":
                data = get_chain(int(params.get("chain_id", self._chain_id))).as_dict()
            elif method == "function_selector":
                data = function_selector(str(params.get("signature", "")))
            elif method == "abi_encode":
                data = abi_encode(list(params.get("types", [])), list(params.get("values", [])))
            elif method == "abi_decode":
                data = abi_decode(list(params.get("types", [])), str(params.get("data", "0x")))
            elif method == "compute_contract_address":
                data = compute_contract_address(str(params.get("deployer", "")), int(params.get("nonce", 0)))
            elif method == "build_transaction":
                data = build_transaction(**params).as_dict()
            else:
                raise ChainValidationError(f"unknown evm method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")