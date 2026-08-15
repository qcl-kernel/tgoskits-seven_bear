#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
common_dir=$(cd -- "$script_dir/.." && pwd)
temporary_directory=$(mktemp -d)
trap 'rm -rf -- "$temporary_directory"' EXIT

cc -std=c11 -Wall -Wextra -Werror -pedantic \
    -I"$common_dir" \
    "$common_dir/latency_stats.c" \
    "$script_dir/test_latency_stats.c" \
    -o "$temporary_directory/test-latency-stats"
"$temporary_directory/test-latency-stats"

python3 -m unittest discover -s "$script_dir" -p 'test_*.py'
