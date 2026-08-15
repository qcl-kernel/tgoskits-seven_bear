#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Validate RT-Thread or FreeRTOS native-baseline evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


RTOS_SPECS = {
    "rt-thread": {
        "display_name": "RT-Thread v5.2.2",
        "config": {
            "schema": "1",
            "os": "rt-thread",
            "rtthread_version": "5.2.2",
            "board": "qemu_virt_aarch64",
            "cpu_model": "cortex-a53",
            "cpu_count": "1",
            "qemu_icount": "false",
            "period_us": "1000",
            "samples": "10000",
            "warmup": "100",
            "benchmark_priority": "1",
            "stress_priority": "20",
            "clock_hz": "62500000",
            "ticks_per_sec": "1000",
        },
        "accounting": "rt-thread-tick-hook",
        "repositories": {
            "rt-thread": "ddf52e2cdd977f14fc04035c88672ac204aec713",
        },
        "method": {
            "period": "1 ms RT-Thread architected-timer tick",
            "callback": "RT-Thread tick hook in timer interrupt context",
            "load": "RT-Thread tick-hook current-thread accounting",
        },
    },
    "freertos": {
        "display_name": "FreeRTOS AArch64",
        "config": {
            "schema": "1",
            "os": "freertos",
            "kernel_version": "V11.1.0+",
            "kernel_commit": "f1043c49d59944353291654c175852bd17b34f99",
            "board": "qemu_aarch64_virt",
            "cpu_model": "cortex-a53",
            "cpu_count": "1",
            "qemu_icount": "false",
            "period_us": "1000",
            "samples": "10000",
            "warmup": "100",
            "benchmark_priority": "7",
            "stress_priority": "1",
            "clock_hz": "62500000",
            "ticks_per_sec": "1000",
        },
        "accounting": "freertos-runtime-counter",
        "repositories": {
            "freertos-over-bao": "cb9112f982c2768872536b811e013254d0184811",
            "FreeRTOS-Kernel": "f1043c49d59944353291654c175852bd17b34f99",
            "bao-baremetal-runtime": "c50068084212ef33115a4c05f9f714cc637f30bc",
        },
        "method": {
            "period": "1 ms FreeRTOS architected virtual-timer tick",
            "callback": "FreeRTOS application tick hook in timer interrupt context",
            "load": "FreeRTOS 64-bit task run-time counter accounting",
        },
    },
}

EXPECTED_METRICS = {"periodic_wake_lateness", "timer_to_task_dispatch"}
SAMPLE_COUNT = 10_000
WARMUP_COUNT = 100
STAT_FIELDS = (
    "min_ns",
    "mean_ns",
    "p50_ns",
    "p90_ns",
    "p99_ns",
    "p999_ns",
    "max_ns",
)


class AnalysisError(ValueError):
    """Raised when evidence violates the native-baseline contract."""


def parse_record(line: str, marker: str) -> dict[str, str] | None:
    """Parse one exact marker followed by space-separated key/value fields."""
    # Bao's PL011 initialization can emit one leading NUL before the first
    # application record. Preserve it in the raw log, but do not treat it as
    # part of the machine-readable marker.
    stripped = line.strip().lstrip("\x00")
    prefix = f"{marker} "
    if not stripped.startswith(prefix):
        return None
    fields: dict[str, str] = {}
    for token in stripped.removeprefix(prefix).split():
        key, separator, value = token.partition("=")
        if not separator or not key or not value:
            raise AnalysisError(f"{marker}: malformed field {token!r}")
        if key in fields:
            raise AnalysisError(f"{marker}: duplicate field {key!r}")
        fields[key] = value
    return fields


def select_records(lines: Sequence[str], marker: str) -> list[dict[str, str]]:
    """Return every parsed record for a marker."""
    return [record for line in lines if (record := parse_record(line, marker))]


def require_one(lines: Sequence[str], marker: str) -> dict[str, str]:
    """Return a marker's unique record."""
    records = select_records(lines, marker)
    if len(records) != 1:
        raise AnalysisError(f"expected one {marker} record, found {len(records)}")
    return records[0]


def parse_nonnegative(record: dict[str, str], field: str, marker: str) -> int:
    """Parse a required non-negative decimal integer."""
    try:
        value = int(record[field], 10)
    except KeyError as error:
        raise AnalysisError(f"{marker}: missing field {field!r}") from error
    except ValueError as error:
        raise AnalysisError(f"{marker}: {field!r} is not an integer") from error
    if value < 0:
        raise AnalysisError(f"{marker}: {field!r} must be non-negative")
    return value


def parse_integer(record: dict[str, str], field: str, marker: str) -> int:
    """Parse a required signed decimal integer."""
    try:
        return int(record[field], 10)
    except KeyError as error:
        raise AnalysisError(f"{marker}: missing field {field!r}") from error
    except ValueError as error:
        raise AnalysisError(f"{marker}: {field!r} is not an integer") from error


def normalize_record(record: dict[str, str]) -> dict[str, object]:
    """Convert obvious booleans and integers while preserving labels."""
    normalized: dict[str, object] = {}
    for key, value in record.items():
        if value == "true":
            normalized[key] = True
        elif value == "false":
            normalized[key] = False
        else:
            try:
                normalized[key] = int(value, 10)
            except ValueError:
                normalized[key] = value
    return normalized


def validate_config(
    record: dict[str, str], workload: str, spec: dict[str, object]
) -> dict[str, object]:
    """Validate the fixed RTOS/platform configuration."""
    expected_config = spec["config"]
    assert isinstance(expected_config, dict)
    for field, expected in expected_config.items():
        if record.get(field) != expected:
            raise AnalysisError(
                f"RTOS_BASELINE_CONFIG: {field} must be {expected!r}, "
                f"got {record.get(field)!r}"
            )
    if record.get("workload") != workload:
        raise AnalysisError("RTOS_BASELINE_CONFIG: workload does not match the run")
    return normalize_record(record)


def validate_workload_ready(record: dict[str, str], workload: str) -> None:
    """Prove the selected workload started before the measurement."""
    if record.get("schema") != "1" or record.get("kind") != workload:
        raise AnalysisError("RTOS_BASELINE_WORKLOAD_READY: wrong schema or workload")
    if record.get("verified") != "true":
        raise AnalysisError("RTOS_BASELINE_WORKLOAD_READY: workload was not verified")
    benchmark_priority = parse_integer(
        record, "benchmark_priority", "RTOS_BASELINE_WORKLOAD_READY"
    )
    stress_priority = parse_integer(
        record, "stress_priority", "RTOS_BASELINE_WORKLOAD_READY"
    )
    blocks = parse_nonnegative(record, "blocks", "RTOS_BASELINE_WORKLOAD_READY")
    if workload == "cpu-stress":
        if record.get("lower_priority") != "true" or blocks == 0:
            raise AnalysisError("stress workload did not prove lower-priority execution")
        if benchmark_priority == stress_priority:
            raise AnalysisError("benchmark and stress priorities must differ")
    elif record.get("lower_priority") != "false" or blocks != 0:
        raise AnalysisError("idle run unexpectedly reports a stress workload")


