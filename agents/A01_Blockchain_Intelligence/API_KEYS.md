# A01 — API keys: what to get, where from, where it goes

Every key goes in **one file**: `agents/A01_Blockchain_Intelligence/.env.local`
(git-ignored). Never in source. After adding one, run:

```
python -m cli providers
```

A key that was picked up moves from `dormant` to `keyed`. If it still says
`dormant`, the variable name is wrong — the table below is the authority.

---

## 1. RPC providers — reading the chains

### Already done

| Provider | Variable | Status |
|---|---|---|
| Alchemy | `ALCHEMY_API_KEY` | **active** — covers Ethereum, Base, Arbitrum, Polygon, Optimism, Solana |

Alchemy's one key covers most of the top chains. Get it at **alchemy.com** →
new app → copy key. Free tier, no card.

### Worth adding next (all free tiers)

| Chain | Provider | Where | Variable | Needed? |
|---|---|---|---|---|
| **Solana** | Helius | helius.dev | `HELIUS_API_KEY` *(new — not in catalog yet)* | Alchemy works; Helius is better for Solana specifically |
| **BNB Chain** | public nodes | — | none | Public BSC RPC is usable; key optional |
| **TRON** | TronGrid | trongrid.io | `TRONGRID_API_KEY` *(new)* | **Yes** — TRON is USDT flow, and free tier is tight without a key |
| **Bitcoin** | mempool.space / Blockchair | mempool.space | none / `BLOCKCHAIR_API_KEY` *(new)* | Public works for basics |
| any | Infura | infura.io | `INFURA_API_KEY` + `INFURA_PROJECT_ID` | Backup for Alchemy |
| any | dRPC | drpc.org | `DRPC_API_KEY` | Backup |
| any | BlockPI | blockpi.io | `BLOCKPI_API_KEY` | Backup |
| any | GetBlock | getblock.io | `GETBLOCK_API_KEY` | Backup |
| any | QuickNode | quicknode.com | `QUICKNODE_URL` | Backup (full URL, not a key) |
| any | Chainstack | chainstack.com | `CHAINSTACK_URL` | Backup (full URL) |

> Variables marked *(new)* do not exist in `blockchain/rpc/providers/catalog.py`
> yet. Adding the key alone will not activate them — the endpoint has to be
> added to the catalog first. That is part of the 15-chain restructure.

---

## 2. Labels — the biggest remaining unlock

**This is the one blocker on exchange inflow/outflow**, which is the highest
value trader signal on the list. Logs are working now; only labels are missing.

| Source | Where | Variable | Free? | Notes |
|---|---|---|---|---|
| **Open-source CEX address lists** ← **recommended** | GitHub (Dune spellbook, community lists) | none | yes | Static files. No rate limit, reproducible, no key |
| Etherscan | etherscan.io/apis | `ETHERSCAN_API_KEY` | free tier | Already in catalog. Labels only partly exposed on free tier |
| Dune Analytics | dune.com/settings/api | `DUNE_API_KEY` *(new)* | free tier | Best label coverage, but query-based and rate limited |
| Arkham | arkm.com | `ARKHAM_API_KEY` *(new)* | limited free | Entity labels |
| Nansen | nansen.ai | — | **no, expensive** | Skip |

**Recommendation: static list first, API second.** Labels are checked on every
transaction — that is the hot path, and an API call there is fatal for rate
limits. Labels also change slowly; Binance's hot wallet does not move daily.

A01's `labels` table already carries `source`, `confidence` and
`verification_status` per row, so every label records where it came from. No
label is ever inferred from behaviour alone.

---

## 3. Market data — price, market cap, liquidity, TVL

| Source | Where | Variable | Free? | Status |
|---|---|---|---|---|
| **DefiLlama** | defillama.com | none | yes, no key | **already wired**, usable now |
| **CoinGecko** | coingecko.com/api | `COINGECKO_API_KEY` *(optional)* | free tier ~10-30/min | already wired keyless; a key raises the limit |

These cover market cap, TVL and liquidity — the dashboard cross-verification
inputs. Neither is blocking today.

---

## 4. What to do first

1. **Nothing** — Alchemy is enough for Ethereum + Base + Arbitrum + Polygon +
   Optimism. That is already the majority of the top-15 by trading relevance.
2. **A label source** — the only thing standing between A01 and exchange flow
   intelligence. Start with an open-source static list; no key needed.
3. **TronGrid** — only when TRON is actually wired, for USDT flows.
4. Everything else is a backup for redundancy, not a capability unlock.

---

## Note on rotating

A key pasted into a chat, a screenshot, or a commit is a key that must be
rotated. Provider dashboards all allow creating a new key and deleting the old
one; only the one line in `.env.local` changes.
