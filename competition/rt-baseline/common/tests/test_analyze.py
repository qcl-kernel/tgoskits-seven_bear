#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the shared native-RTOS evidence analyzer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON_DIR))

import analyze  # noqa: E402


def load_record(
    *,
    workload: str,
    accounting: str,
    benchmark_permille: int,
    idle_permille: int,
    stress_permille: int = 0,
    stress_blocks: int = 0,
    stress_blocks_per_second: int = 0,
    stress_checksum: int = 0,
) -> dict[str, str]:
    """Build one complete scheduler-accounting record."""
    non_idle_permille = 1000 - idle_permille
    return {
        "schema": "1",
        "workload": workload,
        "verified": "true",
        "accounting": accounting,
        "window_duration_us": "10000000",
        "cpu_non_idle_permille": str(non_idle_permille),
        "cpu_idle_permille": str(idle_permille),
        "benchmark_permille": str(benchmark_permille),
        "stress_permille": str(stress_permille),
        "stress_blocks": str(stress_blocks),
        "stress_blocks_per_second": str(stress_blocks_per_second),
        "stress_checksum": str(stress_checksum),
    }


class MarkerParsingTests(unittest.TestCase):
    """Check serial framing quirks without weakening marker matching."""

    def test_accepts_leading_bao_nul_before_exact_marker(self) -> None:
        record = analyze.parse_record(
            "\x00RTOS_BASELINE_COMPLETE schema=1 status=pass",
            "RTOS_BASELINE_COMPLETE",
        )

        self.assertEqual(record, {"schema": "1", "status": "pass"})

    def test_rejects_marker_embedded_in_unrelated_text(self) -> None:
        record = analyze.parse_record(
            "prefix RTOS_BASELINE_COMPLETE schema=1 status=pass",
            "RTOS_BASELINE_COMPLETE",
        )

        self.assertIsNone(record)


class LoadValidationTests(unittest.TestCase):
    """Check the intentionally different RT-Thread and FreeRTOS counters."""

    def test_rtthread_accepts_sub_tick_benchmark_execution(self) -> None:
        record = load_record(
            workload="idle",
            accounting="rt-thread-tick-hook",
            benchmark_permille=0,
            idle_permille=1000,
        )

        result = analyze.validate_load(
            record, "idle", analyze.RTOS_SPECS["rt-thread"]
        )

        self.assertEqual(result["benchmark_permille"], 0)
        self.assertEqual(result["cpu_idle_permille"], 1000)

    def test_freertos_rejects_unmeasured_benchmark_execution(self) -> None:
        record = load_record(
            workload="idle",
            accounting="freertos-runtime-counter",
            benchmark_permille=0,
            idle_permille=999,
        )

        with self.assertRaisesRegex(
            analyze.AnalysisError, "benchmark execution was not measured"
        ):
            analyze.validate_load(
                record, "idle", analyze.RTOS_SPECS["freertos"]
            )

    def test_stress_requires_nonzero_checksum(self) -> None:
        record = load_record(
            workload="cpu-stress",
            accounting="freertos-runtime-counter",
            benchmark_permille=1,
            idle_permille=10,
            stress_permille=989,
            stress_blocks=10_000,
            stress_blocks_per_second=1_000,
            stress_checksum=0,
        )

        with self.assertRaisesRegex(analyze.AnalysisError, "stress was not sustained"):
            analyze.validate_load(
                record, "cpu-stress", analyze.RTOS_SPECS["freertos"]
            )


class CompletionValidationTests(unittest.TestCase):
    """Check completion counters that prevent silently truncated runs."""

    @staticmethod
    def completion(**overrides: str) -> dict[str, str]:
        record = {
            "schema": "1",
            "workload": "idle",
            "status": "pass",
            "timer_misses": "0",
            "warmup_timer_misses": "0",
            "early_wakes": "0",
        }
        record.update(overrides)
        return record

    def test_rejects_early_wake(self) -> None:
        with self.assertRaisesRegex(analyze.AnalysisError, "early wake"):
            analyze.validate_complete(self.completion(early_wakes="1"), "idle")

    def test_accepts_exact_sample_window_boundaries(self) -> None:
        result = analyze.validate_complete(
            self.completion(timer_misses="10000", warmup_timer_misses="99"),
            "idle",
        )

        self.assertEqual(result["timer_misses"], 10_000)
        self.assertEqual(result["warmup_timer_misses"], 99)


if __name__ == "__main__":
    unittest.main()
