#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../.." && pwd)
board_runner=$script_dir/orangepi/board-runner.sh
stage_script=$script_dir/stage-vision.sh
analyzer=$workspace/competition/vision/analyze_closed_loop.py
build_config=competition/ivc/config/axvisor-orangepi-5-plus-vision.toml
board_config=competition/ivc/config/board-orangepi-5-plus-vision.toml
artifact_dir=$workspace/tmp/competition/ivc/starry
starry_kernel=$artifact_dir/starryos-rknpu.bin
starry_dtb=$artifact_dir/starry-orangepi-5-plus-rknpu.dtb
rootfs=$artifact_dir/starry-ivc-rootfs-vision.img
zephyr_guest=$workspace/competition/ivc/zephyr/build-board-vision/zephyr/zephyr.bin
model=$workspace/apps/starry/orangepi-5-plus-uvc-rknn/rknn-yolov8-image/install/rk3588_linux_aarch64/rknn_yolov8_image/model/yolov8.rknn
board_type=${ORANGEPI_BOARD_TYPE:-OrangePi-5-Plus}
timeout_seconds=${ORANGEPI_RUN_TIMEOUT_SECONDS:-900}
host_root=${ORANGEPI_AXVISOR_HOST_ROOT:?set ORANGEPI_AXVISOR_HOST_ROOT to the board Linux root device or PARTUUID}
result_root=${1:-$workspace/competition/results/orangepi-vision-20260818/closed-loop}
run_id=${IVC_VISION_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
run_dir=$result_root/$run_id

if [[ -e "$run_dir" ]]; then
    echo "Vision result directory already exists: $run_dir" >&2
    exit 1
fi
for input_path in \
    "$board_runner" "$stage_script" "$analyzer" "$starry_kernel" "$starry_dtb" \
    "$rootfs" "$zephyr_guest" "$model" "$workspace/$build_config" \
    "$workspace/$board_config"; do
    if [[ ! -r "$input_path" ]]; then
        echo "Required vision run input is not readable: $input_path" >&2
        exit 1
    fi
done
for command_name in date git gzip python3 sha256sum tee; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required vision evidence command not found: $command_name" >&2
        exit 1
    fi
done
case "$timeout_seconds" in
    ''|*[!0-9]*)
        echo "ORANGEPI_RUN_TIMEOUT_SECONDS must be a positive integer" >&2
        exit 2
        ;;
esac
if ((timeout_seconds == 0)); then
    echo "ORANGEPI_RUN_TIMEOUT_SECONDS must be a positive integer" >&2
    exit 2
fi

mkdir -p "$run_dir"
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
git -C "$workspace" rev-parse HEAD >"$run_dir/source-commit.txt"
git -C "$workspace" status --short >"$run_dir/worktree-status.txt"

ORANGEPI_BOARD_TYPE="$board_type" bash "$stage_script" \
    >"$run_dir/stage.log" 2>&1

set +e
ORANGEPI_AXVISOR_BUILD_CONFIG=$build_config \
ORANGEPI_AXVISOR_BOARD_CONFIG=$board_config \
ORANGEPI_AXVISOR_HOST_ROOT=$host_root \
ORANGEPI_AXVISOR_SHUTDOWN_MARKER_REQUIRED=1 \
ORANGEPI_BOARD_TYPE=$board_type \
ORANGEPI_LEASE_WAIT_SECONDS=$timeout_seconds \
ORANGEPI_RUN_TIMEOUT_SECONDS=$timeout_seconds \
ORANGEPI_RESTORE_LINUX=1 \
ORANGEPI_IVC_GUEST_IMAGE=/home/orangepi/axvisor-guest/starry-ivc-rootfs-vision.img \
ORANGEPI_IVC_RAW_CSV= \
    bash "$board_runner" 2>&1 | tee "$run_dir/console.log"
pipeline_status=("${PIPESTATUS[@]}")
set -e

runner_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}
gzip -n -c "$run_dir/console.log" >"$run_dir/console.log.gz"
analysis_status=1
if ((runner_status == 0 && tee_status == 0)); then
    set +e
    python3 "$analyzer" "$run_dir/console.log" --output "$run_dir/summary.json"
    analysis_status=$?
    set -e
fi
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf 'started_at=%s\nfinished_at=%s\nboard_type=%s\nrunner_status=%s\nanalysis_status=%s\n' \
    "$started_at" "$finished_at" "$board_type" "$runner_status" "$analysis_status" \
    >"$run_dir/run.env"

(
    cd "$workspace"
    sha256sum \
        "$build_config" \
        "$board_config" \
        "${starry_kernel#$workspace/}" \
        "${starry_dtb#$workspace/}" \
        "${rootfs#$workspace/}" \
        "${zephyr_guest#$workspace/}" \
        "${model#$workspace/}" \
        >"$run_dir/input-checksums.sha256"
)
(
    cd "$run_dir"
    evidence=(
        console.log console.log.gz input-checksums.sha256 run.env source-commit.txt
        stage.log worktree-status.txt
    )
    if [[ -f summary.json ]]; then
        evidence+=(summary.json)
    fi
    sha256sum "${evidence[@]}" >checksums.sha256
)

if ((runner_status != 0)); then
    echo "Vision board runner failed; evidence retained in $run_dir" >&2
    exit "$runner_status"
fi
if ((tee_status != 0)); then
    echo "Vision console capture failed; evidence retained in $run_dir" >&2
    exit "$tee_status"
fi
if ((analysis_status != 0)); then
    echo "Vision evidence analysis failed; evidence retained in $run_dir" >&2
    exit "$analysis_status"
fi

echo "ORANGEPI_VISION_CLOSED_LOOP_PASS result_dir=$run_dir"
