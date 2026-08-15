#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Create the deterministic RT-Thread v5.2.2 AxVisor IVC configuration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence


CONFIGURATION: dict[str, str | None] = {
    "CONFIG_RT_USING_SMP": None,
    "CONFIG_RT_CPUS_NR": "1",
    "CONFIG_RT_TICK_PER_SECOND": "1000",
    "CONFIG_RT_CONSOLEBUF_SIZE": "512",
    "CONFIG_BSP_USING_GICV2": None,
    "CONFIG_BSP_USING_GICV3": "y",
    "CONFIG_RT_USING_FINSH": None,
    "CONFIG_RT_USING_MSH": None,
    "CONFIG_RT_USING_DFS": None,
    "CONFIG_RT_USING_POSIX_FS": None,
    "CONFIG_RT_USING_POSIX_DEVIO": None,
    "CONFIG_RT_USING_POSIX_STDIO": None,
    "CONFIG_RT_USING_POSIX_POLL": None,
    "CONFIG_RT_USING_POSIX_SELECT": None,
    "CONFIG_RT_USING_POSIX_TERMIOS": None,
    "CONFIG_RT_USING_POSIX_DELAY": None,
    "CONFIG_RT_USING_POSIX_CLOCK": None,
    "CONFIG_RT_USING_POSIX_PIPE": None,
    "CONFIG_RT_USING_SAL": None,
    "CONFIG_SAL_INTERNET_CHECK": None,
    "CONFIG_SAL_USING_LWIP": None,
    "CONFIG_RT_USING_NETDEV": "y",
    "CONFIG_RT_USING_LWIP": "y",
    "CONFIG_RT_USING_LWIP_LOCAL_VERSION": "y",
    "CONFIG_RT_USING_LWIP141": None,
    "CONFIG_RT_USING_LWIP203": None,
    "CONFIG_RT_USING_LWIP212": "y",
    "CONFIG_RT_USING_LWIP_LATEST": None,
    "CONFIG_RT_USING_LWIP_IPV6": None,
    "CONFIG_RT_LWIP_IGMP": None,
    "CONFIG_RT_LWIP_ICMP": "y",
    "CONFIG_RT_LWIP_SNMP": None,
    "CONFIG_RT_LWIP_DNS": None,
    "CONFIG_RT_LWIP_DHCP": None,
    "CONFIG_RT_LWIP_IPADDR": '"10.0.0.2"',
    "CONFIG_RT_LWIP_GWADDR": '"0.0.0.0"',
    "CONFIG_RT_LWIP_MSKADDR": '"255.255.255.0"',
    "CONFIG_RT_LWIP_UDP": "y",
    "CONFIG_RT_LWIP_TCP": None,
    "CONFIG_RT_LWIP_RAW": None,
    "CONFIG_RT_LWIP_PPP": None,
    "CONFIG_LWIP_SO_SNDTIMEO": "0",
    "CONFIG_RT_LWIP_PBUF_NUM": "32",
    "CONFIG_RT_LWIP_UDP_PCB_NUM": "4",
    "CONFIG_RT_LWIP_TCPTHREAD_PRIORITY": "10",
    "CONFIG_RT_LWIP_TCPTHREAD_MBOX_SIZE": "16",
    "CONFIG_RT_LWIP_TCPTHREAD_STACKSIZE": "4096",
    "CONFIG_RT_LWIP_ETHTHREAD_PRIORITY": "12",
    "CONFIG_RT_LWIP_ETHTHREAD_STACKSIZE": "4096",
    "CONFIG_RT_LWIP_ETHTHREAD_MBOX_SIZE": "16",
    "CONFIG_RT_LWIP_REASSEMBLY_FRAG": None,
    "CONFIG_BSP_USING_VIRTIO_BLK": None,
    "CONFIG_BSP_USING_VIRTIO_NET": None,
    "CONFIG_BSP_USING_VIRTIO_CONSOLE": None,
    "CONFIG_BSP_USING_VIRTIO_GPU": None,
    "CONFIG_BSP_USING_VIRTIO_INPUT": None,
    "CONFIG_BSP_USING_RTC": None,
}


class ConfigurationError(ValueError):
    """Raised when the pinned configuration cannot be rendered safely."""


def symbol_from_line(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("CONFIG_") and "=" in stripped:
        return stripped.partition("=")[0]
    if stripped.startswith("# CONFIG_") and stripped.endswith(" is not set"):
        return stripped.removeprefix("# ").removesuffix(" is not set")
    return None


def render_symbol(symbol: str, value: str | None) -> str:
    return f"# {symbol} is not set" if value is None else f"{symbol}={value}"


def configure(source: Path) -> str:
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
        rendered.append(render_symbol(symbol, CONFIGURATION[symbol]))

    # Child symbols of disabled upstream menus are absent from the source
    # .config. Kconfig accepts explicit values appended here and normalizes
    # their final placement during --pyconfig-silent.
    for symbol in sorted(set(CONFIGURATION) - seen):
        rendered.append(render_symbol(symbol, CONFIGURATION[symbol]))
    return "\n".join(rendered) + "\n"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    temporary_output = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        if args.output.exists():
            raise ConfigurationError(f"refusing to overwrite: {args.output}")
        temporary_output.write_text(configure(args.source), encoding="utf-8")
        os.link(temporary_output, args.output)
    except (ConfigurationError, OSError, UnicodeError) as error:
        print(f"RT-Thread IVC configuration failed: {error}", file=sys.stderr)
        return 2
    finally:
        temporary_output.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
