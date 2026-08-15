#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Create and verify a deterministic competition evidence archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import BinaryIO, Sequence


MANIFEST_NAME = "EVIDENCE-MANIFEST.json"


class PackagingError(ValueError):
    """Raised when evidence cannot be packaged without weakening provenance."""


def sha256_stream(stream: BinaryIO) -> str:
    """Return the lowercase SHA-256 digest of a binary stream."""
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of a file."""
    with path.open("rb") as stream:
        return sha256_stream(stream)


def collect_files(source: Path) -> list[dict[str, object]]:
    """Hash a stable, sorted set of regular files below ``source``."""
    files: list[dict[str, object]] = []
    for path in sorted(source.rglob("*"), key=lambda candidate: candidate.as_posix()):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        relative = path.relative_to(source).as_posix()
        if not stat.S_ISREG(metadata.st_mode):
            raise PackagingError(f"evidence contains a non-regular file: {relative}")
        files.append(
            {
                "path": relative,
                "bytes": metadata.st_size,
                "mode": "0755" if metadata.st_mode & 0o111 else "0644",
                "sha256": sha256_file(path),
            }
        )
    if not files:
        raise PackagingError("evidence directory contains no regular files")
    return files


def build_manifest(source: Path, files: list[dict[str, object]]) -> dict[str, object]:
    """Build the content-addressed archive manifest."""
    return {
        "schema_version": 1,
        "archive_format": "deterministic tar+gzip; mtime/uid/gid fixed to zero",
        "source_root": source.name,
        "file_count": len(files),
        "payload_bytes": sum(int(record["bytes"]) for record in files),
        "files": files,
    }


def render_manifest(manifest: dict[str, object]) -> bytes:
    """Render canonical, human-readable manifest bytes."""
    return (
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def normalized_tar_info(name: str, size: int, mode: int) -> tarfile.TarInfo:
    """Create deterministic metadata for one archive member."""
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    return info


def write_archive(
    source: Path,
    archive: Path,
    files: list[dict[str, object]],
    manifest_bytes: bytes,
) -> None:
    """Write deterministic gzip and tar framing around the evidence payload."""
    with archive.open("xb") as raw_stream:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw_stream, compresslevel=9, mtime=0
        ) as gzip_stream:
            with tarfile.open(
                fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT
            ) as output:
                root = source.name
                manifest_name = f"{root}/{MANIFEST_NAME}"
                output.addfile(
                    normalized_tar_info(manifest_name, len(manifest_bytes), 0o644),
                    io.BytesIO(manifest_bytes),
                )
                for record in files:
                    relative = str(record["path"])
                    path = source / Path(relative)
                    info = normalized_tar_info(
                        f"{root}/{relative}",
                        int(record["bytes"]),
                        int(str(record["mode"]), 8),
                    )
                    with path.open("rb") as stream:
                        output.addfile(info, stream)


def verify_archive(
    archive: Path, manifest: dict[str, object], manifest_bytes: bytes
) -> None:
    """Re-read every archive payload and compare it with the manifest."""
    root = str(manifest["source_root"])
    records = manifest["files"]
    if not isinstance(records, list):
        raise PackagingError("manifest file list is malformed")
    expected = {
        f"{root}/{record['path']}": record
        for record in records
        if isinstance(record, dict)
    }
    manifest_name = f"{root}/{MANIFEST_NAME}"
    observed: set[str] = set()
    manifest_seen = False
    try:
        with tarfile.open(archive, mode="r:gz") as input_archive:
            for member in input_archive:
                if not member.isfile():
                    raise PackagingError(
                        f"archive contains a non-regular member: {member.name}"
                    )
                stream = input_archive.extractfile(member)
                if stream is None:
                    raise PackagingError(f"could not read archive member: {member.name}")
                if member.name == manifest_name:
                    if manifest_seen:
                        raise PackagingError("archive contains duplicate evidence manifests")
                    if stream.read() != manifest_bytes:
                        raise PackagingError("embedded evidence manifest differs")
                    manifest_seen = True
                    continue
                record = expected.get(member.name)
                if record is None or member.name in observed:
                    raise PackagingError(f"unexpected archive member: {member.name}")
                if member.size != record["bytes"] or sha256_stream(stream) != record["sha256"]:
                    raise PackagingError(f"archive payload differs: {member.name}")
                observed.add(member.name)
    except (OSError, tarfile.TarError) as error:
        raise PackagingError(f"could not verify evidence archive: {error}") from error
    if not manifest_seen:
        raise PackagingError("archive is missing the embedded evidence manifest")
    if observed != set(expected):
        missing = sorted(set(expected) - observed)
        raise PackagingError(f"archive is missing payloads: {missing}")


def sidecar_paths(output: Path) -> tuple[Path, Path]:
    """Return the manifest and checksum paths associated with an archive."""
    return (
        output.with_name(f"{output.name}.manifest.json"),
        output.with_name(f"{output.name}.sha256"),
    )


def ensure_new_outputs(paths: Sequence[Path]) -> None:
    """Refuse to overwrite any archive or sidecar."""
    for path in paths:
        if path.exists():
            raise PackagingError(f"refusing to overwrite output: {path}")


def publish_file(temporary: Path, destination: Path) -> None:
    """Publish a prepared file with exclusive hard-link semantics."""
    os.link(temporary, destination)


def package(source: Path, output: Path) -> tuple[Path, Path]:
    """Create one verified archive plus its manifest and SHA-256 sidecars."""
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise PackagingError(f"evidence source is not a directory: {source}")
    if output.suffixes[-2:] != [".tar", ".gz"]:
        raise PackagingError("archive output must end in .tar.gz")
    try:
        output.parent.relative_to(source)
    except ValueError:
        pass
    else:
        raise PackagingError("archive output must be outside the evidence directory")
    manifest_path, checksum_path = sidecar_paths(output)
    ensure_new_outputs((output, manifest_path, checksum_path))
    output.parent.mkdir(parents=True, exist_ok=True)

    files = collect_files(source)
    manifest = build_manifest(source, files)
    manifest_bytes = render_manifest(manifest)
    temporary_paths: list[Path] = []
    published_sidecars: list[Path] = []
    try:
        for suffix in ("archive", "manifest", "checksum"):
            descriptor, name = tempfile.mkstemp(
                prefix=f".{output.name}.{suffix}.", dir=output.parent
            )
            os.close(descriptor)
            temporary = Path(name)
            temporary.unlink()
            temporary_paths.append(temporary)
        archive_temporary, manifest_temporary, checksum_temporary = temporary_paths
        write_archive(source, archive_temporary, files, manifest_bytes)
        verify_archive(archive_temporary, manifest, manifest_bytes)
        archive_digest = sha256_file(archive_temporary)
        manifest_temporary.write_bytes(manifest_bytes)
        checksum_temporary.write_text(
            f"{archive_digest}  {output.name}\n", encoding="utf-8", newline="\n"
        )

        publish_file(manifest_temporary, manifest_path)
        published_sidecars.append(manifest_path)
        publish_file(checksum_temporary, checksum_path)
        published_sidecars.append(checksum_path)
        publish_file(archive_temporary, output)
    except (OSError, PackagingError) as error:
        for path in published_sidecars:
            path.unlink(missing_ok=True)
        if isinstance(error, PackagingError):
            raise
        raise PackagingError(f"could not publish evidence archive: {error}") from error
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)
    return manifest_path, checksum_path


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Package evidence and report content-addressed output paths."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        manifest_path, checksum_path = package(args.source, args.output)
    except PackagingError as error:
        print(f"evidence packaging failed: {error}", file=sys.stderr)
        return 2
    print(f"EVIDENCE_ARCHIVE_READY archive={args.output.resolve()}")
    print(f"EVIDENCE_ARCHIVE_MANIFEST path={manifest_path}")
    print(f"EVIDENCE_ARCHIVE_CHECKSUM path={checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
