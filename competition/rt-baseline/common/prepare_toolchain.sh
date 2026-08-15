#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
default_toolchain_root="$workspace/arm-gnu-toolchain-13.2.Rel1-x86_64-aarch64-none-elf"
toolchain_root=${RT_BASELINE_TOOLCHAIN_ROOT:-"$default_toolchain_root"}
archive="$workspace/arm-gnu-toolchain-13.2.rel1-x86_64-aarch64-none-elf.tar.xz"
archive_url=https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu/13.2.rel1/binrel/arm-gnu-toolchain-13.2.rel1-x86_64-aarch64-none-elf.tar.xz
archive_sha256=7fe7b8548258f079d6ce9be9144d2a10bd2bf93b551dafbf20fe7f2e44e014b8
compiler="$toolchain_root/bin/aarch64-none-elf-gcc"

for command in curl sha256sum tar xz; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing Arm toolchain prerequisite: $command" >&2
        exit 2
    fi
done

mkdir -p -- "$workspace"
if [[ ! -x "$compiler" ]]; then
    if [[ "$toolchain_root" != "$default_toolchain_root" ]]; then
        echo "custom RT_BASELINE_TOOLCHAIN_ROOT is not prepared: $toolchain_root" >&2
        exit 2
    fi
    if [[ -e "$toolchain_root" ]]; then
        echo "refusing to replace incomplete toolchain directory: $toolchain_root" >&2
        exit 2
    fi
    if [[ -f "$archive" ]]; then
        actual_sha256=$(sha256sum "$archive" | awk '{print $1}')
        if [[ "$actual_sha256" != "$archive_sha256" ]]; then
            echo "Arm toolchain archive checksum mismatch: $archive" >&2
            exit 2
        fi
    else
        temporary_archive="$archive.part.$$"
        trap 'rm -f -- "$temporary_archive"' EXIT
        curl --fail --location --retry 5 --retry-all-errors \
            --output "$temporary_archive" "$archive_url"
        actual_sha256=$(sha256sum "$temporary_archive" | awk '{print $1}')
        if [[ "$actual_sha256" != "$archive_sha256" ]]; then
            echo "downloaded Arm toolchain checksum mismatch" >&2
            exit 2
        fi
        mv -- "$temporary_archive" "$archive"
        trap - EXIT
    fi
    tar -xJf "$archive" -C "$workspace"
fi

compiler_version=$("$compiler" --version | head -n 1)
if [[ "$compiler_version" != *"13.2.1 20231009"* ]]; then
    echo "unexpected Arm compiler version: $compiler_version" >&2
    exit 2
fi

echo "Arm bare-metal toolchain ready"
echo "  root: $toolchain_root"
echo "  compiler: $compiler_version"
