"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.nft.analysis

Purpose:
    Report NFT-related transfer activity from stored token transfers.
    Without ERC-721/1155 event decoding, this identifies potential NFT
    activity heuristically: token transfers with value of 1 or very small
    quantities to distinct contracts.

Notes:
    The token_transfers table stores all ERC-20 Transfer events. ERC-721
    transfers emit the same event signature but with a value that represents
    a token ID rather than an amount. This skill uses the heuristic of
    value == 1 to flag potential NFT transfers, but cannot distinguish with
    certainty. The bound is stated in every result.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository

from ..base import Skill, SkillRequest, SkillResult


class NftSkill(Skill):
    """
    NFT-like transfer detection from stored token transfers.

    One responsibility: identify potential NFT activity. Whether a transfer
    is truly an NFT or a fungible token with value 1 cannot be determined
    without contract metadata.
    """

    name = "nft"
    description = "Potential NFT transfer detection from token transfer heuristics"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        if request.address is None:
            return self.undetermined(coverage, "nft analysis requires an address")

        address = request.address
        token_flows = analytics.token_flow(address)

        nft_candidates: list[dict[str, Any]] = []
        fungible_tokens = 0

        for token, (gross_in, gross_out, count) in token_flows.items():
            total_moved = gross_in + gross_out
            if count > 0 and total_moved <= count:
                nft_candidates.append({
                    "token": token,
                    "transfers": count,
                    "total_moved": str(total_moved),
                    "likely_nft": True,
                })
            else:
                fungible_tokens += 1

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "tokens_analyzed": len(token_flows),
            "nft_candidates": len(nft_candidates),
            "fungible_tokens": fungible_tokens,
            "candidates": nft_candidates[:20],
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "no ERC-721/1155 event decoding; NFT detection is heuristic only",
                "a token transfer with value 1 may be a fungible token, not an NFT",
                "collection metadata (name, floor price, rarity) is unavailable",
            ],
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "nft_candidates": len(nft_candidates),
            "tokens_analyzed": len(token_flows),
        }

        reason = (
            f"{len(nft_candidates)} potential NFT contract(s) among "
            f"{len(token_flows)} token(s)"
            if nft_candidates
            else f"no NFT-like activity among {len(token_flows)} token(s)"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["NftSkill"]
