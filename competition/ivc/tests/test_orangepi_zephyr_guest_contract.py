#!/usr/bin/env python3

import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ORANGEPI_ZEPHYR_CONFIGS = (
    REPOSITORY_ROOT / "competition/ivc/config/orangepi-5-plus-zephyr-smp1.toml",
    REPOSITORY_ROOT / "competition/ivc/config/orangepi-5-plus-zephyr-smoke.toml",
)
ZEPHYR_MAIN = REPOSITORY_ROOT / "competition/ivc/zephyr/src/main.c"


class OrangePiZephyrGuestContractTests(unittest.TestCase):
    def test_guests_use_the_typed_virtual_network_device(self) -> None:
        for config_path in ORANGEPI_ZEPHYR_CONFIGS:
            with self.subTest(config=config_path.name), config_path.open("rb") as source:
                config = tomllib.load(source)

            self.assertEqual(config["base"]["guest_type"], "virtualized")
            devices = config["devices"]
            self.assertEqual(devices["passthrough"], [])
            self.assertEqual(devices["disabled"], [])
            self.assertNotIn("interrupt_mode", devices)
            self.assertNotIn("emu_devices", devices)
            self.assertEqual(
                devices["virtual"],
                [
                    {
                        "id": "net0",
                        "model": "virtio-net-mmio",
                        "mac_suffix": 2,
                        "segment_id": 1,
                        "header_mode": "fixed-twelve-byte",
                    }
                ],
            )

    def test_terminal_evidence_uses_redundant_compact_records(self) -> None:
        source = ZEPHYR_MAIN.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r"(?m)^#define IVC_RESULT_RECORD_COPIES 2U$",
        )
        self.assertIn("IVC-RTOS-OUTCOME profile=%s", source)
        self.assertIn("IVC-RTOS-MESSAGES status_sent=%llu", source)

    def test_poweroff_evidence_is_delayed_and_replayed_after_controller_output(self) -> None:
        source = ZEPHYR_MAIN.read_text(encoding="utf-8")

        self.assertRegex(
            source,
            r"(?m)^#define IVC_POWEROFF_RECORD_COPIES 5U$",
        )
        self.assertRegex(
            source,
            r"(?m)^#define IVC_POWEROFF_INITIAL_PAUSE_MS 500$",
        )
        self.assertRegex(
            source,
            r"(?m)^#define IVC_POWEROFF_RECORD_PAUSE_MS 100$",
        )
        self.assertIn("report_poweroff_evidence(server, profile);", source)
        self.assertGreaterEqual(
            source.count("report_combined_result(server, profile);"), 2
        )

    def test_restart_ready_contract_uses_a_separate_compact_record(self) -> None:
        source = ZEPHYR_MAIN.read_text(encoding="utf-8")

        self.assertIn("IVC-RTOS-RESTART-READY commands=%u", source)
        self.assertIn("report_restart_ready();", source)

    def test_restart_terminal_evidence_replays_safe_fallback_with_pacing(self) -> None:
        source = ZEPHYR_MAIN.read_text(encoding="utf-8")

        self.assertIn("restart_safe_session", source)
        self.assertIn("restart_safe_sequence", source)
        self.assertIn("restart_safe_actuator_permille", source)
        self.assertIn("report_safe_fallback_evidence(server);", source)
        self.assertRegex(
            source,
            r"(?m)^#define IVC_RESTART_RECORD_PAUSE_MS 50$",
        )
        self.assertIn("k_sleep(K_MSEC(IVC_RESTART_RECORD_PAUSE_MS));", source)


if __name__ == "__main__":
    unittest.main()
