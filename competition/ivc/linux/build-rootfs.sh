#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../../.." && pwd)
toolchain=nightly-2026-07-15
managed_image="$workspace/tmp/axbuild/rootfs/rootfs-aarch64-alpine.img/rootfs-aarch64-alpine.img"
output_dir="$workspace/tmp/competition/ivc/linux"
output_image="$output_dir/rootfs.img"
target_dir="$output_dir/target"
controller="$target_dir/aarch64-unknown-linux-musl/release/ivcproto"

cd "$workspace"
if [[ ! -f "$managed_image" ]]; then
    cargo "+$toolchain" xtask image pull --arch aarch64
fi

rustup "+$toolchain" target add aarch64-unknown-linux-musl
CARGO_TARGET_DIR="$target_dir" \
    CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=rust-lld \
    cargo "+$toolchain" build --release --target aarch64-unknown-linux-musl -p ivcproto

mkdir -p "$output_dir"
cp --reflink=auto --sparse=always "$managed_image" "$output_image"

# The managed image may carry a pending journal from its last use. Replaying it
# before raw debugfs writes prevents the later mount from reverting new files.
set +e
e2fsck -fy "$output_image"
fsck_status=$?
set -e
if ((fsck_status > 1)); then
    echo "e2fsck failed before populating $output_image" >&2
    exit "$fsck_status"
fi

# The image is a private copy. Replacing exact paths inside it is recoverable by
# rerunning this script and never mutates the managed source image.
debugfs -w -R "rm /usr/local/bin/ivcproto" "$output_image" >/dev/null 2>&1 || true
debugfs -w -R "mkdir /usr" "$output_image" >/dev/null 2>&1 || true
debugfs -w -R "mkdir /usr/local" "$output_image" >/dev/null 2>&1 || true
debugfs -w -R "mkdir /usr/local/bin" "$output_image" >/dev/null 2>&1 || true
debugfs -w -R "write $controller /usr/local/bin/ivcproto" "$output_image"
debugfs -w -R "set_inode_field /usr/local/bin/ivcproto mode 0100755" "$output_image"

debugfs -w -R "rm /ivc-init.sh" "$output_image" >/dev/null 2>&1 || true
debugfs -w -R "write $script_dir/ivc-init.sh /ivc-init.sh" "$output_image"
debugfs -w -R "set_inode_field /ivc-init.sh mode 0100755" "$output_image"

# Commit the debugfs updates as the filesystem's clean baseline. AxVisor's ext4
# implementation may otherwise replay an older journal when it mounts the disk.
set +e
e2fsck -fy "$output_image"
fsck_status=$?
set -e
if ((fsck_status > 1)); then
    echo "e2fsck failed after populating $output_image" >&2
    exit "$fsck_status"
fi

debugfs -R "stat /usr/local/bin/ivcproto" "$output_image"
debugfs -R "stat /ivc-init.sh" "$output_image"
sha256sum "$controller" "$output_image"
echo "IVC Linux rootfs ready at $output_image"
