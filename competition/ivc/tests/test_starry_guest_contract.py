#!/usr/bin/env python3

import re
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and older
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
STARRY_AUTORUN = REPOSITORY_ROOT / "competition/ivc/starry/autorun.sh"
STARRY_BUILD = REPOSITORY_ROOT / "competition/ivc/starry/build.sh"
STARRY_ROOTFS_BUILD = REPOSITORY_ROOT / "competition/ivc/starry/build-rootfs.sh"
AX_DRIVER_MANIFEST = REPOSITORY_ROOT / "drivers/ax-driver/Cargo.toml"
AXVISOR_MAIN = REPOSITORY_ROOT / "os/axvisor/src/main.rs"
AXVISOR_SHELL = REPOSITORY_ROOT / "os/axvisor/src/shell/mod.rs"
STARRY_BUILD_CONFIGS = (
    REPOSITORY_ROOT / "competition/ivc/config/starry-aarch64.toml",
    REPOSITORY_ROOT / "competition/ivc/config/starry-aarch64-rknpu.toml",
    REPOSITORY_ROOT / "scripts/benchmark/axvisor-rt/config/starry-aarch64-rt.toml",
    REPOSITORY_ROOT
    / "scripts/benchmark/axvisor-rt/config/starry-aarch64-rt-soak.toml",
)
ORANGEPI_STARRY_RUN_CONFIGS = (
    (
        REPOSITORY_ROOT
        / "competition/ivc/config/axvisor-orangepi-5-plus.toml",
        "competition/ivc/config/orangepi-5-plus-starry-smp2.toml",
        REPOSITORY_ROOT / "competition/ivc/config/board-orangepi-5-plus.toml",
        "/home/orangepi/ivc-n",
    ),
    (
        REPOSITORY_ROOT
        / "competition/ivc/config/axvisor-orangepi-5-plus-smoke.toml",
        "competition/ivc/config/orangepi-5-plus-starry-smp2-smoke.toml",
        REPOSITORY_ROOT
        / "competition/ivc/config/board-orangepi-5-plus-smoke.toml",
        "/home/orangepi/ivc-ns",
    ),
)
ORANGEPI_STARRY_CONFIGS = (
    REPOSITORY_ROOT / "competition/ivc/config/orangepi-5-plus-starry-smp2.toml",
    REPOSITORY_ROOT
    / "competition/ivc/config/orangepi-5-plus-starry-smp2-smoke.toml",
)
ORANGEPI_STARRY_MANUAL_CONFIGS = (
    (
        REPOSITORY_ROOT / "competition/ivc/config/orangepi-5-plus-starry-smp2.toml",
        REPOSITORY_ROOT
        / "competition/ivc/config/orangepi-5-plus-starry-smp2-manual.toml",
        "starry-ivc-rootfs-manual.img",
    ),
    (
        REPOSITORY_ROOT
        / "competition/ivc/config/orangepi-5-plus-starry-smp2-smoke.toml",
        REPOSITORY_ROOT
        / "competition/ivc/config/orangepi-5-plus-starry-smp2-manual-smoke.toml",
        "starry-ivc-rootfs-manual-smoke.img",
    ),
)


