#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
starry_dir=$(cd -- "$script_dir/.." && pwd)
build_script=$starry_dir/build-rknpu-offline.sh

grep -Fq \
    'built_elf=$workspace/target/aarch64-unknown-none-softfloat/release/starryos' \
    "$build_script"
grep -Fq \
    'built_kernel=$workspace/target/aarch64-unknown-none-softfloat/release/starryos.bin' \
    "$build_script"
if grep -Fq 'llvm-objcopy' "$build_script"; then
    echo "xtask already owns StarryOS ELF-to-BIN conversion" >&2
    exit 1
fi

echo "STARRY_RKNPU_BUILD_ARTIFACT_CONTRACT_PASS"
