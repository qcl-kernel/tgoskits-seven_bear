#!/usr/bin/env python3
"""Validate one profiled Orange Pi UVC + RKNN benchmark console capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BEGIN_MARKER = "UVC_RKNN_BENCH_BEGIN"
VALIDATION_BEGIN_PREFIX = "UVC_RKNN_VALIDATE_BEGIN "
VALIDATION_PASS_PREFIX = "UVC_RKNN_VALIDATE_PASS "
VALIDATION_FAIL_PREFIX = "UVC_RKNN_VALIDATE_FAIL "
RESULT_PREFIX = "UVC_RKNN_BENCH_RESULT "
PROFILE_PREFIX = "UVC_RKNN_BENCH_PROFILE_RESULT "
DONE_MARKER = "UVC_RKNN_BENCH_DONE"
CORE_MASK_PREFIX = "bench-rknn: set_core_mask="
CONFIG_PREFIX = "model="

CONFIG_KEYS = {
    "model",
    "label",
    "device",
    "size",
    "fps",
    "duration",
    "infer_every",
    "report_interval",
    "min_confidence",
    "core_mask",
    "profile",
    "profile_frames",
    "validate_list",
    "expected",
    "write_expected",
}
CONFIG_INTEGER_KEYS = {
    "device",
    "fps",
    "duration",
    "infer_every",
    "report_interval",
    "min_confidence",
    "profile",
    "profile_frames",
}
CONFIG_INVARIANTS = (
    "model",
    "label",
    "device",
    "size",
    "fps",
    "duration",
    "infer_every",
    "report_interval",
    "min_confidence",
    "core_mask",
    "profile",
    "profile_frames",
)

RESULT_INTEGER_KEYS = {
    "captured",
    "inferences",
    "bytes",
    "dropped_latest",
    "decode_errors",
    "inference_errors",
    "detections",
    "vm_size_kb",
    "vm_rss_kb",
    "vm_hwm_kb",
    "mem_total_kb",
    "mem_free_kb",
    "mem_available_kb",
}
RESULT_FLOAT_KEYS = {
    "duration_sec",
    "capture_fps",
    "infer_fps",
    "throughput_mib_s",
    "decode_ms_avg",
    "decode_ms_p50",
    "decode_ms_p95",
    "infer_ms_avg",
    "infer_ms_p50",
    "infer_ms_p95",
}
RESULT_KEYS = RESULT_INTEGER_KEYS | RESULT_FLOAT_KEYS

PROFILE_INTEGER_KEYS = {"profile_samples", "perf_run_query_errors"}
PROFILE_FLOAT_KEYS = {
    "total_ms_avg",
    "total_ms_p50",
    "total_ms_p95",
    "malloc_ms_avg",
    "letterbox_ms_avg",
    "letterbox_ms_p50",
    "letterbox_ms_p95",
    "inputs_set_ms_avg",
    "run_ms_avg",
    "run_ms_p50",
    "run_ms_p95",
    "outputs_get_ms_avg",
    "outputs_get_ms_p50",
    "outputs_get_ms_p95",
    "rknn_perf_run_ms_avg",
    "rknn_perf_run_ms_p50",
    "rknn_perf_run_ms_p95",
    "postprocess_ms_avg",
    "postprocess_ms_p50",
    "postprocess_ms_p95",
    "outputs_release_ms_avg",
}
PROFILE_KEYS = PROFILE_INTEGER_KEYS | PROFILE_FLOAT_KEYS


class AnalysisError(ValueError):
    """The console capture violates the benchmark evidence contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_lines(text: str) -> list[str]:
    return [ANSI_ESCAPE.sub("", line).strip() for line in text.splitlines()]


def records_with_prefix(lines: list[str], prefix: str) -> list[str]:
    records = []
    for line in lines:
        offset = line.find(prefix)
        if offset >= 0:
            records.append(line[offset:])
    return records


def require_exact_marker(lines: list[str], marker: str) -> None:
    records = records_with_prefix(lines, marker)
    exact = [record for record in records if record == marker]
    if len(exact) != 1:
        raise AnalysisError(f"expected exactly one {marker} marker, found {len(exact)}")


def parse_tokens(record: str, prefix: str) -> dict[str, str]:
    if not record.startswith(prefix):
        raise AnalysisError(f"record does not start with {prefix!r}")
    fields: dict[str, str] = {}
    body = record[len(prefix) :]
    for token in body.split():
        if "=" not in token:
            raise AnalysisError(f"malformed token in {prefix.strip()}: {token!r}")
        name, value = token.split("=", 1)
        if not name or not value:
            raise AnalysisError(f"empty field in {prefix.strip()}: {token!r}")
        if name in fields:
            raise AnalysisError(f"duplicate {name} field in {prefix.strip()}")
        fields[name] = value
    return fields


