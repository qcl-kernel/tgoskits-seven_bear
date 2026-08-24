#!/usr/bin/env python3
"""Serve an exact-frame picture-in-picture view from an AxVisor serial log."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ROUTE_PREFIX = re.compile(r"^(?:\[[^\]\r\n]{1,40}\]\s*)+")
JPEG_BEGIN = re.compile(r"^STARRY_JPEG_BEGIN frame=(\d+) bytes=(\d+)$")
JPEG_END = re.compile(r"^STARRY_JPEG_END frame=(\d+)$")
BASE64_LINE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
MAX_JPEG_BYTES = 2 * 1024 * 1024
MAX_PENDING_FRAMES = 256


def clean_serial_line(line: str) -> str:
    """Remove terminal decoration and one or more VM routing prefixes."""

    return ROUTE_PREFIX.sub("", ANSI_ESCAPE.sub("", line).strip())


def parse_fields(line: str, marker: str) -> dict[str, str] | None:
    cleaned = clean_serial_line(line)
    if not cleaned.startswith(marker + " "):
        return None
    fields: dict[str, str] = {}
    for token in cleaned[len(marker) + 1 :].split():
        if "=" not in token:
            raise ValueError(f"malformed {marker} token: {token}")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise ValueError(f"malformed {marker} field: {token}")
        fields[key] = value
    return fields


def required_int(fields: dict[str, str], key: str) -> int:
    try:
        value = int(fields[key], 10)
    except (KeyError, ValueError) as error:
        raise ValueError(f"missing or invalid integer field: {key}") from error
    if value < 0:
        raise ValueError(f"negative integer field: {key}")
    return value


@dataclass(frozen=True)
class PublishedFrame:
    jpeg: bytes
    state: dict[str, Any]


class ExactFrameJoiner:
    """Join camera, AI, RTOS, actuator, and JPEG evidence by exact identity."""

    def __init__(self, require_physical: bool = False) -> None:
        self.require_physical = require_physical
        self._captures: dict[int, dict[str, str]] = {}
        self._decisions: dict[int, dict[str, str]] = {}
        self._authorizations: dict[int, dict[str, str]] = {}
        self._actuators: dict[int, dict[str, str]] = {}
        self._jpegs: dict[int, bytes] = {}
        self._jpeg_frame: int | None = None
        self._jpeg_size = 0
        self._jpeg_lines: list[str] = []
        self._published: PublishedFrame | None = None
        self._published_frames: set[int] = set()
        self._revision = 0
        self._error_count = 0
        self._last_error = ""
        self._lock = threading.Lock()

    def feed_line(self, line: str) -> None:
        with self._lock:
            try:
                self._feed_line_locked(line)
            except ValueError as error:
                self._abort_jpeg()
                self._error_count += 1
                self._last_error = str(error)

    def _feed_line_locked(self, line: str) -> None:
        cleaned = clean_serial_line(line)
        begin = JPEG_BEGIN.fullmatch(cleaned)
        if begin:
            frame_id = int(begin.group(1), 10)
            size = int(begin.group(2), 10)
            if frame_id == 0 or size == 0 or size > MAX_JPEG_BYTES:
                raise ValueError("invalid serial JPEG identity or size")
            self._jpeg_frame = frame_id
            self._jpeg_size = size
            self._jpeg_lines = []
            return

        if self._jpeg_frame is not None:
            end = JPEG_END.fullmatch(cleaned)
            if end:
                frame_id = int(end.group(1), 10)
                if frame_id != self._jpeg_frame:
                    raise ValueError("serial JPEG end frame does not match begin frame")
                try:
                    jpeg = base64.b64decode("".join(self._jpeg_lines), validate=True)
                except (binascii.Error, ValueError) as error:
                    raise ValueError("invalid serial JPEG base64") from error
                if len(jpeg) != self._jpeg_size:
                    raise ValueError("serial JPEG byte count does not match declaration")
                if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
                    raise ValueError("serial frame is not a complete JPEG")
                existing_jpeg = self._jpegs.get(frame_id)
                if existing_jpeg is not None and existing_jpeg != jpeg:
                    raise ValueError(f"conflicting serial JPEG replay for frame {frame_id}")
                self._jpegs[frame_id] = jpeg
                self._abort_jpeg()
                self._try_publish(frame_id)
                self._prune()
                return
            if not cleaned or not BASE64_LINE.fullmatch(cleaned):
                raise ValueError("unexpected line inside serial JPEG")
            self._jpeg_lines.append(cleaned)
            return

        record_specs = (
            ("VISION_CAPTURE_IDENTITY", self._captures),
            ("VISION_DECISION_RECORD", self._decisions),
            ("VISION_RTOS_AUTH_RECORD", self._authorizations),
            ("VISION_ACTUATOR_RECORD", self._actuators),
        )
        for marker, destination in record_specs:
            fields = parse_fields(cleaned, marker)
            if fields is None:
                continue
            if fields.get("version") != "1":
                raise ValueError(f"unsupported {marker} version")
            frame_id = required_int(fields, "frame_id")
            if frame_id == 0:
                raise ValueError(f"zero {marker} frame_id")
            existing_fields = destination.get(frame_id)
            if existing_fields is not None:
                if existing_fields != fields:
                    raise ValueError(f"conflicting {marker} replay for frame {frame_id}")
                return
            destination[frame_id] = fields
            self._try_publish(frame_id)
            self._prune()
            return

    def _try_publish(self, frame_id: int) -> None:
        if frame_id in self._published_frames:
            return
        capture = self._captures.get(frame_id)
        decision = self._decisions.get(frame_id)
        authorization = self._authorizations.get(frame_id)
        actuator = self._actuators.get(frame_id)
        jpeg = self._jpegs.get(frame_id)
        if None in (capture, decision, authorization, actuator, jpeg):
            return
        assert capture is not None
        assert decision is not None
        assert authorization is not None
        assert actuator is not None
        assert jpeg is not None

        session_id = required_int(authorization, "session_id")
        sequence = required_int(authorization, "sequence")
        if session_id == 0 or sequence == 0:
            raise ValueError("zero RTOS session_id or sequence")
        if required_int(actuator, "session_id") != session_id:
            raise ValueError("actuator session does not match RTOS authorization")
        if required_int(actuator, "sequence") != sequence:
            raise ValueError("actuator sequence does not match RTOS authorization")
        requested = decision.get("requested_action")
        if requested not in {"left", "right", "hold", "emergency-stop"}:
            raise ValueError("unsupported AI action")
        if authorization.get("requested_action") != requested:
            raise ValueError("AI action does not match RTOS request")
        if authorization.get("authorized_action") != requested:
            raise ValueError("RTOS authorization does not match AI action")
        if authorization.get("state") != "applied":
            raise ValueError("RTOS authorization is not applied")
        if actuator.get("action") != requested:
            raise ValueError("actuator action does not match RTOS authorization")
        detection_present = required_int(decision, "detection_present")
        if detection_present not in {0, 1}:
            raise ValueError("invalid detection_present value")
        if detection_present == 0 and requested != "hold":
            raise ValueError("absent detection must produce HOLD")
        if detection_present == 1 and requested not in {"left", "right"}:
            raise ValueError("present detection must produce LEFT or RIGHT")
        captured_at_us = required_int(capture, "captured_at_us")
        if required_int(decision, "captured_at_us") != captured_at_us:
            raise ValueError("AI capture timestamp does not match camera identity")
        physical_applied = required_int(actuator, "physical_applied")
        physical_verified = required_int(actuator, "physical_verified")
        device_io_attempted = required_int(actuator, "device_io_attempted")
        if physical_applied not in {0, 1}:
            raise ValueError("invalid physical_applied value")
        if physical_verified not in {0, 1}:
            raise ValueError("invalid physical_verified value")
        if device_io_attempted not in {0, 1}:
            raise ValueError("invalid device_io_attempted value")
        if physical_applied == 1 and (
            physical_verified != 1
            or device_io_attempted != 1
            or actuator.get("gate") != "stable"
        ):
            raise ValueError("physical application lacks stable verified device I/O")
        if self.require_physical and physical_verified != 1:
            return

        self._revision += 1
        state: dict[str, Any] = {
            "sync": "SYNC",
            "revision": self._revision,
            "frame_id": frame_id,
            "camera_sequence": required_int(capture, "camera_sequence"),
            "session_id": session_id,
            "sequence": sequence,
            "ai_action": requested.upper(),
            "rtos_action": authorization["authorized_action"].upper(),
            "rtos_state": authorization["state"],
            "gate": actuator.get("gate", "unknown"),
            "target_position": actuator.get("target_position", "unknown"),
            "physical_applied": physical_applied,
            "physical_verified": physical_verified,
            "device_io_attempted": device_io_attempted,
            "detection_present": detection_present,
            "confidence_q10000": required_int(decision, "confidence_q10000"),
            "captured_at_us": captured_at_us,
            "joined_at_unix_ms": time.time_ns() // 1_000_000,
        }
        self._published = PublishedFrame(jpeg=jpeg, state=state)
        self._published_frames.add(frame_id)

    def _abort_jpeg(self) -> None:
        self._jpeg_frame = None
        self._jpeg_size = 0
        self._jpeg_lines = []

    def _prune(self) -> None:
        all_frames = set().union(
            self._captures,
            self._decisions,
            self._authorizations,
            self._actuators,
            self._jpegs,
        )
        if len(all_frames) <= MAX_PENDING_FRAMES:
            return
        keep = set(sorted(all_frames)[-MAX_PENDING_FRAMES:])
        for records in (
            self._captures,
            self._decisions,
            self._authorizations,
            self._actuators,
            self._jpegs,
        ):
            for frame_id in tuple(records):
                if frame_id not in keep:
                    del records[frame_id]

    def snapshot(self) -> tuple[PublishedFrame | None, dict[str, Any]]:
        with self._lock:
            diagnostics = {
                "error_count": self._error_count,
                "last_error": self._last_error,
                "require_physical": self.require_physical,
            }
            return self._published, diagnostics


HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StarryOS exact-frame monitor</title>
<style>
:root { color-scheme: dark; font-family: Inter, Segoe UI, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #070b12; color: #f5f7fb; overflow: hidden; }
.shell { min-height: 100vh; padding: 18px; display: grid; grid-template-rows: 1fr auto; gap: 12px; }
.view { position: relative; min-height: 0; border: 2px solid #39d98a; border-radius: 18px; overflow: hidden; background: #0d1420; box-shadow: 0 0 28px #39d98a33; }
.view img { width: 100%; height: 100%; object-fit: contain; display: none; }
.waiting { position: absolute; inset: 0; display: grid; place-items: center; color: #92a3b8; font-size: 22px; letter-spacing: .08em; }
.badge { position: absolute; top: 14px; left: 14px; padding: 7px 11px; border-radius: 999px; background: #07120ddd; border: 1px solid #39d98a; color: #65f0aa; font-weight: 800; font-size: 13px; letter-spacing: .08em; }
.status { display: grid; grid-template-columns: 1.3fr 1fr 1fr 1fr; gap: 10px; }
.cell { min-width: 0; padding: 12px 14px; border: 1px solid #29384d; border-radius: 12px; background: #111a28; }
.label { color: #8ea1b8; font-size: 11px; text-transform: uppercase; letter-spacing: .09em; }
.value { margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 800; font-size: 18px; }
.ok { color: #65f0aa; } .warn { color: #ffc857; }
</style>
</head>
<body><main class="shell">
  <section class="view"><img id="frame" alt="exact USB camera inference frame"><div class="waiting" id="waiting">WAITING FOR EXACT FRAME JOIN</div><div class="badge">LIVE USB · STARRYOS</div></section>
  <section class="status">
    <div class="cell"><div class="label">Identity</div><div class="value" id="identity">FRAME — · CAMERA — · IVC —</div></div>
    <div class="cell"><div class="label">AI → RTOS</div><div class="value ok" id="action">— → —</div></div>
    <div class="cell"><div class="label">SO-100 ID1</div><div class="value" id="motor">GATE — · TARGET —</div></div>
    <div class="cell"><div class="label">Evidence</div><div class="value" id="evidence">SYNC WAIT</div></div>
  </section>
</main><script>
let revision = 0;
async function update() {
  try {
    const response = await fetch('/state.json', {cache: 'no-store'});
    const state = await response.json();
    if (!state.ready) return;
    if (state.revision !== revision) {
      revision = state.revision;
      const image = document.getElementById('frame');
      image.src = '/frame.jpg?revision=' + revision;
      image.style.display = 'block';
      document.getElementById('waiting').style.display = 'none';
    }
    document.getElementById('identity').textContent = `FRAME ${state.frame_id} · CAMERA ${state.camera_sequence} · IVC ${state.sequence}`;
    document.getElementById('action').textContent = `${state.ai_action} → ${state.rtos_action}`;
    document.getElementById('motor').textContent = `GATE ${state.gate.toUpperCase()} · TARGET ${state.target_position}`;
    const evidence = document.getElementById('evidence');
    evidence.textContent = state.physical_verified ? 'SYNC · PHYSICAL VERIFIED' : 'SYNC · DRY-RUN';
    evidence.className = 'value ' + (state.physical_verified ? 'ok' : 'warn');
  } catch (_) { /* retain the last fully joined frame */ }
}
setInterval(update, 100); update();
</script></body></html>"""


