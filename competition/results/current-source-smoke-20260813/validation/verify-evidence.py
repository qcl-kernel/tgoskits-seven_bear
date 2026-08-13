#!/usr/bin/env python3
"""Verify compact evidence formats and repository-relative Markdown links."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_hash(path: Path, expected: str, label: str) -> None:
    if sha256_file(path) != expected:
        raise ValueError(f"{label} hash does not match provenance")


def verify_runner_manifest(bundle: Path) -> None:
    ivc = bundle / "ivc"
    manifest = ivc / "runner-checksums.sha256"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, filename = line.split(maxsplit=1)
        verify_hash(ivc / filename, expected, f"IVC runner file {filename}")
    print("RUNNER_MANIFEST_OK")


def verify_bundle(bundle: Path) -> None:
    json_files = sorted(bundle.rglob("*.json"))
    gzip_files = sorted(bundle.rglob("*.gz"))
    for path in json_files:
        json.loads(path.read_text(encoding="utf-8"))
        print(f"JSON_OK {path.relative_to(bundle).as_posix()}")
    for path in gzip_files:
        with gzip.open(path, "rb") as source:
            while source.read(1024 * 1024):
                pass
        print(f"GZIP_OK {path.relative_to(bundle).as_posix()}")

    metadata = json.loads((bundle / "ivc" / "metadata.json").read_text(encoding="utf-8"))
    if metadata["source"]["commit"] != "598b357f92c848e669c12cca830a4d08d0a50e36":
        raise ValueError("IVC metadata does not identify the final clean source")
    if metadata["run"]["exit_status"] != 0 or metadata["result"]["validated"] is not True:
        raise ValueError("IVC metadata does not record a validated zero-exit run")

    comparison = json.loads((bundle / "rt" / "comparison.json").read_text(encoding="utf-8"))
    if comparison["assessment"]["m2_exit_gate_met"] is not False:
        raise ValueError("current RT comparison must preserve the observed M2 failure")
    if comparison["pair"]["iterations_per_metric"] != 100:
        raise ValueError("current RT comparison has an unexpected sample count")

    provenance = json.loads((bundle / "provenance.json").read_text(encoding="utf-8"))
    if provenance["rt_pair"]["source_commit"] != "077ba386c20c29b84749f509b29e8a3f6f76e1e2":
        raise ValueError("provenance does not identify the current RT pair")
    if provenance["ivc_fault_restart"]["source_commit"] != metadata["source"]["commit"]:
        raise ValueError("provenance and IVC metadata source commits differ")
    if provenance["rt_pair"]["m2_exit_gate_met"] != comparison["assessment"]["m2_exit_gate_met"]:
        raise ValueError("provenance and RT comparison M2 decisions differ")

    ivc_outputs = provenance["ivc_fault_restart"]["outputs"]
    for filename, key in (
        ("metadata.json", "metadata_sha256"),
        ("summary.json", "summary_sha256"),
        ("console.log.gz", "console_gzip_sha256"),
        ("raw.csv.gz", "post_reset_raw_gzip_sha256"),
        ("raw-before-reset.csv.gz", "pre_reset_raw_gzip_sha256"),
    ):
        verify_hash(bundle / "ivc" / filename, ivc_outputs[key], f"IVC {filename}")

    rt_pair = provenance["rt_pair"]
    for profile in ("shared", "partitioned"):
        profile_data = rt_pair[profile]
        profile_dir = bundle / "rt" / profile
        verify_hash(
            profile_dir / "summary.json",
            profile_data["summary_sha256"],
            f"RT {profile} summary",
        )
        verify_hash(
            profile_dir / "raw.log",
            profile_data["raw_sha256"],
            f"RT {profile} raw",
        )
    verify_hash(
        bundle / "rt" / "comparison.json",
        rt_pair["comparison"]["sha256"],
        "RT comparison",
    )
    verify_runner_manifest(bundle)

    media = provenance["media"]
    video = bundle / media["path"]
    if video.stat().st_size != media["size_bytes"]:
        raise ValueError("video size does not match provenance")
    if sha256_file(video) != media["sha256"]:
        raise ValueError("video hash does not match provenance")
    media_log = (bundle / "validation" / "media.log").read_text(encoding="utf-8")
    expected_duration = f'"duration": "{media["duration_seconds"]:.6f}"'
    if expected_duration not in media_log:
        raise ValueError("ffprobe duration does not match provenance")
    if media["evidence_replay"] is not True:
        raise ValueError("video must be identified as an evidence replay")
    print("EVIDENCE_CONTRACT_OK")


def verify_markdown_links(repo: Path) -> None:
    delivery_documents = (
        "README.md",
        "design.md",
        "reproduce.md",
        "requirement.md",
        "scorecard.md",
        "test-report.md",
        "video-storyboard.md",
    )
    markdown_files = [repo / "competition" / name for name in delivery_documents]
    markdown_files.extend(sorted((repo / "competition" / "video").glob("*.md")))
    markdown_files.extend(
        sorted(
            (repo / "competition" / "results" / "current-source-smoke-20260813").rglob(
                "*.md"
            )
        )
    )
    for markdown in markdown_files:
        if not markdown.is_file():
            raise FileNotFoundError(f"missing delivery document: {markdown}")
        for raw_target in LINK.findall(markdown.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (markdown.parent / unquote(target)).resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"{markdown}: missing link target {target}")
            print(
                f"LINK_OK {markdown.relative_to(repo).as_posix()} -> "
                f"{resolved.relative_to(repo).as_posix()}"
            )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify-evidence.py REPOSITORY", file=sys.stderr)
        return 2
    repo = Path(sys.argv[1]).resolve()
    bundle = repo / "competition" / "results" / "current-source-smoke-20260813"
    verify_bundle(bundle)
    verify_markdown_links(repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
