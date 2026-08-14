"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.token_flow.flow

Purpose:
    Aggregate native-value flow over the stored window: how much moved, in
    which direction for a given address, and how concentrated it was.

Design goals:
    - Exact integer arithmetic; no float accumulation
    - Net flow signed explicitly, never inferred from magnitude
    - Concentration reported, because a total hides whether one transfer made it
    - Window stated, so a total is not read as all-time volume

Notes:
    Net flow is the figure most easily read wrongly. A net of zero can mean no
    activity, or it can mean a hundred million moved in and the same moved out,
    which is a completely different situation. So gross in, gross out and net
    are all reported, and the caller cannot see only the net.

    Concentration is reported for the same reason. "Ten thousand ETH moved
    through this address" reads as sustained activity; if one transfer accounts
    for 99% of it, the honest description is one large transfer and some noise.
    The share of the largest transfer is therefore part of the answer rather
    than something a consumer has to compute.

    Native and token flow are reported **side by side, never summed**. They are
    denominated in different units, and one of those units has an unknown
    exponent: adding wei to raw USDC base units produces a number with no
    meaning that looks entirely ordinary in a report.

    Token flow is likewise kept **per contract**. A cross-token total would add
    a 6-decimal token's units to an 18-decimal token's, so the result would be
    dominated by whichever contract happens to use more digits rather than by
    what actually moved. This is the same discipline
    :meth:`database.tokens.SqliteTokenRepository.largest_transfers` enforces by
    requiring a token argument.

    On layer 2 the token side is the only side that exists. Measured on live
    Arbitrum blocks, the largest native transfer was ``0.0000`` while USDC and
    USDT moved in the same blocks -- so a flow skill reporting native value
    alone answers "nothing happened" about a chain that was busy.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from schemas.amount import Amount

from ..base import Skill, SkillRequest, SkillResult

#: Transfers examined per flow computation. Bounded so the aggregate stays
#: proportional to the window rather than to chain history.
DEFAULT_FLOW_LIMIT: Final[int] = 1_000


