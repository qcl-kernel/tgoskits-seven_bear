from __future__ import annotations

import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUTORUN = REPOSITORY_ROOT / "competition/ivc/starry/autorun-vision-so100-prep.sh"
ROOTFS_BUILDER = REPOSITORY_ROOT / "competition/ivc/starry/build-vision-rootfs.sh"
STARRY_BUILD_CONFIG = (
    REPOSITORY_ROOT / "competition/ivc/config/starry-aarch64-rknpu-usb.toml"
)
STARRY_GUEST_CONFIG = (
    REPOSITORY_ROOT
    / "competition/ivc/config/orangepi-5-plus-starry-smp2-vision-so100-prep.toml"
)
ZEPHYR_PROFILE = (
    REPOSITORY_ROOT / "competition/ivc/zephyr/board-vision-so100-prep.conf"
)
PREFLIGHT = REPOSITORY_ROOT / "competition/ivc/preflight-vision-so100.sh"
RUNNER = REPOSITORY_ROOT / "competition/ivc/run-vision-so100-prep.sh"
BUILD_PREP = REPOSITORY_ROOT / "competition/ivc/build-vision-so100-prep.sh"
IMAGE_RUNNER_BUILD = (
    REPOSITORY_ROOT
    / "apps/starry/orangepi-5-plus-uvc-rknn/build-image-runner.sh"
)
LIBUSB_BUILDER = REPOSITORY_ROOT / "competition/vision/build-libusb-aarch64.sh"
LIBUVC_BUILDER = REPOSITORY_ROOT / "competition/vision/build-libuvc-aarch64.sh"
UVC_CAPTURE = (
    REPOSITORY_ROOT
    / "apps/starry/orangepi-5-plus-uvc-rknn/rknn-yolov8-image/cpp/uvc_capture.cc"
)


