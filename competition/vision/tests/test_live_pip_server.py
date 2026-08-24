from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path


VISION_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VISION_DIR))

from live_pip_server import ExactFrameJoiner  # noqa: E402
from validate_live_pip_log import validate  # noqa: E402


JPEG = b"\xff\xd8exact-frame\xff\xd9"


def records(
    *,
    frame_id: int = 41,
    sequence: int = 7,
    action: str = "right",
    physical_applied: int = 1,
    physical_verified: int = 1,
    device_io_attempted: int = 1,
) -> list[str]:
    encoded = base64.b64encode(JPEG).decode()
    detection_present = 0 if action == "hold" else 1
    confidence_q10000 = 0 if action == "hold" else 8000
    target_position = {"hold": "hold", "left": "2042", "right": "2074"}[action]
    return [
        (
            "[VM 1] VISION_CAPTURE_IDENTITY version=1 "
            f"frame_id={frame_id} camera_sequence=91 captured_at_us=1000"
        ),
        (
            "[VM 1] VISION_DECISION_RECORD version=1 "
            f"frame_id={frame_id} captured_at_us=1000 inference_finished_at_us=1200 "
            f"ttl_us=1000000 requested_action={action} safe_action=hold "
            f"detection_present={detection_present} class_id=32 "
            f"confidence_q10000={confidence_q10000} region_id=2 "
            "left=200 top=20 right=260 bottom=90"
        ),
        (
            "[VM 1] VISION_RTOS_AUTH_RECORD version=1 session_id=33 "
            f"sequence={sequence} frame_id={frame_id} requested_action={action} "
            f"authorized_action={action} state=applied retries=0"
        ),
        (
            "[VM 1] VISION_ACTUATOR_RECORD version=1 session_id=33 "
            f"sequence={sequence} frame_id={frame_id} action={action} gate=stable "
            f"target_position={target_position} physical_applied={physical_applied} "
            f"physical_verified={physical_verified} "
            f"device_io_attempted={device_io_attempted}"
        ),
        f"[VM 1] STARRY_JPEG_BEGIN frame={frame_id} bytes={len(JPEG)}",
        f"[VM 1] {encoded}",
        f"[VM 1] STARRY_JPEG_END frame={frame_id}",
    ]


