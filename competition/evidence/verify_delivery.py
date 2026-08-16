#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Fail closed when compact competition delivery evidence is inconsistent."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from delivery_support import (
    ISOLATION_EVIDENCE,
    RT_FORMAL_EVIDENCE,
    RTOS_EVIDENCE,
    EvidenceVerificationError,
    decode_log,
    load_json_object,
    read_checksum_sidecar,
    require_commit,
    require_equal,
    require_list,
    require_mapping,
    require_nonnegative_integer,
    require_object,
    require_positive_integer,
    require_sha256,
    require_string,
    require_successful_runner_log,
    safe_relative_file,
    sha256_file,
    unique_line_containing,
    validate_relative_path,
    verify_checksum_manifest,
    verify_source_commit,
    verify_source_inputs,
)


@dataclass(frozen=True)
class FaultExpectation:
    """Expected reliability counters for one deterministic RTOS profile."""

    duplicates: int
    dropped_acks: int
    retransmissions: int
    recoveries: int


@dataclass(frozen=True)
class EvidenceSetResult:
    """Verification result for one independently checksummed evidence set."""

    source_commit: str
    checked_files: int
    qemu_logs: int


@dataclass(frozen=True)
class DeliveryVerification:
    """Combined result printed by the submission preflight command."""

    source_commit: str
    formal_source_commit: str | None
    evidence_sets: int
    checked_files: int
    qemu_logs: int
    archive_files: int


@dataclass(frozen=True)
class FormalEvidenceResult:
    """Verified formal RT campaign and its preregistered source boundary."""

    source_commit: str
    source_tree: str
    source_inputs: dict[str, tuple[str, int]]
    checked_files: int
    archive_files: int


EXPECTED_RTOS_RUNS = {
    ("rt-thread", "normal"): FaultExpectation(0, 0, 0, 0),
    ("rt-thread", "ack-loss"): FaultExpectation(20, 20, 20, 20),
    ("freertos", "normal"): FaultExpectation(0, 0, 0, 0),
    ("freertos", "ack-loss"): FaultExpectation(20, 20, 20, 20),
}
EXPECTED_ISOLATION_MARKERS = (
    "VM2_VIRTIO_NET_TX bytes=65536 checksum=0x7f8000",
    "VM1_VIRTIO_NET_RX bytes=65536 checksum=0x7f8000 "
    "peer=10.0.2.16:49152",
    "VM3_VIRTIO_NET_ISOLATED_PASS default_routes=0 probes=100 "
    "tx_frames=100 target=10.0.2.255:5002",
    "VM1_VIRTIO_NET_ISOLATION_PASS "
    "received_cross_segment_probes=0 observation_ms=7000",
    "VM1_VIRTIO_NET_PASS",
    "VM2_VIRTIO_NET_PASS",
    "VM3_VIRTIO_NET_PASS",
)
EXPECTED_FORMAL_METRICS = (
    "dispatch_latency",
    "emulated_irq_response",
    "periodic_jitter",
    "virtual_timer_injection_to_guest_irq",
)
EXPECTED_ARCHIVE_NAME = "axvisor-rt-formal-20260816-77704718a.tar.gz"
MAX_UNCOMPRESSED_LOG_BYTES = 16 * 1024 * 1024


def verify_repository_delivery(repository: Path) -> DeliveryVerification:
    """Verify tracked compact evidence and its source-commit freshness."""
    repository = repository.resolve()
    report = verify_evidence_sets(
        repository / RTOS_EVIDENCE,
        repository / ISOLATION_EVIDENCE,
        repository / RT_FORMAL_EVIDENCE,
    )
    verify_source_commit(repository, report.source_commit)
    formal = verify_formal_realtime(repository / RT_FORMAL_EVIDENCE)
    verify_source_inputs(
        repository,
        formal.source_commit,
        formal.source_tree,
        formal.source_inputs,
    )
    return report


def verify_evidence_sets(
    rtos_evidence: Path,
    isolation_evidence: Path,
    formal_evidence: Path | None = None,
) -> DeliveryVerification:
    """Verify compact QEMU evidence and, when supplied, formal RT evidence."""
    rtos = verify_rtos_guest_ivc(rtos_evidence)
    isolation = verify_network_isolation(isolation_evidence)
    if rtos.source_commit != isolation.source_commit:
        raise EvidenceVerificationError(
            "evidence source commits differ: "
            f"RTOS={rtos.source_commit}, isolation={isolation.source_commit}"
        )
    formal = (
        None
        if formal_evidence is None
        else verify_formal_realtime(formal_evidence)
    )
    return DeliveryVerification(
        source_commit=rtos.source_commit,
        formal_source_commit=None if formal is None else formal.source_commit,
        evidence_sets=2 if formal is None else 3,
        checked_files=(
            rtos.checked_files
            + isolation.checked_files
            + (0 if formal is None else formal.checked_files)
        ),
        qemu_logs=rtos.qemu_logs + isolation.qemu_logs,
        archive_files=0 if formal is None else formal.archive_files,
    )


