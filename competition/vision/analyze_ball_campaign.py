#!/usr/bin/env python3
"""Validate and summarize the preregistered 30-pair ball campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_RECORD_KEYS = {
    "trial_id",
    "strategy",
    "frame_id",
    "session_id",
    "sequence",
    "actual_action",
    "captured_at_us",
    "stable_at_us",
    "physical_result_verified",
}
VALID_ACTIONS = {"left", "right", "hold"}
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON {path}: {error}") from error


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read JSONL {path}: {error}") from error
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL line {line_number}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"JSONL line {line_number} is not an object")
        records.append(record)
    return records


def require_positive_int(record: dict[str, Any], key: str, context: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{context}: {key} must be a positive integer")
    return value


def percentile_nearest_rank(values: list[int], percentile: float) -> int:
    if not values:
        raise ValueError("cannot calculate a percentile from no values")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported campaign manifest schema")
    if manifest.get("paired_trial_count") != 30:
        raise ValueError("formal campaign must preregister exactly 30 paired trials")
    trials = manifest.get("trials")
    if not isinstance(trials, list) or len(trials) != 30:
        raise ValueError("manifest must contain exactly 30 trials")
    identifiers: set[str] = set()
    conditions: Counter[str] = Counter()
    for index, trial in enumerate(trials, 1):
        if not isinstance(trial, dict):
            raise ValueError(f"manifest trial {index} is not an object")
        trial_id = trial.get("trial_id")
        condition = trial.get("condition")
        expected_action = trial.get("expected_action")
        order = trial.get("strategy_order")
        if not isinstance(trial_id, str) or not trial_id:
            raise ValueError(f"manifest trial {index} has invalid trial_id")
        if trial_id in identifiers:
            raise ValueError(f"duplicate manifest trial_id: {trial_id}")
        identifiers.add(trial_id)
        if condition not in {"left", "right", "absent"}:
            raise ValueError(f"manifest trial {trial_id} has invalid condition")
        expected_for_condition = "hold" if condition == "absent" else condition
        if expected_action != expected_for_condition:
            raise ValueError(f"manifest trial {trial_id} has inconsistent expected action")
        if order not in (["ai", "fixed"], ["fixed", "ai"]):
            raise ValueError(f"manifest trial {trial_id} has invalid strategy order")
        conditions[condition] += 1
    if conditions != Counter({"left": 10, "right": 10, "absent": 10}):
        raise ValueError(f"campaign conditions are not balanced: {dict(conditions)}")
    return trials


def analyze_campaign(
    manifest_path: Path, records_path: Path, source_commit: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("source commit must be a full lowercase 40-hex commit")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("campaign manifest is not an object")
    trials = validate_manifest(manifest)
    records = load_jsonl(records_path)
    expected_order = [
        (trial["trial_id"], strategy)
        for trial in trials
        for strategy in trial["strategy_order"]
    ]
    actual_order: list[tuple[Any, Any]] = [
        (record.get("trial_id"), record.get("strategy")) for record in records
    ]
    if actual_order != expected_order:
        raise ValueError(
            "record order or count differs from the preregistered 30-pair schedule"
        )

    maximum_latency_us = manifest["evidence_gate"]["maximum_latency_us"]
    trial_by_id = {trial["trial_id"]: trial for trial in trials}
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[int, int, int]] = set()
    for record in records:
        context = f"{record.get('trial_id')}/{record.get('strategy')}"
        if set(record) != REQUIRED_RECORD_KEYS:
            missing = sorted(REQUIRED_RECORD_KEYS - set(record))
            extra = sorted(set(record) - REQUIRED_RECORD_KEYS)
            raise ValueError(f"{context}: record keys differ; missing={missing} extra={extra}")
        trial = trial_by_id[record["trial_id"]]
        strategy = record["strategy"]
        action = record["actual_action"]
        if action not in VALID_ACTIONS:
            raise ValueError(f"{context}: unsupported actual action")
        if strategy == "fixed" and action != "hold":
            raise ValueError(f"{context}: fixed policy was adapted instead of always HOLD")
        if record["physical_result_verified"] is not True:
            raise ValueError(f"{context}: physical result is not verified")
        frame_id = require_positive_int(record, "frame_id", context)
        session_id = require_positive_int(record, "session_id", context)
        sequence = require_positive_int(record, "sequence", context)
        identity = (frame_id, session_id, sequence)
        if identity in identities:
            raise ValueError(f"{context}: repeated frame/session/sequence identity")
        identities.add(identity)
        captured_at_us = require_positive_int(record, "captured_at_us", context)
        stable_at_us = require_positive_int(record, "stable_at_us", context)
        latency_us = stable_at_us - captured_at_us
        if latency_us <= 0 or latency_us > maximum_latency_us:
            raise ValueError(f"{context}: capture-to-stable latency is outside the gate")
        normalized.append(
            {
                **record,
                "condition": trial["condition"],
                "expected_action": trial["expected_action"],
                "correct": action == trial["expected_action"],
                "capture_to_stable_us": latency_us,
            }
        )

    metrics: dict[str, dict[str, Any]] = {}
    for strategy in ("ai", "fixed"):
        strategy_records = [record for record in normalized if record["strategy"] == strategy]
        correct = sum(record["correct"] for record in strategy_records)
        latencies = [record["capture_to_stable_us"] for record in strategy_records]
        absent = [record for record in strategy_records if record["condition"] == "absent"]
        false_motion = sum(record["actual_action"] != "hold" for record in absent)
        metrics[strategy] = {
            "trials": len(strategy_records),
            "correct": correct,
            "action_accuracy": correct / len(strategy_records),
            "capture_to_stable_p50_us": percentile_nearest_rank(latencies, 0.50),
            "capture_to_stable_p95_us": percentile_nearest_rank(latencies, 0.95),
            "capture_to_stable_max_us": max(latencies),
            "absent_false_motion_count": false_motion,
            "absent_false_motion_rate": false_motion / len(absent),
        }

    summary = {
        "schema_version": 1,
        "status": "pass",
        "campaign_id": manifest["campaign_id"],
        "source_commit": source_commit,
        "paired_trial_count": len(trials),
        "record_count": len(normalized),
        "manifest_sha256": sha256_file(manifest_path),
        "records_sha256": sha256_file(records_path),
        "preregistered_primary_metrics": [
            "action_accuracy",
            "capture_to_stable_p95_us",
        ],
        "metrics": metrics,
        "paired_deltas": {
            "action_accuracy_percentage_points_ai_minus_fixed": (
                metrics["ai"]["action_accuracy"] - metrics["fixed"]["action_accuracy"]
            )
            * 100.0,
            "capture_to_stable_p95_us_ai_minus_fixed": (
                metrics["ai"]["capture_to_stable_p95_us"]
                - metrics["fixed"]["capture_to_stable_p95_us"]
            ),
        },
        "claim_boundary": (
            "This finite, balanced, preregistered campaign reports observed paired results; "
            "it is not a population-level accuracy or WCET proof."
        ),
    }
    return summary, normalized


def write_svg(summary: dict[str, Any], destination: Path) -> None:
    ai = summary["metrics"]["ai"]
    fixed = summary["metrics"]["fixed"]
    ai_accuracy = ai["action_accuracy"] * 100.0
    fixed_accuracy = fixed["action_accuracy"] * 100.0
    ai_latency = ai["capture_to_stable_p95_us"] / 1000.0
    fixed_latency = fixed["capture_to_stable_p95_us"] / 1000.0
    latency_max = max(ai_latency, fixed_latency, 1.0)
    accuracy_heights = (3.6 * ai_accuracy, 3.6 * fixed_accuracy)
    latency_heights = (360.0 * ai_latency / latency_max, 360.0 * fixed_latency / latency_max)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="650" viewBox="0 0 1200 650">
<rect width="1200" height="650" rx="28" fill="#07101b"/>
<text x="60" y="60" fill="#f5f7fb" font-family="sans-serif" font-size="30" font-weight="700">AI vs fixed policy · preregistered 30 paired trials</text>
<text x="60" y="94" fill="#8ea1b8" font-family="sans-serif" font-size="17">Same board, scene schedule and physical-result evidence gate</text>
<line x1="60" y1="520" x2="560" y2="520" stroke="#40536b" stroke-width="2"/>
<text x="60" y="145" fill="#dbe6f3" font-family="sans-serif" font-size="22">Action accuracy · higher is better</text>
<rect x="150" y="{520-accuracy_heights[0]:.1f}" width="120" height="{accuracy_heights[0]:.1f}" rx="8" fill="#39d98a"/>
<rect x="350" y="{520-accuracy_heights[1]:.1f}" width="120" height="{accuracy_heights[1]:.1f}" rx="8" fill="#60758f"/>
<text x="210" y="{500-accuracy_heights[0]:.1f}" text-anchor="middle" fill="#65f0aa" font-family="sans-serif" font-size="24" font-weight="700">{ai_accuracy:.1f}%</text>
<text x="410" y="{500-accuracy_heights[1]:.1f}" text-anchor="middle" fill="#dbe6f3" font-family="sans-serif" font-size="24" font-weight="700">{fixed_accuracy:.1f}%</text>
<text x="210" y="555" text-anchor="middle" fill="#dbe6f3" font-family="sans-serif" font-size="20">AI</text>
<text x="410" y="555" text-anchor="middle" fill="#dbe6f3" font-family="sans-serif" font-size="20">FIXED HOLD</text>
<line x1="640" y1="520" x2="1140" y2="520" stroke="#40536b" stroke-width="2"/>
<text x="640" y="145" fill="#dbe6f3" font-family="sans-serif" font-size="22">Capture-to-stable p95 · lower is better</text>
<rect x="730" y="{520-latency_heights[0]:.1f}" width="120" height="{latency_heights[0]:.1f}" rx="8" fill="#ffc857"/>
<rect x="930" y="{520-latency_heights[1]:.1f}" width="120" height="{latency_heights[1]:.1f}" rx="8" fill="#60758f"/>
<text x="790" y="{500-latency_heights[0]:.1f}" text-anchor="middle" fill="#ffd77d" font-family="sans-serif" font-size="24" font-weight="700">{ai_latency:.1f} ms</text>
<text x="990" y="{500-latency_heights[1]:.1f}" text-anchor="middle" fill="#dbe6f3" font-family="sans-serif" font-size="24" font-weight="700">{fixed_latency:.1f} ms</text>
<text x="790" y="555" text-anchor="middle" fill="#dbe6f3" font-family="sans-serif" font-size="20">AI</text>
<text x="990" y="555" text-anchor="middle" fill="#dbe6f3" font-family="sans-serif" font-size="20">FIXED HOLD</text>
<text x="60" y="610" fill="#8ea1b8" font-family="sans-serif" font-size="15">Observed finite-campaign result; not a population accuracy or WCET claim.</text>
</svg>"""
    destination.write_text(svg, encoding="utf-8")


def write_outputs(
    output_dir: Path, summary: dict[str, Any], normalized: list[dict[str, Any]]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    columns = [
        "trial_id",
        "condition",
        "strategy",
        "frame_id",
        "session_id",
        "sequence",
        "expected_action",
        "actual_action",
        "correct",
        "capture_to_stable_us",
        "physical_result_verified",
    ]
    with (output_dir / "paired-records.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(normalized)
    write_svg(summary, output_dir / "ai-vs-fixed.svg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary, normalized = analyze_campaign(
            args.manifest, args.records, args.source_commit
        )
        write_outputs(args.output_dir, summary, normalized)
    except ValueError as error:
        raise SystemExit(f"BALL_CAMPAIGN_FAIL reason={error}") from error
    print(
        "BALL_CAMPAIGN_PASS "
        f"pairs={summary['paired_trial_count']} records={summary['record_count']} "
        f"output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