def validate_results(
    records: Sequence[dict[str, str]], workload: str
) -> dict[str, dict[str, object]]:
    """Validate the two aggregate latency distributions."""
    if len(records) != len(EXPECTED_METRICS):
        raise AnalysisError(
            f"expected {len(EXPECTED_METRICS)} result records, found {len(records)}"
        )
    results: dict[str, dict[str, object]] = {}
    observed_duration: int | None = None
    for record in records:
        metric = record.get("metric")
        if metric not in EXPECTED_METRICS or metric in results:
            raise AnalysisError(f"unexpected or duplicate metric {metric!r}")
        if record.get("schema") != "1" or record.get("workload") != workload:
            raise AnalysisError(f"{metric}: wrong schema or workload")
        if record.get("unit") != "ns":
            raise AnalysisError(f"{metric}: unit must be ns")
        if parse_nonnegative(record, "count", metric) != SAMPLE_COUNT:
            raise AnalysisError(f"{metric}: count must be {SAMPLE_COUNT}")
        statistics = [parse_nonnegative(record, field, metric) for field in STAT_FIELDS]
        minimum, mean, p50, p90, p99, p999, maximum = statistics
        if not minimum <= p50 <= p90 <= p99 <= p999 <= maximum:
            raise AnalysisError(f"{metric}: percentiles are not monotonic")
        if not minimum <= mean <= maximum:
            raise AnalysisError(f"{metric}: mean is outside the observed range")
        expected_duration = parse_nonnegative(record, "expected_duration_us", metric)
        actual_duration = parse_nonnegative(record, "actual_duration_us", metric)
        if expected_duration != SAMPLE_COUNT * 1000:
            raise AnalysisError(f"{metric}: expected duration is not ten seconds")
        if actual_duration < expected_duration:
            raise AnalysisError(f"{metric}: actual duration is shorter than requested")
        if observed_duration is None:
            observed_duration = actual_duration
        elif actual_duration != observed_duration:
            raise AnalysisError("latency metrics report different run durations")
        results[metric] = normalize_record(record)
    if set(results) != EXPECTED_METRICS:
        raise AnalysisError("result metrics are incomplete")
    return results


def validate_load(
    record: dict[str, str], workload: str, spec: dict[str, object]
) -> dict[str, object]:
    """Validate scheduler-accounted idle/stress execution."""
    if record.get("schema") != "1" or record.get("workload") != workload:
        raise AnalysisError("RTOS_BASELINE_LOAD: wrong schema or workload")
    if record.get("verified") != "true":
        raise AnalysisError("RTOS_BASELINE_LOAD: load verification failed")
    if record.get("accounting") != spec["accounting"]:
        raise AnalysisError("RTOS_BASELINE_LOAD: unexpected accounting method")
    if parse_nonnegative(record, "window_duration_us", "RTOS_BASELINE_LOAD") < 10_000_000:
        raise AnalysisError("RTOS_BASELINE_LOAD: load window is too short")
    fields = {
        field: parse_nonnegative(record, field, "RTOS_BASELINE_LOAD")
        for field in (
            "cpu_non_idle_permille",
            "cpu_idle_permille",
            "benchmark_permille",
            "stress_permille",
        )
    }
    if any(value > 1000 for value in fields.values()):
        raise AnalysisError("RTOS_BASELINE_LOAD: a CPU share exceeds 1000 permille")
    accounted = fields["cpu_non_idle_permille"] + fields["cpu_idle_permille"]
    if not 995 <= accounted <= 1000:
        raise AnalysisError("RTOS_BASELINE_LOAD: CPU accounting is incomplete")
    if (
        fields["benchmark_permille"] == 0
        and record.get("accounting") != "rt-thread-tick-hook"
    ):
        raise AnalysisError("RTOS_BASELINE_LOAD: benchmark execution was not measured")
    stress_blocks = parse_nonnegative(record, "stress_blocks", "RTOS_BASELINE_LOAD")
    stress_rate = parse_nonnegative(
        record, "stress_blocks_per_second", "RTOS_BASELINE_LOAD"
    )
    stress_checksum = parse_nonnegative(
        record, "stress_checksum", "RTOS_BASELINE_LOAD"
    )
    if workload == "cpu-stress":
        if (
            fields["stress_permille"] < 900
            or fields["cpu_non_idle_permille"] < 900
            or stress_blocks == 0
            or stress_rate == 0
            or stress_checksum == 0
        ):
            raise AnalysisError("RTOS_BASELINE_LOAD: CPU stress was not sustained")
    elif (
        fields["stress_permille"] != 0
        or stress_blocks != 0
        or stress_rate != 0
        or stress_checksum != 0
        or fields["cpu_idle_permille"] < 900
    ):
        raise AnalysisError("RTOS_BASELINE_LOAD: idle workload was not sustained")
    return normalize_record(record)


def validate_complete(record: dict[str, str], workload: str) -> dict[str, object]:
    """Validate the terminal success marker and miss bounds."""
    if (
        record.get("schema") != "1"
        or record.get("workload") != workload
        or record.get("status") != "pass"
    ):
        raise AnalysisError("RTOS_BASELINE_COMPLETE: unsuccessful run")
    timer_misses = parse_nonnegative(record, "timer_misses", "RTOS_BASELINE_COMPLETE")
    warmup_misses = parse_nonnegative(
        record, "warmup_timer_misses", "RTOS_BASELINE_COMPLETE"
    )
    if timer_misses > SAMPLE_COUNT or warmup_misses > WARMUP_COUNT - 1:
        raise AnalysisError("RTOS_BASELINE_COMPLETE: invalid timer miss count")
    if parse_nonnegative(record, "early_wakes", "RTOS_BASELINE_COMPLETE") != 0:
        raise AnalysisError("RTOS_BASELINE_COMPLETE: early wake was observed")
    return normalize_record(record)


def sha256(path: Path) -> str:
    """Return a file's lowercase SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path, logical_path: str) -> dict[str, object]:
    """Describe a required evidence artifact."""
    if not path.is_file():
        raise AnalysisError(f"missing artifact: {path}")
    return {
        "path": logical_path,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def command_output(command: Sequence[str]) -> str:
    """Run a metadata-only command and return its first non-empty line."""
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise AnalysisError(f"metadata command failed: {' '.join(command)}") from error
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AnalysisError(f"metadata command produced no output: {' '.join(command)}")
    return lines[0]


def git_index_path(repository: Path) -> Path:
    """Resolve a checkout or submodule's active Git index."""
    index = Path(command_output(["git", "-C", str(repository), "rev-parse", "--git-path", "index"]))
    return index if index.is_absolute() else repository / index


def repository_paths(kind: str, source_root: Path) -> dict[str, Path]:
    """Return the build-relevant repository paths for one RTOS source root."""
    if kind == "rt-thread":
        return {"rt-thread": source_root}
    return {
        "freertos-over-bao": source_root,
        "FreeRTOS-Kernel": source_root / "src" / "freertos",
        "bao-baremetal-runtime": source_root / "src" / "baremetal-runtime",
    }


