"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    interfaces.dashboard

Purpose:
    Render stored chain intelligence as one self-contained HTML page.

Design goals:
    - One file, no server, no CDN, no external font or script (DR: zero deps)
    - Honesty rendered, not annotated: coverage governs what a panel may claim
    - Token figures never shown as human quantities while decimals are unknown
    - Deterministic: the same database produces the same page
    - Read-only; the snapshot is assembled once and the page is inert

Notes:
    A dashboard is where an honest system most easily becomes a dishonest one.
    "Whale detected: 773 ETH" as a large green number is the exact claim the
    rest of A01 refuses to make -- confident, unqualified, and read at a glance.
    So the visual carries the caveat rather than a footnote:

    * **Coverage is a bar, not a sentence.** A chain with nine stored blocks
      shows a nearly-empty bar toward the 3,600 it would need before an absence
      means anything, and its "no activity" statements are greyed rather than
      shown, so the reason they are absent is visible.
    * **Token amounts are never scaled.** Their decimals are unresolved, so the
      page shows transfer *counts* and *relative* magnitude within one token,
      and labels raw values as raw. A dashboard that printed "1,000,000 USDC"
      from an unscaled integer would be wrong by a factor of a million and look
      ordinary doing it.

    The page is assembled from a :class:`Snapshot` taken once. It embeds no live
    call, so it can be saved, mailed, and opened offline -- and it cannot drift
    between what it says and what the database holds, because it is a photograph
    of the database at one instant.

    The animated background is pure CSS and honours ``prefers-reduced-motion``.
    Motion that cannot be turned off is a distraction in a tool people read
    numbers from.
"""

from __future__ import annotations

import html

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from database.analytics import SqliteAnalyticsRepository
from database.repositories import SqliteBlockRepository
from database.tokens import SqliteTokenRepository
from skills.base import Coverage

#: Blocks of contiguous history below which no negative claim is licensed.
#: Mirrors skills.base.MIN_BLOCKS_FOR_ABSENCE so the bar and the detectors
#: agree on what "enough" means.
ABSENCE_THRESHOLD = 3_600

#: An accent per chain, so a reader tells them apart without reading the label.
#: Values are the brand hues chains use themselves, muted for a dark ground.
_CHAIN_ACCENT: dict[str, str] = {
    "ethereum": "#7b8cff",
    "bnb_chain": "#f3ba2f",
    "polygon": "#a06bff",
    "arbitrum": "#3a9df5",
    "optimism": "#ff5c6c",
    "base": "#4f7dff",
    "avalanche": "#ff5f57",
    "linea": "#61dfff",
    "scroll": "#e8b57a",
    "gnosis": "#3fd0a0",
    "celo": "#f2e05a",
    "mantle": "#9fb4c7",
    "unichain": "#ff5fb0",
    "solana": "#59d6a0",
    "bitcoin": "#f7931a",
}

_DEFAULT_ACCENT = "#8a93b5"


def _accent(chain: str) -> str:
    return _CHAIN_ACCENT.get(chain, _DEFAULT_ACCENT)


# ==============================================================================
# SNAPSHOT — the data, assembled once
# ==============================================================================


@dataclass(frozen=True, slots=True)
class ChainCard:
    """One chain's stored state, everything a card needs."""

    chain: str
    display: str
    accent: str
    blocks: int
    from_height: int | None
    to_height: int | None
    contiguous: bool
    supports_absence: bool
    coverage_limitation: str
    transactions: int
    token_transfers: int
    nft_transfers: int
    largest_native: str
    native_symbol: str
    freshness: str
    top_tokens: tuple[tuple[str, int], ...] = ()

    @property
    def coverage_fraction(self) -> float:
        return min(self.blocks / ABSENCE_THRESHOLD, 1.0)


@dataclass(frozen=True, slots=True)
class FlowNode:
    address: str
    x: float
    y: float
    degree: int
    is_mint_source: bool = False


@dataclass(frozen=True, slots=True)
class FlowEdge:
    src: str
    dst: str
    x1: float
    y1: float
    x2: float
    y2: float
    weight: float  # 0..1, relative within one token
    is_mint: bool = False


@dataclass(frozen=True, slots=True)
class FlowGraph:
    """
    A transfer graph for one token, laid out for inline SVG.

    Scoped to a single token on purpose: raw amounts across tokens are not
    comparable, so a graph mixing them would size its edges by which contract
    uses more decimals. Within one token, relative magnitude is honest.
    """

    chain: str
    token: str
    accent: str
    transfer_count: int
    nodes: tuple[FlowNode, ...] = ()
    edges: tuple[FlowEdge, ...] = ()
    note: str = ""

    @property
    def empty(self) -> bool:
        return not self.edges


@dataclass(frozen=True, slots=True)
class ChainReach:
    """
    One registered chain and whether anything has been captured from it.

    The page used to show only chains with stored history, which quietly turned
    "A01 has two chains" and "A01 supports fifteen and two are ingested" into
    the same picture. Those are different facts and an operator needs the
    second one to know what is available rather than what has been used.
    """

    chain: str
    display: str
    accent: str
    chain_id: int | None
    native: str
    observable: bool
    stored_blocks: int
    note: str = ""

    @property
    def state(self) -> str:
        if not self.observable:
            return "unobservable"
        return "stored" if self.stored_blocks else "idle"


