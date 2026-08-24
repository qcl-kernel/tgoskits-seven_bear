#!/usr/bin/env python3
"""Validate a captured exact-frame StarryOS picture-in-picture evidence log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from live_pip_server import ExactFrameJoiner


def validate(
    log_path: Path, expected_frames: int, physical: str
) -> dict[str, object]:
    if expected_frames <= 0:
        raise ValueError("expected frame count must be positive")
    joiner = ExactFrameJoiner(require_physical=physical == "required")
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                joiner.feed_line(line)
    except OSError as error:
        raise ValueError(f"cannot read live log: {error}") from error
    published, diagnostics = joiner.snapshot()
    if diagnostics["error_count"] != 0:
        raise ValueError(
            f"exact-frame parser errors={diagnostics['error_count']} "
            f"last={diagnostics['last_error']}"
        )
    if published is None:
        raise ValueError("log contains no fully joined frame")
    joined_frames = published.state["revision"]
    if joined_frames != expected_frames:
        raise ValueError(
            f"joined frame count is {joined_frames}, expected {expected_frames}"
        )
    physical_applied = published.state["physical_applied"]
    physical_verified = published.state["physical_verified"]
    if physical == "forbidden" and (
        physical_applied != 0 or physical_verified != 0
    ):
        raise ValueError("dry-run log claims physical application or verification")
    if physical == "required" and physical_verified != 1:
        raise ValueError("physical evidence gate is not satisfied")
    return {
        "schema_version": 1,
        "status": "pass",
        "log": str(log_path),
        "joined_frames": joined_frames,
        "last_frame_id": published.state["frame_id"],
        "last_camera_sequence": published.state["camera_sequence"],
        "last_session_id": published.state["session_id"],
        "last_sequence": published.state["sequence"],
        "last_action": published.state["ai_action"],
        "physical_applied": physical_applied,
        "physical_verified": physical_verified,
        "physical_gate": physical,
        "parser_errors": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected-frames", type=int, required=True)
    parser.add_argument(
        "--physical", choices=("required", "forbidden", "either"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = validate(args.log, args.expected_frames, args.physical)
    except ValueError as error:
        raise SystemExit(f"LIVE_PIP_VALIDATION_FAIL reason={error}") from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"LIVE_PIP_VALIDATION_PASS frames={summary['joined_frames']} "
        f"physical_applied={summary['physical_applied']} "
        f"physical_verified={summary['physical_verified']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
