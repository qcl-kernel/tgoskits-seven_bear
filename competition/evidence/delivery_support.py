#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Strict file, JSON, and Git primitives for competition evidence checks."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath


RTOS_EVIDENCE = Path(
    "competition/results/rtos-guest-ivc-qemu-20260815"
)
ISOLATION_EVIDENCE = Path(
    "competition/results/axvisor-isolation-reference"
)
RT_FORMAL_EVIDENCE = Path(
    "competition/results/axvisor-rt-formal-20260816"
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
CHECKSUM_LINE_PATTERN = re.compile(r"^([0-9a-f]{64})  (.+)$")
DOCUMENT_SUFFIXES = frozenset({".md", ".rst", ".adoc"})
DELIVERY_DOCUMENT_PREFIXES = ("competition/",)
DELIVERY_ONLY_PATHS = frozenset(
    {
        ".github/workflows/competition-delivery.yml",
        ".github/workflows/ci.yml",
    }
)
DELIVERY_ONLY_PREFIXES = (
    "competition/evidence/",
    f"{RTOS_EVIDENCE.as_posix()}/",
    f"{ISOLATION_EVIDENCE.as_posix()}/",
    f"{RT_FORMAL_EVIDENCE.as_posix()}/",
)
DELIVERY_GITATTRIBUTE_ADDITIONS = frozenset(
    {
        "competition/results/rtos-guest-ivc-qemu-20260815/*.md text eol=lf",
        "competition/results/rtos-guest-ivc-qemu-20260815/*.json text eol=lf",
        "competition/results/rtos-guest-ivc-qemu-20260815/SHA256SUMS text eol=lf",
        "competition/results/rtos-guest-ivc-qemu-20260815/*.gz binary",
        "competition/results/axvisor-isolation-reference/*.md text eol=lf",
        "competition/results/axvisor-isolation-reference/*.json text eol=lf",
        "competition/results/axvisor-isolation-reference/*.sha256 text eol=lf",
        "competition/results/axvisor-isolation-reference/*.gz binary",
        "competition/results/axvisor-rt-formal-20260816/**/*.json text eol=lf",
        "competition/results/axvisor-rt-formal-20260816/*.json text eol=lf",
        "competition/results/axvisor-rt-formal-20260816/*.md text eol=lf",
        "competition/results/axvisor-rt-formal-20260816/*.sha256 text eol=lf",
        "competition/results/axvisor-rt-formal-20260816/SHA256SUMS text eol=lf",
    }
)


class EvidenceVerificationError(ValueError):
    """Raised when delivery evidence does not prove its declared result."""


def verify_checksum_manifest(directory: Path, manifest_name: str) -> int:
    """Verify every regular evidence file is listed exactly once."""
    directory = directory.resolve()
    if not directory.is_dir():
        raise EvidenceVerificationError(
            f"evidence directory does not exist: {directory}"
        )
    manifest_path = directory / manifest_name
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise EvidenceVerificationError(
            f"cannot read checksum manifest {manifest_path}: {error}"
        ) from error
    if not lines:
        raise EvidenceVerificationError(
            f"checksum manifest is empty: {manifest_path}"
        )

    entries: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        match = CHECKSUM_LINE_PATTERN.fullmatch(line)
        if match is None:
            raise EvidenceVerificationError(
                f"malformed checksum line {manifest_path}:{line_number}"
            )
        digest, relative = match.groups()
        validate_relative_path(relative, "checksum")
        if relative == manifest_name:
            raise EvidenceVerificationError(
                f"checksum manifest must not list itself: {relative}"
            )
        if relative in entries:
            raise EvidenceVerificationError(
                f"duplicate checksum path: {relative}"
            )
        entries[relative] = digest

    actual_files: set[str] = set()
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        relative = path.relative_to(directory).as_posix()
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceVerificationError(
                f"evidence contains a non-regular file: {relative}"
            )
        if relative != manifest_name:
            actual_files.add(relative)

    if set(entries) != actual_files:
        missing = sorted(actual_files - set(entries))
        unexpected = sorted(set(entries) - actual_files)
        raise EvidenceVerificationError(
            "checksum manifest does not cover evidence exactly: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for relative, expected_digest in entries.items():
        path = safe_relative_file(directory, relative, "checksum")
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
            raise EvidenceVerificationError(
                f"SHA-256 mismatch for {relative}: "
                f"expected {expected_digest}, got {actual_digest}"
            )
    return len(entries)


def read_checksum_sidecar(path: Path, expected_name: str) -> str:
    """Read a one-entry SHA-256 sidecar for an external or adjacent artifact."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise EvidenceVerificationError(
            f"cannot read checksum sidecar {path}: {error}"
        ) from error
    if len(lines) != 1:
        raise EvidenceVerificationError(
            f"checksum sidecar must contain exactly one entry: {path}"
        )
    match = CHECKSUM_LINE_PATTERN.fullmatch(lines[0])
    if match is None:
        raise EvidenceVerificationError(f"malformed checksum sidecar: {path}")
    digest, relative = match.groups()
    validate_relative_path(relative, "checksum sidecar")
    if relative != expected_name:
        raise EvidenceVerificationError(
            f"checksum sidecar names {relative}, expected {expected_name}"
        )
    return digest


def verify_source_commit(repository: Path, source_commit: str) -> None:
    """Require evidence source to be an ancestor with no later runtime change."""
    verify_commit_ancestor(repository, source_commit)
    repository = repository.resolve()
    committed_paths = set(
        run_git(
            repository,
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{source_commit}..HEAD",
        ).stdout.splitlines()
    )
    if (
        ".gitattributes" in committed_paths
        and has_only_delivery_gitattributes_additions(repository, source_commit)
    ):
        committed_paths.remove(".gitattributes")
    changed_paths = committed_paths | worktree_paths(repository)
    runtime_changes = sorted(
        path for path in changed_paths if not is_delivery_only_path(path)
    )
    if runtime_changes:
        raise EvidenceVerificationError(
            "runtime-relevant paths changed after the evidence source commit: "
            + ", ".join(runtime_changes)
        )


def verify_commit_ancestor(repository: Path, source_commit: str) -> None:
    """Require an exact source commit that is an ancestor of ``HEAD``."""
    if COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise EvidenceVerificationError(
            f"invalid evidence source commit: {source_commit}"
        )
    repository = repository.resolve()
    resolved = run_git(
        repository,
        "rev-parse",
        "--verify",
        f"{source_commit}^{{commit}}",
    ).stdout.strip()
    if resolved != source_commit:
        raise EvidenceVerificationError(
            f"evidence source does not resolve exactly: {source_commit}"
        )
    ancestor = run_git(
        repository,
        "merge-base",
        "--is-ancestor",
        source_commit,
        "HEAD",
        check=False,
    )
    if ancestor.returncode != 0:
        raise EvidenceVerificationError(
            f"evidence source is not an ancestor of HEAD: {source_commit}"
        )


def verify_source_inputs(
    repository: Path,
    source_commit: str,
    source_tree: str,
    source_inputs: dict[str, tuple[str, int]],
) -> None:
    """Require preregistered inputs to match both the source commit and HEAD."""
    verify_commit_ancestor(repository, source_commit)
    if COMMIT_PATTERN.fullmatch(source_tree) is None:
        raise EvidenceVerificationError(
            f"invalid evidence source tree: {source_tree}"
        )
    repository = repository.resolve()
    resolved_tree = run_git(
        repository,
        "rev-parse",
        f"{source_commit}^{{tree}}",
    ).stdout.strip()
    if resolved_tree != source_tree:
        raise EvidenceVerificationError(
            "evidence source tree differs from the declared tree: "
            f"expected {source_tree}, got {resolved_tree}"
        )
    if not source_inputs:
        raise EvidenceVerificationError("source input set must not be empty")

    dirty_paths = worktree_paths(repository)
    for relative, (expected_sha256, expected_bytes) in source_inputs.items():
        validate_relative_path(relative, "source input")
        if SHA256_PATTERN.fullmatch(expected_sha256) is None:
            raise EvidenceVerificationError(
                f"invalid source input SHA-256 for {relative}: {expected_sha256}"
            )
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
        ):
            raise EvidenceVerificationError(
                f"invalid source input byte count for {relative}: {expected_bytes}"
            )
        if relative in dirty_paths:
            raise EvidenceVerificationError(
                f"preregistered source input has an uncommitted change: {relative}"
            )

        source_blob = run_git(
            repository,
            "rev-parse",
            f"{source_commit}:{relative}",
        ).stdout.strip()
        head_blob_result = run_git(
            repository,
            "rev-parse",
            f"HEAD:{relative}",
            check=False,
        )
        head_blob = head_blob_result.stdout.strip()
        if head_blob_result.returncode != 0 or head_blob != source_blob:
            raise EvidenceVerificationError(
                "preregistered source input changed after evidence capture: "
                f"{relative}"
            )
        blob = read_git_blob(repository, source_blob)
        if len(blob) != expected_bytes:
            raise EvidenceVerificationError(
                f"source input byte count differs for {relative}: "
                f"expected {expected_bytes}, got {len(blob)}"
            )
        actual_sha256 = hashlib.sha256(blob).hexdigest()
        if actual_sha256 != expected_sha256:
            raise EvidenceVerificationError(
                f"source input SHA-256 differs for {relative}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )


def has_only_delivery_gitattributes_additions(
    repository: Path,
    source_commit: str,
) -> bool:
    """Accept only the reviewed evidence-specific attribute insertions."""
    source = run_git(
        repository,
        "show",
        f"{source_commit}:.gitattributes",
        check=False,
    )
    head = run_git(
        repository,
        "show",
        "HEAD:.gitattributes",
        check=False,
    )
    if head.returncode != 0:
        return False
    source_lines = [] if source.returncode != 0 else source.stdout.splitlines()
    head_lines = head.stdout.splitlines()
    additions: list[str] = []
    matcher = SequenceMatcher(None, source_lines, head_lines, autojunk=False)
    for operation, source_start, source_end, head_start, head_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        if operation != "insert" or source_start != source_end:
            return False
        additions.extend(head_lines[head_start:head_end])
    return bool(additions) and set(additions).issubset(
        DELIVERY_GITATTRIBUTE_ADDITIONS
    ) and len(additions) == len(set(additions))


def worktree_paths(repository: Path) -> set[str]:
    """Return tracked and untracked paths that differ from repository HEAD."""
    result = run_git(
        repository,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    paths: set[str] = set()
    records = result.stdout.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise EvidenceVerificationError(
                f"cannot parse Git worktree status record: {record!r}"
            )
        status = record[:2]
        paths.add(record[3:])
        if "R" in status or "C" in status:
            if index >= len(records) or not records[index]:
                raise EvidenceVerificationError(
                    "Git worktree status omitted a rename source path"
                )
            paths.add(records[index])
            index += 1
    return paths


def is_delivery_only_path(path: str) -> bool:
    """Return whether a descendant change cannot alter validated runtime."""
    normalized = PurePosixPath(path).as_posix()
    if (
        PurePosixPath(normalized).suffix in DOCUMENT_SUFFIXES
        and normalized.startswith(DELIVERY_DOCUMENT_PREFIXES)
    ):
        return True
    if normalized in DELIVERY_ONLY_PATHS:
        return True
    return normalized.startswith(DELIVERY_ONLY_PREFIXES)


def run_git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run Git with an explicit repository and safe-directory boundary."""
    command = [
        "git",
        "-c",
        f"safe.directory={repository}",
        "-c",
        "core.autocrlf=true",
        "-C",
        str(repository),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise EvidenceVerificationError(f"cannot execute Git: {error}") from error
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise EvidenceVerificationError(
            f"Git command failed ({' '.join(arguments)}): {detail}"
        )
    return result


def read_git_blob(repository: Path, object_id: str) -> bytes:
    """Read one Git blob without text transcoding or checkout conversion."""
    repository = repository.resolve()
    command = [
        "git",
        "-c",
        f"safe.directory={repository}",
        "-C",
        str(repository),
        "cat-file",
        "blob",
        object_id,
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError as error:
        raise EvidenceVerificationError(f"cannot execute Git: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceVerificationError(
            f"cannot read Git blob {object_id}: {detail or 'unknown error'}"
        )
    return result.stdout


def load_json_object(path: Path) -> dict[str, object]:
    """Load one UTF-8 JSON object with a diagnostic path."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceVerificationError(f"cannot read JSON {path}: {error}") from error
    return require_mapping(value, str(path))


def require_object(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> dict[str, object]:
    """Return a required object field."""
    if key not in mapping:
        raise EvidenceVerificationError(f"{context} is missing field: {key}")
    return require_mapping(mapping[key], f"{context}.{key}")


def require_mapping(value: object, context: str) -> dict[str, object]:
    """Return ``value`` as a string-keyed object or fail."""
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise EvidenceVerificationError(f"{context} must be a JSON object")
    return value


def require_list(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> list[object]:
    """Return a required list field."""
    value = mapping.get(key)
    if not isinstance(value, list):
        raise EvidenceVerificationError(f"{context}.{key} must be a list")
    return value


def require_string(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> str:
    """Return a required non-empty string field."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceVerificationError(
            f"{context}.{key} must be a non-empty string"
        )
    return value


def require_sha256(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> str:
    """Return a required lowercase SHA-256 identity."""
    value = require_string(mapping, key, context)
    if SHA256_PATTERN.fullmatch(value) is None:
        raise EvidenceVerificationError(
            f"{context}.{key} must be a lowercase SHA-256"
        )
    return value


def require_commit(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> str:
    """Return a required full lowercase Git commit identity."""
    value = require_string(mapping, key, context)
    if COMMIT_PATTERN.fullmatch(value) is None:
        raise EvidenceVerificationError(
            f"{context}.{key} must be a full lowercase Git commit"
        )
    return value


def require_positive_integer(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> int:
    """Return a required integer greater than zero."""
    value = require_nonnegative_integer(mapping, key, context)
    if value == 0:
        raise EvidenceVerificationError(f"{context}.{key} must be positive")
    return value


def require_nonnegative_integer(
    mapping: dict[str, object],
    key: str,
    context: str,
) -> int:
    """Return a required integer greater than or equal to zero."""
    value = mapping.get(key)
    if type(value) is not int or value < 0:
        raise EvidenceVerificationError(
            f"{context}.{key} must be a nonnegative integer"
        )
    return value


def require_equal(
    mapping: dict[str, object],
    key: str,
    expected: object,
    context: str,
) -> None:
    """Require one field to equal its competition contract value."""
    if key not in mapping:
        raise EvidenceVerificationError(f"{context} is missing field: {key}")
    actual = mapping[key]
    if type(actual) is not type(expected) or actual != expected:
        raise EvidenceVerificationError(
            f"{context}.{key} differs: expected {expected!r}, got {actual!r}"
        )


def safe_relative_file(directory: Path, relative: str, context: str) -> Path:
    """Resolve a declared POSIX path without permitting traversal or links."""
    validate_relative_path(relative, context)
    path = directory.joinpath(*PurePosixPath(relative).parts)
    try:
        metadata = path.lstat()
    except OSError as error:
        raise EvidenceVerificationError(
            f"{context} artifact does not exist: {relative}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode):
        raise EvidenceVerificationError(
            f"{context} artifact is not a regular file: {relative}"
        )
    return path


def validate_relative_path(relative: str, context: str) -> None:
    """Reject absolute, non-canonical, or parent-traversing artifact paths."""
    candidate = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != relative
    ):
        raise EvidenceVerificationError(
            f"unsafe {context} path: {relative}"
        )


def sha256_file(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceVerificationError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def decode_log(payload: bytes, context: str) -> str:
    """Decode a retained console log without hiding invalid byte sequences."""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceVerificationError(
            f"{context} is not valid UTF-8: {error}"
        ) from error


def unique_line_containing(log: str, marker: str, context: str) -> str:
    """Return the unique terminal line containing ``marker``."""
    matches = [
        line
        for line in log.splitlines()
        if marker in line and "=== SUCCESS PATTERN MATCHED:" not in line
    ]
    if len(matches) != 1:
        raise EvidenceVerificationError(
            f"{context} expected one '{marker}' line, found {len(matches)}"
        )
    return matches[0]


def require_successful_runner_log(log: str, context: str) -> None:
    """Require the runner success marker and reject an explicit failure match."""
    if "=== SUCCESS PATTERN MATCHED:" not in log:
        raise EvidenceVerificationError(
            f"{context} is missing the runner success marker"
        )
    if "=== FAILURE PATTERN MATCHED:" in log:
        raise EvidenceVerificationError(
            f"{context} contains a runner failure marker"
        )
