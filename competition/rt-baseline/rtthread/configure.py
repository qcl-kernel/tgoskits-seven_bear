#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Create the deterministic RT-Thread baseline configuration overlay."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence


CONFIGURATION = {
    "CONFIG_RT_USING_SMP": None,
    "CONFIG_RT_CPUS_NR": "1",
    "CONFIG_RT_TICK_PER_SECOND": "1000",
    "CONFIG_RT_CONSOLEBUF_SIZE": "512",
    "CONFIG_RT_USING_CPU_USAGE_TRACER": None,
    "CONFIG_BSP_USING_GICV2": None,
    "CONFIG_BSP_USING_GICV3": "y",
    "CONFIG_RT_USING_MSH": None,
    "CONFIG_RT_USING_FINSH": None,
    "CONFIG_RT_USING_DFS": None,
    "CONFIG_RT_USING_RTC": None,
    "CONFIG_RT_USING_SOFT_RTC": None,
    "CONFIG_RT_USING_POSIX_FS": None,
    "CONFIG_RT_USING_POSIX_DEVIO": None,
    "CONFIG_RT_USING_POSIX_STDIO": None,
    "CONFIG_RT_USING_POSIX_POLL": None,
    "CONFIG_RT_USING_POSIX_SELECT": None,
    "CONFIG_RT_USING_POSIX_TERMIOS": None,
    "CONFIG_RT_USING_POSIX_DELAY": None,
    "CONFIG_RT_USING_POSIX_CLOCK": None,
    "CONFIG_RT_USING_POSIX_PIPE": None,
    "CONFIG_BSP_USING_VIRTIO_BLK": None,
    "CONFIG_BSP_USING_VIRTIO_NET": None,
    "CONFIG_BSP_USING_VIRTIO_CONSOLE": None,
    "CONFIG_BSP_USING_VIRTIO_GPU": None,
    "CONFIG_BSP_USING_VIRTIO_INPUT": None,
    "CONFIG_BSP_USING_RTC": None,
}


class ConfigurationError(ValueError):
    """Raised when the pinned upstream configuration changed unexpectedly."""


def symbol_from_line(line: str) -> str | None:
    """Return the Kconfig symbol represented by one .config line."""
    stripped = line.strip()
    if stripped.startswith("CONFIG_") and "=" in stripped:
        return stripped.partition("=")[0]
    if stripped.startswith("# CONFIG_") and stripped.endswith(" is not set"):
        return stripped.removeprefix("# ").removesuffix(" is not set")
    return None


def configure(source: Path) -> str:
    """Apply the exact baseline choices while preserving upstream ordering."""
    lines = source.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    rendered: list[str] = []
    for line in lines:
        symbol = symbol_from_line(line)
        if symbol not in CONFIGURATION:
            rendered.append(line)
            continue
        if symbol in seen:
            raise ConfigurationError(f"duplicate upstream symbol: {symbol}")
        seen.add(symbol)
        value = CONFIGURATION[symbol]
        rendered.append(
            f"# {symbol} is not set" if value is None else f"{symbol}={value}"
        )

    missing = sorted(set(CONFIGURATION) - seen)
    if missing:
        raise ConfigurationError(
            "pinned upstream configuration is missing: " + ", ".join(missing)
        )
    return "\n".join(rendered) + "\n"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Write one immutable generated configuration."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    temporary_output = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        if args.output.exists():
            raise ConfigurationError(f"refusing to overwrite: {args.output}")
        rendered = configure(args.source)
        temporary_output.write_text(rendered, encoding="utf-8")
        os.link(temporary_output, args.output)
    except (ConfigurationError, OSError, UnicodeError) as error:
        print(f"RT-Thread configuration failed: {error}", file=sys.stderr)
        return 2
    finally:
        temporary_output.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
