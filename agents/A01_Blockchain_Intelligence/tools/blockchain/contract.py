"""
Tools :: Blockchain :: Contract
===============================

Contract interface analysis: ABI normalization, function/event catalog,
method signatures and verification status.

Local analysis operates on the ABI JSON and a deterministic function
selector table; on-chain verification requires a backend hook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import ChainValidationError, ChainRequest, ChainResponse, BaseChainClient
from .evm import function_selector, event_topic, normalize_address

__all__ = [
    "ContractInterface",
    "ContractFunction",
    "ContractEvent",
    "ContractClient",
    "LocalContract",
    "analyze_abi",
]

_ABI_KINDS = {"function", "constructor", "event", "error", "fallback", "receive"}


def _canonical_signature(item: Mapping[str, Any]) -> str:
    name = str(item.get("name", ""))
    inputs = item.get("inputs", [])
    parts = []
    for entry in inputs:
        inner = entry.get("type", "uint256")
        parts.append(inner if "tuple" not in inner else "tuple")
    return f"{name}({','.join(parts)})"


@dataclass
class ContractFunction:
    """One function entry."""

    name: str
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    state_mutability: str = "view"
    selector: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "state_mutability": self.state_mutability,
            "selector": self.selector,
        }


@dataclass
class ContractEvent:
    """One event entry."""

    name: str
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    topic: str = ""
    anonymous: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "inputs": list(self.inputs),
            "topic": self.topic,
            "anonymous": self.anonymous,
        }


@dataclass
class ContractInterface:
    """Full ABI-derived contract interface."""

    address: str
    name: str = ""
    functions: List[ContractFunction] = field(default_factory=list)
    events: List[ContractEvent] = field(default_factory=list)
    verified: bool = False
    compiler_version: str = ""

    @property
    def function_names(self) -> List[str]:
        return [fn.name for fn in self.functions]

    @property
    def event_names(self) -> List[str]:
        return [ev.name for ev in self.events]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "name": self.name,
            "functions": [fn.as_dict() for fn in self.functions],
            "events": [ev.as_dict() for ev in self.events],
            "function_names": self.function_names,
            "event_names": self.event_names,
            "verified": self.verified,
            "compiler_version": self.compiler_version,
        }


def analyze_abi(abi: Sequence[Mapping[str, Any]], *, address: str = "") -> ContractInterface:
    """Build a :class:`ContractInterface` from an ABI JSON array."""
    if not isinstance(abi, (list, tuple)):
        raise ChainValidationError("ABI must be a JSON array of entries")
    functions: List[ContractFunction] = []
    events: List[ContractEvent] = []
    name = ""
    for item in abi:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("type", ""))
        if kind == "function":
            signature = _canonical_signature(item)
            functions.append(
                ContractFunction(
                    name=str(item.get("name", "")),
                    inputs=list(item.get("inputs", [])),
                    outputs=list(item.get("outputs", [])),
                    state_mutability=str(item.get("stateMutability", "view")),
                    selector=function_selector(signature),
                )
            )
        elif kind == "event":
            signature = _canonical_signature(item)
            events.append(
                ContractEvent(
                    name=str(item.get("name", "")),
                    inputs=list(item.get("inputs", [])),
                    topic=event_topic(signature),
                    anonymous=bool(item.get("anonymous", False)),
                )
            )
        elif kind == "constructor":
            pass
        elif kind not in _ABI_KINDS:
            raise ChainValidationError(f"unknown ABI entry kind {kind!r}")
    return ContractInterface(address=normalize_address(address) if address else address, name=name, functions=functions, events=events)


class ContractClient(BaseChainClient):
    """Contract service: interface analysis and verification lookups."""

    provider = "contract"
    capability = "contract"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._interfaces: Dict[str, ContractInterface] = {}

    # -- provider hooks -------------------------------------------------------- #

    def _onchain_interface(self, address: str) -> Optional[ContractInterface]:
        return None

    def _verification(self, address: str) -> Dict[str, Any]:
        return {}

    # -- capabilities ---------------------------------------------------------- #

    def register(self, interface: ContractInterface) -> None:
        self._interfaces[normalize_address(interface.address)] = interface

    def interface(self, address: str, abi: Optional[Sequence[Mapping[str, Any]]] = None) -> ContractInterface:
        address = normalize_address(address)
        if abi is not None:
            interface = analyze_abi(abi, address=address)
            self._interfaces[address] = interface
            return interface
        interface = self._interfaces.get(address)
        if interface is not None:
            return interface
        interface = self._onchain_interface(address)
        if interface is None:
            raise ChainValidationError(f"no ABI available for contract {address}")
        self._interfaces[address] = interface
        return interface

    def verify(self, address: str) -> Dict[str, Any]:
        address = normalize_address(address)
        interface = self._interfaces.get(address) or self._onchain_interface(address)
        info = self._verification(address)
        if interface is not None:
            info.setdefault("verified", interface.verified)
            info.setdefault("name", interface.name)
        return {"address": address, **info}

    def function_signature(self, address: str, name: str, inputs: Sequence[str]) -> str:
        interface = self.interface(address)
        signature = f"{name}({','.join(inputs)})"
        for fn in interface.functions:
            if fn.name == name and fn.selector == function_selector(signature):
                return fn.selector
        raise ChainValidationError(f"function {signature} not found on {address}")

    def execute(self, request: ChainRequest) -> ChainResponse:
        method = request.method
        params = request.params
        try:
            if method == "interface":
                data = self.interface(str(params["address"]), params.get("abi")).as_dict()
            elif method == "verify":
                data = self.verify(str(params["address"]))
            elif method == "function_signature":
                data = {
                    "address": str(params["address"]),
                    "name": str(params["name"]),
                    "selector": self.function_signature(str(params["address"]), str(params["name"]), [str(x) for x in params.get("inputs", [])]),
                }
            else:
                raise ChainValidationError(f"unknown contract method {method!r}")
            return self.normalize(True, data=data, request=request)
        except ChainValidationError as exc:
            return self.normalize(False, error=exc, request=request, status="error")


class LocalContract(ContractClient):
    """Deterministic contract service backed by a local ABI registry."""

    provider = "local-contract"

    def __init__(self, *, chain_id: int = 1, logger: Any = None) -> None:
        super().__init__(chain_id=chain_id, logger=logger)
        self._verified: Dict[str, Dict[str, Any]] = {}

    def mark_verified(self, address: str, *, name: str = "", compiler_version: str = "") -> None:
        address = normalize_address(address)
        self._verified[address] = {"verified": True, "name": name, "compiler_version": compiler_version}
        if address in self._interfaces:
            self._interfaces[address].verified = True
            self._interfaces[address].name = name
            self._interfaces[address].compiler_version = compiler_version

    def _verification(self, address: str) -> Dict[str, Any]:
        return dict(self._verified.get(normalize_address(address), {"verified": False}))