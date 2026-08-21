from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUTORUN = REPOSITORY_ROOT / "competition/ivc/starry/autorun-vision.sh"


class VisionGuestContractTests(unittest.TestCase):
    def test_machine_evidence_is_replayed_three_times_with_spacing(self) -> None:
        script = AUTORUN.read_text(encoding="utf-8")

        self.assertIn("evidence_copy=0", script)
        self.assertIn('while [ "$evidence_copy" -lt 3 ]; do', script)
        self.assertIn("evidence_quiet_seconds=2", script)
        self.assertIn("evidence_line_interval_seconds=0.25", script)
        self.assertIn("evidence_copy_interval_seconds=1", script)
        self.assertIn('"$BB" sleep "$evidence_quiet_seconds"', script)
        self.assertIn('"$BB" sleep "$evidence_line_interval_seconds"', script)
        self.assertIn('"$BB" sleep "$evidence_copy_interval_seconds"', script)

    def test_replay_carries_boot_network_and_terminal_identity(self) -> None:
        script = AUTORUN.read_text(encoding="utf-8")
        loop_start = script.index('while [ "$evidence_copy" -lt 3 ]; do')
        loop_end = script.index("done\n\ndone_copy=0", loop_start)
        replay_loop = script[loop_start:loop_end]

        self.assertIn('echo "$vision_boot_record"', replay_loop)
        self.assertIn('echo "$vision_net_record"', replay_loop)
        self.assertIn("done_copy=0", script)
        self.assertIn('while [ "$done_copy" -lt 3 ]; do', script)
        self.assertIn('echo "IVC-STARRY-VISION-DONE exit=0"', script)

        boot_match = re.search(r"vision_boot_record='([^']+)'", script)
        self.assertIsNotNone(boot_match)
        assert boot_match is not None
        routed_record = "[VM 1] " + boot_match.group(1)
        self.assertLessEqual(len(routed_record.encode("ascii")), 128)

    def test_split_hash_records_fit_the_shared_uart_line_budget(self) -> None:
        script = AUTORUN.read_text(encoding="utf-8")
        patterns = (
            r'echo "(IVC-STARRY-VISION-RUNNER-SHA256 [^"]+)"',
            r'echo "(IVC-STARRY-VISION-CONTROLLER-SHA256 [^"]+)"',
        )

        for pattern in patterns:
            with self.subTest(pattern=pattern):
                marker_match = re.search(pattern, script)
                self.assertIsNotNone(marker_match)
                assert marker_match is not None
                rendered = re.sub(r"\$[a-z_]+", "a" * 64, marker_match.group(1))
                routed_record = "[VM 1] " + rendered
                self.assertLessEqual(len(routed_record.encode("ascii")), 128)


if __name__ == "__main__":
    unittest.main()
