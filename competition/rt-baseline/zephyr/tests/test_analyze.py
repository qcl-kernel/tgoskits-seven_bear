#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Deterministic contract tests for native Zephyr evidence analysis."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import analyze  # noqa: E402
import analyze_board  # noqa: E402


class OrangePiContractTests(unittest.TestCase):
    """Check the strict RK3588 short and soak measurement contracts."""

    def test_short_and_soak_profiles_keep_the_same_bounded_sample_count(self) -> None:
        self.assertEqual(analyze_board.expected_duration_us("short"), 10_000_000)
        self.assertEqual(analyze_board.expected_duration_us("soak"), 1_800_000_000)
        self.assertEqual(analyze_board.SAMPLE_COUNT, 10_000)

    def test_board_contract_rejects_the_qemu_platform_identity(self) -> None:
        record = {
            **analyze_board.expected_config("short"),
            "workload": "idle",
            "board": "qemu_cortex_a53",
        }

        with self.assertRaisesRegex(analyze.AnalysisError, "board must be"):
            analyze.validate_config(
                record,
                "idle",
                analyze_board.expected_config("short"),
            )

    def test_soak_results_require_the_full_thirty_minute_window(self) -> None:
        base = {
            "schema": "1",
            "workload": "cpu-stress",
            "unit": "ns",
            "count": "10000",
            "min_ns": "1",
            "mean_ns": "2",
            "p50_ns": "2",
            "p90_ns": "3",
            "p99_ns": "4",
            "p999_ns": "5",
            "max_ns": "6",
            "actual_duration_us": "1799999999",
            "expected_duration_us": "1800000000",
        }
        records = [
            {**base, "metric": "periodic_wake_lateness"},
            {**base, "metric": "timer_to_task_dispatch"},
        ]

        with self.assertRaisesRegex(analyze.AnalysisError, "shorter than requested"):
            analyze.validate_results(
                records,
                "cpu-stress",
                sample_count=10_000,
                expected_duration_us=1_800_000_000,
            )

    @staticmethod
    def result_line(metric: str, replay: int, maximum: int = 6) -> str:
        return (
            "RTOS_BASELINE_RESULT schema=1 workload=idle "
            f"metric={metric} unit=ns count=10000 min_ns=1 mean_ns=2 "
            "p50_ns=2 p90_ns=3 p99_ns=4 p999_ns=5 "
            f"max_ns={maximum} actual_duration_us=10000000 "
            f"expected_duration_us=10000000 replay={replay}"
        )

    def test_board_result_replays_ignore_an_incomplete_copy(self) -> None:
        lines = [
            self.result_line("periodic_wake_lateness", replay)
            for replay in (1, 2, 3)
        ]
        lines.extend(
            self.result_line("timer_to_task_dispatch", replay)
            for replay in (1, 2, 3)
        )
        lines[0] = lines[0].replace("p999_ns=5 ", "")

        selected, evidence = analyze_board.select_result_replays(lines, "idle")

        self.assertEqual(len(selected), 2)
        self.assertEqual(evidence["incomplete_copies"], 1)
        self.assertEqual(
            evidence["complete_copies"]["periodic_wake_lateness"], 2
        )

    def test_board_result_replays_reject_complete_conflicts(self) -> None:
        lines = [
            self.result_line("periodic_wake_lateness", 1),
            self.result_line("periodic_wake_lateness", 2, maximum=7),
            self.result_line("timer_to_task_dispatch", 1),
        ]

        with self.assertRaisesRegex(analyze.AnalysisError, "conflicting complete"):
            analyze_board.select_result_replays(lines, "idle")

    def test_board_record_replays_ignore_an_incomplete_copy(self) -> None:
        complete = (
            "RTOS_BASELINE_COMPLETE schema=1 workload=idle status=pass "
            "timer_misses=0 warmup_timer_misses=0 early_wakes=0"
        )
        lines = [
            f"{complete} replay=1",
            f"{complete} replay=2",
            "RTOS_BASELINE_COMPLETE schema=1 workload=idle status=pass replay=3",
        ]

        selected, evidence = analyze_board.select_record_replays(
            lines,
            "RTOS_BASELINE_COMPLETE",
            analyze_board.COMPLETE_REQUIRED_FIELDS,
        )

        self.assertNotIn("replay", selected)
        self.assertEqual(evidence["complete_copies"], 2)
        self.assertEqual(evidence["complete_replays"], [1, 2])
        self.assertEqual(evidence["incomplete_copies"], 1)

    def test_board_record_replays_reject_complete_conflicts(self) -> None:
        common = (
            "RTOS_BASELINE_LOAD schema=1 workload=idle verified=true "
            "window_duration_us=10000000 cpu_non_idle_permille=0 "
            "cpu_idle_permille=999 benchmark_permille=0 stress_permille=0 "
            "stress_blocks=0 stress_blocks_per_second=0 cpu_cycles=240000000 "
            "idle_cycles=239000000 stress_cycles=0"
        )
        lines = [
            f"{common} benchmark_cycles=100 replay=1",
            f"{common} benchmark_cycles=101 replay=2",
        ]

        with self.assertRaisesRegex(analyze.AnalysisError, "conflicting complete"):
            analyze_board.select_record_replays(
                lines,
                "RTOS_BASELINE_LOAD",
                analyze_board.LOAD_REQUIRED_FIELDS,
            )

    def test_board_config_requires_the_record_replay_contract(self) -> None:
        config = analyze_board.expected_config("short")

        self.assertEqual(config["record_replays"], "3")
        self.assertEqual(config["record_tx_chunk_bytes"], "16")
        self.assertEqual(config["record_tx_chunk_delay_ms"], "5")

    def test_board_load_accepts_measured_cycles_below_one_permille(self) -> None:
        record = {
            "schema": "1",
            "workload": "idle",
            "verified": "true",
            "window_duration_us": "10000000",
            "cpu_non_idle_permille": "0",
            "cpu_idle_permille": "999",
            "benchmark_permille": "0",
            "stress_permille": "0",
            "stress_blocks": "0",
            "stress_blocks_per_second": "0",
            "benchmark_cycles": "42",
        }

        load = analyze.validate_load(
            record, "idle", allow_sub_permille_benchmark=True
        )

        self.assertEqual(load["benchmark_cycles"], 42)


