from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ANALYZER_PATH = Path(__file__).resolve().parents[1] / "analyze_uvc_rknn.py"
SPEC = importlib.util.spec_from_file_location("analyze_uvc_rknn", ANALYZER_PATH)
assert SPEC is not None and SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)


CONFIG_TEMPLATE = (
    "model=./model/yolov8.rknn label=./model/coco_80_labels_list.txt "
    "device=0 size=640x480 fps=30 duration=60 infer_every=1 "
    "report_interval=5 min_confidence={min_confidence} core_mask=all "
    "profile=1 profile_frames=0 validate_list={validate_list} "
    "expected={expected} write_expected=none"
)

PROFILE_TEMPLATE = (
    "UVC_RKNN_BENCH_PROFILE_RESULT profile_samples={samples} "
    "perf_run_query_errors=0 total_ms_avg=18.00 total_ms_p50=17.50 "
    "total_ms_p95=20.00 malloc_ms_avg=0.10 letterbox_ms_avg=2.00 "
    "letterbox_ms_p50=1.90 letterbox_ms_p95=2.20 inputs_set_ms_avg=0.10 "
    "run_ms_avg=11.00 run_ms_p50=10.80 run_ms_p95=12.00 "
    "outputs_get_ms_avg=2.00 outputs_get_ms_p50=1.90 "
    "outputs_get_ms_p95=2.20 rknn_perf_run_ms_avg=9.00 "
    "rknn_perf_run_ms_p50=8.80 rknn_perf_run_ms_p95=10.00 "
    "postprocess_ms_avg=2.50 postprocess_ms_p50=2.40 "
    "postprocess_ms_p95=2.80 outputs_release_ms_avg=0.20"
)

RESULT = (
    "UVC_RKNN_BENCH_RESULT duration_sec=60.0 captured=1805 "
    "capture_fps=30.08 inferences=1800 infer_fps=30.00 bytes=62914560 "
    "throughput_mib_s=1.00 dropped_latest=5 decode_errors=0 "
    "inference_errors=0 decode_ms_avg=2.00 decode_ms_p50=1.90 "
    "decode_ms_p95=2.20 infer_ms_avg=18.00 infer_ms_p50=17.50 "
    "infer_ms_p95=20.00 detections=900 vm_size_kb=200000 "
    "vm_rss_kb=50000 vm_hwm_kb=52000 mem_total_kb=524288 "
    "mem_free_kb=200000 mem_available_kb=300000"
)


def valid_log() -> str:
    validation_config = CONFIG_TEMPLATE.format(
        min_confidence=25,
        validate_list="validation/images.txt",
        expected="validation/expected.txt",
    )
    benchmark_config = CONFIG_TEMPLATE.format(
        min_confidence=25,
        validate_list="none",
        expected="none",
    )
    return "\n".join(
        (
            "UVC_RKNN_BENCH_BEGIN",
            validation_config,
            "bench-rknn: init_yolov8_model success width=640 height=640 channel=3",
            "bench-rknn: set_core_mask=all ret=0",
            "UVC_RKNN_VALIDATE_BEGIN images=3 mode=verify",
            PROFILE_TEMPLATE.format(samples=3),
            "UVC_RKNN_VALIDATE_PASS images=3",
            benchmark_config,
            "bench-rknn: init_yolov8_model success width=640 height=640 channel=3",
            "bench-rknn: set_core_mask=all ret=0",
            RESULT,
            PROFILE_TEMPLATE.format(samples=1800),
            "UVC_RKNN_BENCH_DONE",
            "",
        )
    )


class UvcRknnAnalysisTests(unittest.TestCase):
    def write_text(self, contents: str) -> Path:
        temporary = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        )
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        with temporary:
            temporary.write(contents)
        return Path(temporary.name)

    def write_model(self, contents: bytes = b"deterministic-rknn-model") -> Path:
        temporary = tempfile.NamedTemporaryFile(delete=False)
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        with temporary:
            temporary.write(contents)
        return Path(temporary.name)

    def test_valid_profiled_run_is_bound_to_log_and_model(self) -> None:
        log = self.write_text(valid_log())
        model = self.write_model()

        result = analyzer.analyze(
            log,
            model_artifact=model,
            expected_duration_sec=60.0,
            expected_validation_images=3,
        )

        self.assertEqual(result["schema_version"], 1)
        self.assertTrue(result["acceptance"]["passed"])
        self.assertEqual(result["validation"]["images"], 3)
        self.assertEqual(result["benchmark"]["inferences"], 1800)
        self.assertEqual(result["configuration"]["core_mask"], "all")
        self.assertEqual(result["profile"]["profile_samples"], 1800)
        self.assertAlmostEqual(result["derived"]["dropped_latest_percent"], 0.277, places=3)
        self.assertEqual(
            result["source"]["log_sha256"],
            hashlib.sha256(log.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            result["source"]["model_sha256"],
            hashlib.sha256(b"deterministic-rknn-model").hexdigest(),
        )

    def test_inference_error_is_rejected(self) -> None:
        log = self.write_text(valid_log().replace("inference_errors=0", "inference_errors=1"))

        with self.assertRaisesRegex(analyzer.AnalysisError, "inference_errors"):
            analyzer.analyze(log, model_artifact=self.write_model())

    def test_profile_sample_mismatch_is_rejected(self) -> None:
        log = self.write_text(
            valid_log().replace("profile_samples=1800", "profile_samples=1799")
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "profile_samples"):
            analyzer.analyze(log, model_artifact=self.write_model())

    def test_missing_completion_marker_is_rejected(self) -> None:
        log = self.write_text(valid_log().replace("UVC_RKNN_BENCH_DONE\n", ""))

        with self.assertRaisesRegex(analyzer.AnalysisError, "BENCH_DONE"):
            analyzer.analyze(log, model_artifact=self.write_model())

    def test_configuration_drift_between_validation_and_benchmark_is_rejected(self) -> None:
        contents = valid_log()
        last_config = contents.rfind("min_confidence=25")
        contents = (
            contents[:last_config]
            + "min_confidence=30"
            + contents[last_config + len("min_confidence=25") :]
        )
        log = self.write_text(contents)

        with self.assertRaisesRegex(analyzer.AnalysisError, "min_confidence"):
            analyzer.analyze(log, model_artifact=self.write_model())

    def test_conflicting_duplicate_result_is_rejected(self) -> None:
        conflicting = RESULT.replace("infer_fps=30.00", "infer_fps=10.00")
        log = self.write_text(valid_log().replace(RESULT, RESULT + "\n" + conflicting))

        with self.assertRaisesRegex(analyzer.AnalysisError, "BENCH_RESULT"):
            analyzer.analyze(log, model_artifact=self.write_model())

    def test_short_run_is_rejected(self) -> None:
        log = self.write_text(valid_log().replace("duration_sec=60.0", "duration_sec=30.0"))

        with self.assertRaisesRegex(analyzer.AnalysisError, "duration_sec"):
            analyzer.analyze(
                log,
                model_artifact=self.write_model(),
                expected_duration_sec=60.0,
            )


if __name__ == "__main__":
    unittest.main()
