#!/usr/bin/env bash

set -euo pipefail

workspace=$(git rev-parse --show-toplevel)
expected_source=069c911c1de02cecdc0c1fe891f5d5a288065ef0
actual_source=$(git rev-parse HEAD)
result_root=$workspace/tmp/competition/current-source-069c911c1/rt
host_root=PARTUUID=5874edd8-1582-a144-a298-b139acd7b0e6

if [[ "$actual_source" != "$expected_source" ]]; then
    echo "source mismatch: expected $expected_source, got $actual_source" >&2
    exit 1
fi

mkdir -p "$result_root"
printf '%s\n' "$actual_source" >"$result_root/source-commit.txt"
sha256sum \
    "$workspace/tmp/axvisor-rt/starryos-rt.bin" \
    "$workspace/tmp/competition/ivc/starry/starry-orangepi-5-plus.dtb" \
    "$workspace/tmp/axvisor-rt/starry-rt-capture-rootfs.img" \
    >"$result_root/staged-artifacts.sha256"

for profile in shared partitioned; do
    result_dir=$result_root/$profile
    if [[ -e "$result_dir" ]]; then
        echo "refusing to overwrite existing result directory: $result_dir" >&2
        exit 1
    fi
    mkdir -p "$result_dir"

    env \
        ORANGEPI_AXVISOR_HOST_ROOT="$host_root" \
        ORANGEPI_AXVISOR_BUILD_CONFIG="scripts/benchmark/axvisor-rt/config/axvisor-orangepi-5-plus-starry-$profile.toml" \
        ORANGEPI_AXVISOR_BOARD_CONFIG="scripts/benchmark/axvisor-rt/config/board-orangepi-5-plus-starry-$profile.toml" \
        ORANGEPI_AXVISOR_SHUTDOWN_MARKER_REQUIRED=1 \
        ORANGEPI_RESTORE_LINUX=1 \
        ORANGEPI_RUN_TIMEOUT_SECONDS=900 \
        bash competition/ivc/orangepi/board-runner.sh \
        2>&1 | tee "$result_dir/console.log"

    env \
        ORANGEPI_RT_RESULT_IMAGE=/home/rt \
        ORANGEPI_RT_RAW_LOG="$result_dir/raw.log" \
        ORANGEPI_RT_SUMMARY_JSON="$result_dir/summary.json" \
        ORANGEPI_RT_GUEST_IRQ_LOG="$result_dir/guest-irq.log.gz" \
        ORANGEPI_RT_HOST_TRACE_LOG="$result_dir/host.log" \
        ORANGEPI_RT_PROFILE="$profile" \
        ORANGEPI_RT_EXPECTED_WORKLOAD=cpu-stress \
        ORANGEPI_RT_EXPECTED_ITERATIONS=100 \
        ORANGEPI_RT_SOAK=0 \
        bash scripts/benchmark/axvisor-rt/harvest-starry-board.sh \
        2>&1 | tee "$result_dir/harvest.log"
done

python3 scripts/benchmark/axvisor-rt/compare_starry_board.py \
    "$result_root/shared/summary.json" \
    "$result_root/partitioned/summary.json" \
    --output "$result_root/comparison.json"

echo "AXVISOR_RT_CURRENT_SOURCE_SMOKE_COMPLETE result_root=$result_root source=$actual_source"