class CompletionValidationTests(unittest.TestCase):
    """Check the exact measured and warm-up miss bounds."""

    @staticmethod
    def completion(timer_misses: int, warmup_timer_misses: int) -> dict[str, str]:
        return {
            "schema": "1",
            "workload": "idle",
            "status": "pass",
            "timer_misses": str(timer_misses),
            "warmup_timer_misses": str(warmup_timer_misses),
            "early_wakes": "0",
        }

    def test_accepts_full_measured_window_boundary(self) -> None:
        completion = analyze.validate_complete(
            self.completion(timer_misses=10_000, warmup_timer_misses=99), "idle"
        )

        self.assertEqual(completion["timer_misses"], 10_000)
        self.assertEqual(completion["warmup_timer_misses"], 99)

    def test_rejects_more_misses_than_either_window_can_contain(self) -> None:
        invalid_counts = ((10_001, 0), (0, 100))

        for timer_misses, warmup_timer_misses in invalid_counts:
            with self.subTest(
                timer_misses=timer_misses,
                warmup_timer_misses=warmup_timer_misses,
            ):
                with self.assertRaisesRegex(
                    analyze.AnalysisError, "invalid timer miss count"
                ):
                    analyze.validate_complete(
                        self.completion(timer_misses, warmup_timer_misses), "idle"
                    )


class SourceCleanlinessTests(unittest.TestCase):
    """Check source cleanliness by content instead of filesystem stat noise."""

    def test_ignores_a_status_false_positive_when_content_is_unchanged(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> mock.Mock:
            if "status" in command:
                return mock.Mock(returncode=0, stdout=" M arch/arm64/core/fatal.c\n")
            if "ls-files" in command:
                return mock.Mock(returncode=0, stdout="")
            return mock.Mock(returncode=0, stdout="")

        with mock.patch.object(analyze.subprocess, "run", side_effect=fake_run):
            analyze.require_clean_source(Path("zephyr"))

    def test_rejects_a_tracked_content_change(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> mock.Mock:
            changed = "diff" in command and "--cached" not in command
            return mock.Mock(returncode=1 if changed else 0, stdout="")

        with (
            mock.patch.object(analyze.subprocess, "run", side_effect=fake_run),
            self.assertRaisesRegex(analyze.AnalysisError, "not clean"),
        ):
            analyze.require_clean_source(Path("zephyr"))

    def test_rejects_an_untracked_file(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> mock.Mock:
            stdout = "unexpected.txt\n" if "ls-files" in command else ""
            return mock.Mock(returncode=0, stdout=stdout)

        with (
            mock.patch.object(analyze.subprocess, "run", side_effect=fake_run),
            self.assertRaisesRegex(analyze.AnalysisError, "not clean"),
        ):
            analyze.require_clean_source(Path("zephyr"))


class SourceProvenanceTests(unittest.TestCase):
    """Check that recorded provenance describes the named Git index exactly."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.zephyr_base = self.root / "zephyr"
        self.zephyr_base.mkdir()
        self.index_path = self.root / "index"
        self.index_path.write_bytes(b"deterministic git index fixture\n")
        self.raw_log = self.root / "qemu.log"
        self.raw_log.write_text("measured run\n", encoding="utf-8")
        self.provenance_path = self.root / "source-provenance.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_provenance(self, git_index: dict[str, object]) -> None:
        provenance = {
            "schema_version": 1,
            "zephyr_base": str(self.zephyr_base.resolve()),
            "source": {
                **analyze.EXPECTED_SOURCE,
                "worktree": "clean",
                "core_autocrlf": "unset",
            },
            "git_index": git_index,
        }
        self.provenance_path.write_text(
            json.dumps(provenance), encoding="utf-8"
        )
        os.utime(self.raw_log, (1_000, 1_000))
        os.utime(self.provenance_path, (1_001, 1_001))

    def load(self) -> tuple[dict[str, str], dict[str, object]]:
        with (
            mock.patch.object(
                analyze, "source_identity", return_value=analyze.EXPECTED_SOURCE
            ),
            mock.patch.object(
                analyze, "git_index_path", return_value=self.index_path
            ),
        ):
            return analyze.load_source_provenance(
                self.provenance_path, self.zephyr_base, self.raw_log
            )

    def test_accepts_exact_index_artifact(self) -> None:
        self.write_provenance(analyze.artifact(self.index_path, ".git/index"))

        source, provenance_artifact = self.load()

        self.assertEqual(source["worktree"], "clean")
        self.assertEqual(provenance_artifact["path"], "source-provenance.json")

    def test_rejects_index_metadata_for_a_differently_named_file(self) -> None:
        git_index = analyze.artifact(self.index_path, ".git/not-the-index")
        self.write_provenance(git_index)

        with self.assertRaisesRegex(
            analyze.AnalysisError, "index metadata does not match"
        ):
            self.load()

    def test_rejects_incorrect_index_byte_count(self) -> None:
        git_index = analyze.artifact(self.index_path, ".git/index")
        git_index["bytes"] = int(git_index["bytes"]) + 1
        self.write_provenance(git_index)

        with self.assertRaisesRegex(
            analyze.AnalysisError, "index metadata does not match"
        ):
            self.load()


if __name__ == "__main__":
    unittest.main()
