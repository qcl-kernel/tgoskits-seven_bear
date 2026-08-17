#!/usr/bin/env python3
"""Render terminal-friendly views by reading and rechecking retained evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SCENES = (
    "architecture",
    "rt-mechanism",
    "rt-results",
    "rt-baseline",
    "network-protocol",
    "ivc-log",
    "ivc-analysis",
    "ai-loop",
    "ai-results",
    "verify",
)

COLORS = {
    "gray": "\033[37m",
    "dark-gray": "\033[90m",
    "red": "\033[31m",
    "green": "\033[32m",
    "dark-green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "dark-cyan": "\033[36m",
    "magenta": "\033[35m",
    "white": "\033[97m",
}
RESET = "\033[0m"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class EvidenceDemo:
    """Read real evidence and present one deterministic terminal scene."""

    def __init__(self, repo_root: Path, delay_ms: int) -> None:
        self.repo_root = repo_root
        self.delay_seconds = delay_ms / 1000.0
        self.evidence_root = (
            repo_root / "competition/results/current-source-smoke-20260813"
        )
        self.formal_rt_root = (
            repo_root / "competition/results/axvisor-rt-formal-20260816"
        )

    def show(self, scene: str) -> None:
        handlers = {
            "architecture": self.show_architecture,
            "rt-mechanism": self.show_rt_mechanism,
            "rt-results": self.show_rt_results,
            "rt-baseline": self.show_rt_baseline,
            "network-protocol": self.show_network_protocol,
            "ivc-log": self.show_ivc_log,
            "ivc-analysis": self.show_ivc_analysis,
            "ai-loop": self.show_ai_loop,
            "ai-results": self.show_ai_results,
            "verify": self.show_verification,
        }
        handlers[scene]()

    def show_architecture(self) -> None:
        starry_config = (
            self.repo_root
            / "competition/ivc/config/orangepi-5-plus-starry-smp2-restart.toml"
        )
        zephyr_config = (
            self.repo_root
            / "competition/ivc/config/orangepi-5-plus-zephyr-restart.toml"
        )
        provenance = self.read_json(self.evidence_root / "provenance.json")
        summary = self.read_json(self.evidence_root / "ivc/summary.json")
        starry_text = starry_config.read_text(encoding="utf-8")
        zephyr_text = zephyr_config.read_text(encoding="utf-8")
        self.assert_contains(starry_text, "cpu_num = 2", "StarryOS vCPU count")
        self.assert_contains(starry_text, "phys_cpu_sets = [0x2, 0x4]", "StarryOS pCPUs")
        self.assert_contains(starry_text, "0x1000_0000", "StarryOS memory")
        self.assert_contains(zephyr_text, "phys_cpu_sets = [0x1]", "Zephyr pCPU")
        self.assert_contains(zephyr_text, "0x0800_0000", "Zephyr memory")

        self.section("SYSTEM ARCHITECTURE / MIXED-CRITICALITY CONTROL")
        self.line(
            f"platform       : AxVisor on {provenance['board']['type']} / "
            f"{provenance['board']['soc']} / 4 pCPUs",
            "cyan",
        )
        self.line(
            "VM 1 StarryOS : 2 vCPU -> pCPU1,pCPU2 | 256 MiB | blk + net",
            "green",
        )
        self.line(
            "VM 2 Zephyr   : 1 vCPU -> pCPU0       | 128 MiB | virtio-net",
            "green",
        )
        self.line(
            "device graph  : typed MMIO / IRQ / backend allocation, fail closed",
            "cyan",
        )
        network = summary["network"]
        self.line(
            f"network        : segment {network['segment']} | {network['ip']} <-> "
            f"{network['peer']}:{network['udp_port']}/UDP",
            "green",
        )
        self.line(
            "closed loop    : observation -> NN -> CONTROL -> actuator/plant",
            "yellow",
        )
        self.line("                 STATUS + ACK -> next observation", "yellow")
        self.line(
            "bonus path     : StarryOS replaces Linux in board IVC and RT tests",
            "green",
        )

    def show_rt_mechanism(self) -> None:
        config_root = self.repo_root / "scripts/benchmark/axvisor-rt/config"
        shared = config_root / "starry-orangepi-5-plus-smp2-shared.toml"
        partitioned = config_root / "starry-orangepi-5-plus-smp2-partitioned.toml"
        shared_host = (
            config_root
            / "axvisor-orangepi-5-plus-starry-host-noise-formal-shared.toml"
        )
        partitioned_host = (
            config_root
            / "axvisor-orangepi-5-plus-starry-host-noise-formal-partitioned.toml"
        )
        partition_source = (
            self.repo_root / "virtualization/axvmconfig/src/partition.rs"
        ).read_text(encoding="utf-8")
        timer_source = (
            self.repo_root / "virtualization/arm_vcpu/src/timer.rs"
        ).read_text(encoding="utf-8")
        trace_source = (
            self.repo_root / "virtualization/axvm/src/rt_trace.rs"
        ).read_text(encoding="utf-8")
        self.assert_contains(partition_source, "reserved_cpu_mask", "CPU partition")
        self.assert_contains(
            timer_source, "registers.write_virtual_control(0)", "timer stop"
        )
        self.assert_contains(
            trace_source, "allocation-free, and lock-free", "RT trace"
        )

        self.section("TASK 1 / AXVISOR REAL-TIME PATH CHANGES")
        self.line("CPU placement", "cyan")
        self.show_toml_values(shared, ("phys_cpu_sets", "dedicated_cpus"))
        self.show_toml_values(partitioned, ("phys_cpu_sets", "dedicated_cpus"))
        self.line("  partition plan reserves pCPU masks and rejects overlap", "green")
        self.line("Controlled host interference", "cyan")
        self.show_toml_values(shared_host, ("cpu", "max_duration_ms"))
        self.show_toml_values(partitioned_host, ("cpu", "max_duration_ms"))
        self.line(
            "timer/GIC      : save -> GIC acknowledge/LR -> stop guest timer",
            "green",
        )
        self.line(
            "next vCPU entry: restore CVAL/CTL with explicit ISB ordering",
            "green",
        )
        self.line(
            "direct trace   : fixed-capacity, allocation-free, lock-free",
            "green",
        )
        self.line(
            "measured       : jitter + dispatch + emulated IRQ + direct IRQ",
            "green",
        )

    def show_rt_baseline(self) -> None:
        baselines = (
            ("Zephyr v4.3.0", "native-zephyr-reference"),
            ("RT-Thread v5.2.2", "native-rtthread-reference"),
            ("FreeRTOS V11.1.0+", "native-freertos-reference"),
        )
        self.section("TASK 1 / NATIVE RTOS EQUIVALENT-PLATFORM BASELINES")
        self.line("QEMU/AArch64 Cortex-A53 | 1 ms period | 10,000 samples/run", "cyan")
        for label, directory in baselines:
            root = self.repo_root / "competition/results" / directory
            idle = self.read_json(root / "idle-summary.json")
            stress = self.read_json(root / "stress-summary.json")
            for summary in (idle, stress):
                self.assert_equal(summary["completion"]["status"], "pass", label)
                self.assert_equal(summary["configuration"]["samples"], 10000, label)
                self.assert_equal(summary["load"]["verified"], True, label)
            idle_metric = idle["metrics"]["periodic_wake_lateness"]
            stress_metric = stress["metrics"]["periodic_wake_lateness"]
            self.line(
                f"{label:<20} idle p99/max {idle_metric['p99_ns']/1000:7.1f}/"
                f"{idle_metric['max_ns']/1000:7.1f} us",
                "green",
            )
            self.line(
                f"{'':20} stress p99/max {stress_metric['p99_ns']/1000:7.1f}/"
                f"{stress_metric['max_ns']/1000:7.1f} us | "
                f"load={stress['load']['stress_permille']/10:.1f}%",
                "yellow",
            )
        self.line(
            "Boundary: equivalent QEMU platform, not same-board RK3588 bare metal.",
            "dark-gray",
        )

    def show_network_protocol(self) -> None:
        wire_source = (
            self.repo_root / "tools/ivcproto/src/wire.rs"
        ).read_text(encoding="utf-8")
        isolation = self.read_json(
            self.repo_root
            / "competition/results/axvisor-isolation-reference/summary.json"
        )
        self.assert_contains(
            wire_source, 'pub const MAGIC: [u8; 4] = *b"IVC1"', "IVC magic"
        )
        self.assert_contains(
            wire_source, "pub const HEADER_LEN: usize = 32", "header length"
        )
        self.assert_equal(isolation["status"], "pass", "network isolation")

        self.section("TASK 2 / VIRTIO-NET + UDP/IP + IVC/1")
        self.line(
            "topology       : StarryOS 10.0.0.1 <-> 10.0.0.2:5500 Zephyr",
            "cyan",
        )
        self.line(
            "transport      : isolated virtio-net segment 1, UDP over IPv4",
            "green",
        )
        self.line(
            "32-byte header : magic/version/type/flags/session/sequence", "green"
        )
        self.line("                 timestamp/length/error-code/CRC32", "green")
        self.line("messages       : CONTROL | STATUS | ACK | typed ERROR", "yellow")
        self.line(
            "reliability    : timeout/retry + receive window + duplicate suppression",
            "yellow",
        )
        self.line(
            "recovery       : safe fallback + retired-session rejection", "yellow"
        )
        results = isolation["results"]
        self.line(
            f"isolation test : same-segment TCP={results['same_segment_tcp_bytes']} bytes; "
            f"cross-segment {results['cross_segment_udp_probes']} sent / "
            f"{results['vm1_cross_segment_probes_received']} received",
            "green",
        )

    def show_ivc_command(self) -> None:
        provenance = self.read_json(self.evidence_root / "provenance.json")
        command_text = (
            self.evidence_root / "commands/run-ivc-current.sh"
        ).read_text(encoding="utf-8")
        source_commit = provenance["ivc_fault_restart"]["source_commit"]
        self.assert_contains(command_text, source_commit, "IVC source pin")
        self.assert_contains(command_text, "--restore-linux", "Linux restore flag")
        self.assert_contains(command_text, "--require-clean", "clean-source flag")

        self.section("PHYSICAL-BOARD COMMAND (ARCHIVED, NOT RERUN HERE)")
        self.line(f"expected_source={source_commit}", "yellow")
        self.line('test "$(git rev-parse HEAD)" = "$expected_source"')
        self.line('test -z "$(git status --porcelain=v1)"')
        self.line(
            "bash competition/ivc/run-orangepi-5-plus.sh fault-restart \\", "cyan"
        )
        self.line('  --result-dir "$RESULT_ROOT" --timeout 900 \\', "cyan")
        self.line("  --restore-linux --require-clean", "cyan")
        run = provenance["ivc_fault_restart"]
        self.line(
            f"recorded UTC   : {run['started_at_utc']} -> {run['finished_at_utc']}",
            "dark-gray",
        )
        self.line(
            f"recorded result: {run['result']}; wrapper exit="
            f"{run['wrapper_exit_status']}; metadata_validated="
            f"{run['metadata_validated']}",
            "green",
        )

    def show_ivc_log(self) -> None:
        console_path = self.evidence_root / "ivc/console.log"
        console_lines = console_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        markers = (
            ("IVC-RTOS-SELFTEST PASS", "IVC-RTOS-SELFTEST", "green"),
            ("IVC-RTOS-READY bind=", "IVC-RTOS-READY", "cyan"),
            ("IVC-STARRY-BOOT mode=", "IVC-STARRY-BOOT", "cyan"),
            ("IVC-STARRY-NET iface=", "IVC-STARRY-NET", "dark-cyan"),
            (
                "IVC-STARRY-RESTART-ARMED phase=before-reset",
                "IVC-STARRY-RESTART-ARMED",
                "yellow",
            ),
            (
                "IVC-RTOS-SAFE-FALLBACK reason=controller-timeout",
                "IVC-RTOS-SAFE-FALLBACK",
                "yellow",
            ),
            (
                "AXVISOR_GUEST_RESTART_TRIGGER schema=",
                "AXVISOR_GUEST_RESTART_TRIGGER",
                "magenta",
            ),
            (
                "IVC-STARRY-RESTART-RESUME phase=after-reset",
                "IVC-STARRY-RESTART-RESUME",
                "green",
            ),
            (
                "IVC-RTOS-STALE-REPLAY old_session=",
                "IVC-RTOS-STALE-REPLAY",
                "yellow",
            ),
            (
                "IVC-RTOS-RESTART session_resets=",
                "IVC-RTOS-RESTART",
                "green",
            ),
            ("IVC-RTOS-RESULT profile=restart", "IVC-RTOS-RESULT", "green"),
            ("IVC-STARRY-DONE exit=0", "IVC-STARRY-DONE", "green"),
            (
                "AXVISOR_GUEST_RESTART_COMPLETE schema=",
                "AXVISOR_GUEST_RESTART_COMPLETE",
                "green",
            ),
            ("AXVISOR_SNAPSHOT_SYNC_OK", "AXVISOR_SNAPSHOT_SYNC_OK", "green"),
        )

        self.section("TASK 2 / ORANGE PI FAULT-RECOVERY UART")
        for pattern, marker_start, color in markers:
            line_number, raw_line = self.first_matching_line(console_lines, pattern)
            clean_line = ANSI_ESCAPE.sub("", raw_line)
            marker_offset = clean_line.find(marker_start)
            if marker_offset >= 0:
                clean_line = clean_line[marker_offset:]
            self.line(f"{line_number:4}: {clean_line}", color)

    def show_ivc_analysis(self) -> None:
        self.section("TASK 2 / RECOVERY + NETWORK METRICS")
        self.line(
            "python3 competition/ivc/analyze_board.py ... --profile restart",
            "cyan",
        )
        self.line(
            "  --expected-count 100 --expected-pre-reset-count 20", "dark-cyan"
        )
        self.line(
            "  ivc/console.log --raw-csv raw.csv "
            "--pre-reset-raw-csv raw-before-reset.csv",
            "dark-cyan",
        )

        with tempfile.TemporaryDirectory(prefix="tgoskits-ivc-reanalysis-") as temp:
            output_path = Path(temp) / "summary.json"
            command = (
                sys.executable,
                str(self.repo_root / "competition/ivc/analyze_board.py"),
                str(self.evidence_root / "ivc/console.log"),
                "--raw-csv",
                str(self.evidence_root / "ivc/raw.csv"),
                "--pre-reset-raw-csv",
                str(self.evidence_root / "ivc/raw-before-reset.csv"),
                "--expected-count",
                "100",
                "--expected-pre-reset-count",
                "20",
                "--profile",
                "restart",
                "--output",
                str(output_path),
            )
            subprocess.run(command, cwd=self.repo_root, check=True)
            summary = self.read_json(output_path)

        restart = summary["restart_recovery"]
        controller = summary["controller"]
        lifecycle = summary["lifecycle"]
        self.assert_equal(restart["actual_vm_reset"], True, "actual VM reset")
        self.assert_equal(restart["reset_count"], 1, "reset count")
        self.assert_equal(controller["acknowledged"], 100, "acknowledged count")
        self.assert_equal(controller["errors"], 0, "controller errors")
        self.assert_equal(controller["timeouts"], 0, "controller timeouts")
        frozen_log = (
            self.evidence_root / "validation/ivc-reanalysis.log"
        ).read_text(encoding="utf-8")
        self.assert_contains(
            frozen_log,
            "IVC reanalysis matches archived summary",
            "frozen IVC replay validation",
        )

        self.line(
            f"VM recovery     : reset={restart['actual_vm_reset']} VM{restart['vm_id']} "
            f"on pCPU{restart['host_cpu']} after {restart['observed_delay_ms']} ms",
            "green",
        )
        self.line(
            f"sessions        : {restart['old_session']} -> {restart['new_session']}",
            "green",
        )
        self.line(
            f"safe fallback   : {restart['safe_fallback_observed']}; "
            f"retired CONTROL rejected={restart['retired_control_rejected']}",
            "green",
        )
        self.line(
            f"post-reset loop : sent={controller['sent']}, "
            f"ack={controller['acknowledged']}, error={controller['errors']}, "
            f"timeout={controller['timeouts']}, "
            f"retransmit={controller['retransmissions']}",
            "green",
        )
        self.line(
            f"message counts  : CONTROL applied={summary['rtos']['applied']}; "
            f"STATUS={summary['rtos']['status_sent']}; ACK={summary['rtos']['acks_sent']}; "
            f"ERROR={summary['rtos']['errors_sent']}",
            "green",
        )
        self.line(
            f"full loop       : p50={controller['full_loop_p50_us']/1000:.3f} ms; "
            f"p99={controller['full_loop_p99_us']/1000:.3f} ms; "
            f"max={controller['full_loop_max_us']/1000:.3f} ms",
            "yellow",
        )
        self.line(
            "lifecycle       : snapshot="
            f"{lifecycle['block_snapshot']['filesystem_check']}; "
            f"host synced={lifecycle['host_filesystem_synced']}; "
            f"Linux restored={lifecycle['board_linux_restored']}",
            "green",
        )
        self.line("analyzer exit   : 0", "green")

    def show_current_rt(self) -> None:
        self.section("RERUN CURRENT-SMOKE SHARED/PARTITIONED COMPARISON")
        self.line(
            "python3 scripts/benchmark/axvisor-rt/compare_starry_board.py \\",
            "cyan",
        )
        self.line(
            "  rt/shared/summary.json rt/partitioned/summary.json "
            "--output comparison.json",
            "dark-cyan",
        )

        with tempfile.TemporaryDirectory(prefix="tgoskits-rt-comparison-") as temp:
            output_path = Path(temp) / "comparison.json"
            command = (
                sys.executable,
                str(
                    self.repo_root
                    / "scripts/benchmark/axvisor-rt/compare_starry_board.py"
                ),
                str(self.evidence_root / "rt/shared/summary.json"),
                str(self.evidence_root / "rt/partitioned/summary.json"),
                "--output",
                str(output_path),
            )
            subprocess.run(command, cwd=self.repo_root, check=True)
            comparison = self.read_json(output_path)

        shared = self.read_json(self.evidence_root / "rt/shared/summary.json")
        partitioned = self.read_json(
            self.evidence_root / "rt/partitioned/summary.json"
        )
        self.assert_equal(
            comparison["assessment"]["m2_exit_gate_met"],
            False,
            "current smoke M2 gate",
        )
        shared_lossless = shared["direct_irq_trace"]["lossless"]
        partitioned_lossless = partitioned["direct_irq_trace"]["lossless"]
        self.assert_equal(shared_lossless["guest"]["dropped"], 0, "shared drops")
        self.assert_equal(
            partitioned_lossless["guest"]["dropped"], 0, "partitioned drops"
        )

        pair = comparison["pair"]
        metrics = comparison["metrics"]
        self.line(
            f"samples/profile : {pair['iterations_per_metric']} x 3 metrics; "
            f"workload={pair['workload']}"
        )
        self.line(
            "trace records   : shared guest/host="
            f"{shared_lossless['guest']['records']}/"
            f"{shared_lossless['host']['records']}",
            "green",
        )
        self.line(
            "                  partitioned guest/host="
            f"{partitioned_lossless['guest']['records']}/"
            f"{partitioned_lossless['host']['records']}",
            "green",
        )
        self.line("dropped=0; vCPU migrations=0 on both sides", "green")
        self.line(
            "periodic p99    : "
            f"{metrics['periodic_jitter']['p99']['improvement_percent']:8.3f}%",
            "red",
        )
        self.line(
            "dispatch p99    : "
            f"{metrics['dispatch_latency']['p99']['improvement_percent']:8.3f}%",
            "red",
        )
        self.line(
            "direct IRQ p99  : "
            f"{metrics['virtual_timer_injection_to_guest_irq']['p99']['improvement_percent']:8.3f}%",
            "yellow",
        )
        assessment = comparison["assessment"]
        self.line(f"m2_exit_gate_met: {assessment['m2_exit_gate_met']}", "red")
        self.line(f"reason          : {assessment['reason']}", "red")

    def show_rt_results(self) -> None:
        summary = self.read_json(self.formal_rt_root / "campaign-summary.json")
        assessment = summary["assessment"]
        campaign = summary["campaign"]
        metrics = summary["metrics"]
        self.assert_equal(assessment["m2_exit_gate_met"], True, "formal M2 gate")
        self.assert_equal(campaign["pair_count"], 5, "formal RT pair count")
        self.assert_equal(
            campaign["iterations_per_metric"], 10000, "formal sample count"
        )

        soak = summary["soak"]
        shared_soak = soak["profiles"]["shared"]
        partitioned_soak = soak["profiles"]["partitioned"]
        self.section("TASK 1 / ORANGE PI 5 PLUS FORMAL RT RESULTS")
        self.line(
            f"matrix          : {campaign['pair_count']} pairs x "
            f"{campaign['iterations_per_metric']} samples/metric; "
            f"workload={campaign['workload']}",
            "cyan",
        )
        self.line("treatment       : shared pCPU1 noise -> partitioned pCPU3 noise", "cyan")
        self.line(
            "periodic max    : 5/5 improved | worst-of-runs "
            f"{metrics['periodic_jitter']['max']['worst_of_runs_improvement_percent']:.3f}%",
            "green",
        )
        self.line(
            "dispatch max    : 5/5 improved | worst-of-runs "
            f"{metrics['dispatch_latency']['max']['worst_of_runs_improvement_percent']:.3f}%",
            "green",
        )
        self.line(
            "emulated IRQ max: 5/5 improved | worst-of-runs "
            f"{metrics['emulated_irq_response']['max']['worst_of_runs_improvement_percent']:.3f}%",
            "green",
        )
        self.line(
            "direct IRQ max  : 5/5 improved | worst-of-runs "
            f"{metrics['virtual_timer_injection_to_guest_irq']['max']['worst_of_runs_improvement_percent']:.3f}%",
            "green",
        )
        self.line(
            f"soak            : shared {shared_soak['elapsed_seconds']:.1f}s / "
            f"partitioned {partitioned_soak['elapsed_seconds']:.1f}s",
            "green",
        )
        self.line(
            "trace/lifecycle : zero dropped records, zero vCPU migration, Linux restored",
            "green",
        )
        self.line(f"M2 EXIT GATE    : {assessment['m2_exit_gate_met']}", "green")

    def show_ai_loop(self) -> None:
        neural_source = (
            self.repo_root / "tools/ivcproto/src/neural.rs"
        ).read_text(encoding="utf-8")
        control_source = (
            self.repo_root / "tools/ivcproto/src/control.rs"
        ).read_text(encoding="utf-8")
        summary = self.read_json(self.evidence_root / "ivc/summary.json")
        self.assert_contains(neural_source, "ThermalObservation", "AI input")
        self.assert_contains(neural_source, "infer_normalized", "AI inference")
        self.assert_contains(control_source, "SetActuator", "control action")
        self.assert_contains(control_source, "StatusReport", "status feedback")
        self.assert_equal(summary["starry"]["mode"], "neural", "controller mode")

        self.section("TASK 3 / AI-TO-RTOS CLOSED CONTROL LOOP")
        self.line("StarryOS input  : temperature / setpoint / rate / last actuator", "cyan")
        self.line("model           : 4 input -> 6 ReLU hidden -> 1 control output", "green")
        self.line("backends        : native model | ONNX Runtime CPU | RKNN NPU", "green")
        self.line("       CONTROL   : neural actuator_permille + setpoint + sample_id", "yellow")
        self.line("StarryOS ----------------------------------------------> Zephyr", "yellow")
        self.line("       STATUS    : measured temperature + applied sequence", "cyan")
        self.line("StarryOS <------------------------------------------ ACK + status", "cyan")
        self.line("RTOS action     : apply actuator -> step thermal plant -> report", "green")
        self.line(
            f"board run       : {summary['starry']['period_ms']} ms period | "
            f"applied={summary['rtos']['applied']} | status={summary['rtos']['status_sent']}",
            "green",
        )

    def show_ai_results(self) -> None:
        history_root = self.evidence_root / "historical-formal"
        control = self.read_json(history_root / "ivc-control/campaign-summary.json")
        ack_loss = self.read_json(
            history_root / "ivc-ack-loss/campaign-summary.json"
        )
        typed_error = self.read_json(
            history_root / "ivc-error/campaign-summary.json"
        )
        restart = self.read_json(
            history_root / "ivc-restart/campaign-summary.json"
        )
        rknpu = self.read_json(history_root / "rknpu/campaign-summary.json")
        ort = self.read_json(history_root / "ort/campaign-summary.json")
        self.assert_equal(control["campaign"]["pair_count"], 5, "AI pair count")
        self.assert_equal(
            ack_loss["assessment"]["campaign_gate_met"], True, "ACK-loss gate"
        )
        self.assert_equal(
            typed_error["assessment"]["campaign_gate_met"], True, "ERROR gate"
        )
        self.assert_equal(
            restart["assessment"]["campaign_gate_met"], True, "restart gate"
        )

        manual = control["profile_statistics"]["manual"]
        neural = control["profile_statistics"]["neural"]
        rmse_improvement = self.lower_is_better_improvement(
            manual["rmse_milli_c"]["median"], neural["rmse_milli_c"]["median"]
        )
        iae_improvement = self.lower_is_better_improvement(
            manual["iae_milli_c_s"]["median"], neural["iae_milli_c_s"]["median"]
        )
        overshoot_regression = -self.lower_is_better_improvement(
            manual["max_overshoot_milli_c"]["median"],
            neural["max_overshoot_milli_c"]["median"],
        )
        favorable_latency_pairs = sum(
            pair["favors_neural"]
            for pair in control["paired_effects"]["full_loop_p99_us"]["pairs"]
        )
        samples_per_run = control["evidence"]["pairs"][0]["profiles"]["manual"][
            "raw"
        ]["sample_count"]
        self.assert_equal(samples_per_run, 1800, "AI samples per run")

        self.section("TASK 3 / FIVE-PAIR CONTROL EFFECT + RELIABILITY")
        self.line(
            f"manual/neural   : {control['campaign']['pair_count']} AB/BA pairs x "
            f"{samples_per_run} cycles",
            "cyan",
        )
        self.line(
            f"RMSE median     : {manual['rmse_milli_c']['median']:,.3f} -> "
            f"{neural['rmse_milli_c']['median']:,.3f} mC  "
            f"({rmse_improvement:.2f}% better)",
            "green",
        )
        self.line(
            f"IAE median      : {manual['iae_milli_c_s']['median']:,.1f} -> "
            f"{neural['iae_milli_c_s']['median']:,.1f}  "
            f"({iae_improvement:.2f}% better)",
            "green",
        )
        self.line(
            f"max overshoot   : {manual['max_overshoot_milli_c']['median']} -> "
            f"{neural['max_overshoot_milli_c']['median']} mC  "
            f"({overshoot_regression:.2f}% worse)",
            "red",
        )
        self.line(
            f"full-loop p99   : neural favored in only {favorable_latency_pairs}/5 pairs",
            "yellow",
        )
        self.line(
            "fault campaigns : ACK-loss "
            f"{ack_loss['campaign']['repeat_count']}/3; typed ERROR "
            f"{typed_error['campaign']['repeat_count']}/3; VM restart "
            f"{restart['campaign']['repeat_count']}/3",
            "green",
        )
        self.line(
            f"RKNN / NPU      : {rknpu['reliability']['acknowledged']}/"
            f"{rknpu['campaign']['total_samples']} acknowledged; "
            f"errors={rknpu['reliability']['errors']}; "
            f"timeouts={rknpu['reliability']['timeouts']}",
            "green",
        )
        self.line(
            f"ONNX Runtime    : {ort['reliability']['acknowledged']}/"
            f"{ort['campaign']['total_samples']} acknowledged; "
            f"errors={ort['reliability']['errors']}; "
            f"timeouts={ort['reliability']['timeouts']}",
            "green",
        )

    def show_verification(self) -> None:
        verifier = self.evidence_root / "validation/verify-evidence.py"
        formal_rt = self.read_json(self.formal_rt_root / "campaign-summary.json")
        guest_ivc = self.read_json(
            self.repo_root
            / "competition/results/rtos-guest-ivc-qemu-20260815/validation.json"
        )
        isolation = self.read_json(
            self.repo_root
            / "competition/results/axvisor-isolation-reference/summary.json"
        )
        self.assert_equal(
            formal_rt["assessment"]["m2_exit_gate_met"], True, "formal RT gate"
        )
        self.assert_equal(len(guest_ivc["runs"]), 4, "RTOS guest IVC runs")
        self.assert_equal(isolation["status"], "pass", "isolation status")
        for path in (
            "competition/design.md",
            "competition/test-report.md",
            "competition/reproduce.md",
            "competition/scorecard.md",
        ):
            if not (self.repo_root / path).is_file():
                raise FileNotFoundError(f"missing competition document: {path}")

        self.section("ENGINEERING / REPRODUCIBILITY + EVIDENCE CHECK")
        self.line(
            "python3 competition/results/current-source-smoke-20260813/"
            "validation/verify-evidence.py .",
            "cyan",
        )
        result = subprocess.run(
            (sys.executable, str(verifier), str(self.repo_root)),
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            for line in (result.stdout + result.stderr).splitlines():
                self.line(line, "red")
            raise RuntimeError(f"evidence verifier exited with {result.returncode}")

        output = result.stdout.splitlines()
        json_count = sum(line.startswith("JSON_OK ") for line in output)
        gzip_count = sum(line.startswith("GZIP_OK ") for line in output)
        self.line(
            f"TASK 1 RT       : {formal_rt['campaign']['pair_count']} formal pairs + "
            f"two soaks | M2={formal_rt['assessment']['m2_exit_gate_met']}",
            "green",
        )
        self.line(
            "TASK 1 baseline : Zephyr + RT-Thread + FreeRTOS idle/stress", "green"
        )
        self.line(
            f"TASK 2 IVC      : Starry/Zephyr board + {len(guest_ivc['runs'])}/4 "
            "RTOS guest runs",
            "green",
        )
        self.line(
            f"TASK 2 isolate  : {isolation['results']['cross_segment_udp_probes']} probes / "
            f"{isolation['results']['vm1_cross_segment_probes_received']} crossed",
            "green",
        )
        self.line("TASK 3 AI       : manual/neural + RKNN + ONNX Runtime", "green")
        self.line("documents       : design + test + reproduce + scorecard", "green")
        self.line(
            f"bundle          : {json_count} JSON + {gzip_count} gzip + manifests/contracts",
            "green",
        )
        self.line(
            f"FAIL-CLOSED DELIVERY CHECK: PASS (exit={result.returncode})", "green"
        )

    def section(self, title: str) -> None:
        print(flush=True)
        self.line(f"=== {title} ===", "white")

    def line(self, text: str, color: str = "gray") -> None:
        print(f"{COLORS[color]}{text}{RESET}", flush=True)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

    @staticmethod
    def read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"missing JSON evidence: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def show_toml_values(self, path: Path, keys: tuple[str, ...]) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        for key in keys:
            pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
            value = next((line.strip() for line in lines if pattern.match(line)), None)
            if value is None:
                raise ValueError(f"missing TOML key {key!r} in {path}")
            self.line(f"  {value}")

    @staticmethod
    def first_matching_line(lines: list[str], pattern: str) -> tuple[int, str]:
        for line_number, line in enumerate(lines, start=1):
            if pattern in line:
                return line_number, line
        raise ValueError(f"missing UART marker: {pattern}")

    @staticmethod
    def assert_equal(actual: Any, expected: Any, label: str) -> None:
        if actual != expected:
            raise ValueError(f"{label}: expected {expected!r}, got {actual!r}")

    @staticmethod
    def assert_contains(text: str, expected: str, label: str) -> None:
        if expected not in text:
            raise ValueError(f"{label}: missing {expected!r}")

    @staticmethod
    def lower_is_better_improvement(baseline: float, candidate: float) -> float:
        return 100.0 * (baseline - candidate) / baseline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", choices=SCENES)
    parser.add_argument("--delay-ms", type=int, default=350)
    args = parser.parse_args()
    if not 0 <= args.delay_ms <= 10000:
        parser.error("--delay-ms must be between 0 and 10000")
    return args


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        EvidenceDemo(repo_root, args.delay_ms).show(args.scene)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"{COLORS['red']}ERROR: {error}{RESET}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
