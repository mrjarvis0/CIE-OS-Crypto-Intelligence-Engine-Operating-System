# 15 — Bitcoin

| Field | Value |
|---|---|
| Chain ID | — |
| Type | UTXO (Bitcoin-like) |
| Native | BTC (8 decimals) |
| Block time | ~600s (10 minutes) |
| Finality | Probabilistic |
| Confirmations | 6 |
| Observable | **No** |
| Token-capable | No |

## What A01 can do here

**Nothing yet.** Endpoints are registered and reachable (Esplora REST),
but A01 has no sensor that speaks the Bitcoin/UTXO model. The chain is
in the catalog so that its status is visible rather than silently absent.

## Why Bitcoin needs its own adapter

Bitcoin is fundamentally different from every other chain in this
registry. **Forcing the EVM account model onto Bitcoin produces
confidently wrong output:**

- **No accounts.** Bitcoin has unspent transaction outputs (UTXOs), not
  account balances. An "address balance" is a derived view, not a
  protocol concept.
- **No single sender.** A transaction spends inputs (references to
  previous outputs) and creates new outputs. There is no "from" address
  in the EVM sense — a transaction can spend outputs controlled by
  different keys.
- **Change addresses.** A single user routinely controls many addresses.
  Common-input-ownership heuristics are probabilistic, not deterministic.
- **No event logs.** No smart contracts in the EVM sense. No ERC-20
  token transfers. Ordinals and BRC-20 exist but are a different model.
- **10-minute blocks.** Real-time monitoring is impractical compared to
  EVM chains with sub-second block times.

A01's attribution doctrine (`docs/intelligence/attribution-doctrine.md`)
explicitly addresses this: UTXO-derived confidence values must never be
applied to account-model chains, and vice versa.

## What would be needed

A `UtxoSensor` implementation that:
- Reads via Esplora REST (not JSON-RPC — public Bitcoin JSON-RPC is not
  available)
- Models UTXOs rather than account state
- Applies common-input-ownership heuristics with stated confidence
- Handles change-address detection with known false-positive rates
- Reports its model's limitations in every conclusion

## Providers

4 endpoints — 1 keyed (NowNodes), 3 open (Blockstream, mempool.space,
BlockCypher). See `endpoints.yaml`. BlockCypher's free tier is very
limited (3 requests/minute).

## Known limits

- No sensor — A01 cannot observe this chain at all
- UTXO model incompatible with A01's account-based analysis
- Common-input-ownership is probabilistic
- 10-minute blocks make real-time monitoring impractical