def verify_formal_realtime(directory: Path) -> FormalEvidenceResult:
    """Verify the preregistered five-pair board campaign and both soak runs."""
    checked_files = verify_checksum_manifest(directory, "SHA256SUMS")
    preregistration = load_json_object(directory / "preregistration.json")
    source_commit, source_tree, source_inputs = verify_formal_preregistration(
        preregistration
    )
    archive_entries = verify_formal_archive(
        directory,
        source_commit,
    )

    receipts: dict[tuple[str, int | None, str], dict[str, tuple[str, str, int]]] = {}
    comparisons: dict[int, dict[str, tuple[str, str]]] = {}
    for pair in range(1, 6):
        for profile in ("shared", "partitioned"):
            relative = f"pair-{pair}/{profile}/receipt.json"
            receipts[("pair", pair, profile)] = verify_formal_receipt(
                directory,
                relative,
                phase="pair",
                pair=pair,
                profile=profile,
                source_commit=source_commit,
                source_tree=source_tree,
                archive_entries=archive_entries,
            )
        comparisons[pair] = verify_formal_comparison(
            directory / f"pair-{pair}" / "comparison.json",
            pair,
            receipts[("pair", pair, "shared")],
            receipts[("pair", pair, "partitioned")],
        )

    for profile in ("shared", "partitioned"):
        relative = f"soak/{profile}/receipt.json"
        receipts[("soak", None, profile)] = verify_formal_receipt(
            directory,
            relative,
            phase="soak",
            pair=None,
            profile=profile,
            source_commit=source_commit,
            source_tree=source_tree,
            archive_entries=archive_entries,
        )

    summary = load_json_object(directory / "campaign-summary.json")
    verify_formal_campaign_summary(summary, receipts, comparisons)
    verify_formal_compact_archive_bindings(directory, archive_entries)
    preregistration_digest = read_checksum_sidecar(
        directory / "preregistration.sha256",
        "preregistration.json",
    )
    if preregistration_digest != sha256_file(directory / "preregistration.json"):
        raise EvidenceVerificationError(
            "preregistration sidecar does not match preregistration.json"
        )
    return FormalEvidenceResult(
        source_commit=source_commit,
        source_tree=source_tree,
        source_inputs=source_inputs,
        checked_files=checked_files,
        archive_files=len(archive_entries),
    )


