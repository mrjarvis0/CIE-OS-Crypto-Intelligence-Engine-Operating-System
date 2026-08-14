# Examples

Four walkthroughs of the real pipeline. Every one runs **offline** against
recorded mainnet data in `fixtures/recordings/`, so none needs a network, an API
key, or a live chain — and the test suite runs all four, so they cannot rot into
documentation that no longer works.

```bash
python examples/01_ingest_and_store.py
```

| Example | Shows | The point |
| --- | --- | --- |
| `01_ingest_and_store.py` | sensor → ingestion → normalization → database | A replay writes nothing new: idempotency lives in the primary key, not in the in-memory dedup window |
| `02_token_decoding.py` | ERC-20 vs ERC-721 from real logs | Both hash to the same topic0; identity comes from log **shape**, and a topic0-only decoder reads every `tokenId` as an amount |
| `03_investigate.py` | database → skills → intelligence → decision → narrative | What A01 **refuses** to say — a negative it cannot support, a capped confidence, an alert it will not raise |
| `04_dashboard.py` | rendering the HTML dashboard | Zero external references, so the page works offline; the coverage bar shows *why* findings are withheld |

## What you will actually see

Run `03` and the interesting output is not a finding — it is this:

```
supports absence   : False
  -> only 3 blocks stored, 3600 needed before an absence means anything

[undetermined] cannot be determined: whether whale-scale transfer activity occurred
alerts raised : 0
```

Three stored blocks cannot support "no whale activity here". That statement
would be true of the database and false of Ethereum, so A01 reports the question
as open rather than answering it. Ingest more blocks and the same code reaches a
conclusion.

## Fixtures, not mocks

The recordings are real Ethereum blocks and logs, captured once through A01's own
sensor stack and committed. Nothing in them is synthetic, which is why
`02` finds genuine non-standard contracts to refuse and `03` meets real contract
creations and zero-value calls.

The *sequence* is scripted, though — that is how the test suite exercises a
reorg, a deep fork, and a provider failure mid-range, none of which mainnet will
perform on request.

## Against a live chain instead

```bash
python -m cli ingest --db a01.db --blocks 50 --tokens
python -m cli investigate --db a01.db --address 0x…
python -m cli visualize --db a01.db --open
```
