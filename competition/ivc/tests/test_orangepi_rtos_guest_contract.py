#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
IVC_DIR = REPOSITORY_ROOT / "competition/ivc"
CONFIG_DIR = IVC_DIR / "config"
sys.path.insert(0, str(IVC_DIR))

import analyze_board  # noqa: E402


RTOS_CONTRACTS = {
    "rtthread": {
        "identity": "rt-thread",
        "entry": 0x4008_0000,
        "ram_base": 0x4000_0000,
        "binary": "rtthread.bin",
        "snapshot": "/home/orangepi/ivc-rts",
    },
    "freertos": {
        "identity": "freertos",
        "entry": 0x5000_0000,
        "ram_base": 0x5000_0000,
        "binary": "freertos.bin",
        "snapshot": "/home/orangepi/ivc-fts",
    },
}


def load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as source:
        return tomllib.load(source)


class OrangePiRtosGuestContractTests(unittest.TestCase):
    def test_physical_configs_preserve_cpu_memory_and_typed_nic_boundaries(self) -> None:
        for rtos, contract in RTOS_CONTRACTS.items():
            with self.subTest(rtos=rtos):
                path = CONFIG_DIR / f"orangepi-5-plus-{rtos}-smoke.toml"
                config = load_toml(path)
                kernel = config["kernel"]

                self.assertEqual(config["base"]["phys_cpu_sets"], [0x1])
                self.assertEqual(config["base"]["dedicated_cpus"], True)
                self.assertEqual(kernel["entry_point"], contract["entry"])
                self.assertEqual(kernel["kernel_load_addr"], contract["entry"])
                self.assertEqual(
                    kernel["memory_regions"],
                    [[contract["ram_base"], 0x0800_0000, 0x7, 0]],
                )
                expected_binary = (
                    REPOSITORY_ROOT
                    / "tmp/competition/ivc/guests"
                    / rtos
                    / "board-smoke"
                    / contract["binary"]
                ).resolve()
                self.assertEqual(
                    (path.parent / kernel["kernel_path"]).resolve(),
                    expected_binary,
                )
                self.assertEqual(
                    config["devices"]["virtual"],
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

    def test_axvisor_configs_pair_starry_with_one_named_rtos(self) -> None:
        for rtos in RTOS_CONTRACTS:
            with self.subTest(rtos=rtos):
                config = load_toml(
                    CONFIG_DIR / f"axvisor-orangepi-5-plus-{rtos}-smoke.toml"
                )
                self.assertEqual(config["max_cpu_num"], 4)
                self.assertEqual(
                    config["vm_configs"],
                    [
                        "competition/ivc/config/orangepi-5-plus-starry-smp2-smoke.toml",
                        f"competition/ivc/config/orangepi-5-plus-{rtos}-smoke.toml",
                    ],
                )

    def test_board_configs_snapshot_distinct_starry_result_images(self) -> None:
        for rtos, contract in RTOS_CONTRACTS.items():
            with self.subTest(rtos=rtos):
                config = load_toml(
                    CONFIG_DIR / f"board-orangepi-5-plus-{rtos}-smoke.toml"
                )
                self.assertIn(contract["snapshot"], config["shell_init_cmd"])
                self.assertTrue(
                    any("IVC-(STARRY|RTOS)-" in pattern for pattern in config["fail_regex"])
                )

    def test_analyzer_accepts_a_powered_off_non_zephyr_result(self) -> None:
        lines = [
            "IVC-RTOS-READY rtos=rt-thread",
            "IVC-RTOS-OUTCOME profile=normal accepted=20 applied=20 "
            "duplicates=0 acks_dropped=0",
            "IVC-RTOS-MESSAGES status_sent=20 acks_sent=20 errors_sent=0 "
            "protocol_errors=0",
            "IVC-RTOS-POWEROFF rtos=rt-thread accepted=20",
        ]

        result = analyze_board.parse_rtos(
            lines, 20, "normal", 0, "rt-thread"
        )

        self.assertEqual(result["name"], "rt-thread")
        self.assertEqual(result["applied"], 20)

    def test_analyzer_rejects_a_non_zephyr_result_without_poweroff(self) -> None:
        lines = [
            "IVC-RTOS-READY rtos=rt-thread",
            "IVC-RTOS-OUTCOME profile=normal accepted=20 applied=20 "
            "duplicates=0 acks_dropped=0",
            "IVC-RTOS-MESSAGES status_sent=20 acks_sent=20 errors_sent=0 "
            "protocol_errors=0",
        ]

        with self.assertRaisesRegex(analyze_board.AnalysisError, "POWEROFF"):
            analyze_board.parse_rtos(lines, 20, "normal", 0, "rt-thread")

    def test_analyzer_rejects_a_different_rtos_identity(self) -> None:
        lines = ["IVC-RTOS-READY rtos=freertos"]

        with self.assertRaisesRegex(analyze_board.AnalysisError, "identity"):
            analyze_board.parse_rtos(lines, 20, "normal", 0, "rt-thread")

    def test_runner_builds_and_identifies_each_physical_guest(self) -> None:
        runner = (IVC_DIR / "run-orangepi-5-plus.sh").read_text(encoding="utf-8")
        metadata = (IVC_DIR / "write_board_metadata.py").read_text(encoding="utf-8")
        server = (IVC_DIR / "common/ivc_rtos_server.c").read_text(encoding="utf-8")

        self.assertIn("rtthread-smoke)", runner)
        self.assertIn("freertos-smoke)", runner)
        self.assertIn('bash "$rtos_guest_builder" board-smoke', runner)
        self.assertIn('--expected-rtos "$rtos_guest_kind"', runner)
        self.assertIn('--rtos-guest-kind "$rtos_guest_kind"', runner)
        self.assertIn('"rtos_guest"', metadata)
        self.assertIn("#define IVC_RESULT_RECORD_COPIES 2U", server)
        self.assertIn("IVC-RTOS-OUTCOME profile=%s", server)
        self.assertIn("IVC-RTOS-MESSAGES status_sent=%llu", server)
        self.assertIn("IVC-RTOS-POWEROFF rtos=%s accepted=%llu", server)


if __name__ == "__main__":
    unittest.main()