class ExactFrameJoinerTests(unittest.TestCase):
    def test_publishes_only_a_complete_exact_identity_join(self) -> None:
        joiner = ExactFrameJoiner(require_physical=True)
        lines = records()
        for line in lines[:-1]:
            joiner.feed_line(line)
            self.assertIsNone(joiner.snapshot()[0])

        joiner.feed_line(lines[-1])
        published, diagnostics = joiner.snapshot()
        self.assertIsNotNone(published)
        assert published is not None
        self.assertEqual(published.jpeg, JPEG)
        self.assertEqual(published.state["frame_id"], 41)
        self.assertEqual(published.state["camera_sequence"], 91)
        self.assertEqual(published.state["sequence"], 7)
        self.assertEqual(published.state["ai_action"], "RIGHT")
        self.assertEqual(published.state["rtos_action"], "RIGHT")
        self.assertEqual(published.state["target_position"], "2074")
        self.assertEqual(published.state["physical_verified"], 1)
        self.assertEqual(diagnostics["error_count"], 0)

    def test_rejects_mismatched_rtos_and_actuator_sequence(self) -> None:
        joiner = ExactFrameJoiner()
        lines = records()
        lines[3] = lines[3].replace("sequence=7", "sequence=8")
        for line in lines:
            joiner.feed_line(line)

        published, diagnostics = joiner.snapshot()
        self.assertIsNone(published)
        self.assertGreater(diagnostics["error_count"], 0)
        self.assertIn("sequence", diagnostics["last_error"])

    def test_physical_gate_does_not_relabel_dry_run_as_motion(self) -> None:
        joiner = ExactFrameJoiner(require_physical=True)
        lines = records(
            physical_applied=0, physical_verified=0, device_io_attempted=0
        )
        for line in lines:
            joiner.feed_line(line)
        self.assertIsNone(joiner.snapshot()[0])

        physical_record = (
            lines[3]
            .replace("physical_applied=0", "physical_applied=1")
            .replace("physical_verified=0", "physical_verified=1")
            .replace("device_io_attempted=0", "device_io_attempted=1")
        )
        joiner.feed_line(physical_record)
        published, diagnostics = joiner.snapshot()
        self.assertIsNone(published)
        self.assertEqual(diagnostics["error_count"], 1)
        self.assertIn("conflicting", diagnostics["last_error"])

    def test_verified_hold_does_not_claim_a_servo_write(self) -> None:
        joiner = ExactFrameJoiner(require_physical=True)
        for line in records(
            action="hold",
            physical_applied=0,
            physical_verified=1,
            device_io_attempted=0,
        ):
            joiner.feed_line(line)

        published, diagnostics = joiner.snapshot()
        self.assertIsNotNone(published)
        assert published is not None
        self.assertEqual(published.state["ai_action"], "HOLD")
        self.assertEqual(published.state["physical_applied"], 0)
        self.assertEqual(published.state["physical_verified"], 1)
        self.assertEqual(published.state["device_io_attempted"], 0)
        self.assertEqual(diagnostics["error_count"], 0)

    def test_rejects_physical_application_without_feedback_verification(self) -> None:
        joiner = ExactFrameJoiner()
        for line in records(physical_verified=0):
            joiner.feed_line(line)

        published, diagnostics = joiner.snapshot()
        self.assertIsNone(published)
        self.assertGreater(diagnostics["error_count"], 0)
        self.assertIn("verified", diagnostics["last_error"])

    def test_rejects_camera_and_ai_capture_timestamp_mismatch(self) -> None:
        joiner = ExactFrameJoiner()
        lines = records()
        lines[1] = lines[1].replace("captured_at_us=1000", "captured_at_us=999")
        for line in lines:
            joiner.feed_line(line)

        published, diagnostics = joiner.snapshot()
        self.assertIsNone(published)
        self.assertGreater(diagnostics["error_count"], 0)
        self.assertIn("timestamp", diagnostics["last_error"])

    def test_repository_sample_or_other_frame_cannot_fill_live_frame(self) -> None:
        joiner = ExactFrameJoiner()
        lines = records(frame_id=41)
        for line in lines[:4]:
            joiner.feed_line(line)
        for line in records(frame_id=99)[4:]:
            joiner.feed_line(line)

        self.assertIsNone(joiner.snapshot()[0])

    def test_identical_complete_frame_replay_is_idempotent(self) -> None:
        joiner = ExactFrameJoiner()
        lines = records()
        for line in lines + lines:
            joiner.feed_line(line)

        published, diagnostics = joiner.snapshot()
        self.assertIsNotNone(published)
        assert published is not None
        self.assertEqual(published.state["revision"], 1)
        self.assertEqual(diagnostics["error_count"], 0)

    def test_conflicting_record_replay_is_rejected(self) -> None:
        joiner = ExactFrameJoiner()
        lines = records()
        for line in lines:
            joiner.feed_line(line)
        joiner.feed_line(lines[1].replace("confidence_q10000=8000", "confidence_q10000=7000"))

        _, diagnostics = joiner.snapshot()
        self.assertEqual(diagnostics["error_count"], 1)
        self.assertIn("conflicting", diagnostics["last_error"])

    def test_corrupt_serial_jpeg_fails_closed(self) -> None:
        joiner = ExactFrameJoiner()
        lines = records()
        lines[-2] = "[VM 1] not+valid+base64==="
        for line in lines:
            joiner.feed_line(line)

        published, diagnostics = joiner.snapshot()
        self.assertIsNone(published)
        self.assertEqual(diagnostics["error_count"], 1)
        self.assertIn("JPEG", diagnostics["last_error"])

    def test_offline_validator_counts_complete_joined_frames(self) -> None:
        lines = records(frame_id=41, sequence=7) + records(frame_id=42, sequence=8)
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "console.log"
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            summary = validate(log_path, expected_frames=2, physical="required")

        self.assertEqual(summary["joined_frames"], 2)
        self.assertEqual(summary["last_frame_id"], 42)
        self.assertEqual(summary["physical_applied"], 1)
        self.assertEqual(summary["physical_verified"], 1)


if __name__ == "__main__":
    unittest.main()
