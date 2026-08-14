"""
CIE-OS
A02 News Intelligence Agent

Module:
    cli.main

Purpose:
    Command-line entry point. Grows with each phase.

Usage:
    python -m agents.A02_News_Intelligence.cli doctor
    python -m agents.A02_News_Intelligence.cli scan
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def doctor() -> int:
    """Validate the A02 foundation: paths, settings, sources registry, storage."""

    from agents.A02_News_Intelligence.config import paths, sources
    from agents.A02_News_Intelligence.config.environment import get_environment
    from agents.A02_News_Intelligence.config.settings import get_settings
    from agents.A02_News_Intelligence.core.storage import Storage

    settings = get_settings()
    print(f"[A02] {settings.agent.name} v{settings.agent.version}")
    print(f"[A02] environment: {get_environment().value}")
    print(f"[A02] agent root:  {paths.AGENT_ROOT}")
    print(f"[A02] database:    {paths.DATABASE_FILE}")
    print(f"[A02] sources:     {len(sources.SOURCES)} registered")

    paths.ensure_data_directories()
    db_path = str(paths.DATABASE_FILE)
    asyncio.run(Storage(db_path).init())

    checks = [
        ("agent root exists", paths.AGENT_ROOT.exists()),
        ("data dirs created", paths.RAW_DATA_DIR.exists() and paths.PROCESSED_DATA_DIR.exists()),
        ("settings load", settings.agent.id == "A02"),
        ("database schema ok", paths.DATABASE_FILE.exists()),
        ("keyless sources present", len(sources.sources_by_kind("news")) >= 5),
    ]
    failed = False
    for label, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")
        failed = failed or not ok

    if failed:
        print("[A02] doctor: FAILED")
        return 1
    print("[A02] doctor: OK")
    return 0


def scan() -> int:
    """Run one ingestion cycle: fetch -> normalize -> dedup -> entities -> store -> narratives."""

    import json

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.config.settings import get_settings
    from agents.A02_News_Intelligence.core.pipeline import ingest
    from agents.A02_News_Intelligence.core.storage import Storage

    paths.ensure_data_directories()
    settings = get_settings()
    report = asyncio.run(ingest(settings))

    print(f"[A02] scan: fetched={report.fetched} stored={report.stored} "
          f"duplicates={report.duplicates} failed={report.failed} narratives={report.narratives}")
    if report.sources:
        print(f"[A02] scan: sources={', '.join(sorted(s for s in report.sources if s))}")
    for error in report.errors:
        print(f"[A02] scan: WARN {error}")

    storage = Storage(paths.DATABASE_FILE)
    total = asyncio.run(storage.count_items())
    entities = asyncio.run(storage.count_entities())
    print(f"[A02] scan: database total={total} items, {entities} entities")

    rows = asyncio.run(storage.load_active_narratives("1970-01-01T00:00:00"))
    verdicts: dict[str, int] = {}
    for row in rows:
        status = row.get("epistemic_status") or "unconfirmed"
        verdicts[status] = verdicts.get(status, 0) + 1
    asyncio.run(
        storage.insert_scan_stat(
            {
                "items_fetched": report.fetched,
                "items_stored": report.stored,
                "items_dup": report.duplicates,
                "narratives": len(rows),
                "verdicts": json.dumps(verdicts),
            }
        )
    )
    print(f"[A02] scan: drift snapshot stored (verdicts={verdicts})")
    return 0


def narratives() -> int:
    """Show active narratives ranked by FOMO score."""

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.core.storage import Storage
    from agents.A02_News_Intelligence.intelligence.narrative import _narrative_from_row

    async def run() -> int:
        storage = Storage(paths.DATABASE_FILE)
        await storage.init()
        rows = await storage.load_active_narratives("1970-01-01T00:00:00")
        narratives = sorted((_narrative_from_row(r) for r in rows), key=lambda n: n.fomo_score, reverse=True)
        print(f"[A02] narratives: {len(narratives)} total")
        for narrative in narratives[:15]:
            stances = " ".join(f"{k}={v}" for k, v in narrative.stance_counts.items() if v)
            conf_pct = round(narrative.confidence * 100)
            print(
                f"  #{narrative.id} fomo={narrative.fomo_score:5.1f} vel={narrative.velocity:4.2f}/h "
                f"src={narrative.source_count} mentions={narrative.mention_count} "
                f"status={narrative.status} [{stances}]"
            )
            print(
                f"      claim: {narrative.claim_text[:90]}\n"
                f"      verdict: {narrative.epistemic_status} conf={conf_pct}% "
                f"coord={narrative.coordination_score:4.1f}"
                f"  evidence: {narrative.evidence}"
            )
        return 0

    return asyncio.run(run())


async def _predict_all(narrative, storage, market, settings) -> list[tuple[str, object]]:
    """Run the full predict pipeline for a narrative's crypto entities."""

    from agents.A02_News_Intelligence.core.symbols import entity_type_for
    from agents.A02_News_Intelligence.intelligence.predict import predict_asset

    history_events = await storage.load_impact_events()
    results: list[tuple[str, object]] = []
    for symbol in narrative.entities:
        etype = entity_type_for(symbol)
        if etype != "crypto":
            print(f"      {symbol}: market data connector for '{etype or 'unknown'}' not live (crypto only, keyless)")
            continue
        await market.fetch_and_store(symbol)
        candles = await market.series_around(symbol, narrative.first_seen)
        if not candles:
            print(f"      {symbol}: no price data")
            continue
        history = [e for e in history_events if e["asset"] == symbol]
        results.append((symbol, predict_asset(symbol, narrative, candles, history)))
    return results


