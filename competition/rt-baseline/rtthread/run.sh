#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
    cat <<'EOF'
usage: run.sh [idle|cpu-stress|all] [output-directory]

Build, run, and validate the native RT-Thread v5.2.2 AArch64 baseline.
The default output directory is tmp/competition/rt-baseline/rtthread.
EOF
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
mode=${1:-all}
output_root=${2:-"$repo_root/tmp/competition/rt-baseline/rtthread"}
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
source_root=${RTTHREAD_SOURCE_ROOT:-"$workspace/rt-thread-v5.2.2"}
python_packages=${RTTHREAD_PYTHON_PACKAGES:-"$workspace/rtthread-python"}
toolchain_root=${RT_BASELINE_TOOLCHAIN_ROOT:-"$workspace/arm-gnu-toolchain-13.2.Rel1-x86_64-aarch64-none-elf"}
cross_compile="$toolchain_root/bin/aarch64-none-elf-"
scons="$python_packages/bin/scons"
source_commit=ddf52e2cdd977f14fc04035c88672ac204aec713
jobs=${RT_BASELINE_JOBS:-2}

if [[ "$output_root" != /* ]]; then
    output_root="$repo_root/$output_root"
fi
case "$mode" in
    idle|cpu-stress|all) ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

for command in git install python3 qemu-system-aarch64 tar tee timeout \
    "${cross_compile}gcc"; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing RT-Thread baseline command: $command" >&2
        exit 2
    fi
done
if [[ ! -x "$scons" ]] ||
    [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]] ||
    [[ $(git -C "$source_root" describe --tags --exact-match) != v5.2.2 ]]; then
    echo "run prepare.sh before the RT-Thread baseline" >&2
    exit 2
fi

if [[ "$mode" == all ]]; then
    workloads=(idle cpu-stress)
else
    workloads=("$mode")
fi
source_provenance="$output_root/source-provenance.json"
for workload in "${workloads[@]}"; do
    if [[ -e "$output_root/$workload" ]]; then
        echo "refusing to overwrite RT-Thread evidence: $output_root/$workload" >&2
        exit 2
    fi
done
if [[ -e "$source_provenance" ]]; then
    echo "refusing to overwrite RT-Thread evidence: $source_provenance" >&2
    exit 2
fi

run_case() {
    local workload=$1
    local case_dir="$output_root/$workload"
    local stage="$case_dir/source-stage"
    local bsp="$stage/bsp/qemu-virt64-aarch64"
    local app="$bsp/applications"
    local requested_config="$case_dir/configuration.requested"
    local actual_config="$case_dir/configuration.config"
    local build_log="$case_dir/build.log"
    local raw_log="$case_dir/qemu.log"
    local command_file="$case_dir/qemu-command.txt"
    local -a build_command=("$scons" "-j$jobs")
    local -a qemu_command=(
        qemu-system-aarch64
        -machine virt,gic-version=3
        -cpu cortex-a53
        -smp 1
        -m 128M
        -nographic
        -no-reboot
        -kernel "$case_dir/rtthread.bin"
    )

    mkdir -p -- "$stage" "$workspace/rtthread-packages"
    (
        cd -- "$source_root"
        tar --exclude=.git -cf - .
    ) | (
        cd -- "$stage"
        tar -xf -
    )
    install -m 0644 "$script_dir/src/main.c" "$app/main.c"
    install -m 0644 "$script_dir/SConscript" "$app/SConscript"
    install -m 0644 "$script_dir/../common/latency_stats.c" "$app/latency_stats.c"
    install -m 0644 "$script_dir/../common/latency_stats.h" "$app/latency_stats.h"
    install -m 0644 "$script_dir/../common/miss_accounting.h" "$app/miss_accounting.h"
    python3 "$script_dir/configure.py" \
        "$source_root/bsp/qemu-virt64-aarch64/.config" "$requested_config"
    install -m 0644 "$requested_config" "$bsp/.config"
    if [[ "$workload" == cpu-stress ]]; then
        build_command+=(--global-macros=RT_BASELINE_STRESS)
    fi

    (
        cd -- "$bsp"
        export PYTHONPATH="$python_packages${PYTHONPATH:+:$PYTHONPATH}"
        export PKGS_DIR="$workspace/rtthread-packages"
        export RTT_EXEC_PATH="$toolchain_root/bin"
        export RTT_CC_PREFIX=aarch64-none-elf-
        "$scons" --pyconfig-silent
        "${build_command[@]}"
    ) 2>&1 | tee "$build_log"
    install -m 0644 "$bsp/.config" "$actual_config"
    install -m 0644 "$bsp/rtthread.elf" "$case_dir/rtthread.elf"
    install -m 0644 "$bsp/rtthread.bin" "$case_dir/rtthread.bin"
    printf '%q ' "${qemu_command[@]}" >"$command_file"
    printf '\n' >>"$command_file"
    timeout --foreground 60s "${qemu_command[@]}" 2>&1 | tee "$raw_log"
}

analyze_case() {
    local workload=$1
    local case_dir="$output_root/$workload"

    python3 "$script_dir/../common/analyze.py" "$case_dir/qemu.log" \
        --rtos rt-thread \
        --workload "$workload" \
        --build-log "$case_dir/build.log" \
        --configuration "$case_dir/configuration.config" \
        --elf "$case_dir/rtthread.elf" \
        --binary "$case_dir/rtthread.bin" \
        --qemu-command "$case_dir/qemu-command.txt" \
        --source-root "$source_root" \
        --source-provenance "$source_provenance" \
        --cross-compile "$cross_compile" \
        --output "$case_dir/summary.json"
    echo "validated native RT-Thread $workload result: $case_dir/summary.json"
}

for workload in "${workloads[@]}"; do
    run_case "$workload"
done
python3 "$script_dir/../common/capture_source.py" \
    --kind rt-thread \
    --source-root "$source_root" \
    --output "$source_provenance"
for workload in "${workloads[@]}"; do
    analyze_case "$workload"
done
