# 04 — Arbitrum One

| Field | Value |
|---|---|
| Chain ID | 42161 |
| Type | EVM (L2 rollup) |
| Native | ETH (18 decimals) |
| Block time | 1s |
| Finality | Rollup (settles on Ethereum) |
| Confirmations | 20 |
| Observable | Yes |
| Token-capable | Yes |

## What A01 can do here

Full EVM sensor and log decoding. Archive available via Alchemy.

## Providers

9 endpoints — 3 keyed (free tier), 6 open. See `endpoints.yaml`.

## Known limits

- Native transfers are routinely 0 — real activity is in token logs;
  ingest with `--tokens` or A01 sees an idle chain that is not
- Sequencer ordering is not final until the batch settles on Ethereum
