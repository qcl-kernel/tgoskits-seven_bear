#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Tests for deterministic competition evidence packaging."""

from __future__ import annotations

import gzip
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVIDENCE_DIR))

import package  # noqa: E402


class EvidencePackagingTests(unittest.TestCase):
    """Check determinism, payload verification, and immutability."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "campaign"
        (self.source / "nested").mkdir(parents=True)
        (self.source / "summary.json").write_text(
            '{"status":"pass"}\n', encoding="utf-8"
        )
        (self.source / "nested" / "raw.csv").write_bytes(b"sequence,value\n1,7\n")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_two_archives_have_identical_bytes(self) -> None:
        first = self.root / "first.tar.gz"
        second = self.root / "second.tar.gz"

        package.package(self.source, first)
        package.package(self.source, second)

        self.assertEqual(package.sha256_file(first), package.sha256_file(second))
        first_manifest = json.loads(
            package.sidecar_paths(first)[0].read_text(encoding="utf-8")
        )
        self.assertEqual(first_manifest["file_count"], 2)
        self.assertEqual(
            [record["path"] for record in first_manifest["files"]],
            ["nested/raw.csv", "summary.json"],
        )
        with tarfile.open(first, mode="r:gz") as archive:
            self.assertIn(
                "campaign/EVIDENCE-MANIFEST.json", archive.getnames()
            )

    def test_refuses_to_overwrite_an_existing_archive(self) -> None:
        output = self.root / "evidence.tar.gz"
        package.package(self.source, output)

        with self.assertRaisesRegex(package.PackagingError, "refusing to overwrite"):
            package.package(self.source, output)

    def test_rejects_output_below_source_directory(self) -> None:
        output = self.source / "evidence.tar.gz"

        with self.assertRaisesRegex(package.PackagingError, "outside"):
            package.package(self.source, output)

    def test_rejects_duplicate_embedded_manifest(self) -> None:
        output = self.root / "duplicate-manifest.tar.gz"
        files = package.collect_files(self.source)
        manifest = package.build_manifest(self.source, files)
        manifest_bytes = package.render_manifest(manifest)
        root = self.source.name

        with output.open("xb") as raw_stream:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw_stream, mtime=0
            ) as gzip_stream:
                with tarfile.open(fileobj=gzip_stream, mode="w") as archive:
                    manifest_name = f"{root}/{package.MANIFEST_NAME}"
                    for _ in range(2):
                        archive.addfile(
                            package.normalized_tar_info(
                                manifest_name, len(manifest_bytes), 0o644
                            ),
                            io.BytesIO(manifest_bytes),
                        )
                    for record in files:
                        path = self.source / str(record["path"])
                        with path.open("rb") as stream:
                            archive.addfile(
                                package.normalized_tar_info(
                                    f"{root}/{record['path']}",
                                    int(record["bytes"]),
                                    int(str(record["mode"]), 8),
                                ),
                                stream,
                            )

        with self.assertRaisesRegex(package.PackagingError, "duplicate"):
            package.verify_archive(output, manifest, manifest_bytes)


if __name__ == "__main__":
    unittest.main()
