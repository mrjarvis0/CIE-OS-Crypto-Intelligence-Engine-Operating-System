# 02 — BNB Smart Chain

| Field | Value |
|---|---|
| Chain ID | 56 |
| Type | EVM |
| Native | BNB (18 decimals) |
| Block time | 3s |
| Finality | Probabilistic |
| Confirmations | 15 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. No keyed provider active — all
endpoints are open or dormant.

## Providers

11 endpoints — 3 keyed (free tier), 8 open. See `endpoints.yaml`.

## Known limits

- No archive on the free tier
- Short block time and small validator set make reorgs more common
- Binance operates its own public dataseed endpoints
