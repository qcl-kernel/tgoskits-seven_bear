#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Capture a post-run clean-source attestation for a native RTOS baseline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from analyze import (
    AnalysisError,
    RTOS_SPECS,
    artifact,
    command_output,
    git_index_path,
    repository_paths,
)


def require_clean(repository: Path, name: str) -> None:
    """Reject any tracked, untracked, or submodule source drift."""
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise AnalysisError(f"could not inspect source repository: {name}") from error
    if result.stdout:
        raise AnalysisError(f"source repository is not clean: {name}")


def capture(kind: str, source_root: Path) -> dict[str, object]:
    """Capture exact commits and Git indexes for all build-relevant repositories."""
    spec = RTOS_SPECS[kind]
    expected = spec["repositories"]
    assert isinstance(expected, dict)
    paths = repository_paths(kind, source_root)
    repositories: dict[str, object] = {}
    for name, expected_commit in expected.items():
        repository = paths[name]
        commit = command_output(["git", "-C", str(repository), "rev-parse", "HEAD"])
        if commit != expected_commit:
            raise AnalysisError(
                f"{name} must be at {expected_commit}, got {commit}"
            )
        require_clean(repository, name)
        autocrlf = subprocess.run(
            ["git", "-C", str(repository), "config", "--get", "core.autocrlf"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout.strip()
        repositories[name] = {
            "commit": commit,
            "worktree": "clean",
            "core_autocrlf": autocrlf or "unset",
            "git_index": artifact(git_index_path(repository), f"{name}/.git/index"),
        }
    if kind == "rt-thread":
        version = command_output(
            ["git", "-C", str(source_root), "describe", "--tags", "--exact-match"]
        )
        if version != "v5.2.2":
            raise AnalysisError(f"RT-Thread source is not tagged v5.2.2: {version}")
        assert isinstance(repositories["rt-thread"], dict)
        repositories["rt-thread"]["version"] = version
    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "source_root": str(source_root.resolve()),
        "repositories": repositories,
        "validity": "post-run clean-tree attestation; analyzers recheck commits and indexes",
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=tuple(RTOS_SPECS))
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write one immutable source provenance record."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    temporary_output = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        if args.output.exists():
            raise AnalysisError(f"refusing to overwrite evidence: {args.output}")
        rendered = json.dumps(
            capture(args.kind, args.source_root),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        temporary_output.write_text(rendered, encoding="utf-8")
        os.link(temporary_output, args.output)
    except (AnalysisError, OSError, UnicodeError) as error:
        print(f"source provenance capture failed: {error}", file=sys.stderr)
        return 2
    finally:
        temporary_output.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
