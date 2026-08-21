"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.stablecoin.analysis

Purpose:
    Report stablecoin transfer activity for an address or chain from stored
    token transfers, normalised to a face-dollar figure through the curated
    stablecoin table.

Notes:
    This skill reads the ``token_transfers`` table, which stores ERC-20
    Transfer events, and identifies stablecoins from
    :mod:`knowledge.stablecoins` -- a curated list of ``(chain, address)`` with
    the symbol and, crucially, the decimals. The decimals are what let this
    skill do the one thing raw base units forbid: normalise every stablecoin to
    the same face-dollar scale and sum across them.

    **The total is dollars at par, not market value.** Every coin in the table
    targets the same peg, so their normalised amounts are comparable and
    summable -- but a stablecoin that has de-pegged still normalises to its face
    quantity. This skill reads no price and asserts nothing about whether the
    peg is holding; a reader treating the total as a market value is adding a
    claim the data does not carry.

    Mint and burn detection uses the zero address (``0x0...0``) convention:
    a transfer from zero is a mint, to zero is a burn. This covers the
    standard ERC-20 pattern but not protocol-specific variants.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from knowledge.stablecoins import lookup, normalize, symbols

from ..base import Skill, SkillRequest, SkillResult

ZERO_ADDRESS: Final[str] = "0x" + "00" * 20


def _usd(raw: int, decimals: int) -> Decimal:
    """A raw stablecoin amount as its face-dollar quantity."""
    return normalize(raw, decimals)


def _plain(amount: Decimal) -> str:
    """
    A face-dollar figure as a plain decimal string.

    ``normalize()`` drops the trailing-zero tail that ``scaleb`` leaves behind,
    so $100 does not print as ``100.000000000000000000``; it renders round
    numbers in exponent form (``1E+2``), which ``format(..., "f")`` then expands
    back to fixed point rather than inventing a decimal tail.
    """
    return format(amount.normalize(), "f")


class StablecoinSkill(Skill):
    """
    Stablecoin transfer activity from stored token transfers.

    One responsibility: aggregate stablecoin movement and normalise it to a
    face-dollar figure. Whether the flow implies de-peg risk, capital flight,
    or liquidity is decided elsewhere.
    """

    name = "stablecoin"
    description = "Stablecoin flow, decimal-normalised to dollars at par, from a curated list"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored"
            )

        known = symbols(request.chain)
        if not known:
            return self.undetermined(
                coverage,
                f"no known stablecoin contracts registered for {request.chain}",
            )

        address = request.address
        flows = analytics.token_flow(address) if address is not None else {}

        stable_flows: list[dict[str, Any]] = []
        total_transfers = 0
        total_in_usd = Decimal(0)
        total_out_usd = Decimal(0)

        for token, (gross_in, gross_out, count) in flows.items():
            coin = lookup(request.chain, token)
            if coin is None:
                continue

            in_usd = _usd(gross_in, coin.decimals)
            out_usd = _usd(gross_out, coin.decimals)
            total_transfers += count
            total_in_usd += in_usd
            total_out_usd += out_usd

            if in_usd > out_usd:
                direction = "net_inflow"
            elif out_usd > in_usd:
                direction = "net_outflow"
            else:
                direction = "balanced"

            stable_flows.append({
                "token": token,
                "symbol": coin.symbol,
                "decimals": coin.decimals,
                "transfers": count,
                # Raw base units, kept so the exact on-chain integer survives.
                "gross_in": str(gross_in),
                "gross_out": str(gross_out),
                # Face-dollar figures: the raw units divided by 10**decimals.
                # Summable across tokens precisely because the decimals are
                # resolved and the peg is shared.
                "gross_in_usd": _plain(in_usd),
                "gross_out_usd": _plain(out_usd),
                "net_usd": _plain(in_usd - out_usd),
                "net_direction": direction,
                "decimals_known": True,
            })

        # Sorted by dollar throughput, not transfer count: a single large
        # settlement matters more than many dust transfers, and the normalised
        # figure is now the one that can say so.
        stable_flows.sort(
            key=lambda r: Decimal(r["gross_in_usd"]) + Decimal(r["gross_out_usd"]),
            reverse=True,
        )

        token_totals = analytics.token_totals(request.chain)
        stable_activity = [t for t in token_totals if t["token"].lower() in known]

        net_usd = total_in_usd - total_out_usd
        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value if address else None,
            "known_stablecoins": len(known),
            "stablecoins_with_activity": len(stable_flows),
            "total_transfers": total_transfers,
            # The figures the resolved decimals make possible. Present only for
            # an address-scoped request, because chain-wide value summation is
            # not a query the analytics layer offers yet.
            "total_in_usd": _plain(total_in_usd),
            "total_out_usd": _plain(total_out_usd),
            "net_usd": _plain(net_usd),
            "net_direction": (
                "net_inflow" if net_usd > 0
                else "net_outflow" if net_usd < 0
                else "balanced"
            ),
            "flows": stable_flows,
            "chain_wide_stable_tokens": stable_activity,
            "coverage_limitation": coverage.limitation,
            "bounds": [
                "identification by curated contract list; unlisted stablecoins "
                "are invisible",
                "dollar figures are face value at par -- decimals are resolved, "
                "but no price is read, so a de-pegged coin is still counted at $1",
                "chain-wide figures are transfer counts only; dollar flow is "
                "computed for an address-scoped request, which is the one the "
                "analytics layer sums value for",
            ],
        }

        subject: dict[str, Any] = {
            "stablecoin_transfers": total_transfers,
            "stablecoins_active": len(stable_flows),
            "stablecoin_net_usd": _plain(net_usd),
            "flows": stable_flows,
        }
        if address is not None:
            subject["address"] = address.value

        reason = (
            f"{total_transfers} stablecoin transfer(s) across "
            f"{len(stable_flows)} token(s), ${net_usd:,.2f} net at par"
            if total_transfers
            else "no stablecoin activity in the stored window"
        )
        return self.answer(coverage, data, subject, reason)


__all__ = ["StablecoinSkill"]
