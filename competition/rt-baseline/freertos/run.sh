#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
    cat <<'EOF'
usage: run.sh [idle|cpu-stress|all] [output-directory]

Build, run, and validate the native FreeRTOS AArch64 baseline.
The default output directory is tmp/competition/rt-baseline/freertos.
EOF
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
mode=${1:-all}
output_root=${2:-"$repo_root/tmp/competition/rt-baseline/freertos"}
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
source_root=${FREERTOS_BAO_SOURCE_ROOT:-"$workspace/freertos-over-bao"}
toolchain_root=${RT_BASELINE_TOOLCHAIN_ROOT:-"$workspace/arm-gnu-toolchain-13.2.Rel1-x86_64-aarch64-none-elf"}
cross_compile="$toolchain_root/bin/aarch64-none-elf-"
source_commit=cb9112f982c2768872536b811e013254d0184811
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

for command in git install make python3 qemu-system-aarch64 tee timeout \
    "${cross_compile}gcc"; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing FreeRTOS baseline command: $command" >&2
        exit 2
    fi
done
if [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]]; then
    echo "run prepare.sh before the FreeRTOS baseline" >&2
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
        echo "refusing to overwrite FreeRTOS evidence: $output_root/$workload" >&2
        exit 2
    fi
done
if [[ -e "$source_provenance" ]]; then
    echo "refusing to overwrite FreeRTOS evidence: $source_provenance" >&2
    exit 2
fi

run_case() {
    local workload=$1
    local case_dir="$output_root/$workload"
    local app="$case_dir/application"
    local build="$case_dir/build"
    local build_log="$case_dir/build.log"
    local raw_log="$case_dir/qemu.log"
    local command_file="$case_dir/qemu-command.txt"
    local -a build_command=(
        make -C "$source_root" "-j$jobs"
        PLATFORM=qemu-aarch64-virt
        SINGLE_CORE=y
        "APP_SRC_DIR=$app"
        "BUILD_DIR=$build"
        "CROSS_COMPILE=$cross_compile"
    )
    local -a qemu_command=(
        qemu-system-aarch64
        -machine virt,gic-version=3
        -cpu cortex-a53
        -smp 1
        -m 512M
        -nographic
        -no-reboot
        -semihosting-config enable=on,target=native
        -kernel "$case_dir/freertos.elf"
    )

    mkdir -p -- "$app"
    install -m 0644 "$script_dir/src/FreeRTOSConfig.h" "$app/FreeRTOSConfig.h"
    install -m 0644 "$script_dir/src/main.c" "$app/main.c"
    install -m 0644 "$script_dir/src/sources.mk" "$app/sources.mk"
    install -m 0644 "$script_dir/../common/latency_stats.c" "$app/latency_stats.c"
    install -m 0644 "$script_dir/../common/latency_stats.h" "$app/latency_stats.h"
    install -m 0644 "$script_dir/../common/miss_accounting.h" "$app/miss_accounting.h"
    if [[ "$workload" == cpu-stress ]]; then
        build_command+=(RT_BASELINE_STRESS=y)
    fi
    "${build_command[@]}" 2>&1 | tee "$build_log"
    install -m 0644 "$build/freertos.elf" "$case_dir/freertos.elf"
    install -m 0644 "$build/freertos.bin" "$case_dir/freertos.bin"
    install -m 0644 "$app/FreeRTOSConfig.h" "$case_dir/configuration.h"
    printf '%q ' "${qemu_command[@]}" >"$command_file"
    printf '\n' >>"$command_file"

    set +e
    timeout --foreground 60s "${qemu_command[@]}" 2>&1 | tee "$raw_log"
    local -a pipeline_status=("${PIPESTATUS[@]}")
    set -e
    if [[ ${pipeline_status[1]} -ne 0 ]] ||
        { [[ ${pipeline_status[0]} -ne 0 ]] && [[ ${pipeline_status[0]} -ne 1 ]]; }; then
        echo "FreeRTOS QEMU run failed with status ${pipeline_status[0]}" >&2
        return 2
    fi
}

analyze_case() {
    local workload=$1
    local case_dir="$output_root/$workload"

    python3 "$script_dir/../common/analyze.py" "$case_dir/qemu.log" \
        --rtos freertos \
        --workload "$workload" \
        --build-log "$case_dir/build.log" \
        --configuration "$case_dir/configuration.h" \
        --elf "$case_dir/freertos.elf" \
        --binary "$case_dir/freertos.bin" \
        --qemu-command "$case_dir/qemu-command.txt" \
        --source-root "$source_root" \
        --source-provenance "$source_provenance" \
        --cross-compile "$cross_compile" \
        --output "$case_dir/summary.json"
    echo "validated native FreeRTOS $workload result: $case_dir/summary.json"
}

for workload in "${workloads[@]}"; do
    run_case "$workload"
done
python3 "$script_dir/../common/capture_source.py" \
    --kind freertos \
    --source-root "$source_root" \
    --output "$source_provenance"
for workload in "${workloads[@]}"; do
    analyze_case "$workload"
done
