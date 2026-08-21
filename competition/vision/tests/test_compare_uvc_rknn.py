from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


COMPARATOR_PATH = Path(__file__).resolve().parents[1] / "compare_uvc_rknn.py"
SPEC = importlib.util.spec_from_file_location("compare_uvc_rknn", COMPARATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
comparator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comparator
SPEC.loader.exec_module(comparator)


def summary(
    run: int,
    *,
    infer_fps: float,
    infer_p95_ms: float,
    npu_p95_ms: float,
    core_mask: str = "all",
    model_sha256: str = "a" * 64,
    dropped_latest_percent: float = 0.25,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence_type": "orangepi-5-plus-uvc-rknn",
        "source": {
            "log_sha256": f"{run:064x}",
            "model_sha256": model_sha256,
        },
        "configuration": {
            "device": 0,
            "capture_width": 640,
            "capture_height": 480,
            "fps": 30,
            "duration": 60,
            "infer_every": 1,
            "report_interval": 5,
            "min_confidence": 25,
            "core_mask": core_mask,
            "profile": 1,
            "profile_frames": 0,
        },
        "benchmark": {
            "capture_fps": 30.0,
            "infer_fps": infer_fps,
            "decode_ms_p95": 2.0,
            "infer_ms_p95": infer_p95_ms,
            "vm_rss_kb": 50000,
            "vm_hwm_kb": 52000,
        },
        "profile": {"rknn_perf_run_ms_p95": npu_p95_ms},
        "derived": {"dropped_latest_percent": dropped_latest_percent},
        "acceptance": {"passed": True, "contract": "profiled-uvc-rknn-v1"},
    }


class UvcRknnComparisonTests(unittest.TestCase):
    def write_summary(self, value: dict[str, object]) -> Path:
        temporary = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        )
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        with temporary:
            json.dump(value, temporary)
        return Path(temporary.name)

    def campaign(self) -> tuple[list[Path], list[Path]]:
        baseline = [
            self.write_summary(
                summary(index, infer_fps=20.0, infer_p95_ms=25.0, npu_p95_ms=15.0)
            )
            for index in range(1, 6)
        ]
        candidate = [
            self.write_summary(
                summary(index, infer_fps=22.0, infer_p95_ms=20.0, npu_p95_ms=12.0)
            )
            for index in range(101, 106)
        ]
        return baseline, candidate

    def test_five_pair_comparison_reports_direction_and_worst_case(self) -> None:
        baseline, candidate = self.campaign()

        result = comparator.compare(
            baseline,
            candidate,
            baseline_label="starry-bare-core0",
            candidate_label="starry-bare-all",
            min_runs=5,
        )

        self.assertTrue(result["acceptance"]["passed"])
        self.assertEqual(result["pairs"], 5)
        infer_fps = result["metrics"]["infer_fps"]
        self.assertEqual(infer_fps["direction"], "higher_is_better")
        self.assertAlmostEqual(infer_fps["paired_improvement_percent_median"], 10.0)
        self.assertEqual(infer_fps["favorable_pairs"], 5)
        infer_p95 = result["metrics"]["infer_ms_p95"]
        self.assertEqual(infer_p95["direction"], "lower_is_better")
        self.assertAlmostEqual(infer_p95["paired_improvement_percent_median"], 20.0)
        self.assertEqual(infer_p95["candidate"]["worst"], 20.0)

    def test_duplicate_log_cannot_be_counted_as_multiple_runs(self) -> None:
        baseline, candidate = self.campaign()
        duplicated = json.loads(baseline[0].read_text(encoding="utf-8"))
        baseline[1].write_text(json.dumps(duplicated), encoding="utf-8")

        with self.assertRaisesRegex(comparator.ComparisonError, "duplicate log"):
            comparator.compare(
                baseline,
                candidate,
                baseline_label="baseline",
                candidate_label="candidate",
                min_runs=5,
            )

    def test_model_mismatch_is_rejected(self) -> None:
        baseline, candidate = self.campaign()
        changed = json.loads(candidate[0].read_text(encoding="utf-8"))
        changed["source"]["model_sha256"] = "b" * 64
        candidate[0].write_text(json.dumps(changed), encoding="utf-8")

        with self.assertRaisesRegex(comparator.ComparisonError, "model_sha256"):
            comparator.compare(
                baseline,
                candidate,
                baseline_label="baseline",
                candidate_label="candidate",
                min_runs=5,
            )

    def test_core_mask_drift_requires_an_explicit_vary_dimension(self) -> None:
        baseline, candidate = self.campaign()
        for path in candidate:
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["configuration"]["core_mask"] = "core0"
            path.write_text(json.dumps(changed), encoding="utf-8")

        with self.assertRaisesRegex(comparator.ComparisonError, "core_mask"):
            comparator.compare(
                baseline,
                candidate,
                baseline_label="all",
                candidate_label="core0",
                min_runs=5,
            )

        result = comparator.compare(
            baseline,
            candidate,
            baseline_label="all",
            candidate_label="core0",
            min_runs=5,
            vary=("core_mask",),
        )
        self.assertEqual(result["varied_dimensions"], ["core_mask"])

    def test_too_few_runs_are_rejected(self) -> None:
        baseline, candidate = self.campaign()

        with self.assertRaisesRegex(comparator.ComparisonError, "at least 5"):
            comparator.compare(
                baseline[:3],
                candidate[:3],
                baseline_label="baseline",
                candidate_label="candidate",
                min_runs=5,
            )

    def test_zero_drop_baseline_does_not_make_the_campaign_unreportable(self) -> None:
        baseline, candidate = self.campaign()
        for path in baseline + candidate:
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["derived"]["dropped_latest_percent"] = 0.0
            path.write_text(json.dumps(changed), encoding="utf-8")
        changed = json.loads(candidate[0].read_text(encoding="utf-8"))
        changed["derived"]["dropped_latest_percent"] = 0.5
        candidate[0].write_text(json.dumps(changed), encoding="utf-8")

        result = comparator.compare(
            baseline,
            candidate,
            baseline_label="baseline",
            candidate_label="candidate",
            min_runs=5,
        )

        dropped = result["metrics"]["dropped_latest_percent"]
        self.assertEqual(dropped["undefined_percentage_pairs"], 1)
        self.assertIsNone(dropped["paired_improvement_percent"][0])
        self.assertEqual(dropped["non_regressed_pairs"], 4)


if __name__ == "__main__":
    unittest.main()