class StarryGuestContractTests(unittest.TestCase):
    def test_axvisor_publishes_the_board_shell_ready_marker_after_vm_completion(
        self,
    ) -> None:
        main_source = AXVISOR_MAIN.read_text(encoding="utf-8")
        shell_source = AXVISOR_SHELL.read_text(encoding="utf-8")

        self.assertIn(
            'pub const AUTOMATION_READY_MARKER: &str = "AXVISOR_SHELL_READY";',
            shell_source,
        )
        waiter = main_source.split("AxvmManager::wait_for_default_vms();", 1)[1]
        self.assertIn("shell::publish_automation_ready();", waiter)

    def test_starry_build_profiles_only_request_available_ax_driver_features(self) -> None:
        with AX_DRIVER_MANIFEST.open("rb") as source:
            available_features = tomllib.load(source)["features"]

        self.assertIn("virtio-blk", available_features)
        self.assertEqual(
            available_features["virtio-blk"],
            ["block", "virtio", "dep:ax-kernel-guard"],
        )
        for config_path in STARRY_BUILD_CONFIGS:
            with self.subTest(config=config_path.name), config_path.open("rb") as source:
                build_config = tomllib.load(source)
            for feature in build_config["features"]:
                crate, separator, feature_name = feature.partition("/")
                if crate == "ax-driver" and separator:
                    self.assertIn(feature_name, available_features)

    def test_default_orangepi_profiles_boot_and_gate_on_starry(self) -> None:
        for (
            build_config_path,
            starry_guest,
            board_config_path,
            result_image,
        ) in ORANGEPI_STARRY_RUN_CONFIGS:
            with self.subTest(config=build_config_path.name), build_config_path.open(
                "rb"
            ) as source:
                build_config = tomllib.load(source)
            self.assertEqual(build_config["vm_configs"][0], starry_guest)

            with board_config_path.open(
                "rb"
            ) as source:
                board_config = tomllib.load(source)
            self.assertEqual(board_config["shell_prefix"], "AXVISOR_SHELL_READY")
            self.assertEqual(
                board_config["shell_init_cmd"], f"ss 1 0 {result_image}"
            )
            self.assertEqual(len(board_config["success_regex"]), 1)
            success = re.compile(board_config["success_regex"][0])
            self.assertIsNotNone(success.search("AXVISOR_SNAPSHOT_SYNC_OK"))
            self.assertIsNotNone(success.search("AXVISOR_SNAPSHOT_SYNC_OK\n"))
            self.assertIsNotNone(success.search("AXVISOR_SNAPSHOT_SYNC_OK\r\n"))
            self.assertTrue(
                any(
                    re.compile(pattern).search("IVC-STARRY-DONE exit=1\n")
                    for pattern in board_config["fail_regex"]
                )
            )

    def test_rootfs_builder_exposes_orthogonal_profile_dimensions(self) -> None:
        script = STARRY_ROOTFS_BUILD.read_text(encoding="utf-8")

        for option in (
            "--profile",
            "--policy",
            "--backend",
            "--count",
            "--period-ms",
            "--output",
        ):
            with self.subTest(option=option):
                self.assertIn(option, script)
        self.assertIn("ivc_backend=%s", script)
        self.assertNotIn("printf 'ivc_mode=neural", script)

    def test_starry_build_produces_manual_and_neural_rootfs_images(self) -> None:
        script = STARRY_BUILD.read_text(encoding="utf-8")

        self.assertIn("--policy neural", script)
        self.assertIn("--policy manual", script)
        self.assertIn("starry-ivc-rootfs-manual.img", script)
        self.assertIn("starry-ivc-rootfs-manual-smoke.img", script)

    def test_starry_build_materializes_a_fresh_raw_kernel(self) -> None:
        script = STARRY_BUILD.read_text(encoding="utf-8")

        self.assertIn("built_elf=$workspace/target/", script)
        self.assertIn(
            "target/aarch64-unknown-none-softfloat/release/starryos",
            script,
        )
        self.assertNotIn("aarch64-unknown-linux-musl", script)
        self.assertIn(
            'rustup run "$toolchain" rust-objcopy --strip-all -O binary',
            script,
        )
        self.assertLess(
            script.index("xtask starry build"),
            script.index("rust-objcopy --strip-all -O binary"),
        )
        self.assertLess(
            script.index("rust-objcopy --strip-all -O binary"),
            script.index('install -m 0644 "$built_kernel"'),
        )

    def test_manual_guests_only_change_identity_and_rootfs_policy_image(self) -> None:
        for neural_path, manual_path, manual_image in ORANGEPI_STARRY_MANUAL_CONFIGS:
            with self.subTest(config=manual_path.name):
                with neural_path.open("rb") as source:
                    neural = tomllib.load(source)
                with manual_path.open("rb") as source:
                    manual = tomllib.load(source)

                manual_disk = next(
                    device
                    for device in manual["devices"]["virtual"]
                    if device["id"] == "disk0"
                )
                neural_disk = next(
                    device
                    for device in neural["devices"]["virtual"]
                    if device["id"] == "disk0"
                )
                self.assertEqual(manual_disk["model"], "virtio-blk-mmio")
                self.assertIn(manual_image, manual_disk["image_path"])
                manual["base"]["name"] = neural["base"]["name"]
                manual_disk["image_path"] = neural_disk["image_path"]
                self.assertEqual(manual, neural)

    def test_autorun_records_the_selected_inference_backend(self) -> None:
        script = STARRY_AUTORUN.read_text(encoding="utf-8")

        self.assertRegex(script, r"(?m)^case \"\$\{ivc_backend:-\}\" in$")
        self.assertIn("backend=$ivc_backend", script)

    def test_starry_guest_persists_and_validates_raw_controller_samples(self) -> None:
        builder = STARRY_ROOTFS_BUILD.read_text(encoding="utf-8")
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")

        self.assertIn("ivc_raw_csv=/var/lib/ivc/raw.csv", builder)
        self.assertIn("/var/lib/ivc", builder)
        self.assertIn('--raw-csv "$ivc_raw_csv"', autorun)
        self.assertIn("expected_raw_lines=$((expected_samples + 1))", autorun)
        self.assertIn('"$BB" wc -l < "$raw_path"', autorun)
        self.assertIn(
            "IVC-STARRY-RAW path=$ivc_raw_csv samples=$ivc_count sha256=$raw_sha256",
            autorun,
        )
        self.assertIn('while [ "$raw_identity_copy" -lt 5 ]; do', autorun)
        self.assertIn('raw_identity_copy=$((raw_identity_copy + 1))', autorun)
        self.assertIn("raw_identity_quiet_seconds=4", autorun)
        self.assertIn("raw_identity_line_interval_seconds=0.25", autorun)
        self.assertIn("raw_identity_copy_interval_seconds=1", autorun)
        self.assertIn('"$BB" sleep "$raw_identity_quiet_seconds"', autorun)
        self.assertIn('"$BB" sleep "$raw_identity_line_interval_seconds"', autorun)
        self.assertIn('"$BB" sleep "$raw_identity_copy_interval_seconds"', autorun)
        self.assertIn("raw_manifest=$raw_path.sha256", autorun)
        self.assertIn(
            "printf '%s  %s\\n' \"$validated_raw_sha256\" \"$raw_path\" >\"$raw_manifest\"",
            autorun,
        )
        self.assertIn('"$BB" sync || fatal final-sync-failed', autorun)
        self.assertLess(
            autorun.index('"$BB" sync || fatal final-sync-failed'),
            autorun.index('echo "IVC-STARRY-DONE exit=$result"'),
        )

    def test_rknn_uart_identity_lines_are_spaced_individually(self) -> None:
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")
        loop_start = autorun.index('while [ "$raw_identity_copy" -lt 5 ]; do')
        loop_end = autorun.index("    done", loop_start)
        identity_loop = autorun[loop_start:loop_end]
        expected_sequence = (
            'echo "IVC-STARRY-RAW path=$ivc_raw_csv samples=$ivc_count sha256=$raw_sha256"',
            '"$BB" sleep "$raw_identity_line_interval_seconds"',
            'echo "IVC-STARRY-RKNN-MODEL sha256=$actual_rknn_model_sha256"',
            '"$BB" sleep "$raw_identity_line_interval_seconds"',
            'echo "IVC-STARRY-RKNN-RAW sha256=$validated_rknn_sha256"',
            '"$BB" sleep "$raw_identity_line_interval_seconds"',
            'raw_identity_copy=$((raw_identity_copy + 1))',
            '"$BB" sleep "$raw_identity_copy_interval_seconds"',
        )
        cursor = 0
        for fragment in expected_sequence:
            with self.subTest(fragment=fragment):
                position = identity_loop.find(fragment, cursor)
                self.assertGreaterEqual(position, 0)
                cursor = position + len(fragment)

    def test_rknn_uart_hash_fits_shared_console_line_budget(self) -> None:
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")
        marker_match = re.search(
            r'echo "(IVC-STARRY-RKNN-RAW [^"]+)"', autorun
        )
        self.assertIsNotNone(marker_match)
        assert marker_match is not None
        rendered_marker = (
            marker_match.group(1)
            .replace("$ivc_count", "1800")
            .replace("$validated_rknn_sha256", "a" * 64)
        )
        routed_record = "[guest-console:pl011-starry] " + rendered_marker

        # Keep margin below the shared console's observed 128-byte boundary.
        self.assertLessEqual(len(routed_record.encode("ascii")), 120)

    def test_ort_uart_identity_lines_are_spaced_individually(self) -> None:
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")
        loop_start = autorun.index('while [ "$raw_identity_copy" -lt 5 ]; do')
        loop_end = autorun.index("    done", loop_start)
        identity_loop = autorun[loop_start:loop_end]
        expected_sequence = (
            'echo "IVC-STARRY-RAW path=$ivc_raw_csv samples=$ivc_count sha256=$raw_sha256"',
            'elif [ "$ivc_backend" = onnxruntime ]; then',
            '"$BB" sleep "$raw_identity_line_interval_seconds"',
            'echo "IVC-STARRY-ORT-MODEL sha256=$actual_ort_model_sha256"',
            '"$BB" sleep "$raw_identity_line_interval_seconds"',
            'echo "IVC-STARRY-ORT-RAW sha256=$validated_ort_sha256"',
            '"$BB" sleep "$raw_identity_line_interval_seconds"',
            'raw_identity_copy=$((raw_identity_copy + 1))',
            '"$BB" sleep "$raw_identity_copy_interval_seconds"',
        )
        cursor = 0
        for fragment in expected_sequence:
            with self.subTest(fragment=fragment):
                position = identity_loop.find(fragment, cursor)
                self.assertGreaterEqual(position, 0)
                cursor = position + len(fragment)

    def test_ort_uart_hash_fits_shared_console_line_budget(self) -> None:
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")
        marker_match = re.search(r'echo "(IVC-STARRY-ORT-RAW [^"]+)"', autorun)
        self.assertIsNotNone(marker_match)
        assert marker_match is not None
        rendered_marker = marker_match.group(1).replace(
            "$validated_ort_sha256", "a" * 64
        )
        routed_record = "[guest-console:pl011-starry] " + rendered_marker

        # Keep margin below the shared console's observed 128-byte boundary.
        self.assertLessEqual(len(routed_record.encode("ascii")), 120)

    def test_restart_profile_persists_phase_one_before_waiting_for_vm_reset(self) -> None:
        builder = STARRY_ROOTFS_BUILD.read_text(encoding="utf-8")
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")

        self.assertIn("none|error|restart", builder)
        self.assertIn(
            "fault profile must be 'none', 'error', or 'restart'",
            builder,
        )
        self.assertIn("ivc_restart_previous_session=286331153", builder)
        self.assertIn("ivc_restart_current_session=572662306", builder)
        self.assertIn("ivc_restart_first_count=20", builder)
        self.assertIn("ivc_restart_ack_timeout_ms=1000", builder)
        self.assertIn("ivc_restart_ack_timeout_ms=%s", builder)
        self.assertIn("/var/lib/ivc/restart-phase-1.done", autorun)
        self.assertIn("/var/lib/ivc/raw-before-reset.csv", autorun)
        self.assertIn("IVC-STARRY-RESTART-ARMED", autorun)
        self.assertIn("IVC-STARRY-RESTART-RESUME", autorun)
        self.assertIn("restart_resume_copy=0", autorun)
        self.assertIn('while [ "$restart_resume_copy" -lt 3 ]', autorun)
        self.assertIn('"$BB" sleep 0.1', autorun)
        self.assertIn(
            'restart_uart_sha256=$(printf \'%s\' "$restart_raw_sha256" | "$BB" cut -c1-12)',
            autorun,
        )
        self.assertIn("sha256=$restart_uart_sha256", autorun)
        self.assertIn('--fault-profile restart', autorun)
        self.assertIn('--restart-previous-session "$ivc_restart_previous_session"', autorun)
        self.assertEqual(
            autorun.count('--ack-timeout-ms "$ivc_restart_ack_timeout_ms"'),
            2,
        )
        self.assertLess(
            autorun.index('"$BB" sync || fatal restart-phase-sync-failed'),
            autorun.index('IVC-STARRY-RESTART-ARMED'),
        )

    def test_restart_raw_record_fits_the_shared_uart_budget(self) -> None:
        record = (
            "[guest-console:pl011-starry] "
            "IVC-STARRY-RESTART-RAW "
            "path=/var/lib/ivc/raw-before-reset.csv "
            "samples=20 sha256="
            + "a" * 12
        )

        self.assertLessEqual(len(record.encode("ascii")), 160)

    def test_autorun_does_not_require_linux_link_state_ioctls(self) -> None:
        script = STARRY_AUTORUN.read_text(encoding="utf-8")

        self.assertNotIn("ip link set eth0 down", script)
        self.assertNotIn("ip link set eth0 up", script)
        self.assertIn("ip addr add 10.0.0.1/24 dev eth0", script)

    def test_autorun_waits_for_the_peer_before_the_first_request(self) -> None:
        script = STARRY_AUTORUN.read_text(encoding="utf-8")

        network_ready = script.index('echo "IVC-STARRY-NET')
        wait_marker = script.index('echo "IVC-STARRY-PEER-WAIT seconds=2"')
        wait = script.index('"$BB" sleep "$peer_startup_delay_seconds"')
        first_request = script.index("/usr/local/bin/ivcproto controller")
        self.assertIn("peer_startup_delay_seconds=2", script)
        self.assertLess(network_ready, wait_marker)
        self.assertLess(wait_marker, wait)
        self.assertLess(wait, first_request)

    def test_physical_controller_timeout_covers_network_warmup(self) -> None:
        builder = STARRY_ROOTFS_BUILD.read_text(encoding="utf-8")
        autorun = STARRY_AUTORUN.read_text(encoding="utf-8")

        self.assertIn("ivc_ack_timeout_ms=1000", builder)
        self.assertIn("ivc_ack_timeout_ms=%s", builder)
        self.assertIn('[ "${ivc_ack_timeout_ms:-}" = 1000 ]', autorun)
        self.assertEqual(
            autorun.count('--ack-timeout-ms "$ivc_ack_timeout_ms"'),
            3,
        )

    def test_orangepi_guests_use_typed_graph_devices(self) -> None:
        for config_path in ORANGEPI_STARRY_CONFIGS:
            with self.subTest(config=config_path.name), config_path.open("rb") as source:
                config = tomllib.load(source)

            self.assertEqual(config["base"]["guest_type"], "virtualized")
            devices = config["devices"]
            self.assertEqual(devices["passthrough"], [])
            self.assertEqual(devices["disabled"], [])
            self.assertNotIn("interrupt_mode", devices)
            self.assertNotIn("emu_devices", devices)
            self.assertEqual(
                [(device["id"], device["model"]) for device in devices["virtual"]],
                [
                    ("disk0", "virtio-blk-mmio"),
                    ("net0", "virtio-net-mmio"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