def impact(narrative_id: int) -> int:
    """Predict market impact for a narrative's assets (fetch price, history match)."""

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.config.settings import get_settings
    from agents.A02_News_Intelligence.core.market import MarketData
    from agents.A02_News_Intelligence.core.storage import Storage
    from agents.A02_News_Intelligence.intelligence.narrative import _narrative_from_row

    async def run() -> int:
        settings = get_settings()
        storage = Storage(paths.DATABASE_FILE)
        await storage.init()
        rows = await storage.load_active_narratives("1970-01-01T00:00:00")
        narrative = next((_narrative_from_row(r) for r in rows if r["id"] == narrative_id), None)
        if narrative is None:
            print(f"[A02] impact: narrative #{narrative_id} not found")
            return 1

        market = MarketData(
            storage,
            binance_base_url=settings.market.binance_base_url,
            alpha_vantage_key=settings.market.alpha_vantage_api_key.get_secret_value(),
            timeout=settings.ingestion.request_timeout_seconds,
        )
        print(f"[A02] impact #{narrative_id}: {narrative.claim_text[:90]}")
        print(f"      verdict={narrative.epistemic_status} conf={round(narrative.confidence*100)}% "
              f"fomo={narrative.fomo_score} coord={narrative.coordination_score}")

        predicted = False
        for symbol, prediction in await _predict_all(narrative, storage, market, settings):
            print(
                f"      {symbol} ({prediction.category}): {prediction.direction} {prediction.probability*100:.0f}% "
                f"range={prediction.expected_low_pct}%..{prediction.expected_high_pct}% "
                f"mean={prediction.expected_mean_pct}%"
            )
            print(
                f"          measured(1h/6h/24h)={prediction.measured_returns_pct} "
                f"vol={prediction.volatility_pct}% surge={prediction.volume_surge}x "
                f"severity={prediction.severity}"
            )
            print(
                f"          history: sim={prediction.historical_similarity} "
                f"events={prediction.historical_events_used} risk={prediction.main_risk}"
            )
            horizon = next((h for h in (24, 6, 1) if prediction.measured_returns_pct.get(h) is not None), 24)
            await storage.insert_impact_event(
                {
                    "narrative_id": narrative.id,
                    "asset": symbol,
                    "category": prediction.category,
                    "first_seen": narrative.first_seen.isoformat(),
                    "horizon_hours": horizon,
                    "measured_return": prediction.measured_returns_pct.get(horizon),
                    "fomo_score": narrative.fomo_score,
                    "epistemic_status": narrative.epistemic_status,
                    "confidence": narrative.confidence,
                    "coordination": narrative.coordination_score,
                    "predicted_direction": prediction.direction,
                    "predicted_probability": prediction.probability,
                    "predicted_mean_pct": prediction.expected_mean_pct,
                }
            )
            predicted = True
        if not predicted:
            print("      no predictable assets (no crypto entities or no price data)")
        return 0

    return asyncio.run(run())