def require_keys(fields: dict[str, str], expected: set[str], label: str) -> None:
    missing = sorted(expected - fields.keys())
    if missing:
        raise AnalysisError(f"{label} is missing fields: {', '.join(missing)}")


def parse_int(value: str, label: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise AnalysisError(f"{label} is not an integer: {value!r}") from error
    return parsed


def parse_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise AnalysisError(f"{label} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise AnalysisError(f"{label} must be finite")
    return parsed


def convert_fields(
    fields: dict[str, str],
    integer_keys: set[str],
    float_keys: set[str],
    label: str,
) -> dict[str, object]:
    converted: dict[str, object] = {}
    for name, value in fields.items():
        if name in integer_keys:
            converted[name] = parse_int(value, f"{label}.{name}")
        elif name in float_keys:
            converted[name] = parse_float(value, f"{label}.{name}")
        else:
            converted[name] = value
    return converted


def parse_configurations(lines: list[str]) -> tuple[dict[str, object], dict[str, object]]:
    records = records_with_prefix(lines, CONFIG_PREFIX)
    parsed = []
    for index, record in enumerate(records, start=1):
        fields = parse_tokens(record, "")
        if not CONFIG_KEYS.issubset(fields):
            continue
        require_keys(fields, CONFIG_KEYS, f"configuration {index}")
        unknown = sorted(fields.keys() - CONFIG_KEYS)
        if unknown:
            raise AnalysisError(
                f"configuration {index} has unknown fields: {', '.join(unknown)}"
            )
        converted = convert_fields(
            fields, CONFIG_INTEGER_KEYS, set(), f"configuration {index}"
        )
        parsed.append(converted)

    if len(parsed) != 2:
        raise AnalysisError(f"expected two benchmark configurations, found {len(parsed)}")
    validation, benchmark = parsed
    if validation["validate_list"] == "none" or validation["expected"] == "none":
        raise AnalysisError("validation configuration must name its list and expected data")
    if benchmark["validate_list"] != "none" or benchmark["expected"] != "none":
        raise AnalysisError("benchmark configuration must not run in validation mode")
    for key in CONFIG_INVARIANTS:
        if validation[key] != benchmark[key]:
            raise AnalysisError(
                f"configuration drift for {key}: "
                f"validation={validation[key]!r} benchmark={benchmark[key]!r}"
            )
    if benchmark["profile"] != 1:
        raise AnalysisError("profile must be enabled for competition evidence")
    if benchmark["profile_frames"] != 0:
        raise AnalysisError("per-frame profile output must be disabled for bounded logs")

    size = str(benchmark["size"])
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", size)
    if match is None:
        raise AnalysisError(f"invalid capture size: {size!r}")
    benchmark["capture_width"] = int(match.group(1))
    benchmark["capture_height"] = int(match.group(2))
    benchmark["validation_list"] = validation["validate_list"]
    benchmark["validation_expected"] = validation["expected"]
    return validation, benchmark


def parse_single_record(
    lines: list[str],
    prefix: str,
    expected_keys: set[str],
    integer_keys: set[str],
    float_keys: set[str],
    label: str,
) -> dict[str, object]:
    records = records_with_prefix(lines, prefix)
    if len(records) != 1:
        raise AnalysisError(f"expected exactly one {prefix.strip()} record, found {len(records)}")
    fields = parse_tokens(records[0], prefix)
    require_keys(fields, expected_keys, label)
    unknown = sorted(fields.keys() - expected_keys)
    if unknown:
        raise AnalysisError(f"{label} has unknown fields: {', '.join(unknown)}")
    return convert_fields(fields, integer_keys, float_keys, label)


def require_nonnegative(record: dict[str, object], keys: set[str], label: str) -> None:
    for key in keys:
        value = record[key]
        if not isinstance(value, (int, float)) or value < 0:
            raise AnalysisError(f"{label}.{key} must be nonnegative")


def require_close(observed: float, expected: float, label: str) -> None:
    tolerance = max(0.05, abs(expected) * 0.02)
    if abs(observed - expected) > tolerance:
        raise AnalysisError(
            f"{label} is inconsistent: observed={observed:.6f} "
            f"expected={expected:.6f} tolerance={tolerance:.6f}"
        )


def validate_result(result: dict[str, object], expected_duration_sec: float) -> None:
    require_nonnegative(result, RESULT_KEYS, "benchmark")
    duration = float(result["duration_sec"])
    if duration + 0.05 < expected_duration_sec:
        raise AnalysisError(
            f"benchmark.duration_sec={duration} is shorter than {expected_duration_sec}"
        )
    for key in ("captured", "inferences", "bytes"):
        if int(result[key]) <= 0:
            raise AnalysisError(f"benchmark.{key} must be positive")
    if int(result["inferences"]) > int(result["captured"]):
        raise AnalysisError("benchmark.inferences cannot exceed captured frames")
    for key in ("decode_errors", "inference_errors"):
        if int(result[key]) != 0:
            raise AnalysisError(f"benchmark.{key} must be zero")
    for stem in ("decode_ms", "infer_ms"):
        if float(result[f"{stem}_p50"]) > float(result[f"{stem}_p95"]):
            raise AnalysisError(f"benchmark.{stem}_p50 exceeds {stem}_p95")

    require_close(
        float(result["capture_fps"]),
        int(result["captured"]) / duration,
        "benchmark.capture_fps",
    )
    require_close(
        float(result["infer_fps"]),
        int(result["inferences"]) / duration,
        "benchmark.infer_fps",
    )
    require_close(
        float(result["throughput_mib_s"]),
        int(result["bytes"]) / duration / 1024.0 / 1024.0,
        "benchmark.throughput_mib_s",
    )

    vm_size = int(result["vm_size_kb"])
    vm_rss = int(result["vm_rss_kb"])
    vm_hwm = int(result["vm_hwm_kb"])
    if min(vm_size, vm_rss, vm_hwm) <= 0 or not vm_rss <= vm_hwm <= vm_size:
        raise AnalysisError("benchmark VM memory metrics are missing or inconsistent")
    mem_total = int(result["mem_total_kb"])
    mem_free = int(result["mem_free_kb"])
    mem_available = int(result["mem_available_kb"])
    if mem_total <= 0 or not 0 <= mem_free <= mem_available <= mem_total:
        raise AnalysisError("benchmark system memory metrics are missing or inconsistent")


def parse_profiles(lines: list[str]) -> tuple[dict[str, object], dict[str, object]]:
    records = records_with_prefix(lines, PROFILE_PREFIX)
    if len(records) != 2:
        raise AnalysisError(f"expected two profiled result records, found {len(records)}")
    profiles = []
    for index, record in enumerate(records, start=1):
        fields = parse_tokens(record, PROFILE_PREFIX)
        require_keys(fields, PROFILE_KEYS, f"profile {index}")
        unknown = sorted(fields.keys() - PROFILE_KEYS)
        if unknown:
            raise AnalysisError(f"profile {index} has unknown fields: {', '.join(unknown)}")
        profile = convert_fields(
            fields, PROFILE_INTEGER_KEYS, PROFILE_FLOAT_KEYS, f"profile {index}"
        )
        require_nonnegative(profile, PROFILE_KEYS, f"profile {index}")
        if int(profile["perf_run_query_errors"]) != 0:
            raise AnalysisError(f"profile {index}.perf_run_query_errors must be zero")
        for stem in (
            "total_ms",
            "letterbox_ms",
            "run_ms",
            "outputs_get_ms",
            "rknn_perf_run_ms",
            "postprocess_ms",
        ):
            if float(profile[f"{stem}_p50"]) > float(profile[f"{stem}_p95"]):
                raise AnalysisError(f"profile {index}.{stem}_p50 exceeds {stem}_p95")
        profiles.append(profile)
    return profiles[0], profiles[1]


def parse_validation(lines: list[str], expected_images: int) -> int:
    if expected_images <= 0:
        raise AnalysisError("expected_validation_images must be positive")
    begin = parse_single_record(
        lines,
        VALIDATION_BEGIN_PREFIX,
        {"images", "mode"},
        {"images"},
        set(),
        "validation begin",
    )
    passed = parse_single_record(
        lines,
        VALIDATION_PASS_PREFIX,
        {"images"},
        {"images"},
        set(),
        "validation pass",
    )
    if records_with_prefix(lines, VALIDATION_FAIL_PREFIX):
        raise AnalysisError("console contains UVC_RKNN_VALIDATE_FAIL")
    if begin["mode"] != "verify":
        raise AnalysisError(f"validation mode must be verify, got {begin['mode']!r}")
    if begin["images"] != expected_images or passed["images"] != expected_images:
        raise AnalysisError(
            "validation image count mismatch: "
            f"begin={begin['images']} pass={passed['images']} expected={expected_images}"
        )
    return expected_images


def validate_core_mask(lines: list[str], expected_core_mask: str) -> None:
    records = records_with_prefix(lines, CORE_MASK_PREFIX)
    if len(records) != 2:
        raise AnalysisError(f"expected two core-mask records, found {len(records)}")
    expected = f"{CORE_MASK_PREFIX}{expected_core_mask} ret=0"
    if any(record != expected for record in records):
        raise AnalysisError(
            f"core-mask setup does not match configuration {expected_core_mask!r}"
        )


def analyze(
    log_path: Path,
    *,
    model_artifact: Path,
    expected_duration_sec: float = 60.0,
    expected_validation_images: int = 3,
) -> dict[str, object]:
    if expected_duration_sec <= 0:
        raise AnalysisError("expected_duration_sec must be positive")
    if not log_path.is_file():
        raise AnalysisError(f"console log does not exist: {log_path}")
    if not model_artifact.is_file():
        raise AnalysisError(f"model artifact does not exist: {model_artifact}")
    if model_artifact.stat().st_size <= 0:
        raise AnalysisError("model artifact must not be empty")

    log_bytes = log_path.read_bytes()
    text = log_bytes.decode("utf-8", errors="replace")
    lines = normalized_lines(text)
    require_exact_marker(lines, BEGIN_MARKER)
    require_exact_marker(lines, DONE_MARKER)
    _, configuration = parse_configurations(lines)
    validate_core_mask(lines, str(configuration["core_mask"]))
    validation_images = parse_validation(lines, expected_validation_images)
    result = parse_single_record(
        lines,
        RESULT_PREFIX,
        RESULT_KEYS,
        RESULT_INTEGER_KEYS,
        RESULT_FLOAT_KEYS,
        "benchmark",
    )
    validate_result(result, expected_duration_sec)
    validation_profile, benchmark_profile = parse_profiles(lines)
    if int(validation_profile["profile_samples"]) != validation_images:
        raise AnalysisError("validation profile_samples does not match validated images")
    if int(benchmark_profile["profile_samples"]) != int(result["inferences"]):
        raise AnalysisError("benchmark profile_samples does not match inferences")

    captured = int(result["captured"])
    inferences = int(result["inferences"])
    total_ms = float(benchmark_profile["total_ms_avg"])
    npu_ms = float(benchmark_profile["rknn_perf_run_ms_avg"])
    return {
        "schema_version": 1,
        "evidence_type": "orangepi-5-plus-uvc-rknn",
        "source": {
            "log_path": log_path.as_posix(),
            "log_sha256": hashlib.sha256(log_bytes).hexdigest(),
            "model_path": model_artifact.as_posix(),
            "model_bytes": model_artifact.stat().st_size,
            "model_sha256": sha256_file(model_artifact),
        },
        "configuration": configuration,
        "validation": {
            "images": validation_images,
            "profile": validation_profile,
        },
        "benchmark": result,
        "profile": benchmark_profile,
        "derived": {
            "dropped_latest_percent": round(
                int(result["dropped_latest"]) * 100.0 / captured, 6
            ),
            "capture_to_inference_percent": round(
                inferences * 100.0 / captured, 6
            ),
            "profiled_npu_share_percent": round(
                npu_ms * 100.0 / total_ms if total_ms > 0 else 0.0, 6
            ),
            "host_inference_overhead_ms_avg": round(
                float(result["infer_ms_avg"]) - npu_ms, 6
            ),
        },
        "acceptance": {
            "passed": True,
            "contract": "profiled-uvc-rknn-v1",
        },
    }


def positive_float(value: str) -> float:
    parsed = parse_float(value, "argument")
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def positive_int(value: str) -> int:
    parsed = parse_int(value, "argument")
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="captured board console log")
    parser.add_argument(
        "--model-artifact",
        type=Path,
        required=True,
        help="the RKNN artifact staged into the benchmark image",
    )
    parser.add_argument(
        "--expected-duration-sec", type=positive_float, default=60.0
    )
    parser.add_argument(
        "--expected-validation-images", type=positive_int, default=3
    )
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        result = analyze(
            arguments.log,
            model_artifact=arguments.model_artifact,
            expected_duration_sec=arguments.expected_duration_sec,
            expected_validation_images=arguments.expected_validation_images,
        )
    except (AnalysisError, OSError) as error:
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