class TokenFlowSkill(Skill):
    """
    Aggregates value movement over the stored window.

    One responsibility: measure flow. Whether the flow implies accumulation,
    distribution, or sell pressure is a judgement made in ``intelligence/``
    against context this skill does not hold.
    """

    name = "token_flow"
    description = "Native and per-token gross in/out, net flow and concentration"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored to aggregate"
            )

        limit = int(request.option("flow_limit", DEFAULT_FLOW_LIMIT))
        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=limit,
        )

        if not transfers:
            return self.answer(
                coverage,
                {
                    "chain": request.chain,
                    "transfer_count": 0,
                    "scope": "native_value_only",
                    "coverage_limitation": coverage.limitation,
                },
                {"flow_determinable": False},
                "no transfers in the requested window",
            )

        address = request.address
        # Integer arithmetic throughout: these values exceed a float's exact
        # range, and a total that is nearly right is worse than none.
        gross_in = 0
        gross_out = 0
        largest = 0
        total = 0
        counted = 0

        for transfer in transfers:
            raw = transfer.value.raw
            if address is None:
                total += raw
                largest = max(largest, raw)
                counted += 1
                continue

            if transfer.from_address == address.value:
                gross_out += raw
            elif transfer.to_address == address.value:
                gross_in += raw
            else:
                continue

            total += raw
            largest = max(largest, raw)
            counted += 1

        if counted == 0:
            # No native movement is not the same as no movement. On L2 an
            # address that only ever moves tokens is the normal case, and
            # declining here would report it as inactive.
            token_only = self._token_flows(analytics, address)
            reason = (
                f"no native movement; {len(token_only)} token contract(s) touched"
                if token_only
                else "address does not appear in the stored transfers"
            )
            return self.answer(
                coverage,
                {
                    "chain": request.chain,
                    "address": address.value if address else None,
                    "transfer_count": 0,
                    "scope": "native_and_tokens",
                    "token_flows": token_only,
                    "tokens_touched": len(token_only),
                    "coverage_limitation": coverage.limitation,
                },
                {
                    "flow_determinable": bool(token_only),
                    "token_flows": token_only,
                },
                reason,
            )

        concentration = largest / total if total else 0.0
        token_flows = self._token_flows(analytics, address)

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value if address else None,
            "transfer_count": counted,
            "gross_in": Amount(gross_in).as_dict(),
            "gross_out": Amount(gross_out).as_dict(),
            "gross_in_units": Amount(gross_in).format(6),
            "gross_out_units": Amount(gross_out).format(6),
            "total_moved": Amount(total).as_dict(),
            "largest_transfer": Amount(largest).as_dict(),
            # Signed explicitly: a magnitude with no sign is not a net flow.
            "net_direction": self._direction(gross_in, gross_out, address is not None),
            "net_magnitude": Amount(abs(gross_in - gross_out)).as_dict(),
            "net_units": Amount(abs(gross_in - gross_out)).format(6),
            "concentration": round(concentration, 4),
            "single_transfer_dominated": concentration >= 0.9,
            # Native and token figures are separate keys, never one total.
            "scope": "native_and_tokens",
            "scope_note": (
                "native and token figures are reported separately and must not "
                "be summed: token amounts are raw base units whose decimals are "
                "unresolved, so they share no unit with wei or with each other"
            ),
            "token_flows": token_flows,
            "tokens_touched": len(token_flows),
            "coverage_limitation": coverage.limitation,
        }

        subject: dict[str, Any] = {
            "flow_determinable": True,
            "observed_flow": {
                "gross_in": str(gross_in),
                "gross_out": str(gross_out),
                "net_direction": data["net_direction"],
                "concentration": data["concentration"],
                "scope": "native_value_only",
            },
            # Kept out of `observed_flow` deliberately: a detector reading that
            # key expects one denomination, and token figures are neither in
            # wei nor in a shared unit with each other.
            "token_flows": token_flows,
        }
        if address is not None:
            subject["address"] = address.value

        return self.answer(
            coverage,
            data,
            subject,
            f"{counted} transfer(s), net {data['net_direction']}",
        )

    @staticmethod
    def _token_flows(
        analytics: SqliteAnalyticsRepository, address: Any
    ) -> list[dict[str, Any]]:
        """
        Per-contract token movement for an address, busiest first.

        Empty when no address was given: a chain-wide token flow has the same
        problem a chain-wide native flow does -- every transfer is both an
        inflow and an outflow, so the net is always zero.
        """
        if address is None:
            return []

        rows: list[dict[str, Any]] = []
        for token, (gross_in, gross_out, count) in analytics.token_flow(address).items():
            if gross_in > gross_out:
                direction = "net_inflow"
            elif gross_out > gross_in:
                direction = "net_outflow"
            else:
                direction = "balanced"

            rows.append(
                {
                    "token": token,
                    "transfers": count,
                    "gross_in": str(gross_in),
                    "gross_out": str(gross_out),
                    "net_direction": direction,
                    # Stated per row, because it is the fact that stops these
                    # figures being compared with each other.
                    "decimals_known": False,
                }
            )

        rows.sort(key=lambda r: r["transfers"], reverse=True)
        return rows

    @staticmethod
    def _direction(gross_in: int, gross_out: int, address_scoped: bool) -> str:
        """
        The sign of the net flow, or that there is no meaningful sign.

        Chain-wide flow has no direction: every transfer is both an inflow and
        an outflow somewhere, so a chain-level net is always zero and reporting
        one would be a category error.
        """
        if not address_scoped:
            return "not_applicable"
        if gross_in > gross_out:
            return "net_inflow"
        if gross_out > gross_in:
            return "net_outflow"
        return "balanced"


__all__ = ["DEFAULT_FLOW_LIMIT", "TokenFlowSkill"]
