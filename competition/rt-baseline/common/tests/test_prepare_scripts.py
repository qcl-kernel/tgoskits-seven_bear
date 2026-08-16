#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for portable RT baseline preparation entry points."""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[4]
TOOLCHAIN_INVOCATION = (
    'bash "$script_dir/../common/prepare_toolchain.sh"'
)


class PrepareScriptTests(unittest.TestCase):
    """Keep prepare entry points usable from a regular Linux checkout."""

    def test_non_executable_toolchain_helper_uses_bash(self) -> None:
        for relative in (
            "competition/rt-baseline/rtthread/prepare.sh",
            "competition/rt-baseline/freertos/prepare.sh",
        ):
            with self.subTest(script=relative):
                script = (REPOSITORY / relative).read_text(encoding="utf-8")
                self.assertIn(TOOLCHAIN_INVOCATION, script)


if __name__ == "__main__":
    unittest.main()
