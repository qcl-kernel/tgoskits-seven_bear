#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Validate an AArch64 ELF guest image against an AxVisor RAM contract."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Sequence


ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
ELF_CLASS_64 = 2
ELF_DATA_LITTLE_ENDIAN = 1
ELF_MACHINE_AARCH64 = 183
PROGRAM_TYPE_LOAD = 1
PROGRAM_FLAG_EXECUTE = 1


class ElfContractError(ValueError):
    """The guest image violates its declared VM memory contract."""


def parse_integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from error


def validate_elf(path: Path, expected_entry: int, ram_base: int, ram_size: int) -> dict:
    image = path.read_bytes()
    if len(image) < ELF_HEADER.size:
        raise ElfContractError("ELF header is truncated")
    header = ELF_HEADER.unpack_from(image)
    identity = header[0]
    machine = header[2]
    entry = header[4]
    program_offset = header[5]
    program_entry_size = header[9]
    program_count = header[10]

    if identity[:4] != b"\x7fELF":
        raise ElfContractError("invalid ELF magic")
    if identity[4] != ELF_CLASS_64 or identity[5] != ELF_DATA_LITTLE_ENDIAN:
        raise ElfContractError("guest must be a little-endian ELF64 image")
    if machine != ELF_MACHINE_AARCH64:
        raise ElfContractError(f"guest machine is {machine}, expected AArch64")
    if entry != expected_entry:
        raise ElfContractError(
            f"entry point 0x{entry:x} does not match 0x{expected_entry:x}"
        )
    if ram_size <= 0:
        raise ElfContractError("RAM size must be positive")
    ram_end = ram_base + ram_size
    if ram_end <= ram_base:
        raise ElfContractError("RAM range overflows")
    if program_entry_size != PROGRAM_HEADER.size:
        raise ElfContractError("unexpected ELF64 program-header size")
    table_end = program_offset + program_entry_size * program_count
    if table_end > len(image):
        raise ElfContractError("program-header table is truncated")

    load_segments: list[dict[str, int]] = []
    entry_is_executable = False
    for index in range(program_count):
        offset = program_offset + index * program_entry_size
        (
            segment_type,
            flags,
            file_offset,
            virtual_address,
            physical_address,
            file_size,
            memory_size,
            alignment,
        ) = PROGRAM_HEADER.unpack_from(image, offset)
        if segment_type != PROGRAM_TYPE_LOAD:
            continue
        if memory_size < file_size:
            raise ElfContractError(f"LOAD[{index}] has filesz greater than memsz")
        # GNU ld may emit a zero-sized LOAD placeholder at address zero. It
        # owns no guest bytes and therefore has no RAM placement contract.
        if file_size == 0 and memory_size == 0:
            continue
        if file_offset + file_size > len(image):
            raise ElfContractError(f"LOAD[{index}] file range is truncated")
        segment_end = physical_address + memory_size
        if segment_end < physical_address:
            raise ElfContractError(f"LOAD[{index}] address range overflows")
        if physical_address < ram_base or segment_end > ram_end:
            raise ElfContractError(
                f"LOAD[{index}] 0x{physical_address:x}..0x{segment_end:x} "
                f"is outside RAM 0x{ram_base:x}..0x{ram_end:x}"
            )
        if (
            flags & PROGRAM_FLAG_EXECUTE
            and virtual_address <= entry < virtual_address + memory_size
        ):
            entry_is_executable = True
        load_segments.append(
            {
                "index": index,
                "flags": flags,
                "file_offset": file_offset,
                "virtual_address": virtual_address,
                "physical_address": physical_address,
                "file_size": file_size,
                "memory_size": memory_size,
                "alignment": alignment,
            }
        )

    if not load_segments:
        raise ElfContractError("guest has no LOAD segments")
    if not entry_is_executable:
        raise ElfContractError("entry point is not inside an executable LOAD segment")
    return {
        "schema_version": 1,
        "elf": str(path),
        "machine": "aarch64",
        "entry_point": entry,
        "ram_base": ram_base,
        "ram_size": ram_size,
        "load_segments": load_segments,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("--expected-entry", type=parse_integer, required=True)
    parser.add_argument("--ram-base", type=parse_integer, required=True)
    parser.add_argument("--ram-size", type=parse_integer, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = validate_elf(
            args.elf,
            args.expected_entry,
            args.ram_base,
            args.ram_size,
        )
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (ElfContractError, OSError) as error:
        raise SystemExit(f"guest ELF validation failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
