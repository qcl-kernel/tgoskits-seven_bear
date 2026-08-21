from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ANALYZER_PATH = Path(__file__).resolve().parents[1] / "analyze_closed_loop.py"
SPEC = importlib.util.spec_from_file_location("analyze_closed_loop", ANALYZER_PATH)
assert SPEC is not None and SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)


def valid_log() -> str:
    events = [
        "VISION_CLOSED_LOOP_EVENT frame=1 detection=1 class_id=32 "
        "confidence_q10000=9330 bbox=500,100,752,400 requested=right "
        "actual=right state=applied inference_to_send_us=100 transport_us=250 "
        "end_to_end_us=41000 retries=0",
        "VISION_CLOSED_LOOP_EVENT frame=2 detection=1 class_id=32 "
        "confidence_q10000=9010 bbox=497,100,749,400 requested=left "
        "actual=left state=applied inference_to_send_us=110 transport_us=280 "
        "end_to_end_us=42000 retries=1",
        "VISION_CLOSED_LOOP_EVENT frame=3 detection=0 class_id=65535 "
        "confidence_q10000=0 bbox=0,0,0,0 requested=hold actual=hold "
        "state=applied inference_to_send_us=90 transport_us=230 "
        "end_to_end_us=39000 retries=0",
    ]
    return "\n".join(
        [
            "IVC-STARRY-VISION-BOOT source=fixed-images backend=rknn-npu frames=3 "
            "target_class=32 calibration_x=625",
            "UVC_RKNN_VALIDATE_PASS images=3",
            "VISION_CLOSED_LOOP_BEGIN peer=10.0.0.2:5500 frames=3 session_id=1447646030",
            *events,
            "VISION_CLOSED_LOOP_DONE frames=3 applied=3 errors=0",
            "IVC-RTOS-VISION-RESULT accepted=3 applied=3 duplicates=0 "
            "actuator_status_sent=3 acks_sent=3 errors_sent=0 protocol_errors=0",
            "IVC-STARRY-VISION-EVIDENCE runner_sha256=" + "1" * 64 + " controller_sha256=" + "2" * 64,
            "IVC-STARRY-VISION-DONE exit=0",
            "AXVISOR_HOST_FILESYSTEM_SYNCED",
        ]
    ) + "\n"


class ClosedLoopAnalysisTests(unittest.TestCase):
    def test_valid_three_frame_loop_reports_actions_and_latency(self) -> None:
        result = analyzer.analyze_text(valid_log())

        self.assertTrue(result["acceptance"]["passed"])
        self.assertEqual(result["actions"], ["right", "left", "hold"])
        self.assertEqual(result["frames"], 3)
        self.assertEqual(result["retries"], 1)
        self.assertEqual(result["latency_us"]["end_to_end"]["max"], 42000)

    def test_requested_and_actual_action_mismatch_is_rejected(self) -> None:
        log = valid_log().replace("actual=left", "actual=right", 1)

        with self.assertRaisesRegex(analyzer.AnalysisError, "action mismatch"):
            analyzer.analyze_text(log)

    def test_missing_rtos_result_is_rejected(self) -> None:
        log = "\n".join(
            line
            for line in valid_log().splitlines()
            if not line.startswith("IVC-RTOS-VISION-RESULT")
        )

        with self.assertRaisesRegex(analyzer.AnalysisError, "RTOS result"):
            analyzer.analyze_text(log)

    def test_rtos_result_replay_survives_one_interleaved_copy(self) -> None:
        clean = (
            "IVC-RTOS-VISION-RESULT accepted=3 applied=3 duplicates=0 "
            "actuator_status_sent=3 acks_sent=3 errors_sent=0 protocol_errors=0"
        )
        corrupt = clean.removesuffix("=0") + "[VM 2] IVC-RTOS-VISION-POWEROFF accepted=3"
        log = valid_log().replace(clean, corrupt + "\n" + clean + "\n" + clean)

        result = analyzer.analyze_text(log)

        self.assertEqual(result["rtos"]["accepted"], 3)
        self.assertEqual(result["rtos"]["protocol_errors"], 0)

    def test_duplicate_frame_is_rejected(self) -> None:
        log = valid_log().replace("frame=2 detection=1", "frame=1 detection=1", 1)

        with self.assertRaisesRegex(analyzer.AnalysisError, "conflicting complete vision event"):
            analyzer.analyze_text(log)

    def test_missing_host_sync_is_rejected(self) -> None:
        log = valid_log().replace("AXVISOR_HOST_FILESYSTEM_SYNCED\n", "")

        with self.assertRaisesRegex(analyzer.AnalysisError, "host filesystem sync"):
            analyzer.analyze_text(log)

    def test_snapshot_write_failure_is_rejected(self) -> None:
        log = valid_log() + "AXVISOR_VM_BLOCK_SNAPSHOT_FAILED: I/O error\n"

        with self.assertRaisesRegex(
            analyzer.AnalysisError,
            "AXVISOR_VM_BLOCK_SNAPSHOT_FAILED",
        ):
            analyzer.analyze_text(log)

    def test_replayed_records_survive_one_interleaved_uart_copy(self) -> None:
        lines = valid_log().splitlines()
        replayed_records = [
            line
            for line in lines
            if line.startswith("VISION_CLOSED_LOOP_EVENT ")
            or line.startswith("IVC-STARRY-VISION-EVIDENCE ")
        ]
        first_event = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("VISION_CLOSED_LOOP_EVENT ")
        )
        lines.insert(
            first_event,
            "VISION_CLOSED_LOOP_EVENT frame=2 detection=1"
            "[VM 1] VISION_CLOSED_LOOP_DONE frames=3 applied=3 errors=0",
        )
        log = "\n".join([*lines, *replayed_records, *replayed_records]) + "\n"

        result = analyzer.analyze_text(log)

        self.assertEqual(result["frames"], 3)
        self.assertEqual(result["actions"], ["right", "left", "hold"])

    def test_split_hash_records_are_accepted_with_identical_replays(self) -> None:
        runner_hash = "1" * 64
        controller_hash = "2" * 64
        legacy = (
            "IVC-STARRY-VISION-EVIDENCE runner_sha256="
            + runner_hash
            + " controller_sha256="
            + controller_hash
        )
        split_records = "\n".join(
            [
                "IVC-STARRY-VISION-RUNNER-SHA256 sha256=uart-truncated",
                f"IVC-STARRY-VISION-CONTROLLER-SHA256 sha256={controller_hash}",
                f"IVC-STARRY-VISION-RUNNER-SHA256 sha256={runner_hash}",
                f"IVC-STARRY-VISION-CONTROLLER-SHA256 sha256={controller_hash}",
                f"IVC-STARRY-VISION-RUNNER-SHA256 sha256={runner_hash}",
                f"IVC-STARRY-VISION-CONTROLLER-SHA256 sha256={controller_hash}",
            ]
        )
        log = valid_log().replace(legacy, split_records)

        result = analyzer.analyze_text(log)

        self.assertEqual(
            result["artifact_log_sha256"],
            {"runner": runner_hash, "controller": controller_hash},
        )


if __name__ == "__main__":
    unittest.main()
