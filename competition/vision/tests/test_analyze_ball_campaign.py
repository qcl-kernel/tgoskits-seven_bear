from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


VISION_DIR = Path(__file__).resolve().parents[1]
MANIFEST = VISION_DIR / "ball-campaign-preregistration.json"
sys.path.insert(0, str(VISION_DIR))

from analyze_ball_campaign import analyze_campaign, write_outputs  # noqa: E402


SOURCE_COMMIT = "1" * 40


def valid_records() -> list[dict[str, object]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    identity = 1
    for trial in manifest["trials"]:
        for strategy in trial["strategy_order"]:
            captured = 1_000_000 + identity * 100_000
            records.append(
                {
                    "trial_id": trial["trial_id"],
                    "strategy": strategy,
                    "frame_id": identity,
                    "session_id": 9,
                    "sequence": identity,
                    "actual_action": (
                        trial["expected_action"] if strategy == "ai" else "hold"
                    ),
                    "captured_at_us": captured,
                    "stable_at_us": captured + (20_000 if strategy == "ai" else 10_000),
                    "physical_result_verified": True,
                }
            )
            identity += 1
    return records


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


class AnalyzeBallCampaignTests(unittest.TestCase):
    def test_balanced_manifest_and_complete_pairs_generate_two_metric_chart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records_path = root / "records.jsonl"
            output_dir = root / "output"
            write_jsonl(records_path, valid_records())

            summary, normalized = analyze_campaign(
                MANIFEST, records_path, SOURCE_COMMIT
            )
            write_outputs(output_dir, summary, normalized)

            self.assertEqual(summary["paired_trial_count"], 30)
            self.assertEqual(summary["record_count"], 60)
            self.assertEqual(summary["metrics"]["ai"]["action_accuracy"], 1.0)
            self.assertAlmostEqual(
                summary["metrics"]["fixed"]["action_accuracy"], 1 / 3
            )
            self.assertEqual(
                summary["metrics"]["ai"]["capture_to_stable_p95_us"], 20_000
            )
            self.assertTrue((output_dir / "summary.json").is_file())
            self.assertTrue((output_dir / "paired-records.csv").is_file())
            chart = (output_dir / "ai-vs-fixed.svg").read_text(encoding="utf-8")
            self.assertIn("Action accuracy", chart)
            self.assertIn("Capture-to-stable p95", chart)

    def test_missing_pair_is_rejected_instead_of_reported_as_n29(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            records_path = Path(directory) / "records.jsonl"
            write_jsonl(records_path, valid_records()[:-1])

            with self.assertRaisesRegex(ValueError, "30-pair schedule"):
                analyze_campaign(MANIFEST, records_path, SOURCE_COMMIT)

    def test_reordered_records_are_rejected(self) -> None:
        records = valid_records()
        records[0], records[1] = records[1], records[0]
        with tempfile.TemporaryDirectory() as directory:
            records_path = Path(directory) / "records.jsonl"
            write_jsonl(records_path, records)

            with self.assertRaisesRegex(ValueError, "order or count"):
                analyze_campaign(MANIFEST, records_path, SOURCE_COMMIT)

    def test_fixed_policy_cannot_be_adapted_after_seeing_the_label(self) -> None:
        records = valid_records()
        fixed_right = next(
            record
            for record in records
            if record["strategy"] == "fixed" and record["trial_id"] == "T01"
        )
        fixed_right["actual_action"] = "right"
        with tempfile.TemporaryDirectory() as directory:
            records_path = Path(directory) / "records.jsonl"
            write_jsonl(records_path, records)

            with self.assertRaisesRegex(ValueError, "always HOLD"):
                analyze_campaign(MANIFEST, records_path, SOURCE_COMMIT)

    def test_unverified_physical_result_is_rejected(self) -> None:
        records = valid_records()
        records[0]["physical_result_verified"] = False
        with tempfile.TemporaryDirectory() as directory:
            records_path = Path(directory) / "records.jsonl"
            write_jsonl(records_path, records)

            with self.assertRaisesRegex(ValueError, "not verified"):
                analyze_campaign(MANIFEST, records_path, SOURCE_COMMIT)


if __name__ == "__main__":
    unittest.main()
