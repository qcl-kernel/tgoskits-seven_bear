#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Source-level contracts for the physical RK3588 baseline runner."""

from __future__ import annotations

import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]


class BoardRunnerContractTests(unittest.TestCase):
    """Guard lifecycle details that previously caused physical-run failures."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = (SCRIPT_DIR / "run-board.sh").read_text(encoding="utf-8")

    def test_mount_health_uses_fields_instead_of_spacing_sensitive_output(self) -> None:
        self.assertIn("findmnt -n -o FSTYPE /", self.runner)
        self.assertIn("findmnt -n -o OPTIONS /", self.runner)
        self.assertNotIn("*' ext4 rw,'*", self.runner)

    def test_health_check_does_not_require_unavailable_passwordless_dmesg(self) -> None:
        self.assertIn("journalctl -k -b --no-pager", self.runner)
        self.assertNotIn("sudo -n dmesg", self.runner)

    def test_linux_is_synced_before_the_uboot_handoff(self) -> None:
        self.assertIn("sudo -n /usr/bin/sync", self.runner)
        self.assertIn("NATIVE_ZEPHYR_REBOOT_ARMED", self.runner)

    def test_uboot_command_uses_the_exclusive_serial_helper_after_lease_release(self) -> None:
        release = self.runner.index('cleanup_lease\nsleep 20')
        serial = self.runner.index('bash "$serial_command_runner" "$uboot_command"')
        self.assertLess(release, serial)
        self.assertIn("ORANGEPI_SERIAL_COMMAND_SETTLE_SECONDS", self.runner)

    def test_uboot_failure_detection_ignores_the_echoed_command_branch(self) -> None:
        self.assertIn("^NATIVE_ZEPHYR_UBOOT_LOAD_FAILED", self.runner)

    def test_soak_contract_is_thirty_minutes_under_stress(self) -> None:
        self.assertIn("profile=soak", self.runner)
        self.assertIn("workload=cpu-stress", self.runner)
        self.assertIn("run_timeout_seconds=2100", self.runner)


if __name__ == "__main__":
    unittest.main()
