#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../.." && pwd)
board_runner=$script_dir/orangepi/board-runner.sh
preflight=$script_dir/preflight-vision-so100.sh
stage_script=$script_dir/stage-vision-so100-prep.sh
pip_server=$workspace/competition/vision/live_pip_server.py
validator=$workspace/competition/vision/validate_live_pip_log.py
build_config=competition/ivc/config/axvisor-orangepi-5-plus-vision-so100-prep.toml
board_config=competition/ivc/config/board-orangepi-5-plus-vision-so100-prep.toml
artifact_dir=$workspace/tmp/competition/ivc/starry
board_type=${ORANGEPI_BOARD_TYPE:-OrangePi-5-Plus}
timeout_seconds=${ORANGEPI_RUN_TIMEOUT_SECONDS:-1200}
pip_port=${IVC_LIVE_PIP_PORT:-8765}
host_root=${ORANGEPI_AXVISOR_HOST_ROOT:?set ORANGEPI_AXVISOR_HOST_ROOT to the board Linux root device or PARTUUID}
result_root=${1:-$workspace/competition/results/orangepi-vision-so100-prep}
run_id=${IVC_VISION_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
run_dir=$result_root/$run_id
pip_pid=

cleanup() {
    if [[ -n "$pip_pid" ]] && kill -0 "$pip_pid" 2>/dev/null; then
        kill -TERM "$pip_pid" 2>/dev/null || true
        wait "$pip_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT HUP INT TERM

case "$pip_port" in
    ''|*[!0-9]*) echo "IVC_LIVE_PIP_PORT must be an integer" >&2; exit 2 ;;
esac
if ((pip_port < 1 || pip_port > 65535)); then
    echo "IVC_LIVE_PIP_PORT must be in 1..65535" >&2
    exit 2
fi
if [[ -e "$run_dir" ]]; then
    echo "SO-100 preparation result directory already exists: $run_dir" >&2
    exit 1
fi
for input_path in \
    "$board_runner" "$preflight" "$stage_script" "$pip_server" "$validator" \
    "$artifact_dir/starryos-rknpu-usb.bin" \
    "$artifact_dir/starry-orangepi-5-plus-rknpu-usb.dtb" \
    "$artifact_dir/starry-ivc-rootfs-vision-so100-prep.img" \
    "$workspace/competition/ivc/zephyr/build-board-vision-so100-prep/zephyr/zephyr.bin" \
    "$workspace/$build_config" "$workspace/$board_config"; do
    [[ -r "$input_path" ]] || {
        echo "Required SO-100 preparation input is not readable: $input_path" >&2
        exit 1
    }
done
if [[ -n $(git -C "$workspace" status --porcelain=v1) ]]; then
    echo "SO-100 preparation evidence requires a clean Git worktree" >&2
    exit 1
fi

mkdir -p "$run_dir"
git -C "$workspace" rev-parse HEAD >"$run_dir/source-commit.txt"
bash "$preflight" >"$run_dir/preflight.log" 2>&1
bash "$stage_script" >"$run_dir/stage.log" 2>&1

python3 "$pip_server" \
    --input "$run_dir/console.log" \
    --host 127.0.0.1 \
    --port "$pip_port" \
    >"$run_dir/live-pip.log" 2>&1 &
pip_pid=$!
echo "LIVE_PIP_PREP_URL http://127.0.0.1:$pip_port/ physical=dry-run"

set +e
ORANGEPI_AXVISOR_BUILD_CONFIG=$build_config \
ORANGEPI_AXVISOR_BOARD_CONFIG=$board_config \
ORANGEPI_AXVISOR_HOST_ROOT=$host_root \
ORANGEPI_AXVISOR_SHUTDOWN_MARKER_REQUIRED=1 \
ORANGEPI_BOARD_TYPE=$board_type \
ORANGEPI_LEASE_WAIT_SECONDS=$timeout_seconds \
ORANGEPI_RUN_TIMEOUT_SECONDS=$timeout_seconds \
ORANGEPI_RESTORE_LINUX=1 \
ORANGEPI_IVC_GUEST_IMAGE=/home/orangepi/axvisor-guest/starry-ivc-rootfs-vision-so100-prep.img \
ORANGEPI_IVC_RAW_CSV='' \
    bash "$board_runner" 2>&1 | tee "$run_dir/console.log"
pipeline_status=("${PIPESTATUS[@]}")
set -e
runner_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}

if [[ -n "$pip_pid" ]] && kill -0 "$pip_pid" 2>/dev/null; then
    kill -TERM "$pip_pid" 2>/dev/null || true
    wait "$pip_pid" 2>/dev/null || true
fi
pip_pid=
gzip -n -c "$run_dir/console.log" >"$run_dir/console.log.gz"

validation_status=1
if ((runner_status == 0 && tee_status == 0)); then
    set +e
    python3 "$validator" "$run_dir/console.log" \
        --expected-frames 180 \
        --physical forbidden \
        --output "$run_dir/summary.json"
    validation_status=$?
    set -e
fi
printf '%s\n' \
    "board_type=$board_type" \
    "runner_status=$runner_status" \
    "tee_status=$tee_status" \
    "validation_status=$validation_status" \
    "physical_applied=0" \
    "physical_verified=0" >"$run_dir/run.env"
(
    cd "$run_dir"
    evidence=(console.log console.log.gz live-pip.log preflight.log run.env source-commit.txt stage.log)
    [[ ! -f summary.json ]] || evidence+=(summary.json)
    sha256sum "${evidence[@]}" >checksums.sha256
)

((runner_status == 0)) || exit "$runner_status"
((tee_status == 0)) || exit "$tee_status"
((validation_status == 0)) || exit "$validation_status"
echo "VISION_SO100_PREP_RUN_PASS result_dir=$run_dir frames=180 physical_applied=0 physical_verified=0"