def verify_formal_preregistration(
    preregistration: dict[str, object],
) -> tuple[str, str, dict[str, tuple[str, int]]]:
    """Validate the immutable campaign order, thresholds, and source inputs."""
    context = "formal preregistration"
    require_equal(preregistration, "schema_version", 2, context)
    source = require_object(preregistration, "source", context)
    source_commit = require_commit(source, "commit", "formal source")
    source_tree = require_commit(source, "tree", "formal source")
    require_equal(source, "clean_worktree_required", True, "formal source")

    acceptance = require_object(preregistration, "acceptance", context)
    for key, expected in {
        "pair_count": 5,
        "direct_irq_max_improvement_target_percent": 10.0,
        "direct_irq_max_must_improve_in_at_least_pairs": 4,
        "direct_irq_p99_non_regression_limit_percent": 5.0,
        "harvest_each_half_before_next_boot": True,
        "linux_restore_required": True,
        "snapshot_fsck": "clean",
    }.items():
        require_equal(acceptance, key, expected, "formal acceptance")

    expected_pair_order = [
        {
            "pair": pair,
            "order": (
                ["shared", "partitioned"]
                if pair % 2 == 1
                else ["partitioned", "shared"]
            ),
        }
        for pair in range(1, 6)
    ]
    require_equal(
        preregistration,
        "pair_order",
        expected_pair_order,
        context,
    )
    require_equal(
        preregistration,
        "soak_order",
        ["shared", "partitioned"],
        context,
    )

    measurement = require_object(preregistration, "measurement", context)
    pair_measurement = require_object(measurement, "pair", "formal measurement")
    for key, expected in {
        "iterations_per_metric": 10000,
        "period_us": 1000,
        "guest_vcpus": 2,
        "measurement_cpu": 0,
        "stress_cpu": 1,
        "workload": "idle",
    }.items():
        require_equal(pair_measurement, key, expected, "formal pair measurement")
    soak_measurement = require_object(measurement, "soak", "formal measurement")
    for key, expected in {
        "iterations_per_metric": 10000,
        "period_us": 90000,
        "minimum_elapsed_ns": 1800000000000,
        "guest_vcpus": 2,
        "measurement_cpu": 0,
        "stress_cpu": 1,
        "workload": "idle",
    }.items():
        require_equal(soak_measurement, key, expected, "formal soak measurement")

    board = require_object(preregistration, "board", context)
    require_equal(board, "hardware_id", "bf61f4d4a1d994ad", "formal board")
    require_equal(board, "type", "OrangePi-5-Plus", "formal board")

    artifacts = require_object(preregistration, "artifacts", context)
    if len(artifacts) < 8:
        raise EvidenceVerificationError(
            "formal preregistration omits required artifact identities"
        )
    for name, value in artifacts.items():
        artifact_context = f"formal artifact {name}"
        artifact = require_mapping(value, artifact_context)
        require_string(artifact, "path", artifact_context)
        require_sha256(artifact, "sha256", artifact_context)
        require_positive_integer(artifact, "size_bytes", artifact_context)

    raw_inputs = require_object(preregistration, "source_inputs", context)
    if len(raw_inputs) < 30:
        raise EvidenceVerificationError(
            "formal preregistration source input set is unexpectedly incomplete"
        )
    source_inputs: dict[str, tuple[str, int]] = {}
    for relative, value in raw_inputs.items():
        input_context = f"formal source input {relative}"
        validate_relative_path(relative, "formal source input")
        source_input = require_mapping(value, input_context)
        require_equal(source_input, "path", relative, input_context)
        digest = require_sha256(source_input, "sha256", input_context)
        size = require_positive_integer(source_input, "size_bytes", input_context)
        source_inputs[relative] = (digest, size)
    for required in (
        "scripts/benchmark/axvisor-rt/formal_campaign.py",
        "scripts/benchmark/axvisor-rt/formal_campaign_contract.py",
        "scripts/benchmark/axvisor-rt/formal_campaign_receipt.py",
        "scripts/benchmark/axvisor-rt/run-formal-campaign.sh",
    ):
        if required not in source_inputs:
            raise EvidenceVerificationError(
                f"formal preregistration is missing source input: {required}"
            )
    return source_commit, source_tree, source_inputs


def verify_formal_archive(
    directory: Path,
    source_commit: str,
) -> dict[str, tuple[str, int]]:
    """Validate the external deterministic archive sidecar and file manifest."""
    expected_archive_name = (
        f"axvisor-rt-formal-20260816-{source_commit[:9]}.tar.gz"
    )
    if expected_archive_name != EXPECTED_ARCHIVE_NAME:
        raise EvidenceVerificationError(
            f"unexpected formal archive name: {expected_archive_name}"
        )
    read_checksum_sidecar(directory / "archive.sha256", expected_archive_name)

    manifest = load_json_object(directory / "archive.manifest.json")
    require_equal(manifest, "schema_version", 1, "formal archive manifest")
    require_equal(
        manifest,
        "source_root",
        f"rt-formal-20260816-{source_commit}",
        "formal archive manifest",
    )
    declared_count = require_positive_integer(
        manifest,
        "file_count",
        "formal archive manifest",
    )
    declared_bytes = require_positive_integer(
        manifest,
        "payload_bytes",
        "formal archive manifest",
    )
    files = require_list(manifest, "files", "formal archive manifest")
    if declared_count != len(files) or declared_count < 100:
        raise EvidenceVerificationError(
            "formal archive file count is inconsistent or incomplete"
        )

    entries: dict[str, tuple[str, int]] = {}
    payload_bytes = 0
    for index, value in enumerate(files):
        context = f"formal archive file {index}"
        entry = require_mapping(value, context)
        relative = require_string(entry, "path", context)
        validate_relative_path(relative, "formal archive")
        if relative in entries:
            raise EvidenceVerificationError(
                f"duplicate formal archive path: {relative}"
            )
        digest = require_sha256(entry, "sha256", context)
        size = require_nonnegative_integer(entry, "bytes", context)
        mode = require_string(entry, "mode", context)
        if mode not in {"0644", "0755"}:
            raise EvidenceVerificationError(
                f"unexpected formal archive mode for {relative}: {mode}"
            )
        entries[relative] = (digest, size)
        payload_bytes += size
    if payload_bytes != declared_bytes:
        raise EvidenceVerificationError(
            "formal archive payload byte count differs from its entries"
        )
    return entries


