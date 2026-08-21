"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    cli.main

Purpose:
    Argument parsing and command dispatch for the A01 command line.

Commands
--------
investigate
    Run the intelligence pipeline over a subject and render the result.
detectors
    List registered detectors with their maturity, so a caller can tell
    what A01 can actually conclude before relying on it.
doctor
    Self-check: imports, chain registry, pipeline wiring, secret handling.

Exit codes
----------
0  success
1  usage or input error
2  investigation completed but a pipeline stage failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from interfaces.rest import DEFAULT_HOST as REST_HOST, DEFAULT_PORT as REST_PORT

from .render import render_decision, render_narrative, render_text

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_DEGRADED = 2


# =============================================================================
# Subject loading
# =============================================================================


def load_subject(args: argparse.Namespace) -> dict[str, Any]:
    """
    Build the subject descriptor from CLI arguments.

    A subject file and an inline address can be combined: the file supplies
    context (population, supply, history) and the flag names the target.
    """
    subject: dict[str, Any] = {}

    if args.subject:
        path = Path(args.subject)
        if not path.is_file():
            raise FileNotFoundError(f"subject file not found: {path}")
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"subject file is not valid JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError("subject file must contain a JSON object")
        subject.update(loaded)

    if args.address:
        subject["address"] = args.address

    if not subject.get("address"):
        raise ValueError("no subject address supplied; use --address or --subject")

    return subject


def load_subject_file(path_text: str) -> dict[str, Any]:
    """
    Read a subject override file.

    Overrides supply what storage cannot yet answer — a balance, a circulating
    supply. The service applies them *after* composing from storage, so an
    operator's figure stays visibly theirs rather than being mistaken for
    something A01 established.
    """
    path = Path(path_text)
    if not path.is_file():
        raise FileNotFoundError(f"subject file not found: {path}")
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"subject file is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("subject file must contain a JSON object")
    return loaded


# =============================================================================
# Commands
# =============================================================================


