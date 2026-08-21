from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = (
    REPO_ROOT
    / "apps"
    / "starry"
    / "orangepi-5-plus-uvc-rknn"
)
CONFIG_DIR = (
    APP_DIR / "configs"
)


class UvcRknnBoardConfigTests(unittest.TestCase):
    def read_config(self, name: str) -> str:
        return (CONFIG_DIR / name).read_text(encoding="utf-8")

    def test_core0_and_all_configs_change_only_the_declared_npu_factor(self) -> None:
        core0 = self.read_config("board-orangepi-5-plus-bench-core0.toml")
        all_cores = self.read_config("board-orangepi-5-plus-bench.toml")

        self.assertEqual(core0.count("--core-mask 0"), 2)
        self.assertEqual(all_cores.count("--core-mask all"), 2)
        self.assertEqual(
            core0.replace("--core-mask 0", "--core-mask all"),
            all_cores,
        )

    def test_comparison_configs_require_profiled_machine_readable_evidence(self) -> None:
        for name in (
            "board-orangepi-5-plus-bench-core0.toml",
            "board-orangepi-5-plus-bench.toml",
        ):
            config = self.read_config(name)
            self.assertEqual(config.count("--profile"), 2)
            self.assertIn("--duration-sec 60", config)
            self.assertIn("UVC_RKNN_BENCH_RESULT", config)
            self.assertIn("UVC_RKNN_VALIDATE_FAIL", config)

    def test_board_build_probes_sd_and_emmc_controllers(self) -> None:
        build_config = (
            APP_DIR / "build-aarch64-unknown-none-softfloat.toml"
        ).read_text(encoding="utf-8")

        self.assertEqual(build_config.count('"ax-driver/rockchip-dwmmc"'), 1)
        self.assertEqual(build_config.count('"ax-driver/rockchip-sdhci"'), 1)

    def test_measurement_build_suppresses_async_warning_noise(self) -> None:
        build_config = (
            APP_DIR / "build-aarch64-unknown-none-softfloat.toml"
        ).read_text(encoding="utf-8")

        self.assertIn('log = "Error"', build_config)

    def test_board_configs_use_prepared_stable_root_dtb(self) -> None:
        expected = (
            'dtb_file = "tmp/competition/vision/'
            'orangepi-5-plus-starry.dtb"'
        )
        board_configs = [APP_DIR / "board-orangepi-5-plus.toml"]
        board_configs.extend(sorted(CONFIG_DIR.glob("board-*.toml")))

        self.assertGreaterEqual(len(board_configs), 4)
        for config_path in board_configs:
            with self.subTest(config=config_path.name):
                config = config_path.read_text(encoding="utf-8")
                self.assertIn(expected, config)

    def test_board_configs_use_non_privileged_synced_payload(self) -> None:
        board_configs = [APP_DIR / "board-orangepi-5-plus.toml"]
        board_configs.extend(sorted(CONFIG_DIR.glob("board-*.toml")))

        for config_path in board_configs:
            with self.subTest(config=config_path.name):
                config = config_path.read_text(encoding="utf-8")
                self.assertIn(
                    "cd /home/orangepi/rknn_yolov8_image",
                    config,
                )
                self.assertNotIn("cd /rknn_yolov8_image", config)

    def test_prepare_script_defaults_to_observed_sd_root_partuuid(self) -> None:
        script = (APP_DIR / "prepare-board-dtb.sh").read_text(encoding="utf-8")

        self.assertIn(
            "PARTUUID=5874edd8-1582-a144-a298-b139acd7b0e6",
            script,
        )
        self.assertIn("prepare-service-dtb.sh", script)

    def test_fixed_image_board_smoke_does_not_require_a_uvc_device(self) -> None:
        config = self.read_config("board-orangepi-5-plus-fixed-image.toml")

        self.assertIn("--validate-list validation/images.txt", config)
        self.assertIn("--core-mask all --profile", config)
        self.assertIn("UVC_RKNN_VALIDATE_PASS images=3", config)
        self.assertIn("UVC_RKNN_FIXED_IMAGE_DONE", config)
        self.assertNotIn("--fps 30", config)

    def test_fixed_pair_board_campaign_uses_preregistered_order(self) -> None:
        config = self.read_config("board-orangepi-5-plus-fixed-pairs.toml")

        self.assertIn("for pair in 1 2 3 4 5", config)
        self.assertIn("pair % 2", config)
        self.assertIn("first=0", config)
        self.assertIn("first=all", config)
        self.assertIn("VISION_FIXED_RUN_BEGIN", config)
        self.assertIn("VISION_FIXED_RUN_END", config)
        self.assertIn("VISION_FIXED_CAMPAIGN_DONE os=starry pairs=5", config)
        self.assertIn('>"$run_log" 2>&1', config)
        self.assertIn("grep '^UVC_RKNN_BENCH_PROFILE_RESULT '", config)
        self.assertIn(
            "grep -q '^UVC_RKNN_VALIDATE_PASS images=3$'",
            config,
        )
        self.assertIn('cat "$run_log"', config)

    def test_fixed_pair_board_campaign_emits_compact_verified_records(self) -> None:
        config = self.read_config("board-orangepi-5-plus-fixed-pairs.toml")

        self.assertIn("VISION_FIXED_MODEL_SHA256", config)
        self.assertIn("emit VISION_FIXED_CHECK", config)
        self.assertIn("samples=3", config)
        self.assertIn("query_errors=0", config)
        self.assertIn("emit VISION_FIXED_VALUE", config)
        for metric in (
            "total_avg",
            "total_p95",
            "letterbox_avg",
            "letterbox_p95",
            "npu_avg",
            "npu_p95",
        ):
            self.assertIn(f"metric={metric}", config)
        self.assertIn("emit()", config)
        self.assertIn("sleep 1", config)
        self.assertIn(
            "(?:root@starry:[^\\\\r\\\\n]* # )?VISION_FIXED_CAMPAIGN_DONE",
            config,
        )
        self.assertLess(
            config.index("model_digest=$(sha256sum"),
            config.index("emit VISION_FIXED_CAMPAIGN_BEGIN"),
        )
        self.assertNotIn(
            "grep -E '^UVC_RKNN_(BENCH_PROFILE_RESULT|VALIDATE_PASS)'",
            config,
        )

    def test_axvisor_vision_loop_uses_isolated_fixed_resource_contracts(self) -> None:
        config_dir = REPO_ROOT / "competition" / "ivc" / "config"
        build = (config_dir / "axvisor-orangepi-5-plus-vision.toml").read_text(
            encoding="utf-8"
        )
        starry = (
            config_dir / "orangepi-5-plus-starry-smp2-vision.toml"
        ).read_text(encoding="utf-8")
        zephyr = (config_dir / "orangepi-5-plus-zephyr-vision.toml").read_text(
            encoding="utf-8"
        )
        board = (config_dir / "board-orangepi-5-plus-vision.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn('"rk3588-npu-handoff"', build)
        self.assertEqual(build.count("vision.toml"), 2)
        self.assertIn("cpu_num = 2", starry)
        self.assertIn('passthrough = [{ path = "/npu@fdab0000" }]', starry)
        self.assertIn("starry-ivc-rootfs-vision.img", starry)
        self.assertIn("entry_point = 0x4000_100c", zephyr)
        self.assertIn('header_mode = "fixed-twelve-byte"', zephyr)
        self.assertIn('shell_init_cmd = "sync-host"', board)
        self.assertIn("AXVISOR_HOST_FILESYSTEM_SYNCED", board)

        guest_dts = (
            REPO_ROOT / "competition" / "ivc" / "starry" / "orangepi-5-plus-rknpu.dts"
        ).read_text(encoding="utf-8")
        npu_node = guest_dts.split("npu@fdab0000", maxsplit=1)[1]
        self.assertIn("tgos,host-prepared-resources;", npu_node)
        self.assertNotIn("clock-names", npu_node)

    def test_vision_board_session_waits_for_terminal_host_sync_marker(self) -> None:
        board_config = (
            REPO_ROOT
            / "competition"
            / "ivc"
            / "config"
            / "board-orangepi-5-plus-vision.toml"
        )
        config = board_config.read_text(encoding="utf-8")
        success_block = config.split("success_regex = [", maxsplit=1)[1].split(
            "]", maxsplit=1
        )[0]
        success_patterns = [
            line.strip().removesuffix(",").removeprefix('"').removesuffix('"')
            for line in success_block.splitlines()
            if line.strip()
        ]

        self.assertEqual(
            success_patterns,
            [r"(?m)^AXVISOR_HOST_FILESYSTEM_SYNCED\\r?$"],
        )

    def test_vision_runner_stages_hashed_assets_and_runs_strict_analyzer(self) -> None:
        ivc_dir = REPO_ROOT / "competition" / "ivc"
        stage = (ivc_dir / "stage-vision.sh").read_text(encoding="utf-8")
        runner = (ivc_dir / "run-vision-closed-loop.sh").read_text(
            encoding="utf-8"
        )

        for artifact in (
            "starryos-rknpu.bin",
            "starry-orangepi-5-plus-rknpu.dtb",
            "starry-ivc-rootfs-vision.img",
        ):
            self.assertIn(artifact, stage)
        self.assertIn("sha256sum -c", stage)
        self.assertIn("sync", stage)
        self.assertIn("analyze_closed_loop.py", runner)
        self.assertIn("ORANGEPI_IVC_RAW_CSV=", runner)
        self.assertIn("checksums.sha256", runner)


if __name__ == "__main__":
    unittest.main()