def load_source_provenance(
    provenance_path: Path,
    source_root: Path,
    raw_log: Path,
    kind: str,
    spec: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate a bounded post-run clean-source attestation."""
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as error:
        raise AnalysisError("could not read source provenance") from error
    if not isinstance(provenance, dict) or provenance.get("schema_version") != 1:
        raise AnalysisError("source provenance has the wrong schema")
    if provenance.get("kind") != kind:
        raise AnalysisError("source provenance belongs to another RTOS")
    if Path(str(provenance.get("source_root", ""))).resolve() != source_root.resolve():
        raise AnalysisError("source provenance belongs to another checkout")
    repositories = provenance.get("repositories")
    expected_commits = spec["repositories"]
    if not isinstance(repositories, dict) or not isinstance(expected_commits, dict):
        raise AnalysisError("source provenance repositories are malformed")
    if set(repositories) != set(expected_commits):
        raise AnalysisError("source provenance repository set is incomplete")
    paths = repository_paths(kind, source_root)
    for name, expected_commit in expected_commits.items():
        record = repositories.get(name)
        if not isinstance(record, dict):
            raise AnalysisError(f"source provenance record is invalid: {name}")
        if record.get("commit") != expected_commit or record.get("worktree") != "clean":
            raise AnalysisError(f"source provenance identity is invalid: {name}")
        repository = paths[name]
        if command_output(["git", "-C", str(repository), "rev-parse", "HEAD"]) != expected_commit:
            raise AnalysisError(f"source identity changed after capture: {name}")
        expected_index = artifact(git_index_path(repository), f"{name}/.git/index")
        if record.get("git_index") != expected_index:
            raise AnalysisError(f"source Git index changed after capture: {name}")
    if provenance_path.stat().st_mtime < raw_log.stat().st_mtime:
        raise AnalysisError("source provenance predates the measured run")
    return provenance, artifact(provenance_path, provenance_path.name)


def host_cpu_name() -> str:
    """Return a useful host CPU label when available."""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return platform.machine()
    for preferred in ("model name", "hardware", "processor"):
        for line in cpuinfo.splitlines():
            field, separator, value = line.partition(":")
            if separator and field.strip().lower() == preferred:
                return value.strip()
    return platform.machine()


def tool_metadata(cross_compile: str) -> dict[str, str]:
    """Record the QEMU and cross-compiler implementations."""
    qemu = shutil.which("qemu-system-aarch64")
    compiler = shutil.which(f"{cross_compile}gcc") or f"{cross_compile}gcc"
    if qemu is None:
        raise AnalysisError("qemu-system-aarch64 is not available")
    return {
        "qemu": command_output([qemu, "--version"]),
        "compiler": command_output([compiler, "--version"]),
        "python": platform.python_version(),
        "host_kernel": platform.release(),
        "host_cpu": host_cpu_name(),
    }


def analyze(args: argparse.Namespace) -> dict[str, object]:
    """Validate one complete run and assemble self-contained evidence."""
    spec = RTOS_SPECS[args.rtos]
    raw_text = args.raw_log.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.splitlines()
    if select_records(lines, "RTOS_BASELINE_FATAL"):
        raise AnalysisError("console contains RTOS_BASELINE_FATAL")
    config = validate_config(require_one(lines, "RTOS_BASELINE_CONFIG"), args.workload, spec)
    validate_workload_ready(require_one(lines, "RTOS_BASELINE_WORKLOAD_READY"), args.workload)
    results = validate_results(select_records(lines, "RTOS_BASELINE_RESULT"), args.workload)
    load = validate_load(require_one(lines, "RTOS_BASELINE_LOAD"), args.workload, spec)
    completion = validate_complete(require_one(lines, "RTOS_BASELINE_COMPLETE"), args.workload)
    source, provenance_artifact = load_source_provenance(
        args.source_provenance, args.source_root, args.raw_log, args.rtos, spec
    )
    display_name = spec["display_name"]
    method = dict(spec["method"])
    method.update(
        {
            "clock": "AArch64 architected counter at 62.5 MHz",
            "wake_lateness": "task observation minus the armed tick deadline",
            "dispatch_latency": "task observation minus tick-hook timestamp",
            "percentile": "nearest-rank over 10,000 samples",
            "measurement_logging": "no console output during sample collection",
        }
    )
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": f"native {display_name} on QEMU; no AxVisor or guest virtualization",
        "workload": args.workload,
        "configuration": config,
        "metrics": results,
        "load": load,
        "completion": completion,
        "source": source,
        "tools": tool_metadata(args.cross_compile),
        "artifacts": {
            "raw_console": artifact(args.raw_log, args.raw_log.name),
            "build_log": artifact(args.build_log, args.build_log.name),
            "configuration": artifact(args.configuration, args.configuration.name),
            "elf": artifact(args.elf, args.elf.name),
            "binary": artifact(args.binary, args.binary.name),
            "qemu_command": artifact(args.qemu_command, args.qemu_command.name),
            "source_provenance": provenance_artifact,
        },
        "method": method,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_log", type=Path)
    parser.add_argument("--rtos", required=True, choices=tuple(RTOS_SPECS))
    parser.add_argument("--workload", required=True, choices=("idle", "cpu-stress"))
    parser.add_argument("--build-log", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--qemu-command", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--source-provenance", required=True, type=Path)
    parser.add_argument("--cross-compile", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    temporary_output = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        if args.output.exists():
            raise AnalysisError(f"refusing to overwrite evidence: {args.output}")
        rendered = json.dumps(analyze(args), indent=2, sort_keys=True, allow_nan=False) + "\n"
        temporary_output.write_text(rendered, encoding="utf-8")
        os.link(temporary_output, args.output)
    except (AnalysisError, OSError, UnicodeError) as error:
        print(f"analysis failed: {error}", file=sys.stderr)
        return 2
    finally:
        temporary_output.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
