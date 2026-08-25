from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SUBMISSION = Path(__file__).resolve().parents[1]
REPO = SUBMISSION.parents[1]


def load_tool(name: str):
    path = SUBMISSION / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"competition_submission_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EvidenceSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = json.loads(
            (SUBMISSION / "data" / "evidence-snapshot.json").read_text(encoding="utf-8")
        )

    def test_all_evidence_inputs_match_their_recorded_hashes(self) -> None:
        inputs = self.snapshot["evidence_inputs"]
        self.assertEqual(len(inputs), 21)
        for item in inputs.values():
            path = REPO / item["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(sha256(path), item["sha256"], path)

    def test_formal_rt_metrics_and_provenance_are_frozen(self) -> None:
        realtime = self.snapshot["realtime"]
        self.assertEqual(realtime["campaign_source_commit"], "c82da8464ab69e7da95e9be08293559e67b28fac")
        self.assertFalse(realtime["current_head_rerun"])
        self.assertEqual(realtime["pair_count"], 5)
        self.assertEqual(realtime["iterations_per_metric"], 10_000)
        self.assertEqual(realtime["metrics"]["dispatch"]["worst_max_improvement_percent"], 99.331)
        self.assertEqual(realtime["metrics"]["dispatch"]["worst_p99_improvement_percent"], -1.08)
        self.assertEqual(realtime["current_head_blob_audit"], {"same": 33, "total": 34})

    def test_claim_boundaries_are_fail_closed(self) -> None:
        self.assertTrue(all(value is False for value in self.snapshot["claim_boundaries"].values()))
        self.assertFalse(self.snapshot["vision"]["continuous_loop"]["physical_actuator_claimed"])
        self.assertFalse(self.snapshot["vision"]["labeled_pilot"]["overall_ai_superiority_demonstrated"])
        self.assertEqual(self.snapshot["physical_actuator"]["claims"]["id1_single_cycle"], "pass")
        self.assertEqual(self.snapshot["physical_actuator"]["claims"]["rtos_mediator"], "not-tested")


class UpstreamCiEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = json.loads(
            (
                REPO
                / "competition"
                / "results"
                / "upstream-pr-2182-ci-20260825"
                / "summary.json"
            ).read_text(encoding="utf-8")
        )

    def test_pr_ci_completed_with_all_jobs_successful(self) -> None:
        source = self.summary["source"]
        workflow = self.summary["workflow"]
        self.assertEqual(source["repository"], "rcore-os/tgoskits")
        self.assertEqual(source["pull_request"], 2182)
        self.assertEqual(source["head_sha"], "75d8f3918580471a3451b29ca5d33a015bd5bb81")
        self.assertEqual(workflow["run_id"], 32794757246)
        self.assertEqual(workflow["status"], "completed")
        self.assertEqual(workflow["conclusion"], "success")
        self.assertEqual(workflow["jobs_total"], 35)
        self.assertEqual(workflow["jobs_success"], 35)
        self.assertEqual(workflow["jobs_failed"], 0)
        self.assertEqual(workflow["jobs_cancelled"], 0)
        self.assertTrue(
            all(job["conclusion"] == "success" for job in self.summary["critical_jobs"])
        )

    def test_pr_fixes_map_to_the_results_branch_commits(self) -> None:
        mapping = {
            item["pr_sha"]: item["seven_bear_sha"]
            for item in self.summary["integrated_fixes"]
        }
        self.assertEqual(
            mapping,
            {
                "cf52846efe04166f17282e5fc10426be6d64e947": (
                    "adf9e671dd93f6b8c315aa06d732ede1f6d54d00"
                ),
                "75d8f3918580471a3451b29ca5d33a015bd5bb81": (
                    "7b5c59af5c199dff4c95166ef4e743cdc6d00b1c"
                ),
            },
        )


class PolishGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.polish = load_tool("polish_with_agy")

    def test_allows_only_declared_chinese_count_conversion(self) -> None:
        source = {"entry": "完成五组测试，结果为 99.331%，路径是 `result.json`。"}
        polished = {"entry": "已完成 5 组测试，结果为 99.331%，路径为 `result.json`。"}
        self.polish.validate_batch(source, polished)

    def test_rejects_protected_number_drift(self) -> None:
        source = {"entry": "结果为 99.331%。"}
        with self.assertRaisesRegex(ValueError, "protected token drift"):
            self.polish.validate_batch(source, {"entry": "结果为 99.332%。"})

    def test_rejects_added_numeric_claim(self) -> None:
        with self.assertRaisesRegex(ValueError, "protected token drift"):
            self.polish.validate_batch({"entry": "测试通过。"}, {"entry": "测试 100% 通过。"})


class GeneratorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assemble = load_tool("assemble_documents")
        cls.video = load_tool("build_video")

    def test_routed_corrections_cover_all_final_artifacts(self) -> None:
        routed = self.assemble.load_routed_corrections("evidence-count-corrections.json")
        self.assertEqual(set(routed), {"design", "test", "reproduction", "video"})
        self.assertEqual(routed["video"], {})
        self.assertIn("21 个保留证据输入", routed["design"]["17_traceability"])

    def test_video_timeline_is_exactly_five_minutes(self) -> None:
        scenes = self.video.load_scenes()
        self.assertEqual(len(scenes), 10)
        self.assertEqual(sum(scene.duration for scene in scenes), 300)

    def test_terminal_evidence_stays_inside_the_projection_safe_area(self) -> None:
        self.assertEqual(self.video.TERMINAL_SCENES, frozenset({1, 2, 4}))
        self.assertTrue(
            all(self.video.scene_media_kind(index) == "terminal" for index in self.video.TERMINAL_SCENES)
        )
        left, top, right, bottom = self.video.TERMINAL_MEDIA_BOX
        self.assertGreaterEqual(left, round(self.video.WIDTH * 0.08))
        self.assertGreaterEqual(top, round(self.video.HEIGHT * 0.15))
        self.assertLessEqual(right, round(self.video.WIDTH * 0.92))
        self.assertLessEqual(bottom, round(self.video.HEIGHT * 0.85))

    def test_camera_scenes_use_a_physical_live_capture(self) -> None:
        self.assertEqual(self.video.LIVE_CAMERA_SCENES, frozenset({6, 8}))
        self.assertTrue(
            all(
                self.video.scene_media_kind(index) == "live-camera"
                for index in self.video.LIVE_CAMERA_SCENES
            )
        )
        self.assertTrue(self.video.LIVE_CAMERA_VIDEO.is_file())
        metadata = json.loads(self.video.LIVE_CAMERA_METADATA.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_kind"], "physical-usb-camera-live-capture")
        self.assertEqual(metadata["hostname"], "orangepi5plus")
        self.assertEqual(metadata["device"], "/dev/video0")
        self.assertEqual(metadata["driver"], "uvcvideo")
        self.assertEqual(metadata["frame_count"], 600)
        self.assertEqual(metadata["video_sha256"], sha256(self.video.LIVE_CAMERA_VIDEO))

    def test_closing_scene_focuses_on_the_system_instead_of_material_generation(self) -> None:
        closing = self.video.load_scenes()[-1]
        copy = "\n".join((closing.title, closing.caption, closing.narration))
        for forbidden in ("agy", "Gemini", "ilm-zh", "PDF", "提交材料", "证据输入", "视频来自"):
            self.assertNotIn(forbidden, copy)

    def test_subtitle_chunks_stay_within_display_limit(self) -> None:
        chunks = self.video.subtitle_chunks("第一句用于测试；第二句包含更多内容，但仍需被稳定切分。")
        self.assertTrue(chunks)
        self.assertTrue(all(len(chunk) <= 36 for chunk in chunks))

    def test_final_subtitles_match_the_polished_scene_copy(self) -> None:
        scenes = self.video.load_scenes()
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / "generated.srt"
            self.video.write_subtitles(generated, scenes)
            expected = SUBMISSION / "output" / "video" / "tgoskits-ivc-competition-demo.zh-CN.srt"
            self.assertEqual(generated.read_bytes(), expected.read_bytes())

        manifest = json.loads(
            (SUBMISSION / "output" / "video" / "video-manifest.json").read_text(encoding="utf-8")
        )
        expected_hashes = [hashlib.sha256(scene.narration.encode("utf-8")).hexdigest() for scene in scenes]
        self.assertEqual(
            [item["narration_sha256"] for item in manifest["scenes"]],
            expected_hashes,
        )

    def test_atempo_chain_uses_supported_factors(self) -> None:
        chain = self.video.atempo_chain(4.5)
        factors = [float(item.split("=", 1)[1]) for item in chain.split(",")]
        self.assertTrue(all(0.5 <= factor <= 2.0 for factor in factors))
        product = 1.0
        for factor in factors:
            product *= factor
        self.assertAlmostEqual(product, 4.5, places=5)


if __name__ == "__main__":
    unittest.main()
