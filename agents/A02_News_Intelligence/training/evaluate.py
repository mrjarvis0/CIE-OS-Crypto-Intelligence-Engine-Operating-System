"""
CIE-OS
A02 News Intelligence Agent

Module:
    training.evaluate

Purpose:
    Evaluation harness for the verification engine.

    Runs every labeled sample through the exact same path the live
    pipeline uses (Narrative construction -> coordination -> verify),
    then classifies each result:

        HIT  : verdict matches the human expected verdict
        WEAK : indecisive or over-confident on ambiguous data (not wrong)
        FP   : FALSE POSITIVE - real news flagged as false/fabricated
        FN   : FALSE NEGATIVE - fake news accepted as true

    The goal: FP == 0 AND FN == 0.

    Usage:
        python -m agents.A02_News_Intelligence.training.evaluate
        python -m agents.A02_News_Intelligence.training.evaluate --use-ml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.A02_News_Intelligence.intelligence.manipulation import coordination_score
from agents.A02_News_Intelligence.intelligence.verification import verify_narrative
from agents.A02_News_Intelligence.training.dataset import (
    FALSE_LEANING,
    TRUE_LEANING,
    UNCERTAIN,
    SAMPLES,
    build_narrative,
    groups,
)

REPORT_PATH = Path("data/outcomes/training_report.json")


def classify_result(expected: str, got: str) -> tuple[str, str]:
    """Return (outcome, reason)."""
    if got == expected:
        return ("HIT", "exact match")

    if expected in TRUE_LEANING:
        if got in TRUE_LEANING:
            return ("HIT", "true-leaning (not exact)")
        if got in UNCERTAIN:
            return ("WEAK", f"real news under-flagged as {got}")
        return ("FP", f"REAL news flagged {got}")

    if expected in FALSE_LEANING:
        if got in FALSE_LEANING:
            return ("HIT", "false-leaning (not exact)")
        if got in UNCERTAIN:
            return ("WEAK", f"fake claim not caught (got {got})")
        return ("FN", f"FAKE claim accepted as {got}")

    # Expected uncertain
    if got in UNCERTAIN:
        return ("HIT", "indecisive, correctly")
    if got in TRUE_LEANING:
        return ("WEAK", f"ambiguous data over-flagged as true ({got})")
    return ("WEAK", f"ambiguous data over-flagged as false ({got})")


def run(use_ml: bool) -> dict:
    rows = []
    for sample in SAMPLES:
        narrative = build_narrative(sample)
        narrative.coordination_score, narrative.manipulation_flags = coordination_score(narrative)
        verdict, confidence, evidence = verify_narrative(narrative, use_ml=use_ml)
        outcome, reason = classify_result(sample.expected, verdict)
        rows.append({
            "name": sample.name,
            "group": sample.group,
            "expected": sample.expected,
            "verdict": verdict,
            "confidence": round(confidence, 3),
            "coordination": narrative.coordination_score,
            "underlying_sources": evidence.get("underlying_sources", 0),
            "official": evidence.get("official_sources", 0),
            "credible": evidence.get("credible_sources", 0),
            "social_only": evidence.get("social_only", False),
            "supports": evidence.get("supports", 0),
            "denies": evidence.get("denies", 0),
            "questions": evidence.get("questions", 0),
            "outcome": outcome,
            "reason": reason,
        })

    counts = {"HIT": 0, "WEAK": 0, "FP": 0, "FN": 0}
    for r in rows:
        counts[r["outcome"]] += 1

    summary = {
        "use_ml": use_ml,
        "total": len(rows),
        "counts": counts,
        "pass": counts["FP"] == 0 and counts["FN"] == 0,
        "samples": rows,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def print_report(summary: dict) -> None:
    counts = summary["counts"]
    width = max(len(r["name"]) for r in summary["samples"]) + 2

    print()
    print(f"{'SAMPLE'.ljust(width)} {'GROUP':8} {'EXPECTED':16} {'GOT':16} {'CONF':5} {'OUTCOME':7} REASON")
    print("-" * 130)
    for r in summary["samples"]:
        marker = " " if r["outcome"] == "HIT" else ("!" if r["outcome"] == "WEAK" else "***")
        print(
            f"{marker} {r['name'].ljust(width-2)} {r['group']:8} "
            f"{r['expected']:16} {r['verdict']:16} {r['confidence']:.2f}  "
            f"{r['outcome']:7} {r['reason']}"
        )
    print("-" * 130)
    print(
        f"TOTAL {summary['total']}  HIT {counts['HIT']}  WEAK {counts['WEAK']}  "
        f"FP {counts['FP']}  FN {counts['FN']}  "
        f"-> {'PASS (FP=0, FN=0)' if summary['pass'] else 'FAIL - must fix code'}"
    )

    by_group = {}
    for r in summary["samples"]:
        by_group.setdefault(r["group"], {"HIT": 0, "WEAK": 0, "FP": 0, "FN": 0})[r["outcome"]] += 1
    for g in ("real", "fake", "complex"):
        c = by_group.get(g, {})
        print(f"  {g:8}: HIT {c.get('HIT', 0)}  WEAK {c.get('WEAK', 0)}  FP {c.get('FP', 0)}  FN {c.get('FN', 0)}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="A02 verification training harness")
    parser.add_argument("--use-ml", action="store_true", help="enable ML verification signal")
    parser.add_argument("--name", help="evaluate a single sample by name")
    args = parser.parse_args()

    if args.name:
        from agents.A02_News_Intelligence.training.dataset import by_name

        sample = by_name(args.name)
        narrative = build_narrative(sample)
        narrative.coordination_score, narrative.manipulation_flags = coordination_score(narrative)
        verdict, confidence, evidence = verify_narrative(narrative, use_ml=args.use_ml)
        outcome, reason = classify_result(sample.expected, verdict)
        print(f"{sample.name} [{sample.group}] expected={sample.expected} got={verdict} "
              f"conf={confidence:.3f} outcome={outcome} ({reason})")
        print(f"  underlying={evidence.get('underlying_sources')} official={evidence.get('official_sources')} "
              f"credible={evidence.get('credible_sources')} social_only={evidence.get('social_only')} "
              f"s/d/q={evidence.get('supports')}/{evidence.get('denies')}/{evidence.get('questions')}")
        return 1 if outcome in ("FP", "FN") else 0

    summary = run(use_ml=args.use_ml)
    print_report(summary)
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