def verify_formal_receipt(
    directory: Path,
    relative: str,
    *,
    phase: str,
    pair: int | None,
    profile: str,
    source_commit: str,
    source_tree: str,
    archive_entries: dict[str, tuple[str, int]],
) -> dict[str, tuple[str, str, int]]:
    """Validate one board receipt and bind all referenced raw artifacts."""
    receipt = load_json_object(directory / relative)
    context = f"formal receipt {relative}"
    require_equal(receipt, "schema_version", 1, context)
    slot = require_object(receipt, "slot", context)
    require_equal(slot, "phase", phase, context)
    require_equal(slot, "pair", pair, context)
    require_equal(slot, "profile", profile, context)
    source = require_object(receipt, "source", context)
    require_equal(source, "commit", source_commit, context)
    require_equal(source, "tree", source_tree, context)
    board = require_object(receipt, "board", context)
    require_equal(board, "board_id", "bf61f4d4a1d994ad", context)
    require_equal(board, "type", "OrangePi-5-Plus", context)

    evidence = require_object(receipt, "evidence", context)
    expected_names = {
        "console_log",
        "guest_irq",
        "harvest_log",
        "host_trace",
        "raw",
        "stage_log",
        "summary",
    }
    if set(evidence) != expected_names:
        raise EvidenceVerificationError(
            f"{context} has an incomplete evidence contract"
        )
    expected_prefix = (
        f"pair-{pair}/{profile}/attempts/"
        if phase == "pair"
        else f"soak/{profile}/attempts/"
    )
    identities: dict[str, tuple[str, str, int]] = {}
    for name, value in evidence.items():
        artifact_context = f"{context} evidence {name}"
        artifact = require_mapping(value, artifact_context)
        path = require_string(artifact, "path", artifact_context)
        if not path.startswith(expected_prefix):
            raise EvidenceVerificationError(
                f"{artifact_context} is outside its campaign slot: {path}"
            )
        validate_relative_path(path, "formal receipt evidence")
        digest = require_sha256(artifact, "sha256", artifact_context)
        size = require_positive_integer(artifact, "size_bytes", artifact_context)
        if archive_entries.get(path) != (digest, size):
            raise EvidenceVerificationError(
                f"formal receipt does not match archive manifest: {path}"
            )
        identities[name] = (path, digest, size)
    return identities


def verify_formal_comparison(
    path: Path,
    pair: int,
    shared_receipt: dict[str, tuple[str, str, int]],
    partitioned_receipt: dict[str, tuple[str, str, int]],
) -> dict[str, tuple[str, str]]:
    """Validate one short-run comparison against both run receipts."""
    comparison = load_json_object(path)
    context = f"formal pair {pair} comparison"
    require_equal(comparison, "schema_version", 1, context)
    pair_data = require_object(comparison, "pair", context)
    require_equal(pair_data, "iterations_per_metric", 10000, context)
    require_equal(pair_data, "workload", "idle", context)
    interference = require_object(
        pair_data,
        "controlled_interference",
        context,
    )
    require_equal(interference, "placement_and_coverage_validated", True, context)
    require_equal(interference, "shared_requested_pcpu", 1, context)
    require_equal(interference, "partitioned_requested_pcpu", 3, context)

    assessment = require_object(comparison, "assessment", context)
    for key, expected in {
        "direct_irq_max_improved_in_this_pair": True,
        "primary_guest_max_improved_in_this_pair": True,
        "primary_guest_p99_within_non_regression_limit": True,
        "m2_exit_gate_met": False,
    }.items():
        require_equal(assessment, key, expected, context)
    verify_formal_metrics(require_object(comparison, "metrics", context), context)

    raw_inputs: dict[str, tuple[str, str]] = {}
    for profile, receipt in (
        ("shared", shared_receipt),
        ("partitioned", partitioned_receipt),
    ):
        raw = require_object(pair_data, f"{profile}_raw", context)
        path_value = require_string(raw, "path", context)
        digest = require_sha256(raw, "sha256", context)
        receipt_path, receipt_digest, _ = receipt["raw"]
        if not path_value.endswith(receipt_path) or digest != receipt_digest:
            raise EvidenceVerificationError(
                f"{context} {profile} raw input differs from its receipt"
            )
        raw_inputs[profile] = (receipt_path, receipt_digest)
    return raw_inputs


def verify_formal_metrics(
    metrics: dict[str, object],
    context: str,
    *,
    aggregate: bool = False,
) -> None:
    """Require all four primary metrics to satisfy max and p99 contracts."""
    if set(metrics) != set(EXPECTED_FORMAL_METRICS):
        raise EvidenceVerificationError(
            f"{context} metric set differs from the formal contract"
        )
    for metric_name in EXPECTED_FORMAL_METRICS:
        metric = require_mapping(metrics[metric_name], f"{context} {metric_name}")
        maximum = require_object(metric, "max", f"{context} {metric_name}")
        p99 = require_object(metric, "p99", f"{context} {metric_name}")
        if aggregate:
            require_equal(maximum, "improved_pair_count", 5, context)
            require_equal(maximum, "target_pair_count", 5, context)
            require_equal(
                maximum,
                "worst_of_runs_meets_ten_percent_target",
                True,
                context,
            )
            require_equal(p99, "non_regression_pair_count", 5, context)
        else:
            require_equal(maximum, "improved", True, context)
            require_equal(maximum, "meets_ten_percent_target", True, context)
            require_equal(p99, "within_non_regression_limit", True, context)


