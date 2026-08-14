# 05 — Optimism

| Field | Value |
|---|---|
| Chain ID | 10 |
| Type | EVM (L2 rollup) |
| Native | ETH (18 decimals) |
| Block time | 2s |
| Finality | Rollup (settles on Ethereum) |
| Confirmations | 20 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. Archive available via Alchemy.

## Providers

9 endpoints — 3 keyed (free tier), 6 open. See `endpoints.yaml`.

## Known limits

- Native transfers are routinely 0 — real activity is in token logs
- Token decimals unresolved
