"""
CIE-OS / A01 — Example 2: why token decoding needs log *shape*, not topic0.

ERC-20 and ERC-721 `Transfer` events hash to the same topic0. A decoder keyed on
the signature alone reads every NFT movement as a token transfer of `tokenId`
units — a number that is enormous, plausible, and entirely fabricated.

This runs against recorded mainnet logs, offline.

Run:
    python examples/02_token_decoding.py
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contracts import (  # noqa: E402
    TRANSFER_TOPIC,
    DecodedTransfer,
    decode_log,
    decode_logs,
    shape_for,
)
from fixtures.replay import Recording  # noqa: E402


def main() -> int:
    logging.disable(logging.CRITICAL)

    print("Example 2 — ERC-20 vs ERC-721, told apart by shape")
    print(f"  shared topic0: {TRANSFER_TOPIC[:26]}…\n")

    # The discrimination rule, stated as data.
    print(f"  {'TOPICS':<8}{'DATA':<8}EVENT")
    print("  " + "-" * 52)
    for topics, data in ((3, 32), (4, 0)):
        shape = shape_for(TRANSFER_TOPIC, topics, data)
        print(f"  {topics:<8}{f'{data}B':<8}{shape.kind.value}")
    print(f"  {'other':<8}{'—':<8}refused, never guessed")

    # Against real logs.
    recording = Recording.named("ethereum_logs")
    logs = [log for height in recording.logs for log in recording.logs[height]]
    transfers, refusals = decode_logs(logs, chain="ethereum")

    kinds = Counter(t.kind.value for t in transfers)
    print(f"\n  {len(logs):,} recorded logs across {len(recording.logs)} blocks")
    print(f"    erc20_transfer  : {kinds['erc20_transfer']:,}")
    print(f"    erc721_transfer : {kinds['erc721_transfer']:,}")
    print(f"    refused         : {len(refusals):,}  "
          f"({len(transfers) / len(logs):.0%} decoded)")

    # The refusals are not failures. Most logs are protocol events A01 has no
    # opinion about, and reporting only the transfers would invite reading
    # their count as the block's total activity.
    print("\n  top refusal reasons:")
    for reason, count in Counter(r.reason[:56] for r in refusals).most_common(3):
        print(f"    {count:>5}  {reason}")

    # The confusion, checked on production data.
    nfts = [t for t in transfers if t.is_nft]
    if nfts:
        nft = nfts[0]
        print(f"\n  a real ERC-721 movement:")
        print(f"    collection : {nft.contract.short()}")
        print(f"    tokenId    : {nft.token_id}")
        print(f"    amount     : {nft.amount}  <- None, not a quantity")
        print("    a topic0-only decoder would have read that tokenId as an amount")

    # Decimals are never assumed.
    erc20 = next(t for t in transfers if not t.is_nft and t.amount.raw > 0)
    print(f"\n  a real ERC-20 movement:")
    print(f"    contract   : {erc20.contract.short()}")
    print(f"    raw amount : {erc20.amount.raw}")
    print(f"    decimals   : unresolved — needs eth_call, so the figure is")
    print(f"                 base units, comparable within this token only")

    mints = sum(1 for t in transfers if t.is_mint)
    print(f"\n  mints flagged: {mints:,}")
    print("    counted as ordinary receipts they would inflate a holder's")
    print("    inflows with tokens nobody sent them")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
