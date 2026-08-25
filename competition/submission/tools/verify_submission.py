#!/usr/bin/env python3
"""Verify final competition artifacts, provenance, media, and checksums."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any


SUBMISSION = Path(__file__).resolve().parents[1]
REPO = SUBMISSION.parents[1]
SNAPSHOT = SUBMISSION / "data" / "evidence-snapshot.json"
POLISH_MANIFEST = SUBMISSION / "agy-polish-manifest.json"
VIDEO = SUBMISSION / "output" / "video" / "tgoskits-ivc-competition-demo.mp4"
SUBTITLES = SUBMISSION / "output" / "video" / "tgoskits-ivc-competition-demo.zh-CN.srt"
VIDEO_MANIFEST = SUBMISSION / "output" / "video" / "video-manifest.json"
DESIGN_PDF = SUBMISSION / "output" / "pdf" / "tgoskits-competition-design-zh.pdf"
TEST_PDF = SUBMISSION / "output" / "pdf" / "tgoskits-competition-test-report-zh.pdf"
UPSTREAM_CI_DIR = REPO / "competition" / "results" / "upstream-pr-2182-ci-20260825"
UPSTREAM_CI_SUMMARY = UPSTREAM_CI_DIR / "summary.json"
UPSTREAM_CI_README = UPSTREAM_CI_DIR / "README.md"


def main() -> int:
    snapshot = load_json(SNAPSHOT)
    verify_evidence(snapshot)
    verify_upstream_ci()
    verify_polish_manifest()
    verify_documents()
    verify_charts()
    verify_pdfs()
    verify_video()
    verify_visual_qa()
    checksum_count = write_checksums()
    print(
        "SUBMISSION_VERIFY_PASS "
        f"evidence_inputs={len(snapshot['evidence_inputs'])} charts=10 pdfs=2 "
        f"video_seconds={probe_video()['format']['duration']} checksums={checksum_count}"
    )
    return 0


def load_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(parsed, dict), f"expected JSON object: {path}")
    return parsed


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_evidence(snapshot: dict[str, Any]) -> None:
    inputs = snapshot.get("evidence_inputs")
    require(isinstance(inputs, dict) and len(inputs) == 21, "expected 21 evidence inputs")
    for name, item in inputs.items():
        path = REPO / item["path"]
        require(path.is_file(), f"missing evidence input {name}: {path}")
        require(sha256(path) == item["sha256"], f"evidence hash mismatch: {name}")
    require(snapshot["generation"]["upstream_left_right_count"].split()[0] == "0", "branch is behind upstream/dev")
    require(snapshot["realtime"]["current_head_rerun"] is False, "RT provenance boundary drift")
    boundaries = snapshot["claim_boundaries"]
    require(all(value is False for value in boundaries.values()), "claim boundary unexpectedly widened")


def verify_upstream_ci() -> None:
    summary = load_json(UPSTREAM_CI_SUMMARY)
    source = summary.get("source", {})
    workflow = summary.get("workflow", {})
    require(summary.get("schema_version") == 1, "unexpected upstream CI evidence schema")
    require(source.get("repository") == "rcore-os/tgoskits", "upstream CI repository drift")
    require(source.get("pull_request") == 2182, "upstream CI pull request drift")
    require(
        source.get("base_sha") == "f70cf8d0eadc43caf176e7873244e8fae8154d9c",
        "upstream CI base SHA drift",
    )
    require(
        source.get("head_sha") == "75d8f3918580471a3451b29ca5d33a015bd5bb81",
        "upstream CI head SHA drift",
    )
    require(workflow.get("run_id") == 32794757246, "upstream CI run ID drift")
    require(workflow.get("status") == "completed", "upstream CI run is incomplete")
    require(workflow.get("conclusion") == "success", "upstream CI run did not succeed")
    require(
        (workflow.get("jobs_total"), workflow.get("jobs_success")) == (35, 35),
        "upstream CI successful job count drift",
    )
    require(
        (workflow.get("jobs_failed"), workflow.get("jobs_cancelled")) == (0, 0),
        "upstream CI contains failed or cancelled jobs",
    )
    critical_jobs = summary.get("critical_jobs")
    require(isinstance(critical_jobs, list) and critical_jobs, "upstream CI critical jobs missing")
    require(
        all(job.get("conclusion") == "success" for job in critical_jobs),
        "an upstream CI critical job did not succeed",
    )
    integrated_fixes = {
        item.get("pr_sha"): item.get("seven_bear_sha")
        for item in summary.get("integrated_fixes", [])
    }
    require(
        integrated_fixes
        == {
            "cf52846efe04166f17282e5fc10426be6d64e947": (
                "adf9e671dd93f6b8c315aa06d732ede1f6d54d00"
            ),
            "75d8f3918580471a3451b29ca5d33a015bd5bb81": (
                "7b5c59af5c199dff4c95166ef4e743cdc6d00b1c"
            ),
        },
        "upstream CI integrated-fix mapping drift",
    )
    require(UPSTREAM_CI_README.is_file(), "upstream CI evidence README is missing")
    require(
        workflow["run_url"] in UPSTREAM_CI_README.read_text(encoding="utf-8"),
        "upstream CI run URL is missing from evidence README",
    )


def verify_polish_manifest() -> None:
    manifest = load_json(POLISH_MANIFEST)
    records = manifest.get("records")
    require(isinstance(records, list) and len(records) >= 9, "polish manifest is incomplete")
    outputs: set[str] = set()
    for record in records:
        require(record["model"] == "gemini-3.7-flash-high", "unexpected polish model")
        require(record["effort"] == "high", "unexpected polish effort")
        source = REPO / record["source"]
        output = REPO / record["output"]
        require(source.is_file() and output.is_file(), f"missing polished pair: {record['output']}")
        require(sha256(source) == record["source_sha256"], f"polish source drift: {source}")
        require(sha256(output) == record["output_sha256"], f"polish output drift: {output}")
        calls = record.get("calls")
        require(isinstance(calls, list) and calls, f"missing agy call record: {output}")
        for call in calls:
            require(bool(call.get("conversation_id")), f"missing agy conversation ID: {output}")
            require(isinstance(call.get("usage"), dict), f"missing agy usage: {output}")
        outputs.add(record["output"])
    require(
        "competition/submission/copy/evidence-count-corrections.json" in outputs,
        "final evidence-count correction lacks agy provenance",
    )


def verify_documents() -> None:
    documents = [
        SUBMISSION / "design-document.md",
        SUBMISSION / "test-report.md",
        SUBMISSION / "reproduction-guide.md",
        SUBMISSION / "video-script.md",
    ]
    for path in documents:
        require(path.is_file() and path.stat().st_size > 1024, f"missing or empty document: {path}")
        content = path.read_text(encoding="utf-8")
        require("\u2011" not in content, f"nonbreaking hyphen in {path}")
    require("21 个保留证据输入" in documents[0].read_text(encoding="utf-8"), "design evidence count drift")
    require("21 个输入 JSON" in documents[1].read_text(encoding="utf-8"), "test evidence count drift")
    require("21 个保留结果 JSON" in documents[2].read_text(encoding="utf-8"), "reproduction evidence count drift")
    video_script = documents[3].read_text(encoding="utf-8")
    require("/dev/video0" in video_script, "physical camera source missing from video script")
    require("非 validation 目录中的样本图片" in video_script, "camera sample boundary missing")
    require("未在同一 sequence 下同步" in video_script, "physical-loop boundary missing")
    closing = video_script.rsplit("## Scene 10", maxsplit=1)[-1]
    for forbidden in ("agy", "Gemini", "ilm-zh", "PDF", "提交材料"):
        require(forbidden not in closing, f"material-generation narration remains: {forbidden}")


def verify_charts() -> None:
    chart_dir = SUBMISSION / "assets" / "charts"
    pngs = sorted(chart_dir.glob("[0-9][0-9]-*.png"))
    svgs = sorted(chart_dir.glob("[0-9][0-9]-*.svg"))
    require(len(pngs) == 10 and len(svgs) == 10, "expected ten PNG/SVG chart pairs")
    require({path.stem for path in pngs} == {path.stem for path in svgs}, "chart pair mismatch")
    for path in (*pngs, *svgs):
        require(path.stat().st_size > 10_000, f"chart is unexpectedly small: {path}")


def verify_pdfs() -> None:
    for path, minimum_size in ((DESIGN_PDF, 1_000_000), (TEST_PDF, 1_000_000)):
        require(path.is_file() and path.stat().st_size > minimum_size, f"missing or small PDF: {path}")
        require(path.read_bytes()[:5] == b"%PDF-", f"invalid PDF signature: {path}")
    upstream = (SUBMISSION / "vendor" / "ilm-zh" / "UPSTREAM.md").read_text(encoding="utf-8")
    require("7a6080e891631d45ab2c2b40531ea8a3f211270f" in upstream, "ilm-zh pin drift")


def probe_video() -> dict[str, Any]:
    require(shutil.which("ffprobe") is not None, "ffprobe is required for media verification")
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(VIDEO),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(process.stdout)


def verify_video() -> None:
    require(VIDEO.is_file() and VIDEO.stat().st_size > 10_000_000, "missing or small final video")
    probe = probe_video()
    duration = float(probe["format"]["duration"])
    require(math.isclose(duration, 300.0, abs_tol=0.08), f"video duration drift: {duration}")
    streams = probe["streams"]
    video_stream = next(stream for stream in streams if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in streams if stream["codec_type"] == "audio")
    subtitle_stream = next(stream for stream in streams if stream["codec_type"] == "subtitle")
    require(video_stream["codec_name"] == "h264", "final video must be H.264")
    require(video_stream["width"] == 1920 and video_stream["height"] == 1080, "video resolution drift")
    require(video_stream["avg_frame_rate"] == "30/1", "video frame rate drift")
    require(audio_stream["codec_name"] == "aac" and audio_stream["sample_rate"] == "48000", "audio format drift")
    require(subtitle_stream["codec_name"] == "mov_text", "embedded subtitle stream missing")
    require(subtitle_stream.get("tags", {}).get("language") == "zho", "subtitle language tag drift")

    manifest = load_json(VIDEO_MANIFEST)
    require(sum(scene["duration_seconds"] for scene in manifest["scenes"]) == 300, "scene timeline drift")
    require(manifest["outputs"]["video"]["sha256"] == sha256(VIDEO), "video manifest hash mismatch")
    require(manifest["outputs"]["subtitles"]["sha256"] == sha256(SUBTITLES), "subtitle manifest hash mismatch")
    live_source = manifest["live_camera_source"]
    live_video = REPO / live_source["path"]
    require(live_source["source_kind"] == "physical-usb-camera-live-capture", "camera source kind drift")
    require(live_source["device"] == "/dev/video0", "camera device drift")
    require(live_source["sha256"] == sha256(live_video), "camera source hash mismatch")
    require(
        [scene["index"] for scene in manifest["scenes"] if scene["media_kind"] == "terminal"]
        == [1, 2, 4],
        "terminal scene routing drift",
    )
    require(
        [scene["index"] for scene in manifest["scenes"] if scene["media_kind"] == "live-camera"]
        == [6, 8],
        "live-camera scene routing drift",
    )
    subtitle_text = SUBTITLES.read_text(encoding="utf-8-sig")
    require("/dev/video0" in subtitle_text, "physical camera source missing from subtitles")
    require("不在同一时间线" in subtitle_text, "camera synchronization boundary missing")


def verify_visual_qa() -> None:
    qa = load_json(SUBMISSION / "visual-qa.json")
    require([item["pages"] for item in qa["pdfs"]] == [21, 20], "PDF visual-QA page count drift")
    require(all(item["result"] == "pass" for item in qa["pdfs"]), "PDF visual QA not passed")
    require(len(qa["video"]["midpoint_frames_seconds"]) == 10, "video visual QA needs ten scene frames")
    require(qa["video"]["result"] == "pass", "video visual QA not passed")


def checksum_paths() -> list[Path]:
    paths = [
        SUBMISSION / "README.md",
        SUBMISSION / "design-document.md",
        SUBMISSION / "test-report.md",
        SUBMISSION / "reproduction-guide.md",
        SUBMISSION / "video-script.md",
        SNAPSHOT,
        POLISH_MANIFEST,
        SUBMISSION / "visual-qa.json",
        DESIGN_PDF,
        TEST_PDF,
        VIDEO,
        SUBTITLES,
        VIDEO_MANIFEST,
        UPSTREAM_CI_README,
        UPSTREAM_CI_SUMMARY,
    ]
    paths.extend(sorted((SUBMISSION / "assets" / "charts").glob("[0-9][0-9]-*.*")))
    return paths


def write_checksums() -> int:
    paths = checksum_paths()
    for path in paths:
        require(path.is_file(), f"checksum target missing: {path}")
    lines = [f"{sha256(path)}  {path.resolve().relative_to(REPO.resolve()).as_posix()}" for path in paths]
    output = SUBMISSION / "output" / "SHA256SUMS"
    output.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return len(lines)


if __name__ == "__main__":
    raise SystemExit(main())
