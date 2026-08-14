"""
Solana chain adapter.

Solana uses slots, not blocks. Slots can be skipped, so height arithmetic
that works on EVM chains does not transfer. The RPC dialect is JSON-RPC
but with an entirely different method set from EVM.

A01 has registered Solana endpoints and can reach them, but has no sensor
that speaks the Solana RPC dialect. Until a SolanaSensor is built, this
chain is observable in the catalog and unobservable in practice.
"""

from config.rpc.chains import ChainName, ChainType
from chains.base import SolanaAdapter

adapter = SolanaAdapter(ChainName.SOLANA)