def resolve(event_id: int | None = None) -> int:
    """Resolve open predictions against live price; update the learning loop."""

    from datetime import datetime

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.config.settings import get_settings
    from agents.A02_News_Intelligence.core.market import MarketData
    from agents.A02_News_Intelligence.core.storage import Storage

    async def run() -> int:
        settings = get_settings()
        storage = Storage(paths.DATABASE_FILE)
        await storage.init()
        events = await storage.load_unresolved_impact_events()
        if event_id is not None:
            events = [e for e in events if e["id"] == event_id]
        if not events:
            print("[A02] resolve: no unresolved predictions")
            return 0

        market = MarketData(
            storage,
            binance_base_url=settings.market.binance_base_url,
            alpha_vantage_key=settings.market.alpha_vantage_api_key.get_secret_value(),
            timeout=settings.ingestion.request_timeout_seconds,
        )
        for event in events:
            symbol = event["asset"]
            await market.fetch_and_store(symbol)
            entry = None
            cursor_ts = event["first_seen"] or "1970-01-01T00:00:00"
            for candle in await market.series_around(
                symbol, datetime.fromisoformat(cursor_ts), 1, 24 * 31
            ):
                if candle["open_time"] >= cursor_ts:
                    entry = candle["open"]
                    break
            exit_price = await market.last_close(symbol)
            if entry is None or exit_price is None:
                print(f"  #{event['id']} {symbol}: no price data to resolve")
                continue
            actual_return = (exit_price - entry) / entry * 100
            if actual_return > 0.05:
                direction = "up"
            elif actual_return < -0.05:
                direction = "down"
            else:
                direction = "flat"
            print(f"  #{event['id']} {symbol}: entry={entry:.2f} now={exit_price:.2f} "
                  f"actual={actual_return:+.2f}% direction={direction} (predicted {event.get('predicted_direction')} "
                  f"{event.get('predicted_probability') if event.get('predicted_probability') is not None else '-'})")
            await storage.resolve_impact_event(event["id"], actual_return, direction)
        return 0

    return asyncio.run(run())


def metrics() -> int:
    """Calibration, accuracy and drift summary over resolved predictions."""

    import json

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.core.storage import Storage
    from agents.A02_News_Intelligence.intelligence.learning import (
        drift_report,
        metrics as learning_metrics,
        verification_report,
    )

    async def run() -> int:
        storage = Storage(paths.DATABASE_FILE)
        await storage.init()
        events = await storage.load_impact_events()
        report = learning_metrics(events)
        print(f"[A02] metrics: predictions={len(events)} resolved={report['resolved']}")
        if report["resolved"] == 0:
            print("      run `impact <id>` then `resolve` to start the learning loop")
        else:
            print(f"      direction accuracy: {report['direction_hits']}/{report['resolved']} "
                  f"({report['direction_accuracy']*100:.1f}%)")
            print(f"      brier score:        {report['brier'] if report['brier'] is not None else '-'} "
                  f"(0 = perfect, 0.25 = coin flip)")
            print(f"      mean abs impact error: "
                  f"{report['mean_abs_error_pct'] if report['mean_abs_error_pct'] is not None else '-'}%  "
                  f"signed bias: {report['signed_bias_pct'] if report['signed_bias_pct'] is not None else '-'}%")
        for row in report.get("calibration", []):
            flag = " <-- overconfident" if row["overconfident"] else ""
            print(f"      cal bin {row['bin']:>7}: n={row['n']:>2} mean_pred={row['mean_predicted']:.2f} "
                  f"actual={row['actual_rate']:.2f} delta={row['delta']:+.2f}{flag}")
        verification = verification_report(events)
        if verification["resolved_with_truth"]:
            print(f"      verification truth agreement: {verification['verification_agreement']*100:.0f}% "
                  f"({verification['resolved_with_truth']} events)")
        stats = await storage.load_scan_stats()
        drift = drift_report(stats)
        if drift["scans"]:
            print(f"      drift: {drift['scans']} scans, last verdicts={drift['latest_verdicts']}")
        else:
            print("      drift: no scan stats recorded yet")
        return 0

    return asyncio.run(run())


