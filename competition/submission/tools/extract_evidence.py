#!/usr/bin/env python3
"""Build a normalized competition evidence snapshot from retained JSON artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EvidenceError(RuntimeError):
    """Raised when retained evidence does not satisfy the documented contract."""


@dataclass(frozen=True)
class LoadedEvidence:
    path: str
    sha256: str
    data: dict[str, Any]


EVIDENCE_PATHS = {
    "formal_rt": "competition/results/axvisor-rt-formal-20260816/campaign-summary.json",
    "current_ivc": "competition/results/current-source-smoke-20260813/ivc/summary.json",
    "control": "competition/results/current-source-smoke-20260813/historical-formal/ivc-control/campaign-summary.json",
    "ack_loss": "competition/results/current-source-smoke-20260813/historical-formal/ivc-ack-loss/campaign-summary.json",
    "typed_error": "competition/results/current-source-smoke-20260813/historical-formal/ivc-error/campaign-summary.json",
    "restart": "competition/results/current-source-smoke-20260813/historical-formal/ivc-restart/campaign-summary.json",
    "rknpu": "competition/results/current-source-smoke-20260813/historical-formal/rknpu/campaign-summary.json",
    "ort": "competition/results/current-source-smoke-20260813/historical-formal/ort/campaign-summary.json",
    "continuous_vision": "competition/results/orangepi-vision-continuous-20260822/65bdeed8d-v21/summary.json",
    "live_camera": "competition/results/orangepi-live-camera-20260822-v25/summary.json",
    "vision_preprocess": "competition/results/orangepi-vision-preprocess-20260819-v8/summary.json",
    "vision_core": "competition/results/orangepi-vision-fixed-core-20260820-v4/summary.json",
    "labeled_scenes": "competition/results/orangepi-labeled-scenes-20260823-v1/summary.json",
    "native_zephyr": "competition/results/orangepi-native-zephyr-campaign-20260819-v6/summary.json",
    "native_zephyr_soak": "competition/results/orangepi-native-zephyr-20260818/soak/summary.json",
    "rtthread_ivc": "competition/results/orangepi-rtos-ivc-20260818/rtthread/summary.json",
    "freertos_ivc": "competition/results/orangepi-rtos-ivc-20260818/freertos/summary.json",
    "isolation": "competition/results/orangepi-isolation-20260819-v9/summary.json",
    "so100_summary": "competition/results/orangepi-so100-id1-live-revalidation-20260823/run-summary.json",
    "so100_trace": "competition/results/orangepi-so100-id1-live-revalidation-20260823/live-artifact.json",
    "rt_audit": "competition/results/rt-formal-current-head-audit-20260819/audit.json",
}


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(args.repo_root).resolve())
    output = root / args.output
    snapshot = build_snapshot(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"EVIDENCE_SNAPSHOT_PASS path={output.relative_to(root).as_posix()}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--output",
        default="competition/submission/data/evidence-snapshot.json",
    )
    return parser.parse_args()


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "competition/requirement.md").is_file():
            return candidate
    raise EvidenceError(f"repository root not found from {start}")


def build_snapshot(root: Path) -> dict[str, Any]:
    loaded = {name: load_evidence(root, path) for name, path in EVIDENCE_PATHS.items()}
    data = {name: item.data for name, item in loaded.items()}
    validate_evidence(data)

    formal_rt = data["formal_rt"]
    control = data["control"]
    current_ivc = data["current_ivc"]
    rknpu = data["rknpu"]
    ort = data["ort"]
    continuous = data["continuous_vision"]
    camera = data["live_camera"]
    preprocess = data["vision_preprocess"]
    core = data["vision_core"]
    labeled = data["labeled_scenes"]
    native = data["native_zephyr"]
    native_soak = data["native_zephyr_soak"]
    isolation = data["isolation"]
    so100 = data["so100_summary"]
    so100_trace = data["so100_trace"]

    rt_metrics = {}
    for key, label in (
        ("dispatch_latency", "dispatch"),
        ("emulated_irq_response", "emulated_irq"),
        ("periodic_jitter", "periodic_jitter"),
        ("virtual_timer_injection_to_guest_irq", "direct_irq"),
    ):
        metric = formal_rt["metrics"][key]
        rt_metrics[label] = {
            "shared_worst_max_ns": metric["max"]["shared_worst_of_runs_ns"],
            "partitioned_worst_max_ns": metric["max"]["partitioned_worst_of_runs_ns"],
            "worst_max_improvement_percent": metric["max"]["worst_of_runs_improvement_percent"],
            "improved_max_pairs": metric["max"]["improved_pair_count"],
            "shared_worst_p99_ns": metric["p99"]["shared_worst_of_runs_ns"],
            "partitioned_worst_p99_ns": metric["p99"]["partitioned_worst_of_runs_ns"],
            "worst_p99_improvement_percent": metric["p99"]["worst_of_runs_improvement_percent"],
            "p99_pair_improvement_percent": metric["p99"]["pair_improvement_percent"],
        }

    manual = control["profile_statistics"]["manual"]
    neural = control["profile_statistics"]["neural"]
    control_effect = {}
    for key in ("rmse_milli_c", "iae_milli_c_s", "max_overshoot_milli_c"):
        manual_value = manual[key]["median"]
        neural_value = neural[key]["median"]
        control_effect[key] = {
            "manual": manual_value,
            "neural": neural_value,
            "neural_change_percent": round(
                (neural_value - manual_value) / manual_value * 100.0,
                6,
            ),
        }

    fault_campaigns = {}
    for key in ("ack_loss", "typed_error", "restart"):
        campaign = data[key]
        fault_campaigns[key] = {
            "source_commit": campaign["campaign"]["source_commit"],
            "repeat_count": campaign["campaign"].get("repeat_count", 3),
            "campaign_gate_met": campaign["assessment"]["campaign_gate_met"],
            "reason": campaign["assessment"]["reason"],
        }

    native_workloads = {}
    for workload in ("idle", "cpu-stress"):
        workload_data = native["workloads"][workload]
        native_workloads[workload] = {
            "runs": workload_data["runs"],
            "timer_misses": workload_data["completion"]["timer_misses"],
            "early_wakes": workload_data["completion"]["early_wakes"],
            "wake_p99_median_ns": workload_data["metrics"]["periodic_wake_lateness"]["p99_ns"]["median"],
            "wake_max_median_ns": workload_data["metrics"]["periodic_wake_lateness"]["max_ns"]["median"],
            "dispatch_p99_median_ns": workload_data["metrics"]["timer_to_task_dispatch"]["p99_ns"]["median"],
            "dispatch_max_median_ns": workload_data["metrics"]["timer_to_task_dispatch"]["max_ns"]["median"],
        }

    trace_samples = [
        {
            "elapsed_ms": sample["elapsed_ms"],
            "position": sample["position"],
            "phase": sample["phase"],
            "torque_enabled": sample["torque_enabled"],
            "moving": sample["moving"],
            "status": sample["status"],
        }
        for sample in so100_trace["execution"]["samples"]
    ]

    return {
        "schema_version": 1,
        "generation": {
            "repository_head": git(root, "rev-parse", "HEAD"),
            "repository_branch": git(root, "branch", "--show-current"),
            "upstream_dev": git(root, "rev-parse", "upstream/dev"),
            "upstream_left_right_count": git(
                root, "rev-list", "--left-right", "--count", "upstream/dev...HEAD"
            ),
            "ilm_zh_commit": "7a6080e891631d45ab2c2b40531ea8a3f211270f",
        },
        "evidence_inputs": {
            name: {"path": item.path, "sha256": item.sha256}
            for name, item in sorted(loaded.items())
        },
        "realtime": {
            "campaign_source_commit": "c82da8464ab69e7da95e9be08293559e67b28fac",
            "pair_count": formal_rt["campaign"]["pair_count"],
            "iterations_per_metric": formal_rt["campaign"]["iterations_per_metric"],
            "m2_exit_gate_met": formal_rt["assessment"]["m2_exit_gate_met"],
            "current_head_rerun": False,
            "current_head_blob_audit": {"same": 33, "total": 34},
            "metrics": rt_metrics,
            "soak": {
                profile: {
                    "elapsed_seconds": values["elapsed_seconds"],
                    "guest_records": values["guest_records"],
                    "host_records": values["host_records"],
                    "direct_irq_pair_count": values["direct_irq_pair_count"],
                }
                for profile, values in formal_rt["soak"]["profiles"].items()
            },
        },
        "network": {
            "topology": current_ivc["network"],
            "current_restart_smoke": {
                "source_commit": "598b357f92c848e669c12cca830a4d08d0a50e36",
                "starry_vcpus": current_ivc["starry"]["vcpus"],
                "pre_reset_samples": current_ivc["restart_recovery"]["pre_reset_samples"],
                "post_reset_samples": current_ivc["restart_recovery"]["post_reset_samples"],
                "actual_vm_reset": current_ivc["restart_recovery"]["actual_vm_reset"],
                "accepted": current_ivc["rtos"]["accepted"],
                "applied": current_ivc["rtos"]["applied"],
                "status_sent": current_ivc["rtos"]["status_sent"],
                "acks_sent": current_ivc["rtos"]["acks_sent"],
                "errors_sent": current_ivc["rtos"]["errors_sent"],
                "full_loop_p99_us": current_ivc["controller"]["full_loop_p99_us"],
                "full_loop_max_us": current_ivc["controller"]["full_loop_max_us"],
                "success_percent": current_ivc["controller"]["success_percent"],
            },
            "fault_campaigns": fault_campaigns,
            "physical_rtos_guests": {
                "rtthread": summarize_physical_rtos(data["rtthread_ivc"]),
                "freertos": summarize_physical_rtos(data["freertos_ivc"]),
            },
        },
        "ai_control": {
            "control_effect": control_effect,
            "full_loop_p99_favorable_pairs": sum(
                1
                for pair in control["paired_effects"]["full_loop_p99_us"]["pairs"]
                if pair["favors_neural"]
            ),
            "rknpu": {
                "runs": rknpu["campaign"]["run_count"],
                "total_samples": rknpu["campaign"]["total_samples"],
                "success_percent": rknpu["reliability"]["success_percent"],
                "device_p99_median_us": rknpu["statistics"]["rknn"]["device_p99_us"]["median"],
                "full_loop_p99_median_us": rknpu["statistics"]["controller"]["full_loop_p99_us"]["median"],
            },
            "ort": {
                "runs": ort["campaign"]["run_count"],
                "total_samples": ort["campaign"]["total_samples"],
                "acknowledged": ort["reliability"]["acknowledged"],
                "wall_p99_median_us": round(ort["statistics"]["ort"]["wall_p99_ns"]["median"] / 1000.0, 6),
                "full_loop_p99_median_us": ort["statistics"]["controller"]["full_loop_p99_us"]["median"],
            },
        },
        "vision": {
            "live_camera": {
                "source_commit": camera["source"]["source_commit"],
                "duration_seconds": camera["benchmark"]["duration_sec"],
                "captured": camera["benchmark"]["captured"],
                "inferences": camera["benchmark"]["inferences"],
                "capture_fps": camera["benchmark"]["capture_fps"],
                "inference_fps": camera["benchmark"]["infer_fps"],
                "infer_p95_ms": camera["benchmark"]["infer_ms_p95"],
                "decode_errors": camera["benchmark"]["decode_errors"],
                "inference_errors": camera["benchmark"]["inference_errors"],
            },
            "continuous_loop": {
                "source_commit": "65bdeed8da80459808246fbf3fae85c56196ff2f",
                "decisions": continuous["decisions"],
                "accepted": continuous["rtos"]["accepted"],
                "applied": continuous["rtos"]["applied"],
                "status_sent": continuous["rtos"]["actuator_status_sent"],
                "actions": continuous["action_counts"],
                "latency_us": continuous["latency_us"],
                "retries": continuous["retries"],
                "physical_actuator_claimed": continuous["acceptance"]["physical_actuator_claimed"],
            },
            "preprocess": {
                metric: {
                    "legacy_median_ms": preprocess["metrics"][metric]["legacy_float"]["median"],
                    "optimized_median_ms": preprocess["metrics"][metric]["fixed_q12"]["median"],
                    "paired_improvement_median_percent": preprocess["metrics"][metric]["paired_improvement_percent_median"],
                    "favorable_pairs": preprocess["metrics"][metric]["favorable_pairs"],
                }
                for metric in ("letterbox_ms_avg", "total_ms_avg", "total_ms_p95")
            },
            "npu_core": {
                metric: {
                    "core0_median_ms": core["metrics"][metric]["core0"]["median"],
                    "all_median_ms": core["metrics"][metric]["all"]["median"],
                    "paired_improvement_median_percent": core["metrics"][metric]["paired_improvement_percent_median"],
                    "favorable_pairs": core["metrics"][metric]["favorable_pairs"],
                }
                for metric in ("rknn_perf_run_ms_avg", "rknn_perf_run_ms_p95", "total_ms_avg", "total_ms_p95")
            },
            "labeled_pilot": {
                "scene_count": labeled["acceptance"]["scene_count"],
                "ai_accuracy_percent": labeled["ai"]["action_accuracy_percent"],
                "ai_wrong_direction_percent": labeled["ai"]["wrong_direction_percent"],
                "ai_missed_actions": labeled["ai"]["missed_actions"],
                "best_fixed_accuracy_percent": labeled["comparison"]["best_fixed_accuracy_percent"],
                "overall_ai_superiority_demonstrated": labeled["comparison"]["overall_ai_superiority_demonstrated"],
                "fixed_baselines": labeled["fixed_baselines"],
            },
        },
        "native_rtos": {
            "platform": native["identity"]["board"],
            "configuration": native["identity"]["configuration"],
            "pairs": native["campaign"]["pairs"],
            "runs": native["campaign"]["runs"],
            "workloads": native_workloads,
            "paired_comparison": native["paired_comparison"],
            "soak": {
                "elapsed_seconds": round(native_soak["load"]["window_duration_us"] / 1_000_000.0, 6),
                "samples": native_soak["configuration"]["samples"],
                "timer_misses": native_soak["completion"]["timer_misses"],
                "early_wakes": native_soak["completion"]["early_wakes"],
            },
        },
        "isolation": {
            "source_commit": isolation["source"]["commit"],
            "status": isolation["status"],
            "topology": isolation["topology"],
            "same_segment_tcp_bytes": isolation["results"]["same_segment_tcp_bytes"],
            "cross_segment_udp_probes": isolation["results"]["cross_segment_udp_probes"],
            "cross_segment_received": isolation["results"]["vm1_cross_segment_probes_received"],
            "active_l2_probes": isolation["results"]["active_l2_probes"],
            "drop_unknown_unicast": isolation["results"]["switch_metrics"]["dropped_unknown_unicast"],
            "drop_spoofed_sources": isolation["results"]["switch_metrics"]["dropped_spoofed_sources"],
        },
        "physical_actuator": {
            "source_commit": so100["source"]["commit"],
            "evidence_class": so100["evidence_class"],
            "status": so100["status"],
            "trajectory": so100["dry_run"]["trajectory"],
            "maximum_observed_outbound": so100["execution"]["maximum_observed_outbound"],
            "return_monitor_final": so100["execution"]["return_monitor_final"],
            "postflight_stable": so100["postflight"]["stable_positions"]["1"],
            "position_tolerance": so100["execution"]["position_tolerance"],
            "torque_disabled_at_end": so100["execution"]["torque_disabled_at_end"],
            "claims": so100["claims"],
            "trace": trace_samples,
        },
        "claim_boundaries": {
            "observed_maximum_is_wcet": False,
            "formal_rt_is_current_head_rerun": False,
            "continuous_vision_has_physical_actuator": False,
            "so100_has_rtos_mediator": False,
            "so100_is_camera_synchronized": False,
            "labeled_pilot_proves_ai_superiority": False,
            "virtual_segment_proves_physical_nic_isolation": False,
        },
    }


def summarize_physical_rtos(summary: dict[str, Any]) -> dict[str, Any]:
    controller = summary["controller"]
    rtos = summary["rtos"]
    return {
        "accepted": rtos["accepted"],
        "applied": rtos["applied"],
        "errors": controller["errors"],
        "timeouts": controller["timeouts"],
        "retransmissions": controller["retransmissions"],
        "transport_p50_us": controller["transport_p50_us"],
        "transport_p99_us": controller["transport_p99_us"],
        "transport_max_us": controller["transport_max_us"],
        "full_loop_p50_us": controller["full_loop_p50_us"],
        "full_loop_p99_us": controller["full_loop_p99_us"],
        "full_loop_max_us": controller["full_loop_max_us"],
    }


def validate_evidence(data: dict[str, dict[str, Any]]) -> None:
    expect(data["formal_rt"]["assessment"]["m2_exit_gate_met"] is True, "formal RT M2 gate")
    expect(data["formal_rt"]["campaign"]["pair_count"] == 5, "formal RT pair count")
    expect(data["current_ivc"]["restart_recovery"]["actual_vm_reset"] is True, "actual VM reset")
    expect(data["current_ivc"]["controller"]["success_percent"] == 100.0, "IVC success")
    expect(data["control"]["assessment"]["campaign_gate_met"] is True, "control campaign")
    for key in ("ack_loss", "typed_error", "restart"):
        expect(data[key]["assessment"]["campaign_gate_met"] is True, f"{key} campaign")
    expect(data["rknpu"]["reliability"]["success_percent"] == 100.0, "RKNN reliability")
    expect(data["ort"]["formal_gate_passed"] is True, "ORT formal gate")
    expect(data["continuous_vision"]["acceptance"]["passed"] is True, "continuous vision")
    expect(data["live_camera"]["acceptance"]["passed"] is True, "live camera")
    expect(data["vision_preprocess"]["acceptance"]["passed"] is True, "vision preprocess")
    expect(data["vision_core"]["acceptance"]["passed"] is True, "vision core")
    expect(data["labeled_scenes"]["acceptance"]["passed"] is True, "labeled scenes")
    expect(data["native_zephyr"]["status"] == "pass", "native Zephyr")
    expect(data["isolation"]["status"] == "pass", "physical isolation")
    expect(data["so100_summary"]["status"] == "pass", "SO-100 single cycle")
    expect(data["so100_trace"]["status"] == "pass", "SO-100 trace")
    expect(data["so100_summary"]["claims"]["rtos_mediator"] == "not-tested", "SO-100 RTOS boundary")
    expect(data["so100_summary"]["claims"]["camera_synchronized_physical_loop"] == "not-tested", "SO-100 camera boundary")


def expect(condition: bool, label: str) -> None:
    if not condition:
        raise EvidenceError(f"evidence contract failed: {label}")


def load_evidence(root: Path, relative_path: str) -> LoadedEvidence:
    path = root / relative_path
    if not path.is_file():
        raise EvidenceError(f"missing evidence: {relative_path}")
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise EvidenceError(f"invalid JSON: {relative_path}: {error}") from error
    if not isinstance(parsed, dict):
        raise EvidenceError(f"expected JSON object: {relative_path}")
    return LoadedEvidence(relative_path, hashlib.sha256(raw).hexdigest(), parsed)


def git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
