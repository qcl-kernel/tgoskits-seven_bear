#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
    cat <<'EOF'
usage: build.sh [normal|ack-loss|board-smoke] [output-directory]

Build the pinned FreeRTOS/Bao AxVisor IVC guest. The default output is
tmp/competition/ivc/guests/freertos/<profile>.
EOF
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
profile=${1:-normal}
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
source_root=${FREERTOS_BAO_SOURCE_ROOT:-"$workspace/freertos-over-bao"}
tcp_source=${FREERTOS_PLUS_TCP_SOURCE_ROOT:-"$workspace/freertos-plus-tcp-v4.4.1"}
toolchain_root=${RT_BASELINE_TOOLCHAIN_ROOT:-"$workspace/arm-gnu-toolchain-13.2.Rel1-x86_64-aarch64-none-elf"}
output_dir=${2:-"$workspace/competition/ivc/guests/freertos/$profile"}
cross_compile="$toolchain_root/bin/aarch64-none-elf-"
source_commit=cb9112f982c2768872536b811e013254d0184811
kernel_commit=f1043c49d59944353291654c175852bd17b34f99
runtime_commit=c50068084212ef33115a4c05f9f714cc637f30bc
tcp_commit=c12361095aca68aeed858f45d14395fbffa92c0d
jobs=${IVC_RTOS_BUILD_JOBS:-2}

case "$profile" in
    # The normal QEMU contract remains IVC_EXPECTED_COMMANDS=100; the physical
    # board-smoke profile deliberately narrows only this bound to 20.
    normal)
        expected_commands=100
        drop_ack_every=0
        stop_after_result=0
        ;;
    ack-loss)
        expected_commands=100
        drop_ack_every=5
        stop_after_result=0
        ;;
    board-smoke)
        expected_commands=20
        drop_ack_every=0
        stop_after_result=1
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
if [[ "$output_dir" != /* ]]; then
    output_dir="$repo_root/$output_dir"
fi

for command in git install make python3 sha256sum tee "${cross_compile}gcc"; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing FreeRTOS IVC build command: $command" >&2
        exit 2
    fi
done
if [[ ! -d "$source_root/.git" ]] ||
    [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]] ||
    [[ $(git -C "$source_root/src/freertos" rev-parse HEAD) != "$kernel_commit" ]] ||
    [[ $(git -C "$source_root/src/baremetal-runtime" rev-parse HEAD) != "$runtime_commit" ]] ||
    [[ -n $(git -C "$source_root" status --porcelain=v1 --untracked-files=all --ignore-submodules=none) ]]; then
    echo "run prepare.sh; freertos-over-bao or a pinned submodule has source drift" >&2
    exit 2
fi
if [[ ! -d "$tcp_source/.git" ]] ||
    [[ $(git -C "$tcp_source" rev-parse HEAD) != "$tcp_commit" ]] ||
    [[ $(git -C "$tcp_source" describe --tags --exact-match) != V4.4.1 ]] ||
    [[ -n $(git -C "$tcp_source" status --porcelain=v1 --untracked-files=all) ]]; then
    echo "run prepare.sh; FreeRTOS-Plus-TCP must be the clean pinned V4.4.1 source" >&2
    exit 2
fi
if [[ -e "$output_dir" ]]; then
    echo "refusing to overwrite FreeRTOS IVC output: $output_dir" >&2
    exit 2
fi

output_parent=$(dirname -- "$output_dir")
mkdir -p -- "$output_parent"
temporary_output=$(mktemp -d "$output_parent/.freertos-$profile.XXXXXX")
case "$temporary_output" in
    "$output_parent"/.freertos-"$profile".*) ;;
    *)
        echo "unexpected temporary output path: $temporary_output" >&2
        exit 2
        ;;
esac
cleanup() {
    rm -rf -- "$temporary_output"
}
trap cleanup EXIT HUP INT TERM

app="$temporary_output/application"
build="$temporary_output/build"
mkdir -p -- "$app"
for source in FreeRTOSConfig.h FreeRTOSIPConfig.h main.c network.c network.h sources.mk; do
    install -m 0644 "$script_dir/$source" "$app/$source"
done
for source in aarch64_psci.h ivc_rtos_server.c ivc_rtos_server.h \
    virtio_net_mmio.c virtio_net_mmio.h; do
    install -m 0644 "$script_dir/../common/$source" "$app/$source"
done
for source in protocol.c protocol.h endpoint.c endpoint.h; do
    install -m 0644 "$script_dir/../zephyr/src/$source" "$app/$source"
done

make -C "$source_root" "-j$jobs" \
    PLATFORM=qemu-aarch64-virt \
    SINGLE_CORE=y \
    "APP_SRC_DIR=$app" \
    "BUILD_DIR=$build" \
    "CROSS_COMPILE=$cross_compile" \
    "FREERTOS_PLUS_TCP_DIR=$tcp_source" \
    "IVC_EXPECTED_COMMANDS=$expected_commands" \
    "IVC_DROP_ACK_EVERY=$drop_ack_every" \
    "IVC_STOP_AFTER_RESULT=$stop_after_result" \
    2>&1 | tee "$temporary_output/build.log"

install -m 0644 "$build/freertos.elf" "$temporary_output/freertos.elf"
install -m 0644 "$build/freertos.bin" "$temporary_output/freertos.bin"
python3 "$script_dir/../common/validate_guest_elf.py" \
    "$temporary_output/freertos.elf" \
    --expected-entry 0x50000000 \
    --ram-base 0x50000000 \
    --ram-size 0x08000000 \
    --output "$temporary_output/elf-layout.json"
{
    printf 'rtos=freertos\nprofile=%s\nsource_commit=%s\n' \
        "$profile" "$source_commit"
    printf 'kernel_commit=%s\nruntime_commit=%s\nplus_tcp_commit=%s\n' \
        "$kernel_commit" "$runtime_commit" "$tcp_commit"
    printf 'compiler=%s\nexpected_commands=%s\ndrop_ack_every=%s\n' \
	"$("${cross_compile}gcc" --version | head -n 1)" \
	"$expected_commands" "$drop_ack_every"
    printf 'stop_after_result=%s\n' "$stop_after_result"
} >"$temporary_output/source-provenance.txt"
(
    cd -- "$temporary_output"
    sha256sum freertos.elf freertos.bin application/FreeRTOSConfig.h \
        application/FreeRTOSIPConfig.h elf-layout.json \
        source-provenance.txt >SHA256SUMS
)
rm -rf -- "$build"
mv -- "$temporary_output" "$output_dir"
trap - EXIT HUP INT TERM

echo "FreeRTOS AxVisor IVC guest ready: $output_dir/freertos.bin"
