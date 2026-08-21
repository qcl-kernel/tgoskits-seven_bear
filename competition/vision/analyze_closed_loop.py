#!/usr/bin/env python3
"""Validate the fixed-frame StarryOS-to-RTOS visual sorting evidence."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import statistics
from pathlib import Path
from typing import Any


EXPECTED_ACTIONS = ["right", "left", "hold"]
EVENT_PREFIX = "VISION_CLOSED_LOOP_EVENT "
RTOS_RESULT_PREFIX = "IVC-RTOS-VISION-RESULT "
RUNNER_HASH_PREFIX = "IVC-STARRY-VISION-RUNNER-SHA256 "
CONTROLLER_HASH_PREFIX = "IVC-STARRY-VISION-CONTROLLER-SHA256 "
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
VM_PREFIX = re.compile(r"\[VM [0-9]+\] ")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AnalysisError(ValueError):
    """Raised when a console log does not prove the closed-loop contract."""


def analyze_text(text: str) -> dict[str, Any]:
    """Return a summary after strictly validating one board console log."""

    lines = _normalize_lines(text)
    _reject_failure_markers(lines)
    _require_marker(
        lines,
        "IVC-STARRY-VISION-BOOT source=fixed-images backend=rknn-npu frames=3 "
        "target_class=32 calibration_x=625",
        "Starry vision boot",
    )
    _require_marker(lines, "UVC_RKNN_VALIDATE_PASS images=3", "RKNN validation")
    _require_prefix(lines, "VISION_CLOSED_LOOP_BEGIN ", "controller begin")
    _require_marker(
        lines,
        "VISION_CLOSED_LOOP_DONE frames=3 applied=3 errors=0",
        "controller completion",
    )
    _require_marker(lines, "IVC-STARRY-VISION-DONE exit=0", "Starry completion")
    _require_marker(
        lines,
        "AXVISOR_HOST_FILESYSTEM_SYNCED",
        "host filesystem sync",
    )

    events = _parse_events(lines)
    _validate_events(events)
    rtos_result = _parse_rtos_result(lines)
    hashes = _parse_evidence_hashes(lines)

    return {
        "schema_version": 1,
        "workload": "fixed-frame-rknn-visual-sorting",
        "frames": len(events),
        "actions": [event["requested"] for event in events],
        "retries": sum(event["retries"] for event in events),
        "latency_us": {
            "inference_to_send": _metric(events, "inference_to_send_us"),
            "transport": _metric(events, "transport_us"),
            "end_to_end": _metric(events, "end_to_end_us"),
        },
        "rtos": rtos_result,
        "artifact_log_sha256": hashes,
        "acceptance": {
            "passed": True,
            "fixed_frames": True,
            "real_rknn_backend": True,
            "requested_equals_actual": True,
            "camera_throughput_claimed": False,
        },
    }


def _normalize_lines(text: str) -> list[str]:
    lines: list[str] = []
    for physical_line in text.splitlines():
        physical_line = ANSI_ESCAPE.sub("", physical_line.rstrip("\r"))
        lines.extend(
            fragment.strip()
            for fragment in VM_PREFIX.split(physical_line)
            if fragment.strip()
        )
    return lines


def _reject_failure_markers(lines: list[str]) -> None:
    markers = (
        "IVC-STARRY-VISION-FAIL",
        "IVC-VISION-CONTROLLER-FAIL",
        "IVC-RTOS-SELFTEST FAIL",
        "IVC-RTOS-NET-ERROR",
        "IVC-RTOS-FATAL",
        "AXVISOR_VM_BLOCK_SNAPSHOT_FAILED",
        "AXVISOR_HOST_FILESYSTEM_SYNC_FAILED",
    )
    for line in lines:
        for marker in markers:
            if marker in line:
                raise AnalysisError(f"failure marker present: {marker}")


def _require_marker(lines: list[str], marker: str, description: str) -> None:
    if marker not in lines:
        raise AnalysisError(f"missing {description} marker: {marker}")


def _require_prefix(lines: list[str], prefix: str, description: str) -> None:
    if not any(line.startswith(prefix) for line in lines):
        raise AnalysisError(f"missing {description} marker")


def _parse_events(lines: list[str]) -> list[dict[str, Any]]:
    events_by_frame: dict[int, dict[str, Any]] = {}
    malformed: list[tuple[int | None, AnalysisError]] = []
    for line in lines:
        if not line.startswith(EVENT_PREFIX):
            continue
        try:
            event = _parse_event(line.removeprefix(EVENT_PREFIX))
        except AnalysisError as error:
            malformed.append((_event_frame(line), error))
            continue
        previous = events_by_frame.get(event["frame"])
        if previous is not None and previous != event:
            raise AnalysisError(
                f"conflicting complete vision event records for frame {event['frame']}"
            )
        events_by_frame[event["frame"]] = event

    for frame, error in malformed:
        if frame is None or frame not in events_by_frame:
            raise error
    return [events_by_frame[frame] for frame in sorted(events_by_frame)]


def _parse_event(text: str) -> dict[str, Any]:
    fields = _parse_fields(text)
    required = (
        "frame",
        "detection",
        "class_id",
        "confidence_q10000",
        "bbox",
        "requested",
        "actual",
        "state",
        "inference_to_send_us",
        "transport_us",
        "end_to_end_us",
        "retries",
    )
    missing = [name for name in required if name not in fields]
    if missing:
        raise AnalysisError(f"vision event missing fields: {', '.join(missing)}")
    try:
        bbox = [int(value) for value in fields["bbox"].split(",")]
        event = {
            "frame": int(fields["frame"]),
            "detection": int(fields["detection"]),
            "class_id": int(fields["class_id"]),
            "confidence_q10000": int(fields["confidence_q10000"]),
            "bbox": bbox,
            "requested": fields["requested"],
            "actual": fields["actual"],
            "state": fields["state"],
            "inference_to_send_us": int(fields["inference_to_send_us"]),
            "transport_us": int(fields["transport_us"]),
            "end_to_end_us": int(fields["end_to_end_us"]),
            "retries": int(fields["retries"]),
        }
    except ValueError as error:
        raise AnalysisError(f"invalid numeric vision event field: {error}") from error
    if len(bbox) != 4:
        raise AnalysisError("vision event bbox must contain four coordinates")
    return event


def _event_frame(line: str) -> int | None:
    match = re.search(r"(?:^|\s)frame=([0-9]+)(?:\s|$)", line)
    return int(match.group(1)) if match else None


def _validate_events(events: list[dict[str, Any]]) -> None:
    if [event["frame"] for event in events] != [1, 2, 3]:
        raise AnalysisError("frame sequence must be exactly 1,2,3")
    actions = [event["requested"] for event in events]
    if actions != EXPECTED_ACTIONS:
        raise AnalysisError(f"unexpected calibrated actions: {actions}")

    for event in events:
        if event["requested"] != event["actual"]:
            raise AnalysisError(
                f"action mismatch for frame {event['frame']}: "
                f"{event['requested']} != {event['actual']}"
            )
        if event["state"] != "applied":
            raise AnalysisError(f"frame {event['frame']} was not applied")
        if not 0 <= event["confidence_q10000"] <= 10_000:
            raise AnalysisError("confidence is outside q10000 range")
        if any(event[name] < 0 for name in (
            "inference_to_send_us",
            "transport_us",
            "end_to_end_us",
            "retries",
        )):
            raise AnalysisError("latency and retry fields must be nonnegative")

    for event in events[:2]:
        if event["detection"] != 1 or event["class_id"] != 32:
            raise AnalysisError("ball frames must contain class 32 detections")
    if events[2]["detection"] != 0 or events[2]["class_id"] != 65_535:
        raise AnalysisError("hold frame must carry the no-detection sentinel")


def _parse_rtos_result(lines: list[str]) -> dict[str, int]:
    expected = {
        "accepted": 3,
        "applied": 3,
        "duplicates": 0,
        "actuator_status_sent": 3,
        "acks_sent": 3,
        "errors_sent": 0,
        "protocol_errors": 0,
    }
    matching = [line for line in lines if line.startswith(RTOS_RESULT_PREFIX)]
    if not matching:
        raise AnalysisError("missing RTOS result marker")
    records: list[dict[str, int]] = []
    for line in matching:
        try:
            fields = _parse_fields(line.removeprefix(RTOS_RESULT_PREFIX))
            result = {name: int(value) for name, value in fields.items()}
        except (AnalysisError, ValueError):
            continue
        if result.keys() == expected.keys():
            records.append(result)
    if not records:
        raise AnalysisError("missing complete RTOS result marker")
    if any(record != records[0] for record in records[1:]):
        raise AnalysisError("conflicting RTOS result records")
    result = records[0]
    if result != expected:
        raise AnalysisError(f"unexpected RTOS result: {result}")
    return result


def _parse_evidence_hashes(lines: list[str]) -> dict[str, str]:
    runner_hash = _parse_split_hash(lines, RUNNER_HASH_PREFIX)
    controller_hash = _parse_split_hash(lines, CONTROLLER_HASH_PREFIX)
    if runner_hash is not None or controller_hash is not None:
        if runner_hash is None or controller_hash is None:
            raise AnalysisError("incomplete split Starry evidence hash records")
        return {"runner": runner_hash, "controller": controller_hash}

    prefix = "IVC-STARRY-VISION-EVIDENCE "
    records = [
        _parse_fields(line.removeprefix(prefix))
        for line in lines
        if line.startswith(prefix)
    ]
    if not records:
        raise AnalysisError("missing Starry evidence hash record")
    if any(record != records[0] for record in records[1:]):
        raise AnalysisError("conflicting Starry evidence hash records")
    hashes = {
        "runner": records[0].get("runner_sha256", ""),
        "controller": records[0].get("controller_sha256", ""),
    }
    if not all(SHA256.fullmatch(value) for value in hashes.values()):
        raise AnalysisError("invalid Starry evidence SHA-256")
    return hashes


def _parse_split_hash(lines: list[str], prefix: str) -> str | None:
    matching = [line for line in lines if line.startswith(prefix)]
    if not matching:
        return None
    values: list[str] = []
    for line in matching:
        try:
            value = _parse_fields(line.removeprefix(prefix)).get("sha256", "")
        except AnalysisError:
            continue
        if SHA256.fullmatch(value):
            values.append(value)
    if not values:
        raise AnalysisError(f"invalid SHA-256 in {prefix.strip()} record")
    if any(value != values[0] for value in values[1:]):
        raise AnalysisError(f"conflicting {prefix.strip()} records")
    return values[0]


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in text.split():
        if "=" not in token:
            raise AnalysisError(f"invalid key/value token: {token}")
        name, value = token.split("=", 1)
        if not name or name in fields:
            raise AnalysisError(f"duplicate or empty field: {name}")
        fields[name] = value
    return fields


def _metric(events: list[dict[str, Any]], name: str) -> dict[str, float | int]:
    values = [event[name] for event in events]
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def _read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as stream:
            return stream.read()
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("console", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        summary = analyze_text(_read_text(args.console))
    except AnalysisError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "VISION_CLOSED_LOOP_ANALYSIS_PASS "
        f"frames={summary['frames']} retries={summary['retries']} "
        f"max_end_to_end_us={summary['latency_us']['end_to_end']['max']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