def cmd_investigate(args: argparse.Namespace) -> int:
    """
    Run an investigation and render the result.

    Goes through :class:`IntelligenceService` rather than driving the engine
    directly, so the CLI and the REST API cannot answer the same question
    differently. The CLI's job here is argument handling and rendering.
    """
    from interfaces import IntelligenceService

    overrides: dict[str, Any] | None = None
    try:
        if args.subject:
            overrides = load_subject_file(args.subject)
        if not args.db and not args.address and not overrides:
            raise ValueError(
                "no subject: use --address, --subject, or --db"
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    result = IntelligenceService(database_path=args.db).investigate(
        chain=args.chain, address=args.address, subject=overrides
    )

    if not result.ok:
        print(f"error: {result.error}", file=sys.stderr)
        return EXIT_USAGE

    payload = result.data

    if args.format == "json":
        print(json.dumps(payload, indent=2, default=str))
    else:
        rendered = dict(payload["package"])
        if "composition" in payload:
            rendered["composition"] = payload["composition"]
        print(render_text(rendered))
        print(render_decision(payload["decision"]))
        print(render_narrative(payload["narrative"]))

    failures = (
        (payload["package"].get("pipeline") or {})
        .get("metadata", {})
        .get("failure_count", 0)
    )
    return EXIT_DEGRADED if failures else EXIT_OK


def cmd_detectors(args: argparse.Namespace) -> int:
    """
    List detectors and their maturity.

    Maturity is reported because a caller must be able to tell a validated
    conclusion from a scaffold's guess before acting on either. The rows come
    from `decision.maturity.REGISTRY`, which is also the gate that decides
    whether a detector may alert -- so this listing cannot drift from the
    policy it describes.
    """
    from interfaces import IntelligenceService

    result = IntelligenceService().detectors()
    if args.format == "json":
        print(json.dumps(result.as_dict(), indent=2))
        return EXIT_OK

    print(f"{'ID':<18}{'ANALYZER':<16}{'MATURITY':<14}{'CEILING':<10}{'ALERTS':<8}BLOCKED BY")
    print("-" * 100)
    for row in result.data["detectors"]:
        print(
            f"{row['detector']:<18}{row['analyzer']:<16}{row['maturity']:<14}"
            f"{row['ceiling']:<10.2f}{'yes' if row['may_alert'] else 'no':<8}"
            f"{row['blocked_by']}"
        )
    print()
    rows = result.data["detectors"]
    alerting = [row for row in rows if row["may_alert"]]
    muted = [row for row in rows if not row["may_alert"]]
    if alerting:
        # The counts are derived. A fixed "ceiling is 1.0" was accurate
        # while every detector was validated and became wrong the moment
        # one was not -- the same failure the maturity gate exists to stop
        # a detector committing about itself.
        print(
            f"{len(alerting)} of {len(rows)} detector(s) validated and may "
            "alert at a confidence ceiling of 1.0."
        )
        if muted:
            print(
                f"{len(muted)} held below that ceiling, each with its reason "
                "in the last column."
            )
        print(
            "Run `a01 verify detectors` to re-verify against labelled "
            "evaluation cases."
        )
    else:
        print(
            "Alerting requires validated maturity, which requires a measured error\n"
            "rate from evaluation/. Run `a01 verify detectors` to check readiness."
        )
    return EXIT_OK


def cmd_skills(args: argparse.Namespace) -> int:
    """
    List the skills layer, and what each one is bounded by.

    The planned list is printed alongside the implemented one because eighteen
    skill folders exist and three have code. Showing only the three would hide
    the plan; showing all eighteen without the distinction would advertise
    capabilities that are directories.
    """
    from skills import default_registry

    registry = default_registry()
    catalog = registry.catalog()
    planned = registry.planned()

    if args.format == "json":
        print(json.dumps({"implemented": list(catalog), "planned": list(planned)}, indent=2))
        return EXIT_OK

    print(f"{'SKILL':<20}{'READINESS':<14}DESCRIPTION")
    print("-" * 88)
    for entry in catalog:
        print(f"{entry['name']:<20}{entry['readiness']:<14}{entry['description']}")
        if entry["bounded_by"]:
            print(f"{'':<34}bounded by: {entry['bounded_by']}")

    print(f"\n{len(planned)} skill(s) specified but not built:")
    for entry in planned:
        print(f"  {entry['name']:<20}{entry['blocked_by']}")
    print(
        "\nA skill answers from stored history only. Every result states the "
        "window\nit used, and whether that window is deep enough for an "
        "absence to mean\nanything."
    )
    return EXIT_OK


def cmd_chains(args: argparse.Namespace) -> int:
    """
    Every registered chain, what A01 can observe on it, and what bounds it.

    ``knowledge/chains.py`` has described itself as feeding "`cli chains` and
    the dashboard" since it was written, and neither existed: fifteen chains
    were registered with no way for an operator to see which of them A01 can
    actually read. A registry entry is not a capability, and until this command
    the difference was invisible from outside the code.

    ``--probe`` re-measures against live endpoints instead of reading the
    table. Off by default because it is fifteen chains' worth of network calls,
    and because a stale-but-dated fact is more useful than an unavailable one.
    """
    from knowledge.chains import probe, summary

    report = summary()

    if args.probe:
        results = [probe(entry["chain"]).as_dict() for entry in report["chains"]]
        if args.format == "json":
            print(json.dumps({"probed": results}, indent=2))
            return EXIT_OK

        print(f"{'CHAIN':<12}{'REACHABLE':<11}{'SENSOR':<9}{'LOGS':<7}{'ARCHIVE':<9}HEAD")
        print("-" * 78)
        drifted = 0
        for row in results:
            print(
                f"{row['chain']:<12}{str(row['reachable']):<11}"
                f"{str(row['has_sensor']):<9}{str(row['supports_logs']):<7}"
                f"{str(row['archive_available']):<9}{row['head'] or row['error'][:34]}"
            )
            for note in row["drift"]:
                drifted += 1
                print(f"{'':<12}drift: {note}")
        print()
        print(
            f"{drifted} field(s) disagree with the table measured on "
            f"{report['measured_on']}."
            if drifted
            else f"No drift from the table measured on {report['measured_on']}."
        )
        return EXIT_OK

    if args.format == "json":
        print(json.dumps(report, indent=2))
        return EXIT_OK

    print(
        f"measured   : {report['measured_on']}\n"
        f"registered : {report['total']} chain(s), {report['observable']} observable, "
        f"{report['token_capable']} token-capable"
    )
    print()
    print(f"{'CHAIN':<12}{'ID':<9}{'NATIVE':<8}{'BLOCK':<8}{'FINALITY':<14}{'DEPTH':<7}OBSERVABLE")
    print("-" * 78)
    for entry in report["chains"]:
        block_time = (
            f"{entry['block_time_seconds']}s" if entry["block_time_seconds"] else "-"
        )
        print(
            f"{entry['chain']:<12}{str(entry['chain_id'] or '-'):<9}"
            f"{entry['native_currency']:<8}{block_time:<8}"
            f"{entry['finality']:<14}{entry['reorg_depth']:<7}"
            f"{'yes' if entry['observable'] else 'NO'}"
        )

    unobservable = report["registry_only"]
    if unobservable:
        print(f"\n{len(unobservable)} chain(s) configured and unobservable:")
        for name in unobservable:
            entry = next(e for e in report["chains"] if e["chain"] == name)
            print(f"  {name:<12}{entry['limits'][0]}")

    if args.limits:
        print("\nlimits, per chain:")
        for entry in report["chains"]:
            print(f"\n  {entry['chain']}")
            for limit in entry["limits"]:
                print(f"    - {limit}")
    else:
        print(
            "\nEvery chain carries limits that bound what may be concluded from "
            "it.\nRun with --limits to read them, or --probe to re-measure "
            "against live\nendpoints.\n\nPer-chain details: chains/<number>_<chain>/ "
            "(README.md, endpoints.yaml, limits.yaml, adapter.py)"
        )
    return EXIT_OK


def cmd_labels(args: argparse.Namespace) -> int:
    """
    Load address labels from a file, or report what is already loaded.

    Labels are the one input A01 cannot derive. Everything else it knows it
    read off a chain; who owns an address is an external assertion, and
    ``identity/design_rules.md`` forbids inferring one from behaviour. So this
    command is the only way an exchange address becomes known to the system,
    and it records where each assertion came from.
    """
    from database import Database
    from pipeline.labels import LabelFileError, load
    from tiers import LabelRepository

    with Database(args.db) as database:
        repository = LabelRepository(database)

        if args.load:
            try:
                reports = load(
                    args.load,
                    repository,
                    chain=args.chain,
                    category=args.category,
                    source=args.source or "",
                    confidence=args.confidence,
                    verification_status=args.status,
                )
            except LabelFileError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_USAGE

            if not reports:
                print(f"no label files found under {args.load}", file=sys.stderr)
                return EXIT_USAGE

            for report in reports:
                print(f"file       : {report.path}")
                print(f"source     : {report.source}")
                # Named explicitly, because a category applied from the command
                # line is a claim the file never made. 2,858 rows silently
                # marked `exchange` would be indistinguishable afterwards from
                # 2,858 rows whose source said so.
                origin = "from --category" if report.category_supplied_by_caller else "from the file"
                print(f"category   : {report.category} ({origin})")
                print(
                    f"confidence : {report.confidence} "
                    f"({report.verification_status}; a policy value, not a measurement)"
                )
                if report.columns:
                    mapped = ", ".join(f"{k}={v}" for k, v in sorted(report.columns.items()))
                    print(f"columns    : {mapped}")
                print(
                    f"loaded     : {report.accepted} label(s) — "
                    f"{report.inserted} new, {report.updated} updated"
                )
                if report.duplicates:
                    print(f"duplicates : {report.duplicates} repeated address(es) in the file")
                if report.rejected_count:
                    print(f"rejected   : {report.rejected_count} row(s) could not be read")
                    for rejection in report.rejected:
                        print(f"             line {rejection.line}: {rejection.reason}")
                print()

        if args.lookup:
            found = repository.lookup(args.chain, args.lookup)
            if not found:
                print(f"{args.lookup} is not labelled on {args.chain}")
                return EXIT_OK
            for label in found:
                print(
                    f"{label.address}  {label.name:<24}{label.category:<12}"
                    f"{label.confidence:<6}{label.verification_status:<14}{label.source}"
                )
            return EXIT_OK

        summary = repository.summary()
        if args.format == "json":
            print(json.dumps(summary, indent=2, default=str))
            return EXIT_OK

        if not summary["total"]:
            print("no address labels loaded.")
            print(
                "\nWithout them the materiality gate's labelled-address rule "
                "cannot fire, so\nexchange and bridge flows below the value "
                "floor are invisible, and the\nexchange_flow skill has nothing "
                "to answer from.\n\n  a01 labels --db <db> --load data/labels"
            )
            return EXIT_OK

        print(f"{summary['total']} label(s) loaded")
        print()
        print(f"{'CATEGORY':<16}ADDRESSES")
        for category, count in summary["categories"].items():
            print(f"{category:<16}{count}")

        print(f"\n{'SOURCE':<34}{'ROWS':<8}{'ENTITIES':<10}{'CONF':<7}STATUS")
        for entry in summary["sources"]:
            print(
                f"{entry['source'][:33]:<34}{entry['rows']:<8}{entry['entities']:<10}"
                f"{entry['confidence']:<7}{entry['verification_status']}"
            )

        top = repository.entities(chain=args.chain, limit=10)
        if top:
            print(f"\nlargest operators on {args.chain}:")
            for entry in top:
                print(f"  {entry['entity']:<28}{entry['addresses']} address(es)")

        print(
            "\nEvery label states its source. A label is an external assertion, "
            "never\ninferred from behaviour, and an unverified one bounds any "
            "conclusion drawn\nfrom it."
        )
        return EXIT_OK


def cmd_flows(args: argparse.Namespace) -> int:
    """
    Exchange deposits and withdrawals over the stored window.

    Computed through the same code the ``exchange_flow`` skill uses, so the
    number printed here and the number an investigation reports cannot drift.
    ``--rollup`` persists the hours into the warm tier, which is what turns a
    single reading into the baseline an anomaly could later be measured
    against.
    """
    from database import Database, SqliteAnalyticsRepository
    from skills.base import SkillRequest
    from skills.exchange_flow import ExchangeFlowSkill

    with Database(args.db) as database:
        analytics = SqliteAnalyticsRepository(database)
        request = SkillRequest(
            chain=args.chain,
            from_height=args.from_height,
            to_height=args.to_height,
        )
        result = ExchangeFlowSkill().run(request, analytics)

        if args.format == "json":
            print(json.dumps(result.as_dict(), indent=2, default=str))
            return EXIT_OK if result.determined else EXIT_DEGRADED

        print(f"chain      : {args.chain}")
        if not result.determined:
            print(f"undetermined: {result.reason}")
            if result.coverage.limitation:
                print(f"coverage   : {result.coverage.limitation}")
            return EXIT_DEGRADED

        data = result.data
        totals = data["totals"]
        symbol, decimals = _native_unit(args.chain)

        def units(raw: int) -> str:
            """Whole units for reading. The JSON form keeps the exact integer."""
            from decimal import Decimal

            return f"{Decimal(raw).scaleb(-decimals):+,.4f}"

        print(f"labels     : {data['labelled_addresses']} address(es), "
              f"{data['labelled_entities']} operator(s) from {data['label_source']}")
        print(f"scanned    : {data['transfers_scanned']} transfer(s), "
              f"{data['attributed']} attributed across {data['hours']} hour(s)")
        print()
        print(
            f"{'OPERATOR':<24}{'IN':>7}{'OUT':>7}{'INTERNAL':>10}"
            f"{'NET ' + symbol:>22}"
        )
        print("-" * 70)
        for entity, entry in data["entities"].items():
            print(
                f"{entity[:23]:<24}{entry['inflow_count']:>7}"
                f"{entry['outflow_count']:>7}{entry['internal_count']:>10}"
                f"{units(entry['net_value']):>22}"
            )
        print()
        # Counts and value are printed on separate lines because they can point
        # opposite ways -- many small withdrawals against one large deposit is a
        # net inflow with an outflow-shaped count -- and a single line reading
        # "1174 out ... inflow" invites the reader to think one of them is wrong.
        print(
            f"total      : {totals['inflow_count']} in / {totals['outflow_count']} out "
            f"/ {totals['internal_count']} internal (transfers)"
        )
        print(
            f"net        : {units(int(totals['net_value']))} {symbol} — "
            f"{totals['direction']} by value; internal movement is in neither side"
        )

        if args.rollup:
            from tiers import ExchangeFlowRepository

            hours = [
                _flow_hour_from(entry) for entry in result.subject.get("exchange_flow_hours", [])
            ]
            inserted, replaced = ExchangeFlowRepository(database).save_many(hours)
            print(f"rolled up  : {inserted} new hour(s), {replaced} replaced (warm tier)")

        # Printed last and never omitted. Every figure above is bounded by
        # these, and a flow number read without them is the confident kind of
        # wrong this system exists to avoid.
        print("\nbounds:")
        for bound in data["bounds"]:
            print(f"  - {bound}")
        if data["coverage_limitation"]:
            print(f"  - {data['coverage_limitation']}")
        print(
            "\nDirection is what moved, not why. Deposits are consistent with an "
            "intent to\nsell and with collateral, market making and custody "
            "moves; A01 does not\nclaim to tell them apart."
        )
        return EXIT_OK


def _native_unit(chain: str) -> tuple[str, int]:
    """
    The chain's own currency symbol and decimals, for display only.

    Read from the chain catalog rather than assumed to be 18. An unknown chain
    falls back to raw units and says so, which is better than rendering a
    lamport count as if it were ether.
    """
    try:
        from config.rpc.chains import get_chain

        currency = get_chain(chain).native_currency
        return currency.symbol, currency.decimals
    except Exception:  # noqa: BLE001 - display must not fail on an odd chain name
        return "(raw)", 0


def _flow_hour_from(entry: dict[str, Any]):
    """Rebuild a warm-tier row from the skill's rendered hour."""
    from datetime import datetime

    from schemas.amount import Amount
    from tiers import ExchangeFlowHour

    floor = entry.get("capture_floor")
    return ExchangeFlowHour(
        chain=entry["chain"],
        hour_start=datetime.fromisoformat(entry["hour_start"]),
        entity=entry["entity"],
        inflow_count=entry["inflow_count"],
        inflow_value=Amount(int(entry["inflow_value"])),
        outflow_count=entry["outflow_count"],
        outflow_value=Amount(int(entry["outflow_value"])),
        internal_count=entry["internal_count"],
        internal_value=Amount(int(entry["internal_value"])),
        addresses=entry["addresses"],
        blocks=entry["blocks"],
        complete_blocks=entry["complete_blocks"],
        capture_floor=Amount(int(floor)) if floor else None,
        first_number=entry["range"][0],
        last_number=entry["range"][1],
        label_source=entry["label_source"],
    )


def cmd_approvals(args: argparse.Namespace) -> int:
    """
    Standing spending grants for one address, and what cannot be said of them.

    Reads the stored approval log for the owner, replays it into the grants
    still live, and reports their breadth. It never says a spender is
    dangerous: that needs a label source or contract bytecode, and A01 has
    neither -- so the report carries its own limits rather than implying an
    alarm from a list of unlimited grants.
    """
    from pathlib import Path

    from blockchain.security.approval_risk import exposure_for_owner
    from database import Database, SqliteApprovalRepository
    from schemas.address import Address, AddressError

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return EXIT_USAGE

    try:
        owner = Address.parse(args.address, args.chain)
    except AddressError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    with Database(db_path) as database:
        grants = SqliteApprovalRepository(database).approvals_for_owner(owner)
        # as_of is left unset: a log carries no timestamp, so staleness is not
        # measurable from capture alone, and passing "now" would age every
        # grant from zero and print a staleness that was never observed.
        report = exposure_for_owner(grants, owner=owner.value, chain=args.chain)

        if args.format == "json":
            print(json.dumps(report.as_dict(), indent=2, default=str))
            return EXIT_OK

        print(f"owner      : {owner.value}")
        print(f"chain      : {args.chain}")
        print(
            f"grants     : {report.total} live, {len(report.unlimited)} unlimited, "
            f"{len(report.collection_wide)} collection-wide"
        )
        print(
            f"spread     : {len(report.spenders)} spender(s) across "
            f"{len(report.tokens)} token(s)"
        )
        print(
            f"replayed   : {report.events_replayed} event(s), "
            f"{report.revoked} revoked"
        )

        if report.live:
            print()
            print(f"{'KIND':<24}{'TOKEN':<14}{'SPENDER':<14}{'BREADTH':>18}")
            print("-" * 70)
            for grant in report.live:
                if grant.unlimited:
                    breadth = "unlimited"
                elif grant.allowance is not None:
                    breadth = str(grant.allowance)
                else:
                    breadth = f"token #{grant.token_id}"
                print(
                    f"{str(grant.kind):<24}{grant.token[:12]:<14}"
                    f"{grant.spender[:12]:<14}{breadth[:18]:>18}"
                )

        # Printed last and never omitted. A screen listing unlimited grants
        # without these reads as an accusation the data cannot support.
        print("\nnot determined here:")
        for note in report.unanswerable:
            print(f"  - {note}")
        return EXIT_OK


def cmd_ingest(args: argparse.Namespace) -> int:
    """
    Capture blocks from a chain into the system of record.

    The one command that makes A01 more than a query tool over an empty
    database. It is bounded on purpose -- ``--blocks`` caps the work, because an
    unbounded catch-up on a chain millions of blocks behind is
    indistinguishable from a hang, and an operator cannot report progress on it
    or stop it cleanly.

    Progress is checkpointed to disk, so interrupting this and running it again
    resumes rather than restarting. That is what makes it safe to schedule.
    """
    from database import (
        Database,
        DrainReport,
        RecordWriter,
        SqliteBlockRepository,
        SqliteTokenRepository,
    )
    from blockchain.rpc import ChainDispatcher
    from ingestion import Backfill, BlockPoller, FileCheckpointStore, RecordQueue
    from pipeline import CallBudget
    from sensors import SensorRegistry
    from telemetry import REGISTRY

    # The database opens before the transport now, because the call ledger
    # lives in it and the dispatcher has to be handed its sink at construction.
    # A sink installed after the first read is a sink that missed a read, and
    # the first read of a run is the head fetch -- the call most likely to be
    # the one that runs a free tier out.
    with Database(args.db) as database:
        budget = CallBudget(database)
        dispatcher = ChainDispatcher(on_spend=budget.recorder())

        try:
            sensor = SensorRegistry(dispatcher=dispatcher).get(args.chain)
        except Exception as exc:  # noqa: BLE001
            print(f"error: no sensor for {args.chain!r}: {exc}", file=sys.stderr)
            return EXIT_USAGE

        capability = sensor.capability()
        if not capability.reachable:
            print(
                f"error: {args.chain} is unreachable: {capability.blocked_by}",
                file=sys.stderr,
            )
            return EXIT_DEGRADED

        queue: RecordQueue = RecordQueue(capacity=max(args.blocks * 2, 32))
        checkpoints = FileCheckpointStore(
            args.checkpoints or f"{args.db}.checkpoints.json"
        )

        wants_tokens = args.tokens and not args.headers_only
        if args.tokens and args.headers_only:
            print(
                "error: --tokens needs transaction bodies; drop --headers-only",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if wants_tokens and not capability.logs:
            print(
                f"error: {args.chain} has no log-capable endpoint right now",
                file=sys.stderr,
            )
            return EXIT_DEGRADED

        print(f"chain      : {args.chain} ({capability.endpoints} endpoint(s))")

        tokens = SqliteTokenRepository(database) if wants_tokens else None
        blocks_repo = SqliteBlockRepository(database)
        writer = RecordWriter(blocks_repo, tokens=tokens)

        selective = None
        if args.selective:
            from pipeline import MaterialityGate, SelectiveWriter, floor_from
            from schemas.amount import Amount
            from tiers import BlockAggregateRepository, LabelRepository

            # The floor comes from the chain's own recent distribution wherever
            # there is one. A fixed currency threshold is noise on one chain and
            # unreachable on another, and stale after any large price move.
            population = [
                int(row["value"])
                for row in database.connection.execute(
                    "SELECT value FROM transactions WHERE chain = ? LIMIT 20000",
                    (args.chain,),
                )
            ]
            cold_start = Amount(args.floor if args.floor is not None else 10**18)
            floor = floor_from(population, cold_start=cold_start)

            # Loaded once per run and held as a set. The gate asks "is this
            # address labelled" of every transaction of every block, so a query
            # here would sit between each transaction and its verdict.
            #
            # Passed as None when empty rather than as an empty set: a gate
            # holding one would report its labelled-address rule as available
            # while it could never fire, which is precisely the reassuring lie
            # `MaterialityGate.limitation` exists to prevent.
            labels = LabelRepository(database).label_set(args.chain)
            gate = MaterialityGate(
                floor=floor,
                is_labelled=labels.is_labelled if labels else None,
            )
            selective = SelectiveWriter(
                blocks_repo,
                BlockAggregateRepository(database),
                gate=gate,
                writer=writer,
            )
            derived = "derived" if len(population) >= 200 else "cold start"
            print(f"mode       : selective, floor {floor.raw} ({derived})")
            if labels:
                print(
                    f"labels     : {len(labels)} address(es), "
                    f"{len(labels.entities())} entity(ies) — a transfer touching "
                    "one is kept below the floor"
                )
            if gate.limitation():
                print(f"             note: {gate.limitation()}")

        if args.backfill:
            # The head is only needed to place a range the caller did not give.
            # Reading it unconditionally made an explicit --start depend on a
            # call it never uses: once the endpoints stopped answering head
            # reads, a backfill of a fixed historical range -- every height of
            # which was already settled and fetchable -- refused to run at all.
            if args.start is not None:
                start = args.start
            else:
                head = sensor.head()
                if not head.ok:
                    print(f"error: cannot read head: {head.reason}", file=sys.stderr)
                    return EXIT_DEGRADED
                start = head.unwrap().height - args.blocks + 1
            job = Backfill(
                sensor,
                start=start,
                end=start + args.blocks - 1,
                queue=queue,
                include_transactions=not args.headers_only,
                include_logs=wants_tokens,
            )
            print(
                f"mode       : backfill {start}-{start + args.blocks - 1}"
                + ("  +tokens" if wants_tokens else "")
            )
            progress = job.run(batch=args.blocks)
            if selective is not None:
                # Both capture paths honour --selective. Letting backfill fall
                # through to the full writer would store every transaction of a
                # historical range while the run reported itself as selective --
                # and a historical range is exactly where the volume is.
                drained = 0
                while True:
                    batch = queue.drain(limit=args.blocks * 2)
                    if not batch:
                        break
                    for captured in batch:
                        selective.write(captured)
                    drained += len(batch)
                report = DrainReport(drained=drained, written=selective.stats.blocks,
                                     duplicates=0, rejections=())
            else:
                report = writer.drain(queue, batch=args.blocks * 2)
            print(f"fetched    : {progress.captured} block(s)")
            if progress.missing:
                # A retry list, not an error log: a height lands there when the
                # chain could not be read, which is worth another attempt.
                print(f"missing    : {len(progress.missing)} height(s), retryable")
            log_counts = (
                progress.logs_captured,
                progress.logs_undetermined,
                progress.logs_dropped,
            )
        else:
            start = args.start
            if start is None and checkpoints.load(args.chain) is None:
                # Cold start. Left to itself the poller begins at the settled
                # head, so the first run finds one block and reports "caught
                # up" -- which is correct for a follower and useless as a first
                # command. Reaching back by the requested count makes
                # `--blocks 5` mean five blocks, which is what it says.
                head = sensor.head()
                if not head.ok:
                    print(f"error: cannot read head: {head.reason}", file=sys.stderr)
                    return EXIT_DEGRADED
                depth = args.confirmations
                if depth is None:
                    from config.rpc.chains import get_chain

                    depth = get_chain(args.chain).confirmations
                start = max(head.unwrap().height - depth - args.blocks + 1, 0)
                print(f"cold start : no checkpoint; reaching back to {start}")

            poller = BlockPoller(
                sensor,
                queue=queue,
                checkpoints=checkpoints,
                start_height=start,
                include_transactions=not args.headers_only,
                include_logs=wants_tokens,
                confirmations=args.confirmations,
            )
            print(
                f"mode       : follow head at {poller.confirmations} confirmations"
                + ("  +tokens" if wants_tokens else "")
            )
            results = poller.run(max_steps=args.blocks)
            if selective is not None:
                selective.consume(results, queue)
                report = DrainReport(drained=0, written=selective.stats.blocks,
                                     duplicates=0, rejections=())
            else:
                report = writer.consume(results, queue)

            statuses: dict[str, int] = {}
            for result in results:
                statuses[result.status.value] = statuses.get(result.status.value, 0) + 1
            print(f"poll       : {', '.join(f'{k}={v}' for k, v in sorted(statuses.items())) or 'nothing to do'}")
            log_counts = (
                poller.stats.logs_captured,
                poller.stats.logs_undetermined,
                poller.stats.logs_dropped,
            )

        if wants_tokens:
            # Both capture paths refuse to abandon a good block over a refused
            # log read -- logs are the first thing a free provider rate-limits,
            # and stalling ingestion on the least reliable call in the pipeline
            # would be the worse trade.
            #
            # What was missing is this line. The blocks are stored and marked
            # incomplete, so nothing downstream reads them as transfer-free,
            # but an operator watching a run had no way to see the shortfall
            # at all: the output said "0 transfers" and looked like a quiet
            # chain rather than a provider that never answered.
            captured, undetermined, dropped = log_counts
            print(
                f"logs       : {captured} captured, "
                f"{undetermined} undetermined, {dropped} dropped"
            )
            if undetermined or dropped:
                print(
                    f"             WARNING: transfers were never fetched for "
                    f"{undetermined + dropped} block(s). Those blocks are stored "
                    f"incomplete; an absence over them is not evidence."
                )

        if selective is not None:
            s = selective.stats
            print(f"stored     : {s.blocks} block(s), {s.transactions_kept} "
                  f"material transaction(s)")
            print(f"filtered   : {s.transactions_seen} seen, {s.dropped} dropped "
                  f"({100 * s.kept_share:.2f}% kept)")
        else:
            print(f"stored     : {report.written} block(s), "
                  f"{writer.stats.transactions_written} transaction(s)")
        if wants_tokens:
            print(f"tokens     : {writer.stats.token_transfers_written} transfer(s), "
                  f"{writer.stats.nft_transfers_written} NFT transfer(s)")
            if writer.stats.orphaned_token_records:
                print(f"orphaned   : {writer.stats.orphaned_token_records} token record(s) "
                      "referenced a block that is not stored")
        if report.duplicates:
            print(f"duplicates : {report.duplicates} (already stored; a replay is free)")
        if writer.stats.withdrawn_blocks:
            print(f"withdrawn  : {writer.stats.withdrawn_blocks} block(s) abandoned by a reorg")

        if report.rejections:
            # Surfaced with the field that failed, because a rising rejection
            # count is the only thing distinguishing a bad provider from a
            # quiet chain.
            print(f"rejected   : {len(report.rejections)} record(s)")
            for rejection in report.rejections[:3]:
                fields = ", ".join(i.field for i in rejection.issues) or rejection.reason
                print(f"             {rejection.record_id[:16]}… {fields}")

        health = database.health()
        print(f"database   : {health['rows']['blocks']} block(s), "
              f"{health['rows']['transactions']} transaction(s) total")

        # Cumulative, not per-run: the ledger's whole purpose is to survive the
        # process, and a free tier meters the day, not the invocation. No
        # ceiling is configured for any provider, so these are counts without a
        # verdict -- which is the honest state until a number comes from the
        # provider rather than from a guess.
        for provider, entry in sorted(budget.snapshot().items()):
            day, month = entry["day"], entry["month"]
            allowed = (
                f"{day['ceiling']} allowed/day"
                if day["ceiling"] is not None
                else "no ceiling known"
            )
            pressure = "" if entry["pressure"] == "unknown" else f", {entry['pressure']}"
            print(f"budget     : {provider} {day['spent']} call(s) today, "
                  f"{month['spent']} this month ({allowed}{pressure})")

        writer_registry = REGISTRY
        writer_registry.observe_writer(writer, chain=args.chain)

    if args.format == "json":
        print(json.dumps(report.as_dict(), indent=2, default=str))

    return EXIT_DEGRADED if report.rejections else EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    """
    Run the verification pipeline: label corroboration, detector backtests,
    and promotion verdicts.

    This is the command that closes two loops at once:

    1. Labels: cross-reference sources, upgrade UNVERIFIED to CORROBORATED
       where two independent sources agree.
    2. Detectors: run backtests against labelled evaluation cases, report
       whether each detector has earned promotion to VALIDATED.

    ``--apply`` promotes detectors that pass all gates by rebuilding the
    maturity gate with a promoted registry for the current process. The
    static REGISTRY in ``decision/maturity.py`` records the standing that
    persists across runs.
    """
    mode = args.mode

    if mode == "labels":
        from database import Database
        from pipeline.verification import LabelVerifier

        with Database(args.db) as database:
            verifier = LabelVerifier(database)

            if args.format == "json":
                import json as _json

                report = verifier.scan(args.chain)
                print(_json.dumps(report.as_dict(), indent=2))
                return EXIT_OK

            status = verifier.status(args.chain)
            print(f"chain        : {args.chain}")
            print(f"total labels : {status['total']}")
            print(f"unverified   : {status['unverified']}")
            print(f"corroborated : {status['corroborated']}")
            print(f"verified     : {status['verified']}")
            print(f"coverage     : {status['coverage']:.1%}")
            print()

            report = verifier.scan(args.chain)
            if report.upgraded:
                print(f"upgraded {report.upgraded} address(es) to corroborated:")
                for change in report.changes[:20]:
                    print(
                        f"  {change.address[:16]}… {change.entity:<20} "
                        f"{change.old_status} -> {change.new_status} "
                        f"({change.old_confidence:.2f} -> {change.new_confidence:.2f})"
                    )
                if len(report.changes) > 20:
                    print(f"  ... and {len(report.changes) - 20} more")
            else:
                print("no new corroborations found.")
                if status["total"] and not status["corroborated"] and not status["verified"]:
                    print(
                        "\nEvery label comes from a single source. Load a second "
                        "independent list\nfor the same addresses to enable "
                        "corroboration."
                    )
            print(
                "\nLabel verification is provenance, not measurement. A corroborated "
                "label\nis one where two independent sources agree; it still may be wrong, "
                "but\nthe confidence it carries (0.75) reflects the stronger evidence base."
            )
        return EXIT_OK

    if mode == "detectors":
        from evaluation.promotion import evaluate_all

        if args.format == "json":
            import json as _json

            report = evaluate_all()
            print(_json.dumps(report.as_dict(), indent=2, default=str))
            return EXIT_OK

        print("running backtests against labelled evaluation cases...\n")
        report = evaluate_all()

        print(f"{'DETECTOR':<18}{'SAMPLES':<10}{'PRECISION':<12}{'RECALL':<10}"
              f"{'FPR':<10}{'CAL ERR':<10}VERDICT")
        print("-" * 88)
        for v in report.verdicts:
            m = v.backtest.metrics
            c = v.backtest.calibration
            verdict = "PROMOTABLE" if v.promotable else "BLOCKED"
            print(
                f"{v.detector:<18}{v.backtest.sample_size:<10}"
                f"{_fmt(m.precision):<12}{_fmt(m.recall):<10}"
                f"{_fmt(m.false_positive_rate):<10}"
                f"{c.expected_calibration_error:<10.4f}{verdict}"
            )
            if not v.promotable:
                for blocker in v.blockers:
                    print(f"  blocked: {blocker}")

        print(f"\n{report.promoted_count}/{len(report.verdicts)} detector(s) promotable.")

        if report.all_promoted:
            print(
                "\nAll detectors pass promotion gates. Their confidence ceiling "
                "lifts from\n0.60 to 1.0, and they may raise alerts. The promoted "
                "registry is active\nfor any MaturityGate constructed with it."
            )
        elif report.blocked_count:
            print(
                f"\n{report.blocked_count} detector(s) blocked. See blockers above."
            )

        return EXIT_OK

    print(f"unknown verify mode: {mode}", file=sys.stderr)
    return EXIT_USAGE


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "-"


def cmd_backup(args: argparse.Namespace) -> int:
    """Take a verified snapshot of the chain system of record."""
    from telemetry import backup, snapshot_name

    destination = Path(args.out) if args.out else Path(args.db).parent / snapshot_name()
    try:
        result = backup(args.db, destination)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.format == "json":
        print(json.dumps(result.as_dict(), indent=2, default=str))
    else:
        status = "verified" if result.verified else f"UNVERIFIED ({result.integrity})"
        print(f"{result.path}")
        print(f"  {result.blocks} block(s), {result.transactions} transaction(s)")
        print(f"  {result.size_bytes / 1024:.1f} KiB, {status}")

    return EXIT_OK if result.verified else EXIT_DEGRADED


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore a verified backup over the live database."""
    from telemetry import restore

    try:
        target = restore(args.backup, args.db, overwrite=args.overwrite)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(f"restored to {target}")
    print("  any previous database was moved aside, not deleted")
    return EXIT_OK


def cmd_metrics(args: argparse.Namespace) -> int:
    """Print current metrics in Prometheus text format."""
    from interfaces import IntelligenceService
    from telemetry import REGISTRY

    IntelligenceService(database_path=args.db).observe(REGISTRY)
    print(REGISTRY.render() if args.format != "json" else json.dumps(REGISTRY.as_dict(), indent=2))
    return EXIT_OK


def cmd_providers(args: argparse.Namespace) -> int:
    """
    Report which providers are usable, and what a missing key would unlock.

    The answer to "I added my API key, did it work?" -- a question that
    previously had no way to be answered short of reading the source.
    """
    from blockchain.rpc.providers import default_catalog
    from blockchain.rpc.providers.keys import configured_providers, get_key_spec
    from config.dotenv import describe, load

    env = load()
    catalog = default_catalog()
    active = set(configured_providers())

    endpoints = [e for e in catalog.endpoints if str(e.chain) == args.chain]
    usable = catalog.available(args.chain)
    usable_providers = {e.provider for e in usable}

    if args.format == "json":
        print(json.dumps({
            "chain": args.chain,
            "dotenv": env.as_dict(),
            "keyed_providers_active": sorted(active),
            "endpoints": len(endpoints),
            "usable_now": len(usable),
        }, indent=2))
        return EXIT_OK

    print(f"env        : {describe(env)}")
    print(f"chain      : {args.chain}")
    print(f"endpoints  : {len(endpoints)} configured, {len(usable)} usable right now")
    print()
    print(f"{'PROVIDER':<16}{'ACCESS':<14}{'STATUS':<12}ENV VAR")
    print("-" * 74)

    seen: set[str] = set()
    for endpoint in sorted(endpoints, key=lambda e: (e.access.value, e.provider)):
        if endpoint.provider in seen:
            continue
        seen.add(endpoint.provider)

        if endpoint.access.value == "open":
            status, variable = "usable", "-"
        elif endpoint.provider in active:
            status, variable = "keyed", _env_var_for(endpoint.provider)
        else:
            status, variable = "dormant", _env_var_for(endpoint.provider)

        print(f"{endpoint.provider:<16}{endpoint.access.value:<14}{status:<12}{variable}")

    dormant = [p for p in seen if p not in active and p not in usable_providers]
    if dormant:
        print()
        print(
            f"{len(dormant)} provider(s) dormant. Export the variable above, or put it\n"
            "in a .env beside the agent — keys are read from the process\n"
            "environment, so the file is loaded into it at startup."
        )
    return EXIT_OK


def _env_var_for(provider: str) -> str:
    """The variable a provider's key comes from, or a dash."""
    from blockchain.rpc.providers.keys import get_key_spec

    try:
        return " | ".join(get_key_spec(provider).env_vars)
    except (KeyError, LookupError, ValueError):
        return "-"


def cmd_visualize(args: argparse.Namespace) -> int:
    """
    Render stored chain data as one self-contained HTML page.

    Reads the database and writes a file; opens no socket and calls no chain.
    The page embeds no live request, so it can be saved and opened offline
    without the figures drifting from what the database held when it was made.
    """
    from database import (
        Database,
        SqliteAnalyticsRepository,
        SqliteBlockRepository,
        SqliteTokenRepository,
    )
    from interfaces.dashboard import collect, render

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return EXIT_USAGE

    out = Path(args.out) if args.out else db_path.with_suffix(".html")

    with Database(db_path) as database:
        snapshot = collect(
            SqliteBlockRepository(database),
            SqliteTokenRepository(database),
            SqliteAnalyticsRepository(database),
            database=str(db_path),
        )

    out.write_text(render(snapshot), encoding="utf-8")

    if snapshot.empty:
        print(
            f"wrote {out}\n"
            "note: no chain data stored yet — ingest first, then re-render",
            file=sys.stderr,
        )
        return EXIT_OK

    print(f"dashboard : {out}")
    print(
        f"  {len(snapshot.chains)} chain(s), {snapshot.total_blocks:,} block(s), "
        f"{snapshot.total_token_transfers:,} token transfer(s)"
    )
    if args.open:
        import webbrowser

        webbrowser.open(out.resolve().as_uri())
        print("  opened in your browser")
    else:
        print(f"  open it: {out.resolve().as_uri()}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the REST API until interrupted."""
    from interfaces import IntelligenceService, serve

    service = IntelligenceService(database_path=args.db)
    print(f"A01 REST API on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    print(f"  routes: /health /detectors /skills /coverage /investigate")
    if not service.has_storage:
        print("  note: no database configured; /coverage and composition are unavailable")
    serve(service, host=args.host, port=args.port)
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    """Self-check the agent's wiring and report anything broken."""
    checks: list[tuple[str, bool, str]] = []

    try:
        from config.rpc.chains import supported_chain_names

        names = supported_chain_names()
        checks.append(("chain registry", bool(names), f"{len(names)} chains"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("chain registry", False, str(exc)))

    try:
        from config.settings import DatabaseSettings

        DatabaseSettings()
        checks.append(("settings load", True, "database settings valid"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("settings load", False, str(exc)))

    try:
        from intelligence.core.engine import IntelligenceEngine

        engine = IntelligenceEngine()
        count = engine.pipeline.stage_count
        checks.append(("pipeline wiring", count > 0, f"{count} stages registered"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("pipeline wiring", False, str(exc)))

    try:
        from sensors import SensorRegistry

        registry = SensorRegistry()
        implemented = registry.implemented_chains()
        readable = registry.readable_chains()
        # Implemented-but-unreadable is a configuration gap, not a missing
        # feature, so the two counts are reported separately -- collapsing them
        # would send an operator to the wrong fix.
        checks.append(
            (
                "sensors",
                bool(readable),
                f"{len(readable)}/{len(implemented)} chains readable",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("sensors", False, str(exc)))

    try:
        from ingestion import BlockPoller, InMemoryCheckpointStore
        from sensors import SensorRegistry

        poller = BlockPoller(
            SensorRegistry().get("ethereum"),
            checkpoints=InMemoryCheckpointStore(),
        )
        # Construction only. Stepping the poller would issue live RPC calls,
        # and a doctor run that depends on a provider being up reports the
        # provider's health as though it were the agent's.
        checks.append(
            (
                "ingestion wiring",
                poller.confirmations > 0,
                f"reorg-safe at {poller.confirmations} confirmations",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("ingestion wiring", False, str(exc)))

    try:
        from database import CURRENT_VERSION, Database, RecordWriter, SqliteBlockRepository
        from sensors.envelope import Provenance, RawRecord, RecordKind

        # An in-memory database, so doctor exercises the real schema, the real
        # normalizer and the real repository without touching the operator's
        # data. Reporting on a mock would report on the mock.
        with Database() as probe:
            writer = RecordWriter(SqliteBlockRepository(probe))
            written = writer.write(
                RawRecord(
                    chain="ethereum",
                    kind=RecordKind.BLOCK,
                    payload={
                        "number": "0x1",
                        "hash": "0x" + "d0" * 16,
                        "parentHash": "0x" + "cf" * 16,
                        "timestamp": "0x6577a000",
                        "transactions": [],
                    },
                    height=1,
                    provenance=Provenance("doctor", "ethereum", "probe", "ok"),
                )
            )
            ok = written.storable and probe.schema_version() == CURRENT_VERSION
            detail = f"schema v{probe.schema_version()}, write path clean"
        checks.append(("storage", ok, detail))
    except Exception as exc:  # noqa: BLE001
        checks.append(("storage", False, str(exc)))

    try:
        from database import Database, SqliteAnalyticsRepository
        from intelligence.engines import SubjectComposer
        from skills import default_registry

        registry = default_registry()
        # Compose against an empty database. Every skill should decline rather
        # than answer, which is the behaviour that matters: a skill that
        # invents an answer from no history is the failure mode this layer
        # exists to prevent, and it is only visible with nothing stored.
        with Database() as probe:
            composition = SubjectComposer(registry).compose(
                SqliteAnalyticsRepository(probe), chain="ethereum"
            )
        honest = (
            len(composition.declined) == len(registry)
            and not composition.failed
            and not composition.supports_absence
        )
        checks.append(
            (
                "skills",
                honest,
                f"{len(registry)} implemented, decline cleanly with no history",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("skills", False, str(exc)))

    try:
        from decision import MaturityGate

        gate = MaturityGate()
        alerting = gate.alerting_detectors()
        # Asserts the doctrine, not the absence of alerts. If a detector ever
        # is promoted this check must still pass -- what it verifies is that
        # nothing alerts *without* a measured error rate.
        honest = all(
            entry.maturity.label == "validated" or not entry.may_alert
            for entry in gate
        )
        checks.append(
            (
                "decision gate",
                honest,
                f"{len(gate)} detector(s), {len(alerting)} may alert",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("decision gate", False, str(exc)))

    try:
        from interfaces import IntelligenceService, Router

        probe = IntelligenceService()
        routes = Router(probe).paths()
        reachable = all(
            Router(probe).dispatch(path, {}).status in {200, 400, 503}
            for path in routes
        )
        checks.append(
            ("interfaces", reachable, f"{len(routes)} route(s), loopback-bound")
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("interfaces", False, str(exc)))

    try:
        from blockchain.rpc.providers.keys import configured_providers
        from config.dotenv import describe, load

        env = load()
        active = configured_providers()
        # Never a failure: running on free endpoints is a supported mode, and
        # the check exists so an operator who *did* place keys can see whether
        # they were picked up rather than wondering why nothing changed.
        checks.append(
            (
                "credentials",
                True,
                f"{len(active)} keyed provider(s) active; {describe(env)}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("credentials", False, str(exc)))

    try:
        from telemetry import REGISTRY, snapshot_name

        REGISTRY.gauge("doctor_probe", 1.0)
        rendered = REGISTRY.render()
        checks.append(
            (
                "telemetry",
                "a01_doctor_probe" in rendered and bool(snapshot_name()),
                f"{len(REGISTRY)} metric(s), backup path available",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("telemetry", False, str(exc)))

    try:
        import dataclasses

        from config.security.secrets import SecretValue

        secret = SecretValue(name="probe", _value="sentinel", source="test")
        leaked = "sentinel" in repr(secret) or "sentinel" in str(secret)
        try:
            leaked = leaked or "sentinel" in str(dataclasses.asdict(secret))
        except TypeError:
            pass  # serialization correctly refused
        checks.append(("secret redaction", not leaked, "no plaintext escape"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("secret redaction", False, str(exc)))

    try:
        from config.constants import NO_TRADE_EXECUTION
        from interfaces import IntelligenceService, Router

        # The constant states the boundary; the surface check is what makes the
        # statement worth printing. A flag reporting "ok" while a write route
        # existed would be exactly the reassuring lie this check is here to
        # prevent. The source-level scan for signing primitives is heavier and
        # stays in tests/test_security.py.
        forbidden = ("delete", "write", "ingest", "submit", "sign", "execute")
        routes = tuple(Router(IntelligenceService()).paths())
        exposed = [
            path for path in routes
            if any(word in path.lower() for word in forbidden)
        ]
        checks.append(
            (
                "trade execution",
                NO_TRADE_EXECUTION and not exposed,
                (
                    f"disabled; {len(routes)} route(s) read-only"
                    if not exposed
                    else f"WRITE SURFACE EXPOSED: {', '.join(exposed)}"
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(("trade execution", False, str(exc)))

    try:
        from intelligence.core.engine import IntelligenceEngine

        package = IntelligenceEngine().run({"address": "0x0"})
        failures = package.pipeline.metadata.get("failure_count", 0) if package.pipeline else 1
        checks.append(("smoke investigation", failures == 0, f"{failures} stage failures"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("smoke investigation", False, str(exc)))

    if args.format == "json":
        print(
            json.dumps(
                [{"check": c, "ok": ok, "detail": d} for c, ok, d in checks],
                indent=2,
            )
        )
    else:
        print(f"{'CHECK':<24}{'STATUS':<10}DETAIL")
        print("-" * 72)
        for name, ok, detail in checks:
            print(f"{name:<24}{'ok' if ok else 'FAIL':<10}{detail}")

    return EXIT_OK if all(ok for _, ok, _ in checks) else EXIT_DEGRADED


# =============================================================================
# Parser
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    # The label vocabulary is read from the ledger rather than restated here,
    # so `--category` cannot drift from the categories the store accepts.
    from tiers.ledger import CATEGORIES, CONFIDENCE, EVM_SCOPE, UNVERIFIED

    parser = argparse.ArgumentParser(
        prog="a01",
        description=(
            "A01 Blockchain Intelligence Agent. Produces evidence-backed, "
            "confidence-bounded intelligence from blockchain data."
        ),
        epilog=(
            "A01 is read-only: it holds no keys, signs nothing, and never "
            "submits a transaction."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format (default: text)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    investigate = sub.add_parser(
        "investigate", help="run an investigation over a subject"
    )
    investigate.add_argument("--address", help="subject address")
    investigate.add_argument(
        "--subject", help="path to a JSON file describing the subject"
    )
    investigate.add_argument(
        "--db",
        help=(
            "path to a stored-history database; the subject is composed from "
            "it by the skills layer instead of being supplied by hand"
        ),
    )
    investigate.add_argument(
        "--chain",
        default="ethereum",
        help="chain to compose the subject from, with --db (default: ethereum)",
    )
    investigate.set_defaults(func=cmd_investigate)

    detectors = sub.add_parser("detectors", help="list detectors and maturity")
    detectors.set_defaults(func=cmd_detectors)

    skills = sub.add_parser("skills", help="list skills and what bounds them")
    skills.set_defaults(func=cmd_skills)

    known = sub.add_parser(
        "chains", help="list registered chains and what A01 can observe on each"
    )
    known.add_argument(
        "--limits",
        action="store_true",
        help="print every chain's stated limits, not just the summary line",
    )
    known.add_argument(
        "--probe",
        action="store_true",
        help=(
            "re-measure against live endpoints and report where the table "
            "disagrees; costs one round trip per chain"
        ),
    )
    known.set_defaults(func=cmd_chains)

    creds = sub.add_parser(
        "providers", help="show which RPC providers are reachable and keyed"
    )
    creds.add_argument("--chain", default="ethereum", help="chain to report on")
    creds.set_defaults(func=cmd_providers)

    viz = sub.add_parser("visualize", help="render stored data as an HTML dashboard")
    viz.add_argument("--db", required=True, help="database to render")
    viz.add_argument("--out", help="output HTML path (default: <db>.html)")
    viz.add_argument(
        "--open", action="store_true", help="open the page in your browser when done"
    )
    viz.set_defaults(func=cmd_visualize)

    api = sub.add_parser("serve", help="run the read-only REST API")
    api.add_argument("--db", help="path to a stored-history database")
    api.add_argument(
        "--host",
        default=REST_HOST,
        help=(
            f"bind address (default: {REST_HOST}). The API is unauthenticated, "
            "so any other value publishes ingested data to the network"
        ),
    )
    api.add_argument("--port", type=int, default=REST_PORT, help="bind port")
    api.set_defaults(func=cmd_serve)

    grab = sub.add_parser("ingest", help="capture blocks from a chain into storage")
    grab.add_argument("--db", required=True, help="database to write into")
    grab.add_argument("--chain", default="ethereum", help="chain to read (default: ethereum)")
    grab.add_argument(
        "--blocks", type=int, default=10,
        help="maximum blocks this run may capture (default: 10)",
    )
    grab.add_argument(
        "--start", type=int,
        help="height to start at (default: resume from the checkpoint)",
    )
    grab.add_argument(
        "--confirmations", type=int,
        help="stay this far behind the head (default: the chain's configured depth)",
    )
    grab.add_argument(
        "--backfill", action="store_true",
        help="fetch a fixed historical range instead of following the head",
    )
    grab.add_argument(
        "--headers-only", action="store_true",
        help="skip transaction bodies; faster, but blocks are stored incomplete",
    )
    grab.add_argument(
        "--tokens", action="store_true",
        help=(
            "also capture ERC-20 and ERC-721 transfers from event logs. On L2s "
            "this is most of the real activity: native value is often zero"
        ),
    )
    grab.add_argument(
        "--selective", action="store_true",
        help=(
            "keep only transactions that clear a materiality floor, plus a "
            "per-block aggregate covering the rest. Storing every transaction "
            "costs ~0.70 MB per ethereum block; this costs kilobytes"
        ),
    )
    grab.add_argument(
        "--floor", type=int,
        help=(
            "cold-start materiality floor in the chain's smallest unit, used "
            "only until enough history exists to derive a percentile "
            "(default: 1e18, i.e. one ether on an EVM chain)"
        ),
    )
    grab.add_argument("--checkpoints", help="checkpoint file (default: <db>.checkpoints.json)")
    grab.set_defaults(func=cmd_ingest)

    tags = sub.add_parser(
        "labels", help="load address labels, or show what is loaded"
    )
    tags.add_argument("--db", required=True, help="database holding the label ledger")
    tags.add_argument(
        "--load",
        help=(
            "a label file, or a directory of them (CSV, TSV, JSON or plain "
            "text). Re-loading the same file is free and corrects what changed"
        ),
    )
    tags.add_argument("--lookup", help="show every assertion about one address")
    tags.add_argument(
        "--chain",
        default=EVM_SCOPE,
        help=(
            f"chain the labels apply to (default: {EVM_SCOPE}, meaning every "
            "EVM chain — one EVM address is the same account on all of them)"
        ),
    )
    tags.add_argument(
        "--category",
        default="exchange",
        choices=sorted(CATEGORIES),
        help=(
            "what the labelled addresses are, for files that do not say "
            "(default: exchange). Applied to every row, and reported as coming "
            "from here rather than from the file"
        ),
    )
    tags.add_argument(
        "--source",
        help=(
            "where the list came from, e.g. a repository URL (default: "
            "file:<name>, which records only where A01 read it)"
        ),
    )
    tags.add_argument(
        "--status",
        default=UNVERIFIED,
        choices=sorted(CONFIDENCE),
        help=(
            f"how well checked the list is (default: {UNVERIFIED}). This sets "
            "the confidence every label carries"
        ),
    )
    tags.add_argument(
        "--confidence",
        type=float,
        help="override the confidence implied by --status",
    )
    tags.set_defaults(func=cmd_labels)

    flow = sub.add_parser(
        "flows", help="exchange deposits and withdrawals over stored history"
    )
    flow.add_argument("--db", required=True, help="database to read")
    flow.add_argument("--chain", default="ethereum", help="chain to report on")
    flow.add_argument(
        "--from-height", type=int, dest="from_height", help="first height to include"
    )
    flow.add_argument(
        "--to-height", type=int, dest="to_height", help="last height to include"
    )
    flow.add_argument(
        "--rollup",
        action="store_true",
        help=(
            "persist the hourly rows into the warm tier, which is what a "
            "baseline is later measured against"
        ),
    )
    flow.set_defaults(func=cmd_flows)

    grants = sub.add_parser(
        "approvals",
        help="standing spending grants for one address, and their breadth",
    )
    grants.add_argument("--db", required=True, help="database to read")
    grants.add_argument("--address", required=True, help="owner to screen")
    grants.add_argument("--chain", default="ethereum", help="chain to read on")
    grants.set_defaults(func=cmd_approvals)

    verify = sub.add_parser(
        "verify",
        help="run label corroboration and detector promotion checks",
    )
    verify.add_argument(
        "mode",
        choices=("labels", "detectors"),
        help=(
            "what to verify: 'labels' cross-references sources and upgrades "
            "corroborated labels; 'detectors' runs backtests and reports "
            "promotion readiness"
        ),
    )
    verify.add_argument(
        "--db",
        help="database holding the label ledger (required for labels mode)",
    )
    verify.add_argument(
        "--chain",
        default=EVM_SCOPE,
        help=f"chain to verify labels on (default: {EVM_SCOPE})",
    )
    verify.set_defaults(func=cmd_verify)

    take = sub.add_parser("backup", help="take a verified snapshot of the database")
    take.add_argument("--db", required=True, help="database to back up")
    take.add_argument("--out", help="destination path (default: timestamped, alongside --db)")
    take.set_defaults(func=cmd_backup)

    put = sub.add_parser("restore", help="restore a verified backup")
    put.add_argument("--backup", required=True, help="backup to restore from")
    put.add_argument("--db", required=True, help="database to restore into")
    put.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing database (it is moved aside, never deleted)",
    )
    put.set_defaults(func=cmd_restore)

    metrics = sub.add_parser("metrics", help="print metrics in Prometheus format")
    metrics.add_argument("--db", help="database to report storage metrics for")
    metrics.set_defaults(func=cmd_metrics)

    doctor = sub.add_parser("doctor", help="self-check the agent's wiring")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point. Returns a process exit code.

    A ``.env`` is loaded before anything else runs. Provider credentials are
    read from ``os.environ`` at call time, and nothing else puts a file's
    contents there -- so without this, a correctly written key file activates
    no provider and A01 quietly runs on free endpoints instead.
    """
    from config.dotenv import load

    load()

    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
