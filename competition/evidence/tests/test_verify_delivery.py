#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Tests for fail-closed competition delivery verification."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVIDENCE_DIR))

import verify_delivery  # noqa: E402


SOURCE_COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


class WorkflowRoutingTests(unittest.TestCase):
    """Keep the delivery gate strict without freezing unrelated development."""

    def test_delivery_gate_is_path_scoped(self) -> None:
        repository = EVIDENCE_DIR.parents[1]
        main_ci = (repository / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        delivery_ci = (
            repository / ".github" / "workflows" / "competition-delivery.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn("run-host-validation.sh", main_ci)
        for required in (
            '      - ".gitattributes"',
            '      - ".github/workflows/competition-delivery.yml"',
            '      - "competition/**"',
            "          fetch-depth: 0",
            "bash competition/evidence/run-host-validation.sh",
        ):
            self.assertIn(required, delivery_ci)


class DeliveryEvidenceTests(unittest.TestCase):
    """Verify checksums, campaign semantics, logs, and provenance agreement."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.rtos_evidence = self.root / "rtos"
        self.isolation_evidence = self.root / "isolation"
        self.rtos_evidence.mkdir()
        self.isolation_evidence.mkdir()
        self._write_rtos_evidence()
        self._write_isolation_evidence()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_accepts_complete_delivery_evidence(self) -> None:
        report = verify_delivery.verify_evidence_sets(
            self.rtos_evidence,
            self.isolation_evidence,
        )

        self.assertEqual(report.source_commit, SOURCE_COMMIT)
        self.assertEqual(report.evidence_sets, 2)
        self.assertEqual(report.qemu_logs, 5)
        self.assertEqual(report.checked_files, 9)

    def test_rejects_file_missing_from_checksum_manifest(self) -> None:
        (self.rtos_evidence / "unlisted.txt").write_text(
            "not covered\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "checksum manifest does not cover",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_modified_compressed_log(self) -> None:
        log = self.rtos_evidence / "rtthread-normal-qemu.log.gz"
        log.write_bytes(log.read_bytes() + b"tampered")

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "SHA-256 mismatch",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_semantically_false_counter_claim(self) -> None:
        validation = self._read_json(self.rtos_evidence / "validation.json")
        validation["runs"][0]["accepted"] = 99
        self._write_json(self.rtos_evidence / "validation.json", validation)
        self._write_checksum_manifest(self.rtos_evidence, "SHA256SUMS")

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "accepted",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_isolation_log_without_required_marker(self) -> None:
        summary = self._read_json(self.isolation_evidence / "summary.json")
        missing_marker = summary["pass_markers"][1]
        log = gzip.decompress(
            (self.isolation_evidence / "qemu.log.gz").read_bytes()
        ).decode("utf-8")
        self._replace_isolation_log(log.replace(missing_marker, "marker-removed"))

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "missing pass marker",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_claim_that_removes_required_isolation_marker(self) -> None:
        summary = self._read_json(self.isolation_evidence / "summary.json")
        missing_marker = summary["pass_markers"].pop(1)
        self._write_json(self.isolation_evidence / "summary.json", summary)
        log = gzip.decompress(
            (self.isolation_evidence / "qemu.log.gz").read_bytes()
        ).decode("utf-8")
        self._replace_isolation_log(log.replace(missing_marker, "marker-removed"))

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "pass marker contract differs",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_evidence_sets_from_different_source_commits(self) -> None:
        summary = self._read_json(self.isolation_evidence / "summary.json")
        summary["source"]["commit"] = OTHER_COMMIT
        self._write_json(self.isolation_evidence / "summary.json", summary)
        self._write_checksum_manifest(
            self.isolation_evidence, "checksums.sha256"
        )

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "source commits differ",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_checksum_path_escape(self) -> None:
        manifest = self.rtos_evidence / "SHA256SUMS"
        manifest.write_text(
            f"{'0' * 64}  ../outside\n",
            encoding="utf-8",
            newline="\n",
        )

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "unsafe checksum path",
        ):
            verify_delivery.verify_evidence_sets(
                self.rtos_evidence,
                self.isolation_evidence,
            )

    def test_rejects_oversized_decompressed_log(self) -> None:
        payload = b"0" * (16 * 1024 * 1024 + 1)
        compressed = gzip.compress(payload, compresslevel=9, mtime=0)
        artifact = self.root / "oversized.log.gz"
        artifact.write_bytes(compressed)
        metadata = {
            "path": artifact.name,
            "bytes": len(compressed),
            "sha256": self._sha256(compressed),
            "uncompressed_bytes": len(payload),
            "uncompressed_sha256": self._sha256(payload),
        }

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "uncompressed byte limit",
        ):
            verify_delivery.verify_gzip_artifact(
                self.root,
                metadata,
                compressed_path_key="path",
                compressed_bytes_key="bytes",
                compressed_sha256_key="sha256",
                uncompressed_bytes_key="uncompressed_bytes",
                uncompressed_sha256_key="uncompressed_sha256",
                context="oversized test log",
            )

    def _write_rtos_evidence(self) -> None:
        (self.rtos_evidence / "README.md").write_text(
            "RTOS evidence fixture\n", encoding="utf-8"
        )
        runs = []
        for rtos, profile, fault_count in (
            ("rt-thread", "normal", 0),
            ("rt-thread", "ack-loss", 20),
            ("freertos", "normal", 0),
            ("freertos", "ack-loss", 20),
        ):
            artifact_name = f"{rtos.replace('-', '')}-{profile}-qemu.log.gz"
            log = self._rtos_log(rtos, profile, fault_count).encode("utf-8")
            compressed = gzip.compress(log, compresslevel=9, mtime=0)
            (self.rtos_evidence / artifact_name).write_bytes(compressed)
            runs.append(
                {
                    "rtos": rtos,
                    "profile": profile,
                    "guest_binary_sha256": "c" * 64,
                    "qemu_log_sha256": self._sha256(log),
                    "qemu_log_bytes": len(log),
                    "qemu_log_gzip": artifact_name,
                    "qemu_log_gzip_bytes": len(compressed),
                    "qemu_log_gzip_sha256": self._sha256(compressed),
                    "summary_sha256": "d" * 64,
                    "accepted": 100,
                    "applied": 100,
                    "duplicates": fault_count,
                    "acks_dropped": fault_count,
                    "protocol_errors": 0,
                    "acknowledged": 100,
                    "controller_errors": 0,
                    "controller_timeouts": 0,
                    "retransmissions": fault_count,
                    "recoveries": fault_count,
                }
            )
        validation = {
            "schema_version": 2,
            "repository": {
                "head": SOURCE_COMMIT,
                "tracked_worktree_clean": True,
                "clean_commit_evidence": True,
            },
            "controller_rootfs": {"bytes": 1, "sha256": "e" * 64},
            "source_pins": {
                "rtthread": "f" * 40,
                "freertos_over_bao": "1" * 40,
                "freertos_kernel": "2" * 40,
                "bao_runtime": "3" * 40,
                "freertos_plus_tcp": "4" * 40,
            },
            "runs": runs,
        }
        self._write_json(self.rtos_evidence / "validation.json", validation)
        self._write_checksum_manifest(self.rtos_evidence, "SHA256SUMS")

    def _write_isolation_evidence(self) -> None:
        (self.isolation_evidence / "README.md").write_text(
            "Isolation evidence fixture\n", encoding="utf-8"
        )
        markers = [
            "VM2_VIRTIO_NET_TX bytes=65536 checksum=0x7f8000",
            "VM1_VIRTIO_NET_RX bytes=65536 checksum=0x7f8000 "
            "peer=10.0.2.16:49152",
            "VM3_VIRTIO_NET_ISOLATED_PASS default_routes=0 probes=100 "
            "tx_frames=100 target=10.0.2.255:5002",
            "VM1_VIRTIO_NET_ISOLATION_PASS "
            "received_cross_segment_probes=0 observation_ms=7000",
            "VM1_VIRTIO_NET_PASS",
            "VM2_VIRTIO_NET_PASS",
            "VM3_VIRTIO_NET_PASS",
        ]
        log = "\n".join([*markers, "=== SUCCESS PATTERN MATCHED: fixture", ""])
        compressed = gzip.compress(log.encode("utf-8"), compresslevel=9, mtime=0)
        (self.isolation_evidence / "qemu.log.gz").write_bytes(compressed)
        summary = {
            "schema_version": 2,
            "status": "pass",
            "source": {
                "commit": SOURCE_COMMIT,
                "tracked_worktree_clean": True,
                "clean_commit_evidence": True,
            },
            "results": {
                "same_segment_tcp_bytes": 65536,
                "same_segment_tcp_checksum": "0x7f8000",
                "cross_segment_udp_probes": 100,
                "vm3_tx_frames": 100,
                "vm1_cross_segment_probes_received": 0,
                "observation_ms": 7000,
            },
            "pass_markers": markers,
            "artifacts": {
                "console_build_log_gzip": {
                    "path": "qemu.log.gz",
                    "bytes": len(compressed),
                    "sha256": self._sha256(compressed),
                    "uncompressed_bytes": len(log.encode("utf-8")),
                    "uncompressed_sha256": self._sha256(log.encode("utf-8")),
                }
            },
        }
        self._write_json(self.isolation_evidence / "summary.json", summary)
        self._write_checksum_manifest(
            self.isolation_evidence, "checksums.sha256"
        )

    def _replace_isolation_log(self, log: str) -> None:
        payload = log.encode("utf-8")
        compressed = gzip.compress(payload, compresslevel=9, mtime=0)
        (self.isolation_evidence / "qemu.log.gz").write_bytes(compressed)
        summary = self._read_json(self.isolation_evidence / "summary.json")
        artifact = summary["artifacts"]["console_build_log_gzip"]
        artifact.update(
            {
                "bytes": len(compressed),
                "sha256": self._sha256(compressed),
                "uncompressed_bytes": len(payload),
                "uncompressed_sha256": self._sha256(payload),
            }
        )
        self._write_json(self.isolation_evidence / "summary.json", summary)
        self._write_checksum_manifest(
            self.isolation_evidence, "checksums.sha256"
        )

    @staticmethod
    def _rtos_log(rtos: str, profile: str, fault_count: int) -> str:
        return (
            f"IVC-RTOS-RESULT rtos={rtos} profile={profile} accepted=100 "
            f"applied=100 duplicates={fault_count} acks_dropped={fault_count} "
            "protocol_errors=0\n"
            "IVC-CONTROLLER-RESULT sent=100 acknowledged=100 errors=0 "
            f"timeouts=0 retransmissions={fault_count} recoveries={fault_count} "
            "success_percent=100.000\n"
            "IVC-LINUX-DONE exit=0\n"
            "=== SUCCESS PATTERN MATCHED: fixture ===\n"
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _sha256(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _write_checksum_manifest(self, directory: Path, name: str) -> None:
        records = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if path.name == name:
                continue
            records.append(f"{self._sha256(path.read_bytes())}  {path.name}\n")
        (directory / name).write_text(
            "".join(records), encoding="utf-8", newline="\n"
        )


class SourceCommitTests(unittest.TestCase):
    """Reject runtime changes made after the evidence source commit."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self._git("init", "--quiet")
        self._git("config", "user.name", "Competition Test")
        self._git("config", "user.email", "competition-test@example.invalid")
        runtime = self.root / "competition" / "ivc" / "runtime.txt"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("validated runtime\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "validated source")
        self.source_commit = self._git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_accepts_delivery_tooling_after_source_commit(self) -> None:
        tooling = self.root / "competition" / "evidence" / "verify.py"
        tooling.parent.mkdir(parents=True)
        tooling.write_text("delivery tooling\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "add delivery tooling")

        verify_delivery.verify_source_commit(self.root, self.source_commit)

    def test_rejects_runtime_change_after_source_commit(self) -> None:
        runtime = self.root / "competition" / "ivc" / "runtime.txt"
        runtime.write_text("changed runtime\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "change validated runtime")

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "runtime-relevant paths changed",
        ):
            verify_delivery.verify_source_commit(self.root, self.source_commit)

    def test_rejects_runtime_affecting_gitattributes_change(self) -> None:
        attributes = self.root / ".gitattributes"
        attributes.write_text("*.rs filter=untrusted\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "change checkout behavior")

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "runtime-relevant paths changed",
        ):
            verify_delivery.verify_source_commit(self.root, self.source_commit)

    def test_rejects_document_outside_delivery_scope(self) -> None:
        document = self.root / "components" / "runtime" / "README.md"
        document.parent.mkdir(parents=True)
        document.write_text("runtime input\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "add runtime document")

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "runtime-relevant paths changed",
        ):
            verify_delivery.verify_source_commit(self.root, self.source_commit)

    def test_accepts_unchanged_preregistered_input_after_unrelated_change(
        self,
    ) -> None:
        unrelated = self.root / "competition" / "rt-baseline" / "helper.txt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("later helper fix\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "change unrelated runtime")

        verify_delivery.verify_source_inputs(
            self.root,
            self.source_commit,
            self._git("rev-parse", f"{self.source_commit}^{{tree}}").stdout.strip(),
            {
                "competition/ivc/runtime.txt": (
                    hashlib.sha256(b"validated runtime\n").hexdigest(),
                    len(b"validated runtime\n"),
                )
            },
        )

    def test_rejects_changed_preregistered_source_input(self) -> None:
        runtime = self.root / "competition" / "ivc" / "runtime.txt"
        runtime.write_text("changed input\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "change formal input")

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "preregistered source input changed",
        ):
            verify_delivery.verify_source_inputs(
                self.root,
                self.source_commit,
                self._git(
                    "rev-parse",
                    f"{self.source_commit}^{{tree}}",
                ).stdout.strip(),
                {
                    "competition/ivc/runtime.txt": (
                        hashlib.sha256(b"validated runtime\n").hexdigest(),
                        len(b"validated runtime\n"),
                    )
                },
            )

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )


class FormalRealtimeEvidenceTests(unittest.TestCase):
    """Reject formal claims that drift from receipts or preregistration."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.formal_evidence = Path(self.temporary_directory.name) / "formal"
        source = (
            EVIDENCE_DIR.parent
            / "results"
            / "axvisor-rt-formal-20260816"
        )
        shutil.copytree(source, self.formal_evidence)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_accepts_complete_formal_campaign(self) -> None:
        report = verify_delivery.verify_formal_realtime(self.formal_evidence)

        self.assertEqual(
            report.source_commit,
            "77704718a1b46fc2fbf51ea6a184aa1071eee0ac",
        )
        self.assertEqual(report.checked_files, 23)
        self.assertEqual(report.archive_files, 110)
        self.assertGreaterEqual(len(report.source_inputs), 30)

    def test_accepts_all_three_repository_evidence_sets(self) -> None:
        results = EVIDENCE_DIR.parent / "results"
        report = verify_delivery.verify_evidence_sets(
            results / "rtos-guest-ivc-qemu-20260815",
            results / "axvisor-isolation-reference",
            self.formal_evidence,
        )

        self.assertEqual(report.evidence_sets, 3)
        self.assertEqual(report.checked_files, 32)
        self.assertEqual(report.qemu_logs, 5)
        self.assertEqual(report.archive_files, 110)
        self.assertEqual(
            report.formal_source_commit,
            "77704718a1b46fc2fbf51ea6a184aa1071eee0ac",
        )

    def test_rejects_false_aggregate_m2_claim(self) -> None:
        path = self.formal_evidence / "campaign-summary.json"
        summary = self._read_json(path)
        summary["assessment"]["m2_exit_gate_met"] = False
        self._write_json(path, summary)
        self._write_checksum_manifest()

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "m2_exit_gate_met",
        ):
            verify_delivery.verify_formal_realtime(self.formal_evidence)

    def test_rejects_short_soak(self) -> None:
        path = self.formal_evidence / "campaign-summary.json"
        summary = self._read_json(path)
        summary["soak"]["profiles"]["shared"]["elapsed_seconds"] = 1799.0
        self._write_json(path, summary)
        self._write_checksum_manifest()

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "shorter than 1800 seconds",
        ):
            verify_delivery.verify_formal_realtime(self.formal_evidence)

    def test_rejects_receipt_archive_manifest_mismatch(self) -> None:
        receipt = self._read_json(
            self.formal_evidence / "pair-1" / "shared" / "receipt.json"
        )
        raw_path = receipt["evidence"]["raw"]["path"]
        manifest_path = self.formal_evidence / "archive.manifest.json"
        manifest = self._read_json(manifest_path)
        entry = next(item for item in manifest["files"] if item["path"] == raw_path)
        entry["sha256"] = "0" * 64
        self._write_json(manifest_path, manifest)
        self._write_checksum_manifest()

        with self.assertRaisesRegex(
            verify_delivery.EvidenceVerificationError,
            "receipt does not match archive manifest",
        ):
            verify_delivery.verify_formal_realtime(self.formal_evidence)

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def _write_checksum_manifest(self) -> None:
        records = []
        for path in sorted(
            self.formal_evidence.rglob("*"),
            key=lambda item: item.as_posix(),
        ):
            if not path.is_file() or path.name == "SHA256SUMS":
                continue
            relative = path.relative_to(self.formal_evidence).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            records.append(f"{digest}  {relative}\n")
        (self.formal_evidence / "SHA256SUMS").write_text(
            "".join(records),
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    unittest.main()
