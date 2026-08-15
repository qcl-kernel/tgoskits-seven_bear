#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
    cat <<'EOF'
usage: run-rtos-qemu.sh <rtthread|freertos> [normal|ack-loss] [output-directory]

Build (when absent), run, and strictly analyze one Linux/RTOS AxVisor IVC
campaign. The default evidence directory is
tmp/competition/ivc/results/<rtos>-<profile> and is never overwritten.
EOF
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
rtos=${1:-}
profile=${2:-normal}
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
output_dir=${3:-"$workspace/competition/ivc/results/$rtos-$profile"}
toolchain=nightly-2026-07-15

case "$rtos" in
    rtthread)
        guest_name=rt-thread
        guest_binary=rtthread.bin
        ;;
    freertos)
        guest_name=freertos
        guest_binary=freertos.bin
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
case "$profile" in
    normal)
        drop_ack_every=0
        config_suffix=
        ;;
    ack-loss)
        drop_ack_every=5
        config_suffix=-ack-loss
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
if [[ "$output_dir" != /* ]]; then
    output_dir="$repo_root/$output_dir"
fi

guest_dir="$workspace/competition/ivc/guests/$rtos/$profile"
build_config="$script_dir/config/axvisor-aarch64-$rtos$config_suffix.toml"
qemu_config="$script_dir/config/qemu-aarch64-$rtos$config_suffix.toml"
rootfs="$workspace/competition/ivc/linux/rootfs.img"

for command in cargo debugfs git python3 sha256sum tee; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing RTOS IVC campaign command: $command" >&2
        exit 2
    fi
done
if [[ ! -f "$rootfs" ]]; then
    echo "missing Linux controller rootfs; run competition/ivc/linux/build-initramfs.sh" >&2
    exit 2
fi
rootfs_contains_file() {
    local guest_file=$1
    local stat_output

    stat_output=$(debugfs -R "stat $guest_file" "$rootfs" 2>&1) || return 1
    grep -q '^Inode:' <<<"$stat_output"
}
for guest_file in /guest/linux/linux-qemu /guest/linux/initramfs.cpio.gz; do
    if ! rootfs_contains_file "$guest_file"; then
        echo "Linux controller rootfs is missing $guest_file" >&2
        exit 2
    fi
done
if [[ ! -e "$guest_dir" ]]; then
    bash "$script_dir/$rtos/build.sh" "$profile" "$guest_dir"
elif [[ ! -f "$guest_dir/$guest_binary" ]] || [[ ! -f "$guest_dir/SHA256SUMS" ]]; then
    echo "incomplete existing RTOS guest output: $guest_dir" >&2
    exit 2
fi
(
    cd -- "$guest_dir"
    sha256sum --check --strict SHA256SUMS
)
if [[ -e "$output_dir" ]]; then
    echo "refusing to overwrite RTOS IVC evidence: $output_dir" >&2
    exit 2
fi

mkdir -p -- "$output_dir"
install -m 0644 "$build_config" "$output_dir/axvisor-build.toml"
install -m 0644 "$qemu_config" "$output_dir/qemu.toml"
install -m 0644 "$guest_dir/SHA256SUMS" "$output_dir/guest-SHA256SUMS"
install -m 0644 "$guest_dir/source-provenance.txt" \
    "$output_dir/guest-source-provenance.txt"
printf 'cargo +%s xtask axvisor qemu --config %q --qemu-config %q --rootfs %q\n' \
    "$toolchain" "$build_config" "$qemu_config" "$rootfs" \
    >"$output_dir/qemu-command.txt"

set +e
(
    cd -- "$repo_root"
    cargo "+$toolchain" xtask axvisor qemu \
        --config "$build_config" \
        --qemu-config "$qemu_config" \
        --rootfs "$rootfs"
) 2>&1 | tee "$output_dir/qemu.log"
run_status=${PIPESTATUS[0]}
set -e
if [[ $run_status -ne 0 ]]; then
    printf 'qemu_exit=%s\n' "$run_status" >"$output_dir/failure.txt"
    echo "AxVisor RTOS IVC campaign failed; raw evidence retained at $output_dir" >&2
    exit "$run_status"
fi

python3 "$script_dir/analyze_qemu.py" "$output_dir/qemu.log" \
    --output "$output_dir/summary.json" \
    --expected-count 100 \
    --profile "$profile" \
    --drop-ack-every "$drop_ack_every" \
    --expected-rtos "$guest_name"
(
    cd -- "$output_dir"
    sha256sum axvisor-build.toml qemu.toml guest-SHA256SUMS \
        guest-source-provenance.txt qemu-command.txt qemu.log summary.json \
        >SHA256SUMS
)

echo "validated $guest_name $profile AxVisor IVC result: $output_dir/summary.json"
