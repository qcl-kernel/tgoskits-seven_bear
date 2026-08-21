#!/usr/bin/env python3
"""Compare paired UVC + RKNN summaries without mixing experiment factors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path


EVIDENCE_TYPE = "orangepi-5-plus-uvc-rknn"
CONTRACT = "profiled-uvc-rknn-v1"
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
ALLOWED_VARIED_DIMENSIONS = {"core_mask"}
CONFIG_INVARIANTS = (
    "device",
    "capture_width",
    "capture_height",
    "fps",
    "duration",
    "infer_every",
    "report_interval",
    "min_confidence",
    "core_mask",
    "profile",
    "profile_frames",
)
METRICS = {
    "capture_fps": ("benchmark", "capture_fps", "higher_is_better"),
    "infer_fps": ("benchmark", "infer_fps", "higher_is_better"),
    "decode_ms_p95": ("benchmark", "decode_ms_p95", "lower_is_better"),
    "infer_ms_p95": ("benchmark", "infer_ms_p95", "lower_is_better"),
    "rknn_perf_run_ms_p95": (
        "profile",
        "rknn_perf_run_ms_p95",
        "lower_is_better",
    ),
    "dropped_latest_percent": (
        "derived",
        "dropped_latest_percent",
        "lower_is_better",
    ),
    "vm_rss_kb": ("benchmark", "vm_rss_kb", "lower_is_better"),
    "vm_hwm_kb": ("benchmark", "vm_hwm_kb", "lower_is_better"),
}


class ComparisonError(ValueError):
    """One or more summaries violate the paired-comparison contract."""


def require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ComparisonError(f"{label} must be an object")
    return value


def require_field(mapping: dict[str, object], key: str, label: str) -> object:
    if key not in mapping:
        raise ComparisonError(f"{label} is missing {key}")
    return mapping[key]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_summary(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ComparisonError(f"summary does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComparisonError(f"cannot read summary {path}: {error}") from error
    summary = require_mapping(value, str(path))
    if summary.get("schema_version") != 1:
        raise ComparisonError(f"{path} has unsupported schema_version")
    if summary.get("evidence_type") != EVIDENCE_TYPE:
        raise ComparisonError(f"{path} has unexpected evidence_type")
    acceptance = require_mapping(summary.get("acceptance"), f"{path}.acceptance")
    if acceptance.get("passed") is not True or acceptance.get("contract") != CONTRACT:
        raise ComparisonError(f"{path} is not accepted {CONTRACT} evidence")
    return summary


def nested_mapping(
    summary: dict[str, object], section: str, label: str
) -> dict[str, object]:
    return require_mapping(summary.get(section), f"{label}.{section}")


def numeric_metric(
    summary: dict[str, object], section: str, key: str, label: str
) -> float:
    mapping = nested_mapping(summary, section, label)
    value = require_field(mapping, key, f"{label}.{section}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComparisonError(f"{label}.{section}.{key} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ComparisonError(f"{label}.{section}.{key} must be finite and nonnegative")
    return numeric


def validate_group(
    paths: list[Path], label: str, min_runs: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if len(paths) < min_runs:
        raise ComparisonError(f"{label} requires at least {min_runs} runs")
    summaries = [load_summary(path) for path in paths]
    sources: list[dict[str, object]] = []
    log_hashes: set[str] = set()
    for index, (path, summary) in enumerate(zip(paths, summaries, strict=True), start=1):
        run_label = f"{label}[{index}]"
        source = nested_mapping(summary, "source", run_label)
        log_sha256 = require_field(source, "log_sha256", f"{run_label}.source")
        model_sha256 = require_field(source, "model_sha256", f"{run_label}.source")
        if not isinstance(log_sha256, str) or DIGEST_PATTERN.fullmatch(log_sha256) is None:
            raise ComparisonError(f"{run_label}.source.log_sha256 is invalid")
        if (
            not isinstance(model_sha256, str)
            or DIGEST_PATTERN.fullmatch(model_sha256) is None
        ):
            raise ComparisonError(f"{run_label}.source.model_sha256 is invalid")
        if log_sha256 in log_hashes:
            raise ComparisonError(f"{label} contains a duplicate log: {log_sha256}")
        log_hashes.add(log_sha256)
        configuration = nested_mapping(summary, "configuration", run_label)
        for key in CONFIG_INVARIANTS:
            require_field(configuration, key, f"{run_label}.configuration")
        for metric, (section, key, _) in METRICS.items():
            numeric_metric(summary, section, key, f"{run_label}.{metric}")
        sources.append(
            {
                "path": path.as_posix(),
                "summary_sha256": sha256_file(path),
                "log_sha256": log_sha256,
            }
        )

    reference_source = nested_mapping(summaries[0], "source", f"{label}[1]")
    reference_config = nested_mapping(summaries[0], "configuration", f"{label}[1]")
    for index, summary in enumerate(summaries[1:], start=2):
        source = nested_mapping(summary, "source", f"{label}[{index}]")
        if source["model_sha256"] != reference_source["model_sha256"]:
            raise ComparisonError(f"{label} model_sha256 changes between runs")
        configuration = nested_mapping(summary, "configuration", f"{label}[{index}]")
        for key in CONFIG_INVARIANTS:
            if configuration[key] != reference_config[key]:
                raise ComparisonError(f"{label} {key} changes between runs")
    return summaries, sources


def aggregate(values: list[float], direction: str) -> dict[str, object]:
    worst = min(values) if direction == "higher_is_better" else max(values)
    best = max(values) if direction == "higher_is_better" else min(values)
    return {
        "values": values,
        "median": statistics.median(values),
        "best": best,
        "worst": worst,
    }


def improvement_percent(
    baseline: float, candidate: float, direction: str
) -> float | None:
    if baseline == 0:
        if candidate == 0:
            return 0.0
        return None
    if direction == "higher_is_better":
        return (candidate - baseline) * 100.0 / baseline
    return (baseline - candidate) * 100.0 / baseline


def compare(
    baseline_paths: list[Path],
    candidate_paths: list[Path],
    *,
    baseline_label: str,
    candidate_label: str,
    min_runs: int = 5,
    vary: tuple[str, ...] = (),
) -> dict[str, object]:
    if min_runs <= 0:
        raise ComparisonError("min_runs must be positive")
    if not baseline_label or not candidate_label or baseline_label == candidate_label:
        raise ComparisonError("baseline and candidate labels must be non-empty and distinct")
    if len(baseline_paths) != len(candidate_paths):
        raise ComparisonError("baseline and candidate must have the same number of runs")
    varied = set(vary)
    unknown_varied = varied - ALLOWED_VARIED_DIMENSIONS
    if unknown_varied:
        raise ComparisonError(
            f"unsupported varied dimensions: {', '.join(sorted(unknown_varied))}"
        )

    baseline, baseline_sources = validate_group(
        baseline_paths, baseline_label, min_runs
    )
    candidate, candidate_sources = validate_group(
        candidate_paths, candidate_label, min_runs
    )
    all_log_hashes = [
        source["log_sha256"] for source in baseline_sources + candidate_sources
    ]
    if len(all_log_hashes) != len(set(all_log_hashes)):
        raise ComparisonError("campaign contains a duplicate log across groups")

    baseline_source = nested_mapping(baseline[0], "source", baseline_label)
    candidate_source = nested_mapping(candidate[0], "source", candidate_label)
    if baseline_source["model_sha256"] != candidate_source["model_sha256"]:
        raise ComparisonError("model_sha256 differs between baseline and candidate")
    baseline_config = nested_mapping(baseline[0], "configuration", baseline_label)
    candidate_config = nested_mapping(candidate[0], "configuration", candidate_label)
    for key in CONFIG_INVARIANTS:
        if key not in varied and baseline_config[key] != candidate_config[key]:
            raise ComparisonError(f"{key} differs without being declared as varied")
        if key in varied and baseline_config[key] == candidate_config[key]:
            raise ComparisonError(f"{key} was declared as varied but is unchanged")

    metrics: dict[str, object] = {}
    for metric, (section, key, direction) in METRICS.items():
        baseline_values = [
            numeric_metric(value, section, key, f"{baseline_label}.{metric}")
            for value in baseline
        ]
        candidate_values = [
            numeric_metric(value, section, key, f"{candidate_label}.{metric}")
            for value in candidate
        ]
        improvements: list[float | None] = [
            improvement_percent(base, trial, direction)
            for base, trial in zip(baseline_values, candidate_values, strict=True)
        ]
        defined_improvements = [
            improvement for improvement in improvements if improvement is not None
        ]
        favorable = [
            trial > base if direction == "higher_is_better" else trial < base
            for base, trial in zip(baseline_values, candidate_values, strict=True)
        ]
        non_regressed = [
            trial >= base if direction == "higher_is_better" else trial <= base
            for base, trial in zip(baseline_values, candidate_values, strict=True)
        ]
        metrics[metric] = {
            "direction": direction,
            "baseline": aggregate(baseline_values, direction),
            "candidate": aggregate(candidate_values, direction),
            "paired_improvement_percent": improvements,
            "paired_improvement_percent_median": (
                statistics.median(defined_improvements)
                if defined_improvements
                else None
            ),
            "undefined_percentage_pairs": len(improvements)
            - len(defined_improvements),
            "favorable_pairs": sum(favorable),
            "non_regressed_pairs": sum(non_regressed),
        }

    return {
        "schema_version": 1,
        "evidence_type": "orangepi-5-plus-uvc-rknn-comparison",
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
        "pairs": len(baseline),
        "model_sha256": baseline_source["model_sha256"],
        "varied_dimensions": sorted(varied),
        "fixed_configuration": {
            key: baseline_config[key]
            for key in CONFIG_INVARIANTS
            if key not in varied
        },
        "varied_values": {
            key: {
                "baseline": baseline_config[key],
                "candidate": candidate_config[key],
            }
            for key in sorted(varied)
        },
        "sources": {
            "baseline": baseline_sources,
            "candidate": candidate_sources,
        },
        "metrics": metrics,
        "acceptance": {
            "passed": True,
            "contract": "paired-uvc-rknn-v1",
            "meaning": "evidence contract passed; metric direction remains data-dependent",
        },
    }


def positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, action="append", required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--baseline-label", required=True)
    parser.add_argument("--candidate-label", required=True)
    parser.add_argument("--min-runs", type=positive_int, default=5)
    parser.add_argument(
        "--vary", choices=sorted(ALLOWED_VARIED_DIMENSIONS), action="append", default=[]
    )
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        result = compare(
            arguments.baseline,
            arguments.candidate,
            baseline_label=arguments.baseline_label,
            candidate_label=arguments.candidate_label,
            min_runs=arguments.min_runs,
            vary=tuple(arguments.vary),
        )
    except (ComparisonError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(output, end="")
    else:
        arguments.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
