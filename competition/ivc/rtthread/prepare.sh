#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)

# Reuse the native baseline's pinned source, Python, and Arm toolchain setup.
bash "$repo_root/competition/rt-baseline/rtthread/prepare.sh"

echo "RT-Thread AxVisor IVC build environment ready"
