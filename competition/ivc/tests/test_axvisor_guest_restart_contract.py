#!/usr/bin/env python3

import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GUEST_RESTART_BUILD = (
    REPOSITORY_ROOT
    / "competition/ivc/config/axvisor-orangepi-5-plus-restart.toml"
)


class AxvisorGuestRestartContractTests(unittest.TestCase):
    def test_restart_build_reserves_a_dedicated_host_cpu(self) -> None:
        with GUEST_RESTART_BUILD.open("rb") as config_file:
            config = tomllib.load(config_file)

        restart = config["guest_restart"]
        self.assertEqual(config["max_cpu_num"], 4)
        self.assertEqual(restart["cpu"], 3)
        self.assertLess(restart["cpu"], config["max_cpu_num"])
        self.assertEqual(restart["vm_id"], 1)
        self.assertEqual(restart["delay_ms"], 20_000)
        self.assertEqual(restart["ready_timeout_ms"], 30_000)
        self.assertEqual(len(config["vm_configs"]), 2)
        self.assertTrue(config["vm_configs"][0].endswith("starry-smp2-restart.toml"))
        self.assertTrue(config["vm_configs"][1].endswith("zephyr-restart.toml"))


if __name__ == "__main__":
    unittest.main()
