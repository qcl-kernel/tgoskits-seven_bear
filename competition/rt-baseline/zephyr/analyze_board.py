#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Validate a direct Zephyr RT-baseline run on Orange Pi 5 Plus."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import analyze as baseline


BOARD_CONFIG = {
    "schema": "1",
    "os": "zephyr",
    "zephyr_version": "4.3.0",
    "board": "roc_rk3588_pc",
    "cpu_model": "cortex-a55",
    "cpu_count": "1",
    "platform": "orange-pi-5-plus-rk3588",
    "qemu_icount": "not-applicable",
    "samples": "10000",
    "warmup": "100",
    "benchmark_priority": "-16",
    "stress_priority": "5",
    "clock_hz": "24000000",
    "ticks_per_sec": "1000",
    "record_replays": "3",
    "record_tx_chunk_bytes": "16",
    "record_tx_chunk_delay_ms": "5",
}
PROFILE_PERIOD_US = {
    "short": 1_000,
    "soak": 180_000,
}
SAMPLE_COUNT = 10_000
WARMUP_COUNT = 100
RESULT_REQUIRED_FIELDS = {
    "schema",
    "workload",
    "metric",
    "unit",
    "count",
    "min_ns",
    "mean_ns",
    "p50_ns",
    "p90_ns",
    "p99_ns",
    "p999_ns",
    "max_ns",
    "actual_duration_us",
    "expected_duration_us",
    "replay",
}
WORKLOAD_REQUIRED_FIELDS = {
    "schema",
    "kind",
    "verified",
    "lower_priority",
    "benchmark_priority",
    "stress_priority",
    "blocks",
    "replay",
}
LOAD_REQUIRED_FIELDS = {
    "schema",
    "workload",
    "verified",
    "window_duration_us",
    "cpu_non_idle_permille",
    "cpu_idle_permille",
    "benchmark_permille",
    "stress_permille",
    "stress_blocks",
    "stress_blocks_per_second",
    "cpu_cycles",
    "idle_cycles",
    "benchmark_cycles",
    "stress_cycles",
    "replay",
}
COMPLETE_REQUIRED_FIELDS = {
    "schema",
    "workload",
    "status",
    "timer_misses",
    "warmup_timer_misses",
    "early_wakes",
    "replay",
}


def expected_config(profile: str) -> dict[str, str]:
    """Return the strict console configuration for one board profile."""
    return {
        **BOARD_CONFIG,
        "period_us": str(PROFILE_PERIOD_US[profile]),
    }


def expected_duration_us(profile: str) -> int:
    """Return the requested measured duration for one profile."""
    return SAMPLE_COUNT * PROFILE_PERIOD_US[profile]


