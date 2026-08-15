from __future__ import annotations

import re

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    import tomli as tomllib
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPOSITORY_ROOT / "competition/ivc/config"


RTOS_CONTRACTS = {
    "rtthread": {
        "marker": "rt-thread",
        "entry": 0x4008_0000,
        "ram_base": 0x4000_0000,
        "binary": "rtthread.bin",
    },
    "freertos": {
        "marker": "freertos",
        "entry": 0x5000_0000,
        "ram_base": 0x5000_0000,
        "binary": "freertos.bin",
    },
}


def load_toml(path: Path) -> dict:
    with path.open("rb") as source:
        return tomllib.load(source)


class RtosGuestContractTests(unittest.TestCase):
    def test_linux_controller_is_a_bounded_100_command_peer(self) -> None:
        config = load_toml(CONFIG_DIR / "linux-smp2-rtos.toml")

        self.assertEqual(config["base"]["phys_cpu_sets"], [0x2, 0x4])
        self.assertIn("ivc.mode=neural", config["kernel"]["cmdline"])
        self.assertIn("ivc.count=100", config["kernel"]["cmdline"])
        self.assertIn("ivc.period_ms=100", config["kernel"]["cmdline"])
        self.assertIn("ivc.ack_timeout_ms=500", config["kernel"]["cmdline"])
        self.assertEqual(
            config["kernel"]["memory_regions"],
            [[0x8000_0000, 0x1000_0000, 0x7, 0]],
        )
        self.assertEqual(
            config["devices"]["virtual"],
            [
                {
                    "id": "net0",
                    "model": "virtio-net-mmio",
                    "mac_suffix": 1,
                    "segment_id": 1,
                }
            ],
        )

    def test_rtos_vm_configs_match_the_link_and_virtual_nic_contract(self) -> None:
        for rtos, contract in RTOS_CONTRACTS.items():
            for profile in ("normal", "ack-loss"):
                suffix = "" if profile == "normal" else "-ack-loss"
                path = CONFIG_DIR / f"{rtos}-smp1{suffix}.toml"
                with self.subTest(rtos=rtos, profile=profile):
                    config = load_toml(path)
                    kernel = config["kernel"]
                    self.assertEqual(config["base"]["id"], 2)
                    self.assertEqual(config["base"]["cpu_num"], 1)
                    self.assertEqual(config["base"]["phys_cpu_sets"], [0x1])
                    self.assertEqual(kernel["entry_point"], contract["entry"])
                    self.assertEqual(kernel["kernel_load_addr"], contract["entry"])
                    self.assertEqual(
                        kernel["memory_regions"],
                        [[contract["ram_base"], 0x0800_0000, 0x7, 0]],
                    )
                    self.assertEqual(kernel["image_location"], "memory")
                    expected_binary = (
                        REPOSITORY_ROOT
                        / "tmp/competition/ivc/guests"
                        / rtos
                        / profile
                        / contract["binary"]
                    ).resolve()
                    self.assertEqual(
                        (path.parent / kernel["kernel_path"]).resolve(),
                        expected_binary,
                    )
                    self.assertEqual(config["devices"]["passthrough"], [])
                    self.assertEqual(config["devices"]["disabled"], [])
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

    def test_axvisor_build_configs_pair_one_controller_with_one_endpoint(self) -> None:
        for rtos in RTOS_CONTRACTS:
            for profile in ("normal", "ack-loss"):
                suffix = "" if profile == "normal" else "-ack-loss"
                config = load_toml(
                    CONFIG_DIR / f"axvisor-aarch64-{rtos}{suffix}.toml"
                )
                with self.subTest(rtos=rtos, profile=profile):
                    self.assertEqual(config["max_cpu_num"], 4)
                    self.assertIn("ax-driver/virtio-blk", config["features"])
                    self.assertEqual(
                        config["vm_configs"],
                        [
                            "competition/ivc/config/linux-smp2-rtos.toml",
                            f"competition/ivc/config/{rtos}-smp1{suffix}.toml",
                        ],
                    )

    def test_qemu_success_requires_the_named_rtos_and_linux_completion(self) -> None:
        for rtos, contract in RTOS_CONTRACTS.items():
            for profile in ("normal", "ack-loss"):
                suffix = "" if profile == "normal" else "-ack-loss"
                config = load_toml(CONFIG_DIR / f"qemu-aarch64-{rtos}{suffix}.toml")
                success = re.compile(config["success_regex"][0])
                duplicate_fields = (
                    "duplicates=0 acks_dropped=0"
                    if profile == "normal"
                    else "duplicates=20 acks_dropped=20"
                )
                complete = (
                    f"[VM 2] IVC-RTOS-RESULT rtos={contract['marker']} profile={profile} "
                    f"accepted=100 applied=100 {duplicate_fields} "
                    "status_sent=100 acks_sent=100 errors_sent=0 "
                    "protocol_errors=0\n[VM 1] IVC-LINUX-DONE exit=0\n"
                )
                with self.subTest(rtos=rtos, profile=profile):
                    self.assertIsNone(success.search("IVC-LINUX-DONE exit=0\n"))
                    self.assertIsNotNone(success.search(complete))
                    self.assertTrue(
                        any("IVC-RTOS-" in pattern for pattern in config["fail_regex"])
                    )

    def test_build_scripts_pin_sources_and_both_profiles(self) -> None:
        rtthread = (
            REPOSITORY_ROOT / "competition/ivc/rtthread/build.sh"
        ).read_text(encoding="utf-8")
        freertos = (
            REPOSITORY_ROOT / "competition/ivc/freertos/build.sh"
        ).read_text(encoding="utf-8")
        freertos_prepare = (
            REPOSITORY_ROOT / "competition/ivc/freertos/prepare.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("ddf52e2cdd977f14fc04035c88672ac204aec713", rtthread)
        self.assertIn("IVC_EXPECTED_COMMANDS=100,IVC_DROP_ACK_EVERY=5", rtthread)
        self.assertIn("cb9112f982c2768872536b811e013254d0184811", freertos)
        self.assertIn("f1043c49d59944353291654c175852bd17b34f99", freertos)
        self.assertIn("c50068084212ef33115a4c05f9f714cc637f30bc", freertos)
        self.assertIn("c12361095aca68aeed858f45d14395fbffa92c0d", freertos)
        self.assertIn("IVC_EXPECTED_COMMANDS=100", freertos)
        self.assertIn('drop_ack_every=5', freertos)
        self.assertIn("FreeRTOS/FreeRTOS-Plus-TCP.git", freertos_prepare)

    def test_freertos_heap_stays_within_the_bao_startup_adr_range(self) -> None:
        config = (
            REPOSITORY_ROOT / "competition/ivc/freertos/FreeRTOSConfig.h"
        ).read_text(encoding="utf-8")

        # The pinned Bao startup reaches _stack_base with AArch64 ADR, whose
        # signed range is only 1 MiB from the early entry code.
        self.assertIn(
            "#define configTOTAL_HEAP_SIZE ((size_t)(256U * 1024U))",
            config,
        )

    def test_rtthread_maps_virtual_net_mmio_before_driver_access(self) -> None:
        network = (
            REPOSITORY_ROOT / "competition/ivc/rtthread/network.c"
        ).read_text(encoding="utf-8")

        # RT-Thread enables its MMU before main(), so the AxVisor device GPA is
        # not a directly dereferenceable virtual address.
        self.assertIn("#include <ioremap.h>", network)
        self.assertIn("rt_ioremap", network)
        self.assertIn("stage=ioremap", network)
        self.assertIn(
            "ivc_virtio_net_init(&network.virtio, (uintptr_t)mmio_base,",
            network,
        )

    def test_campaign_runner_uses_strict_identity_analysis(self) -> None:
        runner = (
            REPOSITORY_ROOT / "competition/ivc/run-rtos-qemu.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('--expected-count 100', runner)
        self.assertIn('--expected-rtos "$guest_name"', runner)
        self.assertIn('sha256sum --check --strict SHA256SUMS', runner)
        self.assertIn('refusing to overwrite RTOS IVC evidence', runner)
        self.assertIn('--rootfs "$rootfs"', runner)

    def test_linux_rootfs_injection_is_journal_safe_and_strictly_checked(self) -> None:
        build_rootfs = (
            REPOSITORY_ROOT / "competition/ivc/linux/build-rootfs.sh"
        ).read_text(encoding="utf-8")
        build_initramfs = (
            REPOSITORY_ROOT / "competition/ivc/linux/build-initramfs.sh"
        ).read_text(encoding="utf-8")
        runner = (
            REPOSITORY_ROOT / "competition/ivc/run-rtos-qemu.sh"
        ).read_text(encoding="utf-8")

        # Raw debugfs writes do not participate in the ext4 journal. Repair the
        # copied filesystem before injection and commit a clean state after it.
        self.assertGreaterEqual(build_rootfs.count('e2fsck -fy "$output_image"'), 2)
        self.assertGreater(
            build_initramfs.rfind('e2fsck -fy "$rootfs_image"'),
            build_initramfs.rfind('debugfs -w'),
        )

        # debugfs returns success even when stat reports "File not found".
        self.assertIn("grep -q '^Inode:'", runner)

    def test_linux_init_has_a_unix_shebang(self) -> None:
        init = (REPOSITORY_ROOT / "competition/ivc/linux/ivc-init.sh").read_bytes()

        self.assertTrue(init.startswith(b"#!/bin/sh\n"))
        self.assertNotIn(b"\r\n", init)
        init_text = init.decode("ascii")
        self.assertIn("ivc.ack_timeout_ms", init_text)
        self.assertIn('--ack-timeout-ms "$ack_timeout_ms"', init_text)


if __name__ == "__main__":
    unittest.main()