@dataclass(frozen=True, slots=True)
class OperatorFlow:
    """One labelled operator's movement over the window."""

    entity: str
    inflow_count: int
    outflow_count: int
    net: str
    direction: str


@dataclass(frozen=True, slots=True)
class FlowPanel:
    """
    Exchange flow for one chain, with the label list it rests on.

    The label facts are carried beside the figures rather than under them. An
    attribution is somebody else's claim about an address, and a panel showing
    "Binance +631 ETH" without saying who says that address is Binance would be
    presenting a sourced assertion as an observation.
    """

    chain: str
    accent: str
    determined: bool
    reason: str
    labelled_addresses: int = 0
    labelled_entities: int = 0
    label_source: str = ""
    label_confidence: float = 0.0
    scanned: int = 0
    attributed: int = 0
    symbol: str = ""
    operators: tuple[OperatorFlow, ...] = ()
    bounds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The whole page's data, taken at one instant."""

    generated_at: datetime
    database: str
    chains: tuple[ChainCard, ...] = ()
    flow: FlowGraph | None = None
    total_blocks: int = 0
    total_transactions: int = 0
    total_token_transfers: int = 0
    total_nft_transfers: int = 0
    reach: tuple[ChainReach, ...] = ()
    exchange: FlowPanel | None = None

    @property
    def empty(self) -> bool:
        return not self.chains


# ==============================================================================
# COLLECTION
# ==============================================================================


