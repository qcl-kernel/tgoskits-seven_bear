#!/usr/bin/env python3
"""Compare an archived IVC summary with a replay while ignoring path relocation."""

from __future__ import annotations

import json
import sys
from pathlib import Path


RELOCATABLE_PATHS = (
    ("source_log", "path"),
    ("raw_samples", "path"),
    ("pre_reset_raw_samples", "path"),
)


def normalized_summary(path: Path) -> dict[str, object]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    for section, field in RELOCATABLE_PATHS:
        value = summary.get(section)
        if isinstance(value, dict):
            value.pop(field, None)
    return summary


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare-ivc-summary.py ARCHIVED REANALYZED", file=sys.stderr)
        return 2
    archived = normalized_summary(Path(sys.argv[1]))
    reanalyzed = normalized_summary(Path(sys.argv[2]))
    if archived != reanalyzed:
        print("IVC reanalysis differs after path normalization", file=sys.stderr)
        return 1
    print("IVC reanalysis matches archived summary after path normalization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