def require_marker(path: Path, marker: str) -> None:
    """Require an exact health or lifecycle marker in a text artifact."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if marker not in text.splitlines():
        raise baseline.AnalysisError(f"{path.name} is missing marker {marker!r}")


def load_power_status(path: Path) -> dict[str, object]:
    """Validate a fault-free powered-on smart-plug observation."""
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as error:
        raise baseline.AnalysisError(f"could not read power status: {path}") from error
    if not isinstance(status, dict):
        raise baseline.AnalysisError("power status is not a JSON object")
    if status.get("power_on") is not True or status.get("fault_code") != 0:
        raise baseline.AnalysisError("board power status is not healthy and on")
    return status


def load_serial_status(path: Path) -> int:
    """Read the serial helper status retained even when the board reset closes it."""
    text = path.read_text(encoding="utf-8").strip()
    prefix = "serial_status="
    if not text.startswith(prefix):
        raise baseline.AnalysisError("serial status artifact is malformed")
    try:
        status = int(text.removeprefix(prefix), 10)
    except ValueError as error:
        raise baseline.AnalysisError("serial status is not an integer") from error
    if status < 0:
        raise baseline.AnalysisError("serial status must be non-negative")
    return status


def select_record_replays(
    lines: Sequence[str], marker: str, required_fields: set[str]
) -> tuple[dict[str, str], dict[str, object]]:
    """Select one complete record while rejecting conflicting serial copies."""
    complete_copies: list[dict[str, str]] = []
    complete_replays: list[int] = []
    incomplete_copies = 0
    malformed_copies = 0
    for line in lines:
        try:
            record = baseline.parse_record(line, marker)
        except baseline.AnalysisError:
            if line.strip().startswith(f"{marker} "):
                malformed_copies += 1
            continue
        if record is None:
            continue
        if not required_fields.issubset(record):
            incomplete_copies += 1
            continue
        replay = baseline.parse_nonnegative(record, "replay", marker)
        if replay not in (1, 2, 3):
            raise baseline.AnalysisError(f"{marker}: replay index is outside 1..3")
        complete_replays.append(replay)
        complete_copies.append(
            {key: value for key, value in record.items() if key != "replay"}
        )

    if not complete_copies:
        raise baseline.AnalysisError(f"{marker}: no complete serial replay")
    selected = complete_copies[0]
    if any(copy != selected for copy in complete_copies[1:]):
        raise baseline.AnalysisError(f"{marker}: conflicting complete serial replays")
    return selected, {
        "configured_copies": 3,
        "complete_copies": len(complete_copies),
        "complete_replays": sorted(complete_replays),
        "incomplete_copies": incomplete_copies,
        "malformed_copies": malformed_copies,
    }


def select_result_replays(
    lines: Sequence[str], workload: str
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Select one complete, consistent copy of each replayed result record."""
    complete_by_metric: dict[str, list[dict[str, str]]] = {}
    incomplete_copies = 0
    malformed_copies = 0
    for line in lines:
        try:
            record = baseline.parse_record(line, "RTOS_BASELINE_RESULT")
        except baseline.AnalysisError:
            if line.strip().startswith("RTOS_BASELINE_RESULT "):
                malformed_copies += 1
            continue
        if record is None:
            continue
        if not RESULT_REQUIRED_FIELDS.issubset(record):
            incomplete_copies += 1
            continue
        if record.get("workload") != workload:
            raise baseline.AnalysisError("result replay belongs to another workload")
        replay = baseline.parse_nonnegative(record, "replay", "RTOS_BASELINE_RESULT")
        if replay not in (1, 2, 3):
            raise baseline.AnalysisError("result replay index is outside 1..3")
        metric = record.get("metric", "")
        canonical = {key: value for key, value in record.items() if key != "replay"}
        complete_by_metric.setdefault(metric, []).append(canonical)

    selected: list[dict[str, str]] = []
    observed: dict[str, int] = {}
    for metric in baseline.EXPECTED_METRICS:
        copies = complete_by_metric.get(metric, [])
        if not copies:
            raise baseline.AnalysisError(f"{metric}: no complete serial replay")
        first = copies[0]
        if any(copy != first for copy in copies[1:]):
            raise baseline.AnalysisError(f"{metric}: conflicting complete serial replays")
        selected.append(first)
        observed[metric] = len(copies)
    if set(complete_by_metric) != baseline.EXPECTED_METRICS:
        raise baseline.AnalysisError("result replays contain an unexpected metric")
    return selected, {
        "configured_copies_per_metric": 3,
        "complete_copies": observed,
        "incomplete_copies": incomplete_copies,
        "malformed_copies": malformed_copies,
    }


def board_tool_metadata() -> dict[str, str]:
    """Record the compiler and host tools used to build and validate the run."""
    compiler_prefix = os.environ.get("CROSS_COMPILE", "aarch64-linux-gnu-")
    compiler = shutil.which(f"{compiler_prefix}gcc") or f"{compiler_prefix}gcc"
    return {
        "compiler": baseline.command_output([compiler, "--version"]),
        "python": platform.python_version(),
        "host_kernel": platform.release(),
        "host_machine": platform.machine(),
    }