def _freshness(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "unknown"
    delta = now - when
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 90:
        return f"{secs}s ago"
    if secs < 5400:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def collect(
    blocks: SqliteBlockRepository,
    tokens: SqliteTokenRepository,
    analytics: SqliteAnalyticsRepository,
    *,
    database: str,
    now: datetime | None = None,
) -> Snapshot:
    """
    Assemble a snapshot from the repositories.

    Reads only; issues no chain call. Everything the page shows is what storage
    already holds, which is what lets the page be saved and opened offline
    without misrepresenting a stale figure as current.
    """
    from config.rpc.chains import get_chain

    moment = now or datetime.now(UTC)
    cards: list[ChainCard] = []
    busiest_flow: FlowGraph | None = None
    busiest_activity = -1

    total_blocks = total_tx = total_tokens = total_nfts = 0

    for chain in analytics.chains():
        window = analytics.window(chain)
        coverage = Coverage(window=window, threshold=ABSENCE_THRESHOLD)

        try:
            meta = get_chain(chain)
            display = meta.display_name
            symbol = meta.native_currency.symbol
        except Exception:  # noqa: BLE001 - a stored chain missing from the registry
            display = chain.replace("_", " ").title()
            symbol = ""

        highest = blocks.highest(chain)
        biggest_native = blocks.largest_transfers(chain, limit=1)
        native_label = (
            f"{biggest_native[0].value.format(4)} {symbol}"
            if biggest_native
            else "none"
        )

        block_count = blocks.count(chain)
        token_count = tokens.count(chain)
        nft_count = tokens.nft_count(chain)
        top_tokens = tokens.tokens_seen(chain, limit=4)

        total_blocks += block_count
        total_tokens += token_count
        total_nfts += nft_count

        cards.append(
            ChainCard(
                chain=chain,
                display=display,
                accent=_accent(chain),
                blocks=block_count,
                from_height=window.from_height,
                to_height=window.to_height,
                contiguous=window.contiguous,
                supports_absence=coverage.supports_absence,
                coverage_limitation=coverage.limitation,
                transactions=_chain_tx_count(blocks, chain),
                token_transfers=token_count,
                nft_transfers=nft_count,
                largest_native=native_label,
                native_symbol=symbol,
                freshness=_freshness(highest.timestamp if highest else None, moment),
                top_tokens=top_tokens,
            )
        )

        # The flow graph is drawn for whichever chain+token has moved the most,
        # so the page's most detailed view is of its richest data.
        if top_tokens:
            token, count = top_tokens[0]
            if count > busiest_activity:
                busiest_activity = count
                busiest_flow = _build_flow(tokens, chain, token, count)

    total_tx = sum(c.transactions for c in cards)

    cards.sort(key=lambda c: (c.token_transfers + c.transactions), reverse=True)

    stored = {card.chain: card.blocks for card in cards}
    return Snapshot(
        generated_at=moment,
        database=database,
        chains=tuple(cards),
        flow=busiest_flow,
        total_blocks=total_blocks,
        total_transactions=total_tx,
        total_token_transfers=total_tokens,
        total_nft_transfers=total_nfts,
        reach=_collect_reach(stored),
        exchange=_collect_exchange(analytics, cards),
    )


def _collect_reach(stored: dict[str, int]) -> tuple[ChainReach, ...]:
    """
    Every registered chain, whether A01 can read it, and whether it has.

    Reads the capability table rather than probing: this is a snapshot of a
    database, and a page that made fifteen network calls to render would stop
    being one.
    """
    from knowledge.chains import CAPABILITIES

    rows: list[ChainReach] = []
    for entry in CAPABILITIES:
        try:
            meta = entry.config
            display, symbol, chain_id = (
                meta.display_name,
                meta.native_currency.symbol,
                meta.chain_id,
            )
        except Exception:  # noqa: BLE001 - a capability record without a registry entry
            display, symbol, chain_id = entry.chain.replace("_", " ").title(), "", None

        rows.append(
            ChainReach(
                chain=entry.chain,
                display=display,
                accent=_accent(entry.chain),
                chain_id=chain_id,
                native=symbol,
                observable=entry.observable,
                stored_blocks=stored.get(entry.chain, 0),
                # The first limit is the one that most changes how the row
                # should be read; the rest are on `a01 chains --limits`.
                note=entry.limits[0] if entry.limits else "",
            )
        )

    # Chains with history first, then readable-but-unread, then unreadable.
    order = {"stored": 0, "idle": 1, "unobservable": 2}
    rows.sort(key=lambda r: (order[r.state], -r.stored_blocks, r.chain))
    return tuple(rows)


#: Transfers the dashboard scans for its flow panel. Below the skill's own
#: default because a page render should not cost a 50,000-row scan per chain;
#: the panel says when the cap bound it, so a smaller number is visible rather
#: than silently narrowing the answer.
DASHBOARD_SCAN_LIMIT = 20_000


def _operator_row(entity: str, row: Any) -> OperatorFlow:
    """
    One operator's line, with the net rendered as a signed magnitude.

    ``Amount`` refuses a negative because an on-chain quantity cannot be one,
    and it is right to: a net flow is the difference of two quantities, not a
    quantity. So the magnitude is scaled through ``Amount`` -- which is what
    knows where the decimal point goes -- and the sign is carried alongside it.
    """
    from schemas.amount import Amount

    net = int(row.get("net_value", 0) or 0) if isinstance(row, dict) else 0
    sign = "+" if net > 0 else "−" if net < 0 else ""
    return OperatorFlow(
        entity=entity,
        inflow_count=int(row.get("inflow_count", 0) or 0) if isinstance(row, dict) else 0,
        outflow_count=int(row.get("outflow_count", 0) or 0) if isinstance(row, dict) else 0,
        net=f"{sign}{Amount(abs(net)).format(4)}",
        direction="in" if net > 0 else "out" if net < 0 else "flat",
    )


def _collect_exchange(
    analytics: SqliteAnalyticsRepository, cards: list[ChainCard]
) -> FlowPanel | None:
    """
    Exchange flow for the chain with the most attributed movement.

    One chain rather than all of them: the panel exists to show that direction
    is now attributable at all, and running the scan across every stored chain
    would multiply the page's cost by the number of chains for a view nobody
    reads at a glance. The chain chosen is named on the panel.
    """
    from skills.base import SkillRequest
    from skills.exchange_flow import ExchangeFlowSkill

    if not cards:
        return None

    skill = ExchangeFlowSkill()
    best: FlowPanel | None = None

    for card in cards:
        try:
            result = skill.run(
                SkillRequest(
                    chain=card.chain, options={"scan_limit": DASHBOARD_SCAN_LIMIT}
                ),
                analytics,
            )
        except Exception:  # noqa: BLE001 - one chain failing must not cost the page
            continue

        data = result.data or {}
        attributed = int(data.get("attributed", 0) or 0)

        operators = tuple(
            _operator_row(name, row)
            for name, row in list((data.get("entities") or {}).items())[:8]
        )

        panel = FlowPanel(
            chain=card.chain,
            accent=card.accent,
            determined=result.determined,
            reason=result.reason,
            labelled_addresses=int(data.get("labelled_addresses", 0) or 0),
            labelled_entities=int(data.get("labelled_entities", 0) or 0),
            label_source=str(data.get("label_source", "")),
            label_confidence=float(data.get("label_confidence", 0.0) or 0.0),
            scanned=int(data.get("transfers_scanned", 0) or 0),
            attributed=attributed,
            symbol=card.native_symbol,
            operators=operators,
            bounds=tuple(data.get("bounds") or ()),
        )

        if best is None or attributed > best.attributed:
            best = panel

    return best


def _chain_tx_count(blocks: SqliteBlockRepository, chain: str) -> int:
    """Native transaction count for a chain, via the repository's connection."""
    row = blocks.database.connection.execute(
        """
        SELECT COUNT(*) FROM transactions t
          JOIN blocks b ON b.key = t.block_key
         WHERE t.chain = ? AND b.canonical = 1
        """,
        (chain,),
    ).fetchone()
    return int(row[0]) if row else 0


def _build_flow(
    tokens: SqliteTokenRepository, chain: str, token: str, activity: int
) -> FlowGraph:
    """
    Lay out a transfer graph for one token as SVG coordinates.

    A circular layout computed here rather than by a force simulation in the
    browser: the page ships no script library, and a deterministic layout means
    the same database draws the same graph. Nodes are the busiest addresses,
    edges the transfers between them, sized by value *within this one token* --
    the only comparison its raw amounts support.
    """
    import math

    transfers = tokens.largest_transfers(chain, token, limit=60)
    if not transfers:
        return FlowGraph(chain=chain, token=token, accent=_accent(chain), transfer_count=activity)

    # Degree per address decides who is drawn; the graph is only legible with a
    # dozen or so nodes, so the rest are folded out rather than crammed in.
    degree: dict[str, int] = {}
    for t in transfers:
        degree[t.from_address.value] = degree.get(t.from_address.value, 0) + 1
        degree[t.to_address.value] = degree.get(t.to_address.value, 0) + 1

    top = sorted(degree, key=lambda a: degree[a], reverse=True)[:14]
    keep = set(top)

    values = [t.value.raw for t in transfers if t.value.raw > 0]
    hi = max(values) if values else 1

    cx, cy, radius = 300.0, 260.0, 200.0
    angle = {addr: (2 * math.pi * i / len(top)) for i, addr in enumerate(top)}
    pos = {
        addr: (cx + radius * math.cos(a), cy + radius * math.sin(a))
        for addr, a in angle.items()
    }

    nodes = tuple(
        FlowNode(address=addr, x=pos[addr][0], y=pos[addr][1], degree=degree[addr])
        for addr in top
    )

    edges: list[FlowEdge] = []
    seen: set[tuple[str, str]] = set()
    for t in transfers:
        s, d = t.from_address.value, t.to_address.value
        if s not in keep or d not in keep or (s, d) in seen:
            continue
        seen.add((s, d))
        x1, y1 = pos[s]
        x2, y2 = pos[d]
        edges.append(
            FlowEdge(
                src=s,
                dst=d,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                weight=min(t.value.raw / hi, 1.0) if hi else 0.0,
                is_mint=t.is_mint,
            )
        )

    return FlowGraph(
        chain=chain,
        token=token,
        accent=_accent(chain),
        transfer_count=activity,
        nodes=nodes,
        edges=tuple(edges),
        note=(
            "Edge thickness is relative value within this one token. Amounts are "
            "raw base units — the token's decimals are unresolved, so they are "
            "comparable here and nowhere else."
        ),
    )


# ==============================================================================
# RENDERING
# ==============================================================================


def _e(text: Any) -> str:
    return html.escape(str(text))


def _short(address: str) -> str:
    if len(address) <= 13:
        return address
    return f"{address[:6]}…{address[-4:]}"


def render(snapshot: Snapshot) -> str:
    """Render the snapshot as one self-contained HTML document."""
    return _DOCUMENT.format(
        css=_CSS,
        orbs=_orbs(),
        header=_header(snapshot),
        totals=_totals(snapshot),
        chains=_chain_grid(snapshot),
        reach=_reach_panel(snapshot.reach),
        exchange=_exchange_panel(snapshot.exchange),
        flow=_flow_panel(snapshot.flow),
        footer=_footer(snapshot),
        script=_SCRIPT,
    )


def _reach_panel(reach: tuple[ChainReach, ...]) -> str:
    """Registered chains against ingested ones. Reach is not the same as use."""
    if not reach:
        return ""

    observable = sum(1 for r in reach if r.observable)
    ingested = sum(1 for r in reach if r.stored_blocks)

    rows = "".join(
        f"""
        <tr class="reach-row reach-{_e(r.state)}">
          <td><span class="reach-dot" style="background:{_e(r.accent)}"></span>
              {_e(r.display)}</td>
          <td class="mono">{_e(r.chain_id or '—')}</td>
          <td class="mono">{_e(r.native or '—')}</td>
          <td class="mono">{_e(f"{r.stored_blocks:,}" if r.stored_blocks else "—")}</td>
          <td class="reach-state">{_e(
              "ingested" if r.stored_blocks
              else "readable, nothing captured" if r.observable
              else "no sensor"
          )}</td>
        </tr>"""
        for r in reach
    )

    return f"""
    <section class="section">
      <h2 class="section-title">Reach</h2>
      <div class="glass panel">
        <p class="panel-lead">
          {_e(len(reach))} chain(s) registered · {_e(observable)} readable ·
          {_e(ingested)} with stored history.
          A registered chain is one A01 <em>can</em> read, which is not the same
          as one it has read; only the ingested rows can answer a question.
        </p>
        <div class="table-scroll">
          <table class="reach-table">
            <thead><tr>
              <th>chain</th><th>id</th><th>native</th><th>blocks</th><th>state</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        <p class="panel-note">
          Each chain also carries limits that bound what may be concluded from
          it — native units differ, block times differ by two orders of
          magnitude, and one chain has no usable finality tag. Run
          <code>a01 chains --limits</code> to read them.
        </p>
      </div>
    </section>
    """


def _exchange_panel(panel: FlowPanel | None) -> str:
    """
    Deposits to and withdrawals from labelled exchange addresses.

    When nothing is loaded this renders the reason rather than a zero. An
    exchange-flow figure of zero with no labels behind it is a confident
    statement about a rule that never ran.
    """
    if panel is None:
        return ""

    if not panel.determined or not panel.operators:
        return f"""
        <section class="section">
          <h2 class="section-title">Exchange flow</h2>
          <div class="glass panel">
            <p class="panel-lead undetermined">{_e(panel.reason)}</p>
            <p class="panel-note">
              Direction comes from a labelled address list, and A01 never infers
              one from behaviour. Load a list with
              <code>a01 labels --db … --load data/labels</code>.
            </p>
          </div>
        </section>
        """

    rows = "".join(
        f"""
        <tr>
          <td>{_e(op.entity)}</td>
          <td class="mono">{_e(op.inflow_count)}</td>
          <td class="mono">{_e(op.outflow_count)}</td>
          <td class="mono flow-{_e(op.direction)}">{_e(op.net)} {_e(panel.symbol)}</td>
        </tr>"""
        for op in panel.operators
    )

    bounds = "".join(f"<li>{_e(bound)}</li>" for bound in panel.bounds)
    unverified = panel.label_confidence < 0.9

    return f"""
    <section class="section">
      <h2 class="section-title">Exchange flow · {_e(panel.chain)}</h2>
      <div class="glass panel" style="--accent:{_e(panel.accent)}">
        <p class="panel-lead">
          {_e(f"{panel.attributed:,}")} of {_e(f"{panel.scanned:,}")} scanned
          transfer(s) touched one of
          {_e(f"{panel.labelled_addresses:,}")} labelled address(es) across
          {_e(panel.labelled_entities)} operator(s).
        </p>
        <p class="attribution {'unverified' if unverified else ''}">
          attributed from <span class="mono">{_e(panel.label_source or 'an unnamed list')}</span>
          at confidence {_e(panel.label_confidence)}
          {'— unverified, so an attribution here is an external claim rather than an established fact' if unverified else ''}
        </p>
        <div class="table-scroll">
          <table class="flow-table">
            <thead><tr><th>operator</th><th>in</th><th>out</th><th>net</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        <ul class="bounds">{bounds}</ul>
        <p class="panel-note">
          Direction is what moved, not why. A deposit is consistent with an
          intent to sell and with collateral, market making and custody moves;
          A01 does not claim to tell them apart.
        </p>
      </div>
    </section>
    """


def _orbs() -> str:
    """The animated background. Five drifting radial-gradient spheres."""
    return "".join(f'<div class="orb orb-{i}"></div>' for i in range(1, 6))


def _header(s: Snapshot) -> str:
    stamp = s.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"""
    <header class="masthead">
      <div class="brand">
        <span class="brand-mark">A01</span>
        <div class="brand-text">
          <h1>Blockchain Intelligence</h1>
          <p>CIE-OS · evidence, not decisions</p>
        </div>
      </div>
      <div class="stamp">
        <span class="stamp-dot"></span>
        snapshot {_e(stamp)}
      </div>
    </header>
    """


def _totals(s: Snapshot) -> str:
    tiles = [
        ("chains", len(s.chains), "with stored history"),
        ("blocks", f"{s.total_blocks:,}", "canonical"),
        ("transactions", f"{s.total_transactions:,}", "native"),
        ("token transfers", f"{s.total_token_transfers:,}", "ERC-20"),
        ("nft transfers", f"{s.total_nft_transfers:,}", "ERC-721"),
    ]
    cells = "".join(
        f"""
        <div class="tile">
          <span class="tile-label">{_e(label)}</span>
          <span class="tile-value">{_e(value)}</span>
          <span class="tile-note">{_e(note)}</span>
        </div>"""
        for label, value, note in tiles
    )
    return f'<section class="totals glass">{cells}</section>'


def _chain_grid(s: Snapshot) -> str:
    if not s.chains:
        return (
            '<section class="empty glass">'
            "<h2>No chain data stored yet</h2>"
            "<p>Run <code>a01 ingest --db … --blocks 50 --tokens</code> and reopen "
            "this page.</p></section>"
        )
    cards = "".join(_chain_card(c) for c in s.chains)
    return f"""
    <section class="section">
      <h2 class="section-title">Multi-chain overview</h2>
      <div class="chain-grid">{cards}</div>
    </section>
    """


def _chain_card(c: ChainCard) -> str:
    pct = round(c.coverage_fraction * 100, 1)

    if c.supports_absence:
        cov_state = "ok"
        cov_text = "window deep enough for negative findings"
    else:
        cov_state = "thin"
        cov_text = _e(c.coverage_limitation or "window too thin for negative findings")

    range_text = (
        f"#{c.from_height:,} – #{c.to_height:,}"
        if c.from_height is not None and c.to_height is not None
        else "—"
    )
    gap_badge = (
        ""
        if c.contiguous
        else '<span class="badge badge-warn">has gaps · counts are floors</span>'
    )

    tokens = "".join(
        f'<li><span class="tok-addr">{_e(_short(addr))}</span>'
        f'<span class="tok-count">{count:,}</span></li>'
        for addr, count in c.top_tokens
    )
    tokens_block = (
        f'<ul class="token-list">{tokens}</ul>'
        if tokens
        else '<p class="muted">no token transfers stored</p>'
    )

    return f"""
    <article class="chain-card glass" style="--accent:{c.accent}">
      <div class="chain-head">
        <span class="chain-dot"></span>
        <h3>{_e(c.display)}</h3>
        <span class="chain-fresh">{_e(c.freshness)}</span>
      </div>

      <div class="chain-stats">
        <div><span class="k">blocks</span><span class="v">{c.blocks:,}</span></div>
        <div><span class="k">native tx</span><span class="v">{c.transactions:,}</span></div>
        <div><span class="k">tokens</span><span class="v">{c.token_transfers:,}</span></div>
        <div><span class="k">nfts</span><span class="v">{c.nft_transfers:,}</span></div>
      </div>

      <div class="range">{_e(range_text)} {gap_badge}</div>

      <div class="coverage coverage-{cov_state}">
        <div class="coverage-track">
          <div class="coverage-fill" style="width:{pct}%"></div>
          <span class="coverage-goal">3,600</span>
        </div>
        <span class="coverage-text">{cov_text}</span>
      </div>

      <div class="native-line">
        largest native transfer
        <strong>{_e(c.largest_native)}</strong>
      </div>

      <div class="token-block">
        <span class="block-title">busiest tokens</span>
        {tokens_block}
      </div>
    </article>
    """


def _flow_panel(flow: FlowGraph | None) -> str:
    if flow is None or flow.empty:
        return (
            '<section class="section"><h2 class="section-title">Token flow</h2>'
            '<div class="glass empty-flow"><p class="muted">No token transfers '
            "stored yet — ingest with <code>--tokens</code> to draw a flow "
            "graph.</p></div></section>"
        )

    edges = "".join(_edge_svg(e, flow.accent) for e in flow.edges)
    nodes = "".join(_node_svg(n, flow.accent) for n in flow.nodes)

    return f"""
    <section class="section">
      <h2 class="section-title">Token flow · {_e(_short(flow.token))}</h2>
      <div class="flow glass" style="--accent:{flow.accent}">
        <div class="flow-meta">
          <div><span class="k">contract</span><span class="v mono">{_e(_short(flow.token))}</span></div>
          <div><span class="k">chain</span><span class="v">{_e(flow.chain)}</span></div>
          <div><span class="k">transfers</span><span class="v">{flow.transfer_count:,}</span></div>
          <div><span class="k">addresses</span><span class="v">{len(flow.nodes)}</span></div>
        </div>
        <svg class="flow-svg" viewBox="0 0 600 520" role="img"
             aria-label="Token transfer graph">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="{flow.accent}" opacity="0.7"/>
            </marker>
          </defs>
          <g class="edges">{edges}</g>
          <g class="nodes">{nodes}</g>
        </svg>
        <p class="flow-note">{_e(flow.note)}</p>
      </div>
    </section>
    """


def _edge_svg(e: FlowEdge, accent: str) -> str:
    width = round(0.6 + e.weight * 5.5, 2)
    opacity = round(0.18 + e.weight * 0.55, 2)
    colour = "#59d6a0" if e.is_mint else accent
    # A slight quadratic bow so opposing edges do not overlap into one line.
    mx = (e.x1 + e.x2) / 2 + (e.y2 - e.y1) * 0.08
    my = (e.y1 + e.y2) / 2 - (e.x2 - e.x1) * 0.08
    return (
        f'<path class="edge" d="M{e.x1:.1f},{e.y1:.1f} Q{mx:.1f},{my:.1f} '
        f'{e.x2:.1f},{e.y2:.1f}" stroke="{colour}" stroke-width="{width}" '
        f'fill="none" opacity="{opacity}" marker-end="url(#arrow)"/>'
    )


def _node_svg(n: FlowNode, accent: str) -> str:
    r = round(5 + min(n.degree, 12) * 1.3, 1)
    return (
        f'<g class="node" transform="translate({n.x:.1f},{n.y:.1f})">'
        f'<circle r="{r}" fill="{accent}" opacity="0.85"/>'
        f'<circle r="{r}" fill="none" stroke="{accent}" stroke-width="1" '
        f'opacity="0.35" class="node-halo"/>'
        f'<text y="{-r - 5:.1f}" text-anchor="middle" class="node-label">'
        f"{_e(_short(n.address))}</text></g>"
    )


def _footer(s: Snapshot) -> str:
    return f"""
    <footer class="footer">
      <p>
        A01 provides evidence, not decisions. Coverage bars gate what a panel may
        claim; token amounts are raw base units with unresolved decimals.
      </p>
      <p class="muted">{_e(s.database)}</p>
    </footer>
    """


# ==============================================================================
# STATIC ASSETS (inline)
# ==============================================================================

_CSS = """
:root {
  --bg: #070810;
  --ink: #e6e9f5;
  --muted: #8b93b2;
  --glass: rgba(20, 23, 38, 0.55);
  --glass-line: rgba(255, 255, 255, 0.08);
  --ok: #59d6a0;
  --warn: #f5b74f;
  --thin: #ff6b7d;
  --mono: ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: var(--sans);
  color: var(--ink);
  background: var(--bg);
  min-height: 100vh;
  overflow-x: hidden;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

/* --- animated orb background --------------------------------------------- */
.orbs { position: fixed; inset: 0; z-index: 0; overflow: hidden; }
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  opacity: 0.55;
  will-change: transform;
}
.orb-1 { width: 46vw; height: 46vw; left: -8vw; top: -6vw;
  background: radial-gradient(circle at 30% 30%, #4b5cff, transparent 70%);
  animation: drift1 26s ease-in-out infinite; }
.orb-2 { width: 40vw; height: 40vw; right: -10vw; top: 4vw;
  background: radial-gradient(circle at 40% 40%, #9b4bff, transparent 70%);
  animation: drift2 32s ease-in-out infinite; }
.orb-3 { width: 38vw; height: 38vw; left: 20vw; bottom: -14vw;
  background: radial-gradient(circle at 50% 50%, #1fb8a6, transparent 70%);
  animation: drift3 30s ease-in-out infinite; }
.orb-4 { width: 28vw; height: 28vw; right: 12vw; bottom: -6vw;
  background: radial-gradient(circle at 50% 50%, #ff5c8a, transparent 70%);
  animation: drift1 36s ease-in-out infinite reverse; }
.orb-5 { width: 24vw; height: 24vw; left: 42vw; top: 30vw;
  background: radial-gradient(circle at 50% 50%, #3a9df5, transparent 70%);
  animation: drift2 40s ease-in-out infinite; }
@keyframes drift1 { 0%,100%{transform:translate(0,0) scale(1)} 50%{transform:translate(6vw,4vw) scale(1.12)} }
@keyframes drift2 { 0%,100%{transform:translate(0,0) scale(1)} 50%{transform:translate(-5vw,5vw) scale(1.08)} }
@keyframes drift3 { 0%,100%{transform:translate(0,0) scale(1)} 50%{transform:translate(4vw,-4vw) scale(1.15)} }

/* --- layout -------------------------------------------------------------- */
.shell { position: relative; z-index: 1; max-width: 1180px;
  margin: 0 auto; padding: 40px 24px 80px; }

.glass {
  background: var(--glass);
  border: 1px solid var(--glass-line);
  border-radius: 18px;
  backdrop-filter: blur(22px) saturate(140%);
  -webkit-backdrop-filter: blur(22px) saturate(140%);
  box-shadow: 0 18px 50px rgba(0,0,0,0.35);
}

/* --- masthead ------------------------------------------------------------ */
.masthead { display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 16px; margin-bottom: 32px; }
.brand { display: flex; align-items: center; gap: 16px; }
.brand-mark {
  font-family: var(--mono); font-weight: 700; font-size: 20px;
  padding: 12px 14px; border-radius: 14px; letter-spacing: 1px;
  background: linear-gradient(135deg, #4b5cff, #9b4bff);
  box-shadow: 0 8px 24px rgba(75,92,255,0.4);
}
.brand-text h1 { margin: 0; font-size: 22px; font-weight: 650; letter-spacing: -0.2px; }
.brand-text p { margin: 2px 0 0; color: var(--muted); font-size: 13px; }
.stamp { display: flex; align-items: center; gap: 8px; color: var(--muted);
  font-size: 13px; font-family: var(--mono); }
.stamp-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok);
  box-shadow: 0 0 10px var(--ok); animation: pulse 2.6s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }

/* --- totals -------------------------------------------------------------- */
.totals { display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 4px; padding: 22px; margin-bottom: 34px; }
.tile { display: flex; flex-direction: column; gap: 4px; padding: 6px 14px;
  border-right: 1px solid var(--glass-line); }
.tile:last-child { border-right: none; }
.tile-label { color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.6px; }
.tile-value { font-size: 30px; font-weight: 680; font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px; }
.tile-note { color: var(--muted); font-size: 12px; }

/* --- sections ------------------------------------------------------------ */
.section { margin-bottom: 34px; }
.section-title { font-size: 15px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 1px; color: var(--muted); margin: 0 0 16px 4px; }

/* --- chain cards --------------------------------------------------------- */
.chain-grid { display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
.chain-card { padding: 20px; display: flex; flex-direction: column; gap: 14px;
  transition: transform 0.2s ease, box-shadow 0.2s ease; }
.chain-card:hover { transform: translateY(-3px);
  box-shadow: 0 24px 60px rgba(0,0,0,0.45); }
.chain-head { display: flex; align-items: center; gap: 10px; }
.chain-dot { width: 12px; height: 12px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 14px var(--accent); }
.chain-head h3 { margin: 0; font-size: 17px; font-weight: 620; flex: 1; }
.chain-fresh { font-family: var(--mono); font-size: 12px; color: var(--muted); }

.chain-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.chain-stats > div { display: flex; flex-direction: column; }
.chain-stats .k { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.4px; }
.chain-stats .v { font-size: 19px; font-weight: 640; font-variant-numeric: tabular-nums; }

.range { font-family: var(--mono); font-size: 12px; color: var(--muted);
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 20px;
  font-family: var(--sans); }
.badge-warn { background: rgba(245,183,79,0.16); color: var(--warn);
  border: 1px solid rgba(245,183,79,0.3); }

.coverage { display: flex; flex-direction: column; gap: 6px; }
.coverage-track { position: relative; height: 8px; border-radius: 6px;
  background: rgba(255,255,255,0.07); overflow: hidden; }
.coverage-fill { position: absolute; left: 0; top: 0; bottom: 0;
  border-radius: 6px; background: var(--accent);
  transition: width 0.8s cubic-bezier(0.2,0.8,0.2,1); }
.coverage-ok .coverage-fill { background: var(--ok); }
.coverage-thin .coverage-fill { background: var(--thin); }
.coverage-goal { position: absolute; right: 6px; top: -18px; font-size: 10px;
  color: var(--muted); font-family: var(--mono); }
.coverage-text { font-size: 12px; }
.coverage-ok .coverage-text { color: var(--ok); }
.coverage-thin .coverage-text { color: var(--muted); }

.native-line { font-size: 13px; color: var(--muted);
  display: flex; justify-content: space-between; align-items: center;
  padding-top: 12px; border-top: 1px solid var(--glass-line); }
.native-line strong { color: var(--ink); font-variant-numeric: tabular-nums;
  font-size: 15px; }

.token-block { display: flex; flex-direction: column; gap: 8px; }
.block-title { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.4px; }
.token-list { list-style: none; margin: 0; padding: 0; display: flex;
  flex-direction: column; gap: 5px; }
.token-list li { display: flex; justify-content: space-between;
  font-family: var(--mono); font-size: 12px; }
.tok-addr { color: var(--muted); }
.tok-count { color: var(--ink); font-variant-numeric: tabular-nums; }

/* --- flow graph ---------------------------------------------------------- */
.flow { padding: 22px; }
.flow-meta { display: flex; gap: 28px; flex-wrap: wrap; margin-bottom: 12px; }
.flow-meta > div { display: flex; flex-direction: column; }
.flow-meta .k { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.4px; }
.flow-meta .v { font-size: 16px; font-weight: 620; }
.flow-svg { width: 100%; height: auto; display: block; }
.mono { font-family: var(--mono); }
.node-label { fill: var(--muted); font-size: 9px; font-family: var(--mono); }
.node-halo { animation: halo 3.4s ease-in-out infinite; transform-origin: center; }
@keyframes halo { 0%,100%{opacity:0.35; r:inherit} 50%{opacity:0.05} }
.edge { stroke-linecap: round; }
.flow-note { color: var(--muted); font-size: 12px; margin: 14px 0 0;
  max-width: 60ch; }

/* --- reach + exchange panels --------------------------------------------- */
.panel { padding: 24px 26px; }
.panel-lead { margin: 0 0 14px; font-size: 14px; max-width: 78ch; }
.panel-lead em { color: var(--ink); font-style: normal; border-bottom: 1px dotted var(--muted); }
.panel-lead.undetermined { color: var(--warn); }
.panel-note { margin: 16px 0 0; color: var(--muted); font-size: 12px; max-width: 72ch; }
.table-scroll { overflow-x: auto; }
.reach-table, .flow-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.reach-table th, .flow-table th {
  text-align: left; font-weight: 500; color: var(--muted);
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0 12px 8px 0; border-bottom: 1px solid var(--glass-line);
}
.reach-table td, .flow-table td {
  padding: 7px 12px 7px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
  white-space: nowrap;
}
.mono { font-family: var(--mono); }
.reach-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 9px; vertical-align: middle; }
.reach-state { color: var(--muted); font-size: 12px; }
/* A chain A01 cannot read is dimmed rather than hidden: the gap is a missing
   sensor, which is a different problem from an unsupported chain. */
.reach-unobservable { opacity: 0.45; }
.reach-idle { opacity: 0.75; }
.reach-stored .reach-state { color: var(--ok); }

.attribution { margin: 0 0 16px; font-size: 12px; color: var(--muted); max-width: 78ch; }
.attribution.unverified { color: var(--warn); }
.flow-in { color: var(--ok); }
.flow-out { color: var(--thin); }
.flow-flat { color: var(--muted); }
.bounds { margin: 16px 0 0; padding-left: 18px; color: var(--muted);
  font-size: 12px; max-width: 78ch; }
.bounds li { margin: 3px 0; }

/* --- misc ---------------------------------------------------------------- */
.muted { color: var(--muted); }
code { font-family: var(--mono); font-size: 0.9em; background: rgba(255,255,255,0.07);
  padding: 2px 6px; border-radius: 5px; }
.empty, .empty-flow { padding: 40px; text-align: center; }
.empty h2 { margin: 0 0 8px; }
.footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--glass-line);
  color: var(--muted); font-size: 13px; }
.footer p { margin: 4px 0; max-width: 70ch; }

@media (max-width: 720px) {
  .totals { grid-template-columns: repeat(2, 1fr); }
  .tile { border-right: none; }
}
@media (prefers-reduced-motion: reduce) {
  .orb, .stamp-dot, .node-halo { animation: none; }
  .coverage-fill { transition: none; }
}
"""

_SCRIPT = """
// Count-up on the total tiles. Progressive enhancement only: the real numbers
// are already in the DOM, so a reader with scripting off sees the true values,
// not zeros.
(function () {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const tiles = document.querySelectorAll('.tile-value');
  tiles.forEach(function (el) {
    const raw = el.textContent.replace(/,/g, '');
    const target = parseInt(raw, 10);
    if (!isFinite(target) || target <= 0) return;
    const dur = 700, start = performance.now();
    function step(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased).toLocaleString();
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });
})();
"""

_DOCUMENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>A01 Blockchain Intelligence</title>
<style>{css}</style>
</head>
<body>
<div class="orbs">{orbs}</div>
<div class="shell">
{header}
{totals}
{chains}
{reach}
{exchange}
{flow}
{footer}
</div>
<script>{script}</script>
</body>
</html>
"""


__all__ = [
    "ABSENCE_THRESHOLD",
    "DASHBOARD_SCAN_LIMIT",
    "ChainCard",
    "ChainReach",
    "FlowGraph",
    "FlowPanel",
    "OperatorFlow",
    "Snapshot",
    "collect",
    "render",
]
