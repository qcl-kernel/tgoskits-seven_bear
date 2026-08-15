#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the RT-Thread configuration overlay."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import configure  # noqa: E402


class SymbolParsingTests(unittest.TestCase):
    """Check enabled, valued, disabled, and unrelated input lines."""

    def test_parses_enabled_and_disabled_symbols(self) -> None:
        self.assertEqual(configure.symbol_from_line("CONFIG_EXAMPLE=y"), "CONFIG_EXAMPLE")
        self.assertEqual(
            configure.symbol_from_line("# CONFIG_EXAMPLE is not set"),
            "CONFIG_EXAMPLE",
        )

    def test_ignores_comments(self) -> None:
        self.assertIsNone(configure.symbol_from_line("# menu heading"))


if __name__ == "__main__":
    unittest.main()
