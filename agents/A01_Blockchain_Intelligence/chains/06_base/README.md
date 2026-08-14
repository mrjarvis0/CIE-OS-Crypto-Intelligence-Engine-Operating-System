# 06 — Base

| Field | Value |
|---|---|
| Chain ID | 8453 |
| Type | EVM (L2 rollup) |
| Native | ETH (18 decimals) |
| Block time | 2s |
| Finality | Rollup (settles on Ethereum) |
| Confirmations | 20 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. A01's second-most-exercised chain
after Ethereum. Open endpoints serve `eth_getLogs` here, unlike
Ethereum's open endpoints which refuse them.

## Providers

8 endpoints — 3 keyed (free tier), 5 open. See `endpoints.yaml`.

## Known limits

- Native transfers are routinely 0 — real activity is in token logs
- Token decimals unresolved