def verify_formal_campaign_summary(
    summary: dict[str, object],
    receipts: dict[tuple[str, int | None, str], dict[str, tuple[str, str, int]]],
    comparisons: dict[int, dict[str, tuple[str, str]]],
) -> None:
    """Require the aggregate M2 decision and its pair/soak provenance."""
    context = "formal campaign summary"
    require_equal(summary, "schema_version", 1, context)
    assessment = require_object(summary, "assessment", context)
    for key, expected in {
        "m2_exit_gate_met": True,
        "five_pair_matrix_gate_met": True,
        "direct_irq_max_direction_gate_met": True,
        "direct_irq_max_target_pairs": 5,
        "direct_irq_p99_all_pairs": True,
        "direct_irq_worst_of_runs_gate_met": True,
        "primary_guest_max_direction_gate_met": True,
        "primary_guest_p99_all_pairs": True,
        "primary_guest_worst_of_runs_gate_met": True,
        "soak_evidence_collected": True,
    }.items():
        require_equal(assessment, key, expected, context)

    campaign = require_object(summary, "campaign", context)
    require_equal(campaign, "pair_count", 5, context)
    require_equal(campaign, "iterations_per_metric", 10000, context)
    require_equal(campaign, "workload", "idle", context)
    inputs = require_list(campaign, "inputs", context)
    if len(inputs) != 5:
        raise EvidenceVerificationError("formal campaign must contain five pairs")
    for index, value in enumerate(inputs, start=1):
        pair_input = require_mapping(value, f"{context} pair {index}")
        require_equal(pair_input, "pair", index, context)
        for profile in ("shared", "partitioned"):
            raw = require_object(pair_input, f"{profile}_raw", context)
            path_value = require_string(raw, "path", context)
            digest = require_sha256(raw, "sha256", context)
            expected_path, expected_digest = comparisons[index][profile]
            if not path_value.endswith(expected_path) or digest != expected_digest:
                raise EvidenceVerificationError(
                    f"formal campaign pair {index} {profile} input differs"
                )

    thresholds = require_object(summary, "thresholds", context)
    require_equal(thresholds, "direct_irq_max_required_pairs", 4, context)
    require_equal(thresholds, "max_improvement_target_percent", 10.0, context)
    require_equal(thresholds, "p99_non_regression_limit_percent", 5.0, context)
    verify_formal_metrics(
        require_object(summary, "metrics", context),
        context,
        aggregate=True,
    )

    soak = require_object(summary, "soak", context)
    require_equal(soak, "minimum_duration_seconds", 1800, context)
    require_equal(soak, "iterations_per_metric", 10000, context)
    require_equal(soak, "period_us", 90000, context)
    profiles = require_object(soak, "profiles", context)
    for profile, requested_pcpu, observed_mask in (
        ("shared", 1, 2),
        ("partitioned", 3, 8),
    ):
        profile_data = require_object(profiles, profile, context)
        require_equal(profile_data, "profile", profile, context)
        require_equal(profile_data, "requested_pcpu", requested_pcpu, context)
        require_equal(profile_data, "observed_pcpu_mask", observed_mask, context)
        elapsed = require_finite_number(profile_data, "elapsed_seconds", context)
        if elapsed < 1800.0:
            raise EvidenceVerificationError(
                f"formal {profile} soak is shorter than 1800 seconds"
            )
        guest_records = require_positive_integer(
            profile_data,
            "guest_records",
            context,
        )
        require_equal(
            profile_data,
            "direct_irq_pair_count",
            guest_records,
            context,
        )
        require_positive_integer(profile_data, "host_records", context)
        receipt = receipts[("soak", None, profile)]
        raw = require_object(profile_data, "raw", context)
        raw_path = require_string(raw, "path", context)
        raw_digest = require_sha256(raw, "sha256", context)
        expected_path, expected_digest, _ = receipt["raw"]
        if not raw_path.endswith(expected_path) or raw_digest != expected_digest:
            raise EvidenceVerificationError(
                f"formal {profile} soak raw input differs from its receipt"
            )
        trace_inputs = require_object(profile_data, "trace_inputs", context)
        for trace_name, receipt_name in (
            ("guest", "guest_irq"),
            ("host", "host_trace"),
        ):
            trace = require_object(trace_inputs, trace_name, context)
            trace_path = require_string(trace, "path", context)
            trace_digest = require_sha256(trace, "sha256", context)
            expected_path, expected_digest, _ = receipt[receipt_name]
            if (
                not trace_path.endswith(expected_path)
                or trace_digest != expected_digest
            ):
                raise EvidenceVerificationError(
                    f"formal {profile} soak {trace_name} trace differs"
                )


