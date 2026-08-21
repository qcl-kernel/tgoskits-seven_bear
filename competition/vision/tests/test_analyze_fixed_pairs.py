from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ANALYZER_PATH = Path(__file__).resolve().parents[1] / "analyze_fixed_pairs.py"
SPEC = importlib.util.spec_from_file_location("analyze_fixed_pairs", ANALYZER_PATH)
assert SPEC is not None and SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)


MODEL_SHA256 = "4" * 64


def campaign_log(*, compact: bool = True) -> str:
    lines = [
        "VISION_FIXED_CAMPAIGN_BEGIN os=starry pairs=5",
        f"VISION_FIXED_MODEL_SHA256 {MODEL_SHA256}",
    ]
    for pair in range(1, 6):
        order = "AB" if pair % 2 else "BA"
        masks = ("0", "all") if order == "AB" else ("all", "0")
        for core_mask in masks:
            base = 40.0 + pair if core_mask == "0" else 35.0 + pair
            lines.append(
                "VISION_FIXED_RUN_BEGIN "
                f"pair={pair} order={order} core_mask={core_mask}"
            )
            if compact:
                identity = f"pair={pair} core={core_mask}"
                lines.append(
                    f"VISION_FIXED_CHECK {identity} samples=3 query_errors=0"
                )
                compact_metrics = {
                    "total_avg": base,
                    "total_p95": base + 2,
                    "letterbox_avg": 10.0,
                    "letterbox_p95": 11.0,
                    "npu_avg": base - 12,
                    "npu_p95": base - 10,
                }
                lines.extend(
                    f"VISION_FIXED_VALUE {identity} metric={metric} value={value:.2f}"
                    for metric, value in compact_metrics.items()
                )
            else:
                lines.append(
                    "UVC_RKNN_BENCH_PROFILE_RESULT "
                    "profile_samples=3 perf_run_query_errors=0 "
                    f"total_ms_avg={base:.2f} total_ms_p95={base + 2:.2f} "
                    "letterbox_ms_avg=10.00 letterbox_ms_p95=11.00 "
                    f"rknn_perf_run_ms_avg={base - 12:.2f} "
                    f"rknn_perf_run_ms_p95={base - 10:.2f}"
                )
            lines.append("UVC_RKNN_VALIDATE_PASS images=3")
            lines.append(
                f"VISION_FIXED_RUN_END pair={pair} core_mask={core_mask}"
            )
    lines.append("VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5")
    return "\n".join(lines) + "\n"


class FixedPairAnalysisTests(unittest.TestCase):
    def test_compact_five_pair_campaign_reports_paired_improvement(self) -> None:
        result = analyzer.analyze_text(campaign_log(), expected_os="starry")

        self.assertTrue(result["acceptance"]["passed"])
        self.assertEqual(result["pairs"], 5)
        self.assertEqual(result["model_sha256"], MODEL_SHA256)
        total = result["metrics"]["total_ms_avg"]
        self.assertEqual(total["core0"]["median"], 43.0)
        self.assertEqual(total["all"]["median"], 38.0)
        self.assertEqual(total["all"]["worst"], 40.0)
        self.assertEqual(total["favorable_pairs"], 5)
        self.assertAlmostEqual(
            total["paired_improvement_percent_median"],
            500.0 / 43.0,
        )

    def test_full_linux_profile_lines_are_accepted(self) -> None:
        log = campaign_log(compact=False).replace("os=starry", "os=linux")

        result = analyzer.analyze_text(log, expected_os="linux")

        self.assertTrue(result["acceptance"]["passed"])
        self.assertEqual(result["os"], "linux")

    def test_known_starry_shell_prompt_before_done_marker_is_normalized(self) -> None:
        log = campaign_log().replace(
            f"VISION_FIXED_MODEL_SHA256 {MODEL_SHA256}",
            "root@starry:/home/orangepi/rknn_yolov8_image # "
            "root@starry:/home/orangepi/rknn_yolov8_image # > > "
            f"VISION_FIXED_MODEL_SHA256 {MODEL_SHA256}",
        ).replace(
            "VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5",
            "root@starry:/home/orangepi/rknn_yolov8_image # "
            "VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5",
        )

        result = analyzer.analyze_text(log, expected_os="starry")

        self.assertTrue(result["acceptance"]["passed"])

    def test_unknown_prefix_before_done_marker_is_rejected(self) -> None:
        log = campaign_log().replace(
            "VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5",
            "damaged-prefix VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5",
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "done marker"):
            analyzer.analyze_text(log, expected_os="starry")

    def test_missing_validation_marker_is_rejected(self) -> None:
        log = campaign_log().replace(
            "UVC_RKNN_VALIDATE_PASS images=3\n", "", 1
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "validation"):
            analyzer.analyze_text(log, expected_os="starry")

    def test_duplicate_pair_and_core_mask_is_rejected(self) -> None:
        log = campaign_log()
        duplicate = "\n".join(log.splitlines()[2:6]) + "\n"
        log = log.replace(
            "VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5\n",
            duplicate + "VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5\n",
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "duplicate"):
            analyzer.analyze_text(log, expected_os="starry")

    def test_preregistered_pair_order_drift_is_rejected(self) -> None:
        log = campaign_log().replace(
            "pair=2 order=BA core_mask=all",
            "pair=2 order=AB core_mask=all",
            1,
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "order"):
            analyzer.analyze_text(log, expected_os="starry")

    def test_profile_query_error_is_rejected(self) -> None:
        log = campaign_log().replace(
            "query_errors=0", "query_errors=1", 1
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "query"):
            analyzer.analyze_text(log, expected_os="starry")


if __name__ == "__main__":
    unittest.main()
