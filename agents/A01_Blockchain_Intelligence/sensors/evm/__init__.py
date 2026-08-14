"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    sensors.evm

Purpose:
    Sensors for chains that speak the Ethereum JSON-RPC dialect.

One implementation serves every EVM chain, parameterised by the chain registry
in ``config/rpc/chains.py``. The differences between Ethereum, Base, Arbitrum
and the rest that matter at capture time -- confirmation depth, finality tag,
which endpoints exist -- are configuration, not code, so adding an EVM chain is
a registry entry rather than a new class.
"""

from __future__ import annotations

from .rpc_sensor import (
    DEFAULT_LOG_RANGE,
    EvmRpcSensor,
    parse_quantity,
    to_quantity,
)

__all__ = [
    "DEFAULT_LOG_RANGE",
    "EvmRpcSensor",
    "parse_quantity",
    "to_quantity",
]
