# 10 — Gnosis Chain

| Field | Value |
|---|---|
| Chain ID | 100 |
| Type | EVM (L1) |
| Native | xDAI (18 decimals) |
| Block time | 5s |
| Finality | Checkpoint (Gasper) |
| Confirmations | 32 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. No keyed provider catalogued.

## Providers

3 endpoints — all open. See `endpoints.yaml`.

## Known limits

- No keyed provider, so no archive upgrade path
- The native unit is xDAI (a stablecoin) — a materiality floor of 1e18
  means ~$1 here and ~$4,000 on Ethereum; a floor carried across chains
  is not one threshold
