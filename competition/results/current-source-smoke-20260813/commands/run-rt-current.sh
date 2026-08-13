#!/usr/bin/env bash

set -euo pipefail

expected_source=077ba386c20c29b84749f509b29e8a3f6f76e1e2
result_root=${RESULT_ROOT:?set RESULT_ROOT to a new directory on a Linux filesystem}

test "$(git rev-parse HEAD)" = "$expected_source"
test -z "$(git status --porcelain=v1)"
test ! -e "$result_root"

for profile in shared partitioned; do
  result_dir="$result_root/$profile"
  mkdir -p "$result_dir"

  bash scripts/benchmark/axvisor-rt/stage-starry-board.sh \
    2>&1 | tee "$result_dir/stage.log"

  env \
    ORANGEPI_AXVISOR_HOST_ROOT="${ORANGEPI_AXVISOR_HOST_ROOT:?}" \
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