class So100PreparationContractTests(unittest.TestCase):
    def test_starry_guest_owns_only_the_audited_ehci_tree_and_npu(self) -> None:
        with STARRY_GUEST_CONFIG.open("rb") as stream:
            config = tomllib.load(stream)

        self.assertEqual(
            config["devices"]["passthrough"],
            [{"path": "/npu@fdab0000"}, {"path": "/usb@fc880000"}],
        )
        self.assertNotIn("fc400000", STARRY_GUEST_CONFIG.read_text(encoding="utf-8"))
        self.assertIn(
            "starry-ivc-rootfs-vision-so100-prep.img",
            config["devices"]["virtual"][0]["image_path"],
        )

    def test_starry_build_enables_ehci_without_expanding_the_existing_profile(self) -> None:
        with STARRY_BUILD_CONFIG.open("rb") as stream:
            config = tomllib.load(stream)

        self.assertEqual(
            config["features"],
            [
                "ax-driver/virtio-blk",
                "ax-driver/virtio-net",
                "ax-driver/rockchip-ehci",
                "rknpu",
            ],
        )

    def test_live_runner_controller_and_actuator_are_one_online_pipeline(self) -> None:
        script = AUTORUN.read_text(encoding="utf-8")

        self.assertIn("./rknn_yolov8_stream", script)
        self.assertIn("--closed-loop", script)
        self.assertIn("--serial-fps", script)
        self.assertIn('10.0.0.2:5500 - "$vision_session_id"', script)
        self.assertIn("/usr/local/bin/ivc-vision-actuator --dry-run -", script)
        self.assertNotIn("ivc-vision-actuator --execute", script)
        self.assertGreaterEqual(script.count('"$BB" tee'), 3)
        self.assertGreaterEqual(script.count("/dev/console"), 4)
        self.assertNotIn("--validate-list", script)

    def test_rootfs_profile_and_rtos_freeze_the_same_finite_count(self) -> None:
        builder = ROOTFS_BUILDER.read_text(encoding="utf-8")
        zephyr = ZEPHYR_PROFILE.read_text(encoding="utf-8")

        self.assertIn("base_image=${IVC_VISION_BASE_IMAGE:-", builder)
        self.assertIn('"vision_max_inferences=180"', builder)
        self.assertIn("CONFIG_IVC_EXPECTED_VISION_DECISIONS=180", zephyr)
        self.assertIn("CONFIG_IVC_EXIT_AFTER_EXPECTED_COMMANDS=y", zephyr)
        self.assertIn("/opt/vision/rknn_yolov8_stream", builder)
        self.assertIn("/usr/local/bin/ivc-vision-actuator", builder)
        self.assertIn('"vision_actuator_mode=dry-run"', builder)

    def test_live_rootfs_cannot_fall_back_to_repository_sample_images(self) -> None:
        builder = ROOTFS_BUILDER.read_text(encoding="utf-8")
        fixed_only_assets = builder.index(
            'if [[ "$vision_mode" == fixed-images ]]; then\n'
            '    required_inputs+=('
        )
        live_inputs = builder.index(
            'if [[ "$vision_mode" == so100-prep ]]; then\n'
            '    required_inputs+=("$actuator" "$libuvc" "$libusb")'
        )

        self.assertLess(fixed_only_assets, live_inputs)
        self.assertIn(
            'if [[ "$vision_mode" == fixed-images ]]; then\n'
            '    for name in images.txt expected.txt',
            builder,
        )

    def test_live_rootfs_installs_libuvc_under_its_elf_soname(self) -> None:
        builder = ROOTFS_BUILDER.read_text(encoding="utf-8")
        autorun = AUTORUN.read_text(encoding="utf-8")
        capture = UVC_CAPTURE.read_text(encoding="utf-8")

        self.assertIn('/opt/vision/lib/libuvc.so.0 0100755', builder)
        self.assertIn('[ -r /opt/vision/lib/libuvc.so.0 ]', autorun)
        self.assertIn('"libuvc.so.0"', capture)

    def test_preflight_requires_both_usb_identities_on_the_same_controller(self) -> None:
        script = PREFLIGHT.read_text(encoding="utf-8")

        self.assertIn("4c4a:4a55", script)
        self.assertIn("1a86:55d3", script)
        self.assertIn("expected_controller=/usb@fc880000", script)
        self.assertIn('inspect_usb_identity "$camera_usb_id" uvcvideo', script)
        self.assertIn('inspect_usb_identity "$arm_usb_id" cdc_acm', script)
        self.assertIn("motion_attempted=0", script)
        self.assertNotIn("stty", script)
        self.assertNotIn("cat /dev/ttyACM0", script)
        self.assertNotIn(">/dev/ttyACM0", script)

    def test_prep_run_cannot_be_reported_as_physical_motion(self) -> None:
        script = RUNNER.read_text(encoding="utf-8")

        self.assertIn("--physical forbidden", script)
        self.assertIn("physical_applied=0", script)
        self.assertIn("physical_verified=0", script)
        self.assertNotIn("--require-physical", script)

    def test_external_usb_runtime_sources_are_pinned_and_audited(self) -> None:
        libusb = LIBUSB_BUILDER.read_text(encoding="utf-8")
        libuvc = LIBUVC_BUILDER.read_text(encoding="utf-8")

        self.assertIn("4239bc3a50014b8e6a5a2a59df1fff3b7469543b", libusb)
        self.assertIn("--disable-udev", libusb)
        self.assertIn("unexpected libusb runtime dependency", libusb)
        self.assertIn("047920bcdfb1dac42424c90de5cc77dfc9fba04d", libuvc)
        self.assertIn("unexpected", ROOTFS_BUILDER.read_text(encoding="utf-8"))

    def test_zephyr_cross_prefix_cannot_replace_the_linux_runner_toolchain(self) -> None:
        prep = BUILD_PREP.read_text(encoding="utf-8")
        image_runner = IMAGE_RUNNER_BUILD.read_text(encoding="utf-8")

        self.assertIn(
            "linux_cross_compile=${IVC_LINUX_CROSS_COMPILE:-aarch64-linux-gnu-}",
            prep,
        )
        self.assertIn(
            "zephyr_cross_compile=${IVC_ZEPHYR_CROSS_COMPILE:-${CROSS_COMPILE:-}}",
            prep,
        )
        self.assertIn('IVC_LINUX_CROSS_COMPILE="$linux_cross_compile"', prep)
        self.assertIn('"${zephyr_env[@]}" west build', prep)
        self.assertIn(
            "${IVC_LINUX_CROSS_COMPILE:-${CROSS_COMPILE:-aarch64-linux-gnu-}}",
            image_runner,
        )


if __name__ == "__main__":
    unittest.main()
