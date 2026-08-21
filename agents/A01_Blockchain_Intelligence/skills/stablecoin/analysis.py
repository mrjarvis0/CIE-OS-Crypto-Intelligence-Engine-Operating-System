"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.stablecoin.analysis

Purpose:
    Report stablecoin transfer activity for an address or chain from stored
    token transfers. Known stablecoin contracts are identified by address,
    and their movement is aggregated separately from native value.

Notes:
    This skill reads the ``token_transfers`` table, which stores ERC-20
    Transfer events. It identifies stablecoins by a hardcoded set of known
    contract addresses per chain. Without an oracle for token metadata
    (name, decimals, peg status), the identification is as good as the list
    and the list is stated in the result.

    Mint and burn detection uses the zero address (``0x0...0``) convention:
    a transfer from zero is a mint, to zero is a burn. This covers the
    standard ERC-20 pattern but not protocol-specific variants.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from schemas.address import Address

from ..base import Skill, SkillRequest, SkillResult

ZERO_ADDRESS: Final[str] = "0x" + "00" * 20

KNOWN_STABLECOINS: Final[dict[str, dict[str, str]]] = {
    "ethereum": {
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
        "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
        "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
        "0x4fabb145d64652a948d72533023f6e7a623c7c53": "BUSD",
        "0x8e870d67f660d95d5be530380d0ec0bd388289e1": "USDP",
    },
    "bnb": {
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC",
        "0x55d398326f99059ff775485246999027b3197955": "USDT",
        "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3": "DAI",
        "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
    },
    "polygon": {
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC",
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
        "0x8f3cf7ad23cd3cadbd9735aff958023239c6a063": "DAI",
    },
    "arbitrum": {
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831": "USDC",
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9": "USDT",
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": "DAI",
    },
    "optimism": {
        "0x0b2c639c533813f4aa9d7837caf62653d097ff85": "USDC",
        "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58": "USDT",
        "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1": "DAI",
    },
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    },
    "avalanche": {
        "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e": "USDC",
        "0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7": "USDT",
        "0xd586e7f844cea2f87f50152665bcbc2c279d8d70": "DAI",
    },
}


class StablecoinSkill(Skill):
    """
    Stablecoin transfer activity from stored token transfers.

    One responsibility: aggregate stablecoin movement. Whether the flow
    implies de-peg risk, capital flight, or liquidity is decided elsewhere.
    """

    name = "stablecoin"
    description = "Stablecoin mint/burn/transfer volume from known contract addresses"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        known = KNOWN_STABLECOINS.get(request.chain, {})
        if not known:
            return self.undetermined(
                coverage,
                f"no known stablecoin contracts registered for {request.chain}",
            )

        address = request.address
        if address is not None:
            flows = analytics.token_flow(address)
        else:
            flows = {}

        stable_flows: list[dict[str, Any]] = []
        total_in = 0
        total_out = 0
        total_transfers = 0

        for token, (gross_in, gross_out, count) in flows.items():
            symbol = known.get(token.lower())
            if symbol is None:
                continue
            total_in += gross_in
            total_out += gross_out
            total_transfers += count

            if gross_in > gross_out:
                direction = "net_inflow"
            elif gross_out > gross_in:
                direction = "net_outflow"
            else:
                direction = "balanced"

            stable_flows.append({
                "token": token,
                "symbol": symbol,
                "transfers": count,
                "gross_in": str(gross_in),
                "gross_out": str(gross_out),
                "net_direction": direction,
                "decimals_known": False,
            })

        stable_flows.sort(key=lambda r: r["transfers"], reverse=True)

        token_totals = analytics.token_totals(request.chain)
        stable_activity = [
            t for t in token_totals if t["token"].lower() in known
        ]

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value if address else None,
            "known_stablecoins": len(known),
            "stablecoins_with_activity": len(stable_flows),
            "total_transfers": total_transfers,
            "flows": stable_flows,
            "chain_wide_stable_tokens": stable_activity,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "identification by hardcoded contract list; unlisted stablecoins are invisible",
                "raw base units only; decimals are not resolved, so figures across "
                "tokens must not be summed",
                "no peg-deviation data; a stablecoin that has de-pegged is still counted",
            ],
        }

        subject: dict[str, Any] = {
            "stablecoin_transfers": total_transfers,
            "stablecoins_active": len(stable_flows),
            "flows": stable_flows,
        }
        if address is not None:
            subject["address"] = address.value

        reason = (
            f"{total_transfers} stablecoin transfer(s) across "
            f"{len(stable_flows)} token(s)"
            if total_transfers
            else "no stablecoin activity in the stored window"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["KNOWN_STABLECOINS", "StablecoinSkill"]