def analyze_board(arguments: argparse.Namespace) -> dict[str, object]:
    """Validate one complete physical-board capture and assemble evidence."""
    if arguments.profile == "soak" and arguments.workload != "cpu-stress":
        raise baseline.AnalysisError("the physical soak contract requires cpu-stress")

    raw_text = arguments.raw_log.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.splitlines()
    if baseline.select_records(lines, "RTOS_BASELINE_FATAL"):
        raise baseline.AnalysisError("console contains RTOS_BASELINE_FATAL")

    duration_us = expected_duration_us(arguments.profile)
    selected_config, config_replays = select_record_replays(
        lines,
        "RTOS_BASELINE_CONFIG",
        set(expected_config(arguments.profile)) | {"workload", "replay"},
    )
    config = baseline.validate_config(
        selected_config,
        arguments.workload,
        expected_config(arguments.profile),
    )
    selected_workload, workload_replays = select_record_replays(
        lines,
        "RTOS_BASELINE_WORKLOAD_READY",
        WORKLOAD_REQUIRED_FIELDS,
    )
    baseline.validate_workload_ready(
        selected_workload,
        arguments.workload,
    )
    selected_results, result_replays = select_result_replays(lines, arguments.workload)
    results = baseline.validate_results(
        selected_results,
        arguments.workload,
        sample_count=SAMPLE_COUNT,
        expected_duration_us=duration_us,
    )
    selected_load, load_replays = select_record_replays(
        lines,
        "RTOS_BASELINE_LOAD",
        LOAD_REQUIRED_FIELDS,
    )
    load = baseline.validate_load(
        selected_load,
        arguments.workload,
        minimum_duration_us=duration_us,
        allow_sub_permille_benchmark=True,
    )
    selected_completion, completion_replays = select_record_replays(
        lines,
        "RTOS_BASELINE_COMPLETE",
        COMPLETE_REQUIRED_FIELDS,
    )
    completion = baseline.validate_complete(
        selected_completion,
        arguments.workload,
        measured_expirations=SAMPLE_COUNT,
        warmup_expirations=WARMUP_COUNT,
    )
    source, provenance_artifact = baseline.load_source_provenance(
        arguments.source_provenance, arguments.zephyr_base, arguments.raw_log
    )

    require_marker(arguments.stage_log, "NATIVE_ZEPHYR_STAGE_PASS")
    require_marker(arguments.pre_health, "PRE_NATIVE_LINUX_HEALTH_PASS")
    require_marker(arguments.post_health, "POST_NATIVE_LINUX_HEALTH_PASS")
    if "Allocated board session:" not in arguments.board_service_log.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise baseline.AnalysisError("board service log does not prove lease allocation")
    power_before = load_power_status(arguments.power_before)
    power_after = load_power_status(arguments.power_after)
    serial_status = load_serial_status(arguments.serial_status)

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": (
            "Zephyr directly on Orange Pi 5 Plus RK3588; no AxVisor or guest "
            "virtualization"
        ),
        "profile": arguments.profile,
        "workload": arguments.workload,
        "configuration": config,
        "metrics": results,
        "load": load,
        "completion": completion,
        "serial_replays": {
            "configuration": config_replays,
            "workload_ready": workload_replays,
            "results": result_replays,
            "load": load_replays,
            "completion": completion_replays,
        },
        "serial_capture_status": serial_status,
        "source": source,
        "tools": board_tool_metadata(),
        "hardware": {
            "board": "Orange Pi 5 Plus",
            "soc": "Rockchip RK3588",
            "measured_cpu": "Cortex-A55 CPU0",
            "timer": "AArch64 architected counter at 24 MHz",
            "uart": "RK3588 UART2 at 1,500,000 baud",
            "power_before": power_before,
            "power_after": power_after,
        },
        "artifacts": {
            "raw_console": baseline.artifact(arguments.raw_log, arguments.raw_log.name),
            "build_log": baseline.artifact(arguments.build_log, arguments.build_log.name),
            "dot_config": baseline.artifact(
                arguments.build_dir / "zephyr" / ".config", "build/zephyr/.config"
            ),
            "elf": baseline.artifact(
                arguments.build_dir / "zephyr" / "zephyr.elf",
                "build/zephyr/zephyr.elf",
            ),
            "binary": baseline.artifact(
                arguments.build_dir / "zephyr" / "zephyr.bin",
                "build/zephyr/zephyr.bin",
            ),
            "source_provenance": provenance_artifact,
            "stage_log": baseline.artifact(arguments.stage_log, arguments.stage_log.name),
            "pre_linux_health": baseline.artifact(
                arguments.pre_health, arguments.pre_health.name
            ),
            "post_linux_health": baseline.artifact(
                arguments.post_health, arguments.post_health.name
            ),
            "board_service": baseline.artifact(
                arguments.board_service_log, arguments.board_service_log.name
            ),
            "power_before": baseline.artifact(
                arguments.power_before, arguments.power_before.name
            ),
            "power_after": baseline.artifact(
                arguments.power_after, arguments.power_after.name
            ),
            "serial_status": baseline.artifact(
                arguments.serial_status, arguments.serial_status.name
            ),
        },
        "method": {
            "period": f"{PROFILE_PERIOD_US[arguments.profile]} us absolute k_timer period",
            "clock": "k_cycle_get_64 backed by the RK3588 architected timer",
            "wake_lateness": "task observation minus absolute timer deadline",
            "dispatch_latency": "task observation minus timer callback timestamp",
            "percentile": "nearest-rank over 10,000 samples",
            "measurement_logging": "no console output occurs while samples are collected",
        },
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse physical-board analyzer arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_log", type=Path)
    parser.add_argument("--build-log", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--zephyr-base", required=True, type=Path)
    parser.add_argument("--source-provenance", required=True, type=Path)
    parser.add_argument("--workload", required=True, choices=("idle", "cpu-stress"))
    parser.add_argument("--profile", required=True, choices=tuple(PROFILE_PERIOD_US))
    parser.add_argument("--stage-log", required=True, type=Path)
    parser.add_argument("--pre-health", required=True, type=Path)
    parser.add_argument("--post-health", required=True, type=Path)
    parser.add_argument("--board-service-log", required=True, type=Path)
    parser.add_argument("--power-before", required=True, type=Path)
    parser.add_argument("--power-after", required=True, type=Path)
    parser.add_argument("--serial-status", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write one immutable physical-board summary."""
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    temporary_output = arguments.output.with_name(
        f".{arguments.output.name}.{os.getpid()}.tmp"
    )
    try:
        if arguments.output.exists():
            raise baseline.AnalysisError(
                f"refusing to overwrite evidence: {arguments.output}"
            )
        result = analyze_board(arguments)
        rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        temporary_output.write_text(rendered, encoding="utf-8")
        os.link(temporary_output, arguments.output)
    except (baseline.AnalysisError, OSError, UnicodeError) as error:
        print(f"analysis failed: {error}", file=sys.stderr)
        return 2
    finally:
        temporary_output.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
