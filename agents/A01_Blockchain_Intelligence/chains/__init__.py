"""
Per-chain configuration, endpoints, limits and adapters.

Each numbered subdirectory holds one chain's operational profile:

    README.md       — what the chain is, what A01 can do on it
    endpoints.yaml  — provider endpoints; API key fields empty
    limits.yaml     — finality, reorg depth, block time, known limits
    adapter.py      — chain-specific adapter (EVM, UTXO, or Solana family)

The chain registry (``config.rpc.chains``) remains the authority for chain
identity and metadata. The capability table (``knowledge.chains``) remains the
authority for what A01 can observe. This directory adds the operational layer:
how to reach the chain, what constraints apply, and which adapter family to use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

CHAINS_DIR: Final[Path] = Path(__file__).parent

CHAIN_ORDER: Final[tuple[str, ...]] = (
    "ethereum",
    "bnb_chain",
    "polygon",
    "arbitrum",
    "optimism",
    "base",
    "avalanche",
    "linea",
    "scroll",
    "gnosis",
    "celo",
    "mantle",
    "unichain",
    "solana",
    "bitcoin",
)

__all__ = ["CHAINS_DIR", "CHAIN_ORDER"]
