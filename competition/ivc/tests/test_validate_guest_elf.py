from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR_PATH = (
    Path(__file__).resolve().parents[1] / "common/validate_guest_elf.py"
)
SPEC = importlib.util.spec_from_file_location("ivc_validate_guest_elf", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def test_elf(
    *, physical_address: int = 0x4008_0000, include_empty_load: bool = False
) -> bytes:
    identity = bytearray(16)
    identity[:6] = b"\x7fELF\x02\x01"
    header = validator.ELF_HEADER.pack(
        bytes(identity),
        2,
        validator.ELF_MACHINE_AARCH64,
        1,
        0x4008_0000,
        validator.ELF_HEADER.size,
        0,
        0,
        validator.ELF_HEADER.size,
        validator.PROGRAM_HEADER.size,
        2 if include_empty_load else 1,
        0,
        0,
        0,
    )
    program = validator.PROGRAM_HEADER.pack(
        validator.PROGRAM_TYPE_LOAD,
        5,
        0x1000,
        0x4008_0000,
        physical_address,
        4,
        0x100,
        0x1000,
    )
    empty_load = (
        validator.PROGRAM_HEADER.pack(
            validator.PROGRAM_TYPE_LOAD, 0, 0, 0, 0, 0, 0, 0
        )
        if include_empty_load
        else b""
    )
    headers = header + program + empty_load
    return headers + bytes(0x1000 - len(headers)) + b"test"


class ValidateGuestElfTests(unittest.TestCase):
    def test_accepts_an_executable_load_segment_inside_guest_ram(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "guest.elf"
            path.write_bytes(test_elf())

            result = validator.validate_elf(path, 0x4008_0000, 0x4000_0000, 0x0800_0000)

            self.assertEqual(result["elf"], "guest.elf")
            self.assertEqual(result["entry_point"], 0x4008_0000)
            self.assertEqual(len(result["load_segments"]), 1)

    def test_rejects_a_load_segment_outside_guest_ram(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "guest.elf"
            path.write_bytes(test_elf(physical_address=0x3FFF_F000))

            with self.assertRaisesRegex(validator.ElfContractError, "outside RAM"):
                validator.validate_elf(
                    path, 0x4008_0000, 0x4000_0000, 0x0800_0000
                )

    def test_ignores_a_zero_sized_linker_load_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "guest.elf"
            path.write_bytes(test_elf(include_empty_load=True))

            result = validator.validate_elf(
                path, 0x4008_0000, 0x4000_0000, 0x0800_0000
            )

            self.assertEqual(len(result["load_segments"]), 1)

    def test_rejects_an_unexpected_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "guest.elf"
            path.write_bytes(test_elf())

            with self.assertRaisesRegex(validator.ElfContractError, "entry point"):
                validator.validate_elf(
                    path, 0x4000_0000, 0x4000_0000, 0x0800_0000
                )


if __name__ == "__main__":
    unittest.main()
