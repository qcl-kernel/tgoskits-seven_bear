#!/usr/bin/env python3
"""Validate and summarize a preregistered RK3588 fixed-image pair campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path


PAIR_COUNT = 5
PROFILE_SAMPLES = 3
CONTRACT = "rk3588-fixed-image-five-pairs-v1"
MODEL_PATTERN = re.compile(r"[0-9a-f]{64}")
CAMPAIGN_BEGIN_PATTERN = re.compile(
    r"^VISION_FIXED_CAMPAIGN_BEGIN os=(?P<os>[a-z0-9-]+) pairs=5$"
)
MODEL_PATTERN_LINE = re.compile(
    r"^VISION_FIXED_MODEL_SHA256 (?P<digest>[0-9a-f]{64})$"
)
RUN_BEGIN_PATTERN = re.compile(
    r"^VISION_FIXED_RUN_BEGIN pair=(?P<pair>[1-5]) "
    r"order=(?P<order>AB|BA) core_mask=(?P<core_mask>0|all)$"
)
RUN_END_PATTERN = re.compile(
    r"^VISION_FIXED_RUN_END pair=(?P<pair>[1-5]) core_mask=(?P<core_mask>0|all)$"
)
CAMPAIGN_DONE_PATTERN = re.compile(
    r"^VISION_FIXED_CAMPAIGN_DONE os=(?P<os>[a-z0-9-]+) pairs=5$"
)
STARRY_PROMPT_PATTERN = re.compile(
    r"^(?:(?:root@starry:[^#\r\n]* # )|(?:> ))+"
    r"(?P<line>(?:VISION_FIXED_|UVC_RKNN_).*)$"
)
KEY_VALUE_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>[^ ]+)")
METRIC_KEYS = (
    "total_ms_avg",
    "total_ms_p95",
    "letterbox_ms_avg",
    "letterbox_ms_p95",
    "rknn_perf_run_ms_avg",
    "rknn_perf_run_ms_p95",
)
SHORT_METRICS = {
    "total_avg": "total_ms_avg",
    "total_p95": "total_ms_p95",
    "letterbox_avg": "letterbox_ms_avg",
    "letterbox_p95": "letterbox_ms_p95",
    "npu_avg": "rknn_perf_run_ms_avg",
    "npu_p95": "rknn_perf_run_ms_p95",
}


class AnalysisError(ValueError):
    """The log does not satisfy the fixed-pair evidence contract."""


@dataclass
class PendingRun:
    pair: int
    order: str
    core_mask: str
    metrics: dict[str, float] = field(default_factory=dict)
    profile_verified: bool = False
    validation_passed: bool = False


def expected_sequence() -> list[tuple[int, str, str]]:
    sequence: list[tuple[int, str, str]] = []
    for pair in range(1, PAIR_COUNT + 1):
        order = "AB" if pair % 2 else "BA"
        masks = ("0", "all") if order == "AB" else ("all", "0")
        sequence.extend((pair, order, core_mask) for core_mask in masks)
    return sequence


def parse_nonnegative_float(value: str, key: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise AnalysisError(f"{key} must be numeric") from error
    if not math.isfinite(parsed) or parsed < 0:
        raise AnalysisError(f"{key} must be finite and nonnegative")
    return parsed


def parse_metric_line(
    line: str, pending: PendingRun
) -> tuple[dict[str, float], bool] | None:
    compact_header = line.startswith("VISION_FIXED_METRIC ")
    compact_total = line.startswith("VISION_FIXED_METRIC_TOTAL ")
    compact_stage = line.startswith("VISION_FIXED_METRIC_STAGE ")
    short_check = line.startswith("VISION_FIXED_CHECK ")
    short_value = line.startswith("VISION_FIXED_VALUE ")
    compact = (
        compact_header
        or compact_total
        or compact_stage
        or short_check
        or short_value
    )
    full = line.startswith("UVC_RKNN_BENCH_PROFILE_RESULT ")
    if not compact and not full:
        return None
    fields = {
        match.group("key"): match.group("value")
        for match in KEY_VALUE_PATTERN.finditer(line)
    }
    if compact:
        if fields.get("pair") != str(pending.pair):
            raise AnalysisError("compact metric pair does not match active run")
        observed_core = fields.get("core") if short_check or short_value else fields.get("core_mask")
        if observed_core != pending.core_mask:
            raise AnalysisError("compact metric core_mask does not match active run")
    profile_verified = compact_header or short_check or full
    if profile_verified:
        sample_key = "samples" if short_check else "profile_samples"
        error_key = "query_errors" if short_check else "perf_run_query_errors"
        if fields.get(sample_key) != str(PROFILE_SAMPLES):
            raise AnalysisError("profile sample count is not 3")
        if fields.get(error_key) != "0":
            raise AnalysisError("RKNN performance query reported an error")
    if short_value:
        short_metric = fields.get("metric")
        if short_metric not in SHORT_METRICS:
            raise AnalysisError("compact value has an unknown metric")
        if "value" not in fields:
            raise AnalysisError("compact value is missing its measurement")
        metric_key = SHORT_METRICS[short_metric]
        parsed = {
            metric_key: parse_nonnegative_float(fields["value"], metric_key)
        }
    else:
        parsed = {
            key: parse_nonnegative_float(fields[key], key)
            for key in METRIC_KEYS
            if key in fields
        }
    if not parsed and not profile_verified:
        raise AnalysisError("metric continuation does not contain any measurements")
    return parsed, profile_verified


def aggregate(values: list[float]) -> dict[str, object]:
    return {
        "values": values,
        "median": statistics.median(values),
        "best": min(values),
        "worst": max(values),
    }


def improvement_percent(baseline: float, candidate: float) -> float | None:
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return (baseline - candidate) * 100.0 / baseline


def analyze_text(text: str, *, expected_os: str | None = None) -> dict[str, object]:
    campaign_os: str | None = None
    model_sha256: str | None = None
    done = False
    pending: PendingRun | None = None
    completed: dict[tuple[int, str], PendingRun] = {}
    observed_sequence: list[tuple[int, str, str]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        prompt = STARRY_PROMPT_PATTERN.fullmatch(line)
        if prompt is not None:
            line = prompt.group("line")
        begin_campaign = CAMPAIGN_BEGIN_PATTERN.fullmatch(line)
        if begin_campaign is not None:
            if campaign_os is not None:
                raise AnalysisError("duplicate campaign begin marker")
            campaign_os = begin_campaign.group("os")
            continue
        model = MODEL_PATTERN_LINE.fullmatch(line)
        if model is not None:
            if model_sha256 is not None:
                raise AnalysisError("duplicate model digest")
            model_sha256 = model.group("digest")
            continue
        begin_run = RUN_BEGIN_PATTERN.fullmatch(line)
        if begin_run is not None:
            if pending is not None:
                raise AnalysisError("run begins before the previous run ends")
            pair = int(begin_run.group("pair"))
            order = begin_run.group("order")
            core_mask = begin_run.group("core_mask")
            key = (pair, core_mask)
            if key in completed:
                raise AnalysisError(
                    f"duplicate run for pair={pair} core_mask={core_mask}"
                )
            pending = PendingRun(pair, order, core_mask)
            observed_sequence.append((pair, order, core_mask))
            continue
        if pending is not None:
            metric_record = parse_metric_line(line, pending)
            if metric_record is not None:
                metrics, profile_verified = metric_record
                duplicate_keys = pending.metrics.keys() & metrics.keys()
                if duplicate_keys:
                    raise AnalysisError(
                        "duplicate metrics in one run: "
                        + ", ".join(sorted(duplicate_keys))
                    )
                if profile_verified and pending.profile_verified:
                    raise AnalysisError("duplicate profile verification in one run")
                pending.metrics.update(metrics)
                pending.profile_verified = (
                    pending.profile_verified or profile_verified
                )
                continue
            if line == "UVC_RKNN_VALIDATE_PASS images=3":
                if pending.validation_passed:
                    raise AnalysisError("duplicate validation marker in one run")
                pending.validation_passed = True
                continue
            end_run = RUN_END_PATTERN.fullmatch(line)
            if end_run is not None:
                end_key = (int(end_run.group("pair")), end_run.group("core_mask"))
                if end_key != (pending.pair, pending.core_mask):
                    raise AnalysisError("run end marker does not match active run")
                if not pending.profile_verified:
                    raise AnalysisError("run is missing profile verification")
                missing_metrics = [
                    key for key in METRIC_KEYS if key not in pending.metrics
                ]
                if missing_metrics:
                    raise AnalysisError(
                        "run is missing metrics: " + ", ".join(missing_metrics)
                    )
                if not pending.validation_passed:
                    raise AnalysisError("run is missing its validation pass marker")
                completed[end_key] = pending
                pending = None
                continue
        done_campaign = CAMPAIGN_DONE_PATTERN.fullmatch(line)
        if done_campaign is not None:
            if done:
                raise AnalysisError("duplicate campaign done marker")
            if pending is not None:
                raise AnalysisError("campaign ended while a run was active")
            if campaign_os is None or done_campaign.group("os") != campaign_os:
                raise AnalysisError("campaign OS changes between begin and done")
            done = True

    if campaign_os is None:
        raise AnalysisError("campaign begin marker is missing")
    if expected_os is not None and campaign_os != expected_os:
        raise AnalysisError(
            f"expected os={expected_os}, observed os={campaign_os}"
        )
    if model_sha256 is None or MODEL_PATTERN.fullmatch(model_sha256) is None:
        raise AnalysisError("model digest is missing or invalid")
    if pending is not None:
        raise AnalysisError("last run does not have an end marker")
    if not done:
        raise AnalysisError("campaign done marker is missing")
    if observed_sequence != expected_sequence():
        raise AnalysisError("run order differs from the preregistered AB/BA sequence")
    if len(completed) != PAIR_COUNT * 2:
        raise AnalysisError("campaign does not contain exactly five complete pairs")

    metrics: dict[str, object] = {}
    for metric_key in METRIC_KEYS:
        core0_values = [
            completed[(pair, "0")].metrics[metric_key]
            for pair in range(1, PAIR_COUNT + 1)
        ]
        all_values = [
            completed[(pair, "all")].metrics[metric_key]
            for pair in range(1, PAIR_COUNT + 1)
        ]
        improvements = [
            improvement_percent(baseline, candidate)
            for baseline, candidate in zip(core0_values, all_values, strict=True)
        ]
        defined = [value for value in improvements if value is not None]
        metrics[metric_key] = {
            "direction": "lower_is_better",
            "core0": aggregate(core0_values),
            "all": aggregate(all_values),
            "paired_improvement_percent": improvements,
            "paired_improvement_percent_median": (
                statistics.median(defined) if defined else None
            ),
            "undefined_percentage_pairs": len(improvements) - len(defined),
            "favorable_pairs": sum(
                candidate < baseline
                for baseline, candidate in zip(
                    core0_values, all_values, strict=True
                )
            ),
            "non_regressed_pairs": sum(
                candidate <= baseline
                for baseline, candidate in zip(
                    core0_values, all_values, strict=True
                )
            ),
        }

    return {
        "schema_version": 1,
        "evidence_type": "rk3588-fixed-image-paired-profile",
        "contract": CONTRACT,
        "os": campaign_os,
        "pairs": PAIR_COUNT,
        "model_sha256": model_sha256,
        "pair_order": [
            {"pair": pair, "order": "AB" if pair % 2 else "BA"}
            for pair in range(1, PAIR_COUNT + 1)
        ],
        "metrics": metrics,
        "acceptance": {
            "passed": True,
            "contract": CONTRACT,
            "validation_images_per_run": PROFILE_SAMPLES,
            "perf_run_query_errors": 0,
        },
    }


def analyze_file(path: Path, *, expected_os: str | None = None) -> dict[str, object]:
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise AnalysisError(f"cannot read {path}: {error}") from error
    result = analyze_text(text, expected_os=expected_os)
    result["source"] = {
        "path": path.as_posix(),
        "log_sha256": hashlib.sha256(data).hexdigest(),
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected-os")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        result = analyze_file(arguments.log, expected_os=arguments.expected_os)
    except AnalysisError as error:
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
