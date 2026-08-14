# A01 — What you need, where to get it, what it looks like

Written for the operator, not for a developer. Everything here is free.

---

## The short version

You needed **two things**. Both are done.

| # | Thing | Status | Cost |
|---|---|---|---|
| 1 | Alchemy RPC key | ✅ **done** | free |
| 2 | Exchange address list | ✅ **done** — 2,859 addresses, 316 exchanges | free, no signup |

Nothing is blocking. Every other API in `API_KEYS.md` is a backup.

The list is loaded and in use:

```bash
python -m cli labels --db data/a01.db          # what is loaded, and from where
python -m cli flows --db data/a01.db --chain ethereum
```

---

## 1. Alchemy — already working

You already did this. For reference, or when you rotate it:

**Where:** alchemy.com → sign up with email → **Create new app** → pick
**Ethereum · Mainnet** → open the app → **API Key** button.

**What it looks like:** a short string starting with `alch_`, roughly 25–30
characters. That is the whole key — there is no separate secret or password.

**Where it goes:** `agents/A01_Blockchain_Intelligence/.env.local`, on this line:

```
ALCHEMY_API_KEY=your_key_here
```

**How to check it worked:**

```bash
python -m cli providers
```

Look for `alchemy` in the list. It should say **`keyed`**. If it says
`dormant`, the key did not load — usually a typo in the variable name, or a
space around the `=`.

> **Rotate the current one.** It was pasted into a chat, so treat it as public.
> Alchemy dashboard → create a new key → delete the old → change one line in
> `.env.local`. Two minutes.

---

## 2. Exchange address list — done, and here is what it bought

This unlocked **exchange inflow/outflow**, the highest-value signal on your
Tier 1 list. The list you supplied is loaded: 2,859 addresses across 316
exchanges, stored with its source and an `unverified` confidence of 0.5.

What it changed, measured on the stored ethereum window: **1,379 of 25,743
transfers** are now attributable to an exchange, where before none were. The
materiality gate also stopped reporting a coverage hole — a small transfer into
a known deposit address is now kept, which it could never do before.

Two things it deliberately does **not** claim. The labels are community-sourced
and nothing independent has checked them, so every flow figure says so. And an
address the list does not name is invisible rather than counted as unrelated,
which no list of any size fixes.

The rest of this section is kept for when you refresh or extend the list.

### Why this is not an API

Labels get checked against **every transaction** A01 inspects. That is the
hottest path in the system. An API call there would burn a rate limit in
seconds. Labels also barely change — Binance's hot wallet does not move daily.

So: **a file, not a service.** No signup, no key, no rate limit.

### What you are looking for

A list of known exchange wallet addresses. Search terms that find them:

- `crypto exchange address labels csv github`
- `known CEX hot wallet addresses dataset`
- `dune spellbook labels cex addresses`
- On Etherscan: any exchange's address page shows a **blue tag** like
  `Binance 14` — those tagged addresses are the ones worth collecting

Good sources are community-maintained GitHub repos and the Dune Analytics
**spellbook** repo, which keeps exchange address seed files. Check the repo has
been updated recently — a three-year-old list is missing today's wallets.

### What it looks like

Any of these shapes is fine — a spreadsheet, a CSV, a JSON file, even a plain
list. What matters is that each row has **an address and who it belongs to**:

```csv
address,entity,category,chain
0x28c6c06298d514db089934071355e5743bf21d60,Binance,exchange,ethereum
0x21a31ee1afc51d94c2efccaa2092ad1028285549,Binance,exchange,ethereum
0xdfd5293d8e347dfe59e90efd55b2956a1343963d,Binance,exchange,ethereum
0x47ac0fb4f2d84898e4d9e7b4dab3c24507a6d503,Binance,exchange,ethereum
```

`category` is usually one of: `exchange`, `bridge`, `contract`, `mining_pool`,
`market_maker`.

**If your file looks different, do not reformat it.** The loader matches column
names against aliases — `wallet`, `cex_name`, `distinct_name`, `Wallet Address`
and others all resolve — and it prints which column it read as what, so a
mismatch is visible instead of silent. A bad manual conversion loses addresses;
the loader counts and shows every row it could not read, with line numbers.

### Where to put it, and how to load it

Save it here — any filename, `.csv`, `.tsv`, `.json` or `.txt`:

```
agents/A01_Blockchain_Intelligence/data/labels/
```

Then:

```bash
python -m cli labels --db data/a01.db --load data/labels --source "where it came from"
```

Re-running is free: an address already known is updated, not duplicated, and
the run reports `0 new` so you can see nothing moved.

### How much is enough

You do **not** need thousands. The top exchanges by volume cover most flow:

Binance · Coinbase · OKX · Bybit · Kraken · KuCoin · Bitfinex · Gate.io ·
Huobi/HTX · Crypto.com

Even **50–100 addresses across these** would make exchange flow work. It can
always grow later.

### What A01 does with it

Every label is stored with **where it came from** and **how confident** it is.
A01 never guesses that an address is an exchange from how it behaves — that is
a rule in the system, not a preference, and a label with no source cannot even
be constructed.

One consequence worth knowing, because it decides whether the numbers mean
anything: a transfer with a labelled address on **both** ends is reported as
internal movement, not as a deposit. An exchange shuffles its own funds
constantly, and counting those as incoming is how an "exchange inflow" spike
appears with no user behind it.

---

## 3. Things you do NOT need right now

Skip these until something specifically asks for them:

| Thing | When it becomes relevant |
|---|---|
| Infura, dRPC, BlockPI, GetBlock, QuickNode, Chainstack | Only as backup if Alchemy runs out of allowance |
| TronGrid key | Only when TRON is actually wired up |
| Helius | Only for deep Solana work — Alchemy already covers Solana |
| CoinGecko key | Price data already works without one |
| Dune / Arkham / Nansen | Not needed; the static list replaces them |

Adding a key for a chain that is not wired yet does nothing. The endpoint has
to exist in the provider catalog first.

---

## Quick reference — checking anything

```bash
python -m cli providers    # which keys loaded, which chains reachable
python -m cli doctor       # overall health, 14 checks
python -m cli skills       # what A01 can answer, and what bounds each answer
python -m cli detectors    # detectors and why none of them alert yet
```

`cli skills` is the honest one: every skill states what it *cannot* do and why.
That list shrinks as sources are added.