def backtest() -> int:
    """Replay resolved predictions: hit table + what-if vs naive baseline."""

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.core.storage import Storage
    from agents.A02_News_Intelligence.intelligence.learning import metrics as learning_metrics

    async def run() -> int:
        storage = Storage(paths.DATABASE_FILE)
        await storage.init()
        events = await storage.load_impact_events()
        resolved = [e for e in events if e.get("actual_direction") is not None and e.get("predicted_direction")]
        if not resolved:
            print("[A02] backtest: no resolved events yet - run `impact <id>` then `resolve`")
            return 0
        print(f"[A02] backtest: {len(resolved)} resolved events")
        for e in sorted(resolved, key=lambda r: r["id"]):
            claim = ""
            if e.get("narrative_id"):
                rows = await storage.load_active_narratives("1970-01-01T00:00:00")
                row = next((r for r in rows if r["id"] == e["narrative_id"]), None)
                claim = (row or {}).get("claim_text", "")[:60]
            hit = "HIT" if e["predicted_direction"] == e["actual_direction"] else "miss"
            print(f"  #{e['id']} {e['asset']:<6} pred={e['predicted_direction']:<4} "
                  f"({e.get('predicted_probability') or '-'}) actual={e['actual_direction']:<4} "
                  f"ret={e.get('actual_return') or 0:+.2f}% -> {hit}  {claim}")
        report = learning_metrics(events)
        from collections import Counter
        naive = Counter(e["actual_direction"] for e in resolved)
        baseline = max(naive.values()) / len(resolved) if naive else 0
        print(f"  accuracy: {report['direction_accuracy']*100:.1f}% "
              f"(naive baseline: always '{naive.most_common(1)[0][0]}' = {baseline*100:.1f}%)")
        print(f"  mean abs impact error: {report['mean_abs_error_pct']}%")
        return 0

    return asyncio.run(run())


