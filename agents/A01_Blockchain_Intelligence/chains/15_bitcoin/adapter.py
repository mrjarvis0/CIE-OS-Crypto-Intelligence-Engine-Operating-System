"""
Bitcoin chain adapter — UTXO model.

Bitcoin is fundamentally different from every other chain in this registry.
Forcing the EVM account model onto Bitcoin produces confidently wrong output:

- There are no accounts with balances. There are unspent transaction outputs
  (UTXOs). An "address balance" is a derived view, not a protocol concept.
- A transaction spends inputs (references to previous outputs) and creates
  new outputs. There is no single "from" address — a transaction can spend
  outputs controlled by different keys.
- Change addresses mean a single user routinely controls many addresses.
  Common-input-ownership heuristics are probabilistic, not deterministic.
- There are no event logs, no smart contracts, and no token transfers in
  the EVM sense. Ordinals and BRC-20 exist but are a different model.
- 10-minute blocks make real-time monitoring impractical compared to EVM
  chains with sub-second block times.

A01's attribution doctrine (docs/intelligence/attribution-doctrine.md)
addresses this: UTXO-derived confidence values must never be applied to
account-model chains, and vice versa.
"""

from config.rpc.chains import ChainName, ChainType
from chains.base import UtxoAdapter

adapter = UtxoAdapter(ChainName.BITCOIN)