class PipRequestHandler(BaseHTTPRequestHandler):
    joiner: ExactFrameJoiner

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        published, diagnostics = self.joiner.snapshot()
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", HTML.encode())
            return
        if path == "/state.json":
            state = {"ready": published is not None, **diagnostics}
            if published is not None:
                state.update(published.state)
            self._send(
                HTTPStatus.OK,
                "application/json",
                json.dumps(state, separators=(",", ":")).encode(),
            )
            return
        if path == "/frame.jpg" and published is not None:
            self._send(HTTPStatus.OK, "image/jpeg", published.jpeg)
            return
        self._send(HTTPStatus.NOT_FOUND, "text/plain", b"not found\n")

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def follow_file(path: Path, from_end: bool) -> Iterable[str]:
    while not path.exists():
        time.sleep(0.2)
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        if from_end:
            stream.seek(0, 2)
        while True:
            line = stream.readline()
            if line:
                yield line
                continue
            try:
                if path.stat().st_size < stream.tell():
                    stream.seek(0)
            except FileNotFoundError:
                pass
            time.sleep(0.05)


def consume(lines: Iterable[str], joiner: ExactFrameJoiner) -> None:
    for line in lines:
        joiner.feed_line(line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve only JPEG/status tuples joined by exact StarryOS frame identity."
    )
    parser.add_argument("--input", required=True, help="serial capture log, or - for stdin")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--from-end", action="store_true")
    parser.add_argument(
        "--require-physical",
        action="store_true",
        help="publish nothing unless the actuator record says physical_verified=1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be in 1..65535")
    joiner = ExactFrameJoiner(require_physical=args.require_physical)
    lines: Iterable[str]
    if args.input == "-":
        lines = sys.stdin
    else:
        lines = follow_file(Path(args.input), args.from_end)
    reader = threading.Thread(target=consume, args=(lines, joiner), daemon=True)
    reader.start()
    PipRequestHandler.joiner = joiner
    server = ThreadingHTTPServer((args.host, args.port), PipRequestHandler)
    print(f"LIVE_PIP_READY url=http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