def verify_formal_compact_archive_bindings(
    directory: Path,
    archive_entries: dict[str, tuple[str, int]],
) -> None:
    """Bind each compact campaign record back to the full archive manifest."""
    relative_paths = [
        "campaign-summary.json",
        "preregistration.json",
        "preregistration.sha256",
        "soak/shared/receipt.json",
        "soak/partitioned/receipt.json",
    ]
    for pair in range(1, 6):
        relative_paths.extend(
            (
                f"pair-{pair}/comparison.json",
                f"pair-{pair}/shared/receipt.json",
                f"pair-{pair}/partitioned/receipt.json",
            )
        )
    for relative in relative_paths:
        path = directory / relative
        expected = (sha256_file(path), path.stat().st_size)
        if archive_entries.get(relative) != expected:
            raise EvidenceVerificationError(
                f"compact formal evidence differs from archive manifest: {relative}"
            )


def require_finite_number(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> float:
    """Return one finite JSON number while rejecting booleans."""
    if key not in mapping:
        raise EvidenceVerificationError(f"{context} is missing field: {key}")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceVerificationError(f"{context}.{key} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceVerificationError(f"{context}.{key} must be finite")
    return result


def verify_rtos_guest_ivc(directory: Path) -> EvidenceSetResult:
    """Verify RT-Thread/FreeRTOS normal and ACK-loss QEMU evidence."""
    checked_files = verify_checksum_manifest(directory, "SHA256SUMS")
    validation = load_json_object(directory / "validation.json")
    require_equal(validation, "schema_version", 2, "RTOS validation")

    repository = require_object(validation, "repository", "RTOS validation")
    source_commit = require_commit(repository, "head", "RTOS repository")
    require_equal(
        repository,
        "tracked_worktree_clean",
        True,
        "RTOS repository",
    )
    require_equal(
        repository,
        "clean_commit_evidence",
        True,
        "RTOS repository",
    )
    verify_rtos_inputs(validation)

    runs = require_list(validation, "runs", "RTOS validation")
    observed_profiles: set[tuple[str, str]] = set()
    observed_artifacts: set[str] = set()
    for index, value in enumerate(runs):
        context = f"RTOS run {index}"
        run = require_mapping(value, context)
        rtos_name = require_string(run, "rtos", context)
        profile = require_string(run, "profile", context)
        identity = (rtos_name, profile)
        expectation = EXPECTED_RTOS_RUNS.get(identity)
        if expectation is None:
            raise EvidenceVerificationError(
                f"{context} has unexpected identity: {rtos_name}/{profile}"
            )
        if identity in observed_profiles:
            raise EvidenceVerificationError(
                f"duplicate RTOS evidence profile: {rtos_name}/{profile}"
            )
        observed_profiles.add(identity)
        artifact = verify_rtos_run(
            directory,
            run,
            rtos_name,
            profile,
            expectation,
            context,
        )
        if artifact in observed_artifacts:
            raise EvidenceVerificationError(
                f"multiple RTOS runs reference one log: {artifact}"
            )
        observed_artifacts.add(artifact)

    if observed_profiles != set(EXPECTED_RTOS_RUNS):
        missing = sorted(set(EXPECTED_RTOS_RUNS) - observed_profiles)
        raise EvidenceVerificationError(
            f"RTOS validation is missing required profiles: {missing}"
        )
    tracked_gzip = {
        path.name for path in directory.glob("*.gz") if path.is_file()
    }
    if tracked_gzip != observed_artifacts:
        raise EvidenceVerificationError(
            "RTOS gzip artifacts differ from declared runs: "
            f"declared={sorted(observed_artifacts)}, "
            f"found={sorted(tracked_gzip)}"
        )
    return EvidenceSetResult(source_commit, checked_files, len(runs))


def verify_network_isolation(directory: Path) -> EvidenceSetResult:
    """Verify the three-guest virtual-switch isolation capture."""
    checked_files = verify_checksum_manifest(directory, "checksums.sha256")
    summary = load_json_object(directory / "summary.json")
    require_equal(summary, "schema_version", 2, "isolation summary")
    require_equal(summary, "status", "pass", "isolation summary")

    source = require_object(summary, "source", "isolation summary")
    source_commit = require_commit(source, "commit", "isolation source")
    require_equal(
        source,
        "tracked_worktree_clean",
        True,
        "isolation source",
    )
    require_equal(
        source,
        "clean_commit_evidence",
        True,
        "isolation source",
    )

    results = require_object(summary, "results", "isolation summary")
    expected_results = {
        "same_segment_tcp_bytes": 65536,
        "same_segment_tcp_checksum": "0x7f8000",
        "cross_segment_udp_probes": 100,
        "vm3_tx_frames": 100,
        "vm1_cross_segment_probes_received": 0,
        "observation_ms": 7000,
    }
    for key, expected in expected_results.items():
        require_equal(results, key, expected, "isolation results")

    artifacts = require_object(summary, "artifacts", "isolation summary")
    artifact = require_object(
        artifacts,
        "console_build_log_gzip",
        "isolation artifacts",
    )
    log_path, log_payload = verify_gzip_artifact(
        directory,
        artifact,
        compressed_path_key="path",
        compressed_bytes_key="bytes",
        compressed_sha256_key="sha256",
        uncompressed_bytes_key="uncompressed_bytes",
        uncompressed_sha256_key="uncompressed_sha256",
        context="isolation QEMU log",
    )
    if log_path.name != "qemu.log.gz":
        raise EvidenceVerificationError(
            f"isolation QEMU log has unexpected name: {log_path.name}"
        )
    log = decode_log(log_payload, "isolation QEMU log")
    markers = require_list(summary, "pass_markers", "isolation summary")
    if markers != list(EXPECTED_ISOLATION_MARKERS):
        raise EvidenceVerificationError(
            "isolation pass marker contract differs from the required "
            "same-segment and cross-segment postconditions"
        )
    for value in EXPECTED_ISOLATION_MARKERS:
        if value not in log:
            raise EvidenceVerificationError(
                f"isolation QEMU log is missing pass marker: {value}"
            )
    require_successful_runner_log(log, "isolation QEMU log")
    return EvidenceSetResult(source_commit, checked_files, 1)


def verify_rtos_inputs(validation: dict[str, object]) -> None:
    """Validate source and controller identities used by all RTOS runs."""
    rootfs = require_object(
        validation,
        "controller_rootfs",
        "RTOS validation",
    )
    require_positive_integer(rootfs, "bytes", "controller rootfs")
    require_sha256(rootfs, "sha256", "controller rootfs")

    source_pins = require_object(validation, "source_pins", "RTOS validation")
    for key in (
        "rtthread",
        "freertos_over_bao",
        "freertos_kernel",
        "bao_runtime",
        "freertos_plus_tcp",
    ):
        require_commit(source_pins, key, "RTOS source pins")


def verify_rtos_run(
    directory: Path,
    run: dict[str, object],
    rtos_name: str,
    profile: str,
    expectation: FaultExpectation,
    context: str,
) -> str:
    """Verify one RTOS result's counters and retained console log."""
    expected_counters = {
        "accepted": 100,
        "applied": 100,
        "duplicates": expectation.duplicates,
        "acks_dropped": expectation.dropped_acks,
        "protocol_errors": 0,
        "acknowledged": 100,
        "controller_errors": 0,
        "controller_timeouts": 0,
        "retransmissions": expectation.retransmissions,
        "recoveries": expectation.recoveries,
    }
    for key, expected in expected_counters.items():
        require_equal(run, key, expected, context)
    require_sha256(run, "guest_binary_sha256", context)
    require_sha256(run, "summary_sha256", context)

    log_path, log_payload = verify_gzip_artifact(
        directory,
        run,
        compressed_path_key="qemu_log_gzip",
        compressed_bytes_key="qemu_log_gzip_bytes",
        compressed_sha256_key="qemu_log_gzip_sha256",
        uncompressed_bytes_key="qemu_log_bytes",
        uncompressed_sha256_key="qemu_log_sha256",
        context=f"{rtos_name}/{profile} QEMU log",
    )
    log = decode_log(log_payload, f"{rtos_name}/{profile} QEMU log")
    verify_rtos_log(log, rtos_name, profile, expectation)
    return log_path.name


def verify_rtos_log(
    log: str,
    rtos_name: str,
    profile: str,
    expectation: FaultExpectation,
) -> None:
    """Require terminal RTOS, controller, and runner success markers."""
    context = f"{rtos_name}/{profile} QEMU log"
    rtos_result = unique_line_containing(
        log,
        f"IVC-RTOS-RESULT rtos={rtos_name} profile={profile}",
        context,
    )
    for fragment in (
        " accepted=100",
        " applied=100",
        f" duplicates={expectation.duplicates}",
        f" acks_dropped={expectation.dropped_acks}",
        " protocol_errors=0",
    ):
        if fragment not in rtos_result:
            raise EvidenceVerificationError(
                f"{context} RTOS result is missing: {fragment.strip()}"
            )

    controller_result = unique_line_containing(
        log,
        "IVC-CONTROLLER-RESULT",
        context,
    )
    for fragment in (
        " sent=100",
        " acknowledged=100",
        " errors=0",
        " timeouts=0",
        f" retransmissions={expectation.retransmissions}",
        f" recoveries={expectation.recoveries}",
        " success_percent=100.000",
    ):
        if fragment not in controller_result:
            raise EvidenceVerificationError(
                f"{context} controller result is missing: {fragment.strip()}"
            )
    if "IVC-LINUX-DONE exit=0" not in log:
        raise EvidenceVerificationError(
            f"{context} is missing the Linux completion marker"
        )
    require_successful_runner_log(log, context)


def verify_gzip_artifact(
    directory: Path,
    metadata: dict[str, object],
    *,
    compressed_path_key: str,
    compressed_bytes_key: str,
    compressed_sha256_key: str,
    uncompressed_bytes_key: str,
    uncompressed_sha256_key: str,
    context: str,
) -> tuple[Path, bytes]:
    """Verify a gzip file against compressed and decompressed identities."""
    artifact_name = require_string(metadata, compressed_path_key, context)
    artifact_path = safe_relative_file(directory, artifact_name, context)
    expected_compressed_bytes = require_nonnegative_integer(
        metadata,
        compressed_bytes_key,
        context,
    )
    expected_compressed_hash = require_sha256(
        metadata,
        compressed_sha256_key,
        context,
    )
    actual_compressed_bytes = artifact_path.stat().st_size
    if actual_compressed_bytes != expected_compressed_bytes:
        raise EvidenceVerificationError(
            f"{context} compressed byte count differs: "
            f"expected {expected_compressed_bytes}, got {actual_compressed_bytes}"
        )
    actual_compressed_hash = sha256_file(artifact_path)
    if actual_compressed_hash != expected_compressed_hash:
        raise EvidenceVerificationError(
            f"{context} compressed SHA-256 mismatch: "
            f"expected {expected_compressed_hash}, got {actual_compressed_hash}"
        )
    expected_payload_bytes = require_nonnegative_integer(
        metadata,
        uncompressed_bytes_key,
        context,
    )
    if expected_payload_bytes > MAX_UNCOMPRESSED_LOG_BYTES:
        raise EvidenceVerificationError(
            f"{context} exceeds the uncompressed byte limit: "
            f"{expected_payload_bytes} > {MAX_UNCOMPRESSED_LOG_BYTES}"
        )
    expected_payload_hash = require_sha256(
        metadata,
        uncompressed_sha256_key,
        context,
    )
    payload_buffer = bytearray()
    try:
        with gzip.open(artifact_path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                payload_buffer.extend(chunk)
                if len(payload_buffer) > expected_payload_bytes:
                    raise EvidenceVerificationError(
                        f"{context} uncompressed byte count exceeds "
                        f"the declared {expected_payload_bytes} bytes"
                    )
    except EvidenceVerificationError:
        raise
    except (OSError, EOFError) as error:
        raise EvidenceVerificationError(
            f"{context} cannot be decompressed: {error}"
        ) from error
    payload = bytes(payload_buffer)
    if len(payload) != expected_payload_bytes:
        raise EvidenceVerificationError(
            f"{context} uncompressed byte count differs: "
            f"expected {expected_payload_bytes}, got {len(payload)}"
        )
    actual_payload_hash = hashlib.sha256(payload).hexdigest()
    if actual_payload_hash != expected_payload_hash:
        raise EvidenceVerificationError(
            f"{context} uncompressed SHA-256 mismatch: "
            f"expected {expected_payload_hash}, got {actual_payload_hash}"
        )
    return artifact_path, payload


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the repository containing the competition delivery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the checkout containing this script)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run all compact-evidence and source-freshness gates."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = verify_repository_delivery(args.repository)
    except EvidenceVerificationError as error:
        print(f"competition delivery verification failed: {error}", file=sys.stderr)
        return 2
    print(
        "COMPETITION_DELIVERY_EVIDENCE_PASS "
        f"qemu_source_commit={report.source_commit} "
        f"formal_source_commit={report.formal_source_commit or 'none'} "
        f"evidence_sets={report.evidence_sets} "
        f"checked_files={report.checked_files} "
        f"qemu_logs={report.qemu_logs} "
        f"archive_files={report.archive_files}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
