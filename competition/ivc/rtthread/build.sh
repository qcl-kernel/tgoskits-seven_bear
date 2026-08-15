#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
    cat <<'EOF'
usage: build.sh [normal|ack-loss] [output-directory]

Build the pinned RT-Thread v5.2.2 AxVisor IVC guest. The default output is
tmp/competition/ivc/guests/rtthread/<profile>.
EOF
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
profile=${1:-normal}
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
source_root=${RTTHREAD_SOURCE_ROOT:-"$workspace/rt-thread-v5.2.2"}
python_packages=${RTTHREAD_PYTHON_PACKAGES:-"$workspace/rtthread-python"}
toolchain_root=${RT_BASELINE_TOOLCHAIN_ROOT:-"$workspace/arm-gnu-toolchain-13.2.Rel1-x86_64-aarch64-none-elf"}
output_dir=${2:-"$workspace/competition/ivc/guests/rtthread/$profile"}
source_commit=ddf52e2cdd977f14fc04035c88672ac204aec713
jobs=${IVC_RTOS_BUILD_JOBS:-2}
scons="$python_packages/bin/scons"
cross_compile="$toolchain_root/bin/aarch64-none-elf-"

case "$profile" in
    normal)
        profile_macros=IVC_EXPECTED_COMMANDS=100
        ;;
    ack-loss)
        profile_macros=IVC_EXPECTED_COMMANDS=100,IVC_DROP_ACK_EVERY=5
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

for command in git install python3 sha256sum tar tee "${cross_compile}gcc"; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing RT-Thread IVC build command: $command" >&2
        exit 2
    fi
done
if [[ ! -x "$scons" ]] ||
    [[ ! -d "$source_root/.git" ]] ||
    [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]] ||
    [[ $(git -C "$source_root" describe --tags --exact-match) != v5.2.2 ]] ||
    [[ -n $(git -C "$source_root" status --porcelain=v1 --untracked-files=all) ]]; then
    echo "run prepare.sh; RT-Thread must be the clean pinned v5.2.2 source" >&2
    exit 2
fi
if [[ -e "$output_dir" ]]; then
    echo "refusing to overwrite RT-Thread IVC output: $output_dir" >&2
    exit 2
fi

output_parent=$(dirname -- "$output_dir")
mkdir -p -- "$output_parent"
temporary_output=$(mktemp -d "$output_parent/.rtthread-$profile.XXXXXX")
case "$temporary_output" in
    "$output_parent"/.rtthread-"$profile".*) ;;
    *)
        echo "unexpected temporary output path: $temporary_output" >&2
        exit 2
        ;;
esac
cleanup() {
    rm -rf -- "$temporary_output"
}
trap cleanup EXIT HUP INT TERM

stage="$temporary_output/source-stage"
bsp="$stage/bsp/qemu-virt64-aarch64"
app="$bsp/applications"
mkdir -p -- "$stage" "$workspace/rtthread-packages"
(
    cd -- "$source_root"
    tar --exclude=.git -cf - .
) | (
    cd -- "$stage"
    tar -xf -
)
for source in main.c network.c network.h SConscript; do
    install -m 0644 "$script_dir/$source" "$app/$source"
done
for source in ivc_rtos_server.c ivc_rtos_server.h virtio_net_mmio.c virtio_net_mmio.h; do
    install -m 0644 "$script_dir/../common/$source" "$app/$source"
done
for source in protocol.c protocol.h endpoint.c endpoint.h; do
    install -m 0644 "$script_dir/../zephyr/src/$source" "$app/$source"
done
python3 "$script_dir/configure.py" \
    "$source_root/bsp/qemu-virt64-aarch64/.config" \
    "$temporary_output/configuration.requested"
install -m 0644 "$temporary_output/configuration.requested" "$bsp/.config"

(
    cd -- "$bsp"
    export PYTHONPATH="$python_packages${PYTHONPATH:+:$PYTHONPATH}"
    export PKGS_DIR="$workspace/rtthread-packages"
    export RTT_EXEC_PATH="$toolchain_root/bin"
    export RTT_CC_PREFIX=aarch64-none-elf-
    "$scons" --pyconfig-silent
    "$scons" "-j$jobs" --global-macros="$profile_macros"
) 2>&1 | tee "$temporary_output/build.log"

install -m 0644 "$bsp/.config" "$temporary_output/configuration.config"
install -m 0644 "$bsp/rtthread.elf" "$temporary_output/rtthread.elf"
install -m 0644 "$bsp/rtthread.bin" "$temporary_output/rtthread.bin"
python3 "$script_dir/../common/validate_guest_elf.py" \
    "$temporary_output/rtthread.elf" \
    --expected-entry 0x40080000 \
    --ram-base 0x40000000 \
    --ram-size 0x08000000 \
    --output "$temporary_output/elf-layout.json"
{
    printf 'rtos=rt-thread\nprofile=%s\nsource_commit=%s\n' \
        "$profile" "$source_commit"
    printf 'source_tag=v5.2.2\ncompiler=%s\n' \
        "$("${cross_compile}gcc" --version | head -n 1)"
    printf 'global_macros=%s\n' "$profile_macros"
} >"$temporary_output/source-provenance.txt"
(
    cd -- "$temporary_output"
    sha256sum rtthread.elf rtthread.bin configuration.config \
        elf-layout.json source-provenance.txt >SHA256SUMS
)
rm -rf -- "$stage"
mv -- "$temporary_output" "$output_dir"
trap - EXIT HUP INT TERM

echo "RT-Thread AxVisor IVC guest ready: $output_dir/rtthread.bin"