def output(narrative_id: int) -> int:
    """Flagship final report: the 12-point consumer-facing output."""

    from agents.A02_News_Intelligence.config import paths
    from agents.A02_News_Intelligence.config.settings import get_settings
    from agents.A02_News_Intelligence.core.market import MarketData
    from agents.A02_News_Intelligence.core.storage import Storage
    from agents.A02_News_Intelligence.intelligence.narrative import _narrative_from_row

    def next_signal(narrative) -> str:
        """Rule-based next confirmation/debunk signal to watch for."""
        if narrative.epistemic_status in ("confirmed_true", "likely_true"):
            return "no further confirmation needed; watch for secondary narratives building on this claim"
        if narrative.epistemic_status in ("confirmed_false", "likely_false", "fabricated"):
            return "expect partial retraction coverage; watch for price reversion and clarifications"
        if narrative.confidence < 0.6 and narrative.coordination_score >= 60:
            return "low-credibility coordinated amplification - official source or rebuttal is the deciding signal"
        if narrative.fomo_score >= 60:
            return "market may be front-running confirmation - official announcement or denial likely to land next"
        return "official confirmation or denial expected; track volume surge on next publication wave"

    async def run() -> int:
        settings = get_settings()
        storage = Storage(paths.DATABASE_FILE)
        await storage.init()
        rows = await storage.load_active_narratives("1970-01-01T00:00:00")
        narrative = next((_narrative_from_row(r) for r in rows if r["id"] == narrative_id), None)
        if narrative is None:
            print(f"[A02] output: narrative #{narrative_id} not found")
            return 1

        market = MarketData(
            storage,
            binance_base_url=settings.market.binance_base_url,
            alpha_vantage_key=settings.market.alpha_vantage_api_key.get_secret_value(),
            timeout=settings.ingestion.request_timeout_seconds,
        )
        print(f"[A02] output #{narrative_id} - {narrative.claim_text[:80]}")
        print(" 1. CLAIM")
        print(f"    {narrative.claim_text}")
        print(f" 2. AFFECTED ASSETS")
        print(f"    {', '.join(narrative.entities) if narrative.entities else 'none detected'}")
        print(f" 3. SPREAD")
        print(f"    {narrative.mention_count} mentions, {narrative.source_count} sources, "
              f"{len(narrative.platforms)} platforms, velocity {narrative.velocity:.2f}/h, "
              f"status={narrative.status}, first seen {narrative.first_seen:%Y-%m-%d %H:%M}")
        print(f" 4. FOMO")
        print(f"    {narrative.fomo_score:.0f}/100 "
              f"({'extreme' if narrative.fomo_score >= 70 else 'elevated' if narrative.fomo_score >= 45 else 'mild'})")
        print(f" 5. MANIPULATION RISK")
        print(f"    coordination {narrative.coordination_score:.0f}/100 - {narrative.manipulation_flags or 'no flags'}")
        print(f" 6. EVIDENCE")
        print(f"    {narrative.evidence}")
        print(f" 7. EPISTEMIC STATUS")
        print(f"    {narrative.epistemic_status}")
        print(f" 8. CONFIDENCE")
        print(f"    {round(narrative.confidence*100)}%")
        predictions = await _predict_all(narrative, storage, market, settings)
        if predictions:
            for symbol, prediction in predictions:
                print(f" 9. MARKET REACTION")
                print(f"    {symbol}: measured(1h/6h/24h)={prediction.measured_returns_pct} "
                      f"vol={prediction.volatility_pct}% surge={prediction.volume_surge}x")
                print(f"10. HISTORICAL ANALOG")
                print(f"    category={prediction.category} sim={prediction.historical_similarity} "
                      f"events={prediction.historical_events_used} risk={prediction.main_risk}")
                print(f"11. IMPACT PREDICTION")
                print(f"    {prediction.direction} {prediction.probability*100:.0f}% "
                      f"range={prediction.expected_low_pct}%..{prediction.expected_high_pct}% "
                      f"mean={prediction.expected_mean_pct}%")
        else:
            print(" 9-11. MARKET SECTIONS")
            print("    no predictable assets (no crypto entities or no price data)")
        print("12. NEXT SIGNAL")
        print(f"    {next_signal(narrative)}")
        return 0

    return asyncio.run(run())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a02", description="A02 News Intelligence Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Validate the foundation setup")
    sub.add_parser("scan", help="Run one ingestion cycle")
    sub.add_parser("narratives", help="Show active narratives ranked by FOMO")
    impact_parser = sub.add_parser("impact", help="Predict market impact for a narrative")
    impact_parser.add_argument("narrative_id", type=int, help="Narrative id from `narratives`")
    resolve_parser = sub.add_parser("resolve", help="Resolve open predictions against live price")
    resolve_parser.add_argument("--all", action="store_true", help="Resolve all unresolved events")
    resolve_parser.add_argument("event_id", nargs="?", type=int, help="Specific impact event id")
    sub.add_parser("metrics", help="Calibration, accuracy and drift summary")
    sub.add_parser("backtest", help="Replay resolved predictions vs actual outcomes")
    output_parser = sub.add_parser("output", help="Flagship 12-point final report")
    output_parser.add_argument("narrative_id", type=int, help="Narrative id from `narratives`")
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return doctor()
    if args.command == "scan":
        return scan()
    if args.command == "narratives":
        return narratives()
    if args.command == "impact":
        return impact(args.narrative_id)
    if args.command == "resolve":
        return resolve(None if args.all else args.event_id)
    if args.command == "metrics":
        return metrics()
    if args.command == "backtest":
        return backtest()
    if args.command == "output":
        return output(args.narrative_id)
    return 1


if __name__ == "__main__":
    sys.exit(main())
