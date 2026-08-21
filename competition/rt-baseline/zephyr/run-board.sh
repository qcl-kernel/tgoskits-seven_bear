#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

usage() {
    cat <<'EOF'
usage: run-board.sh [idle|cpu-stress|soak] <output-directory>

Build Zephyr v4.3.0 for RK3588 and run it directly on Orange Pi 5 Plus.
The soak profile uses sustained lower-priority CPU stress and a 30-minute
measured window. The output directory is immutable and must not already exist.
EOF
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
mode=${1:-}
output_root=${2:-}
zephyr_base=${ZEPHYR_BASE:-"$repo_root/tmp/zephyr-v4.3.0"}
west_workspace=${WEST_WORKSPACE:-"$repo_root/tmp"}
west=${WEST:-"$repo_root/tmp/zephyr-venv/bin/west"}
cross_compile=${CROSS_COMPILE:-"$repo_root/tmp/zephyr-toolchain/bin/aarch64-zephyr-"}
board_type=${ORANGEPI_BOARD_TYPE:-OrangePi-5-Plus}
ssh_target=${ORANGEPI_SSH_TARGET:-orangepi@192.168.31.33}
ssh_identity=${ORANGEPI_SSH_IDENTITY:-${HOME}/.ssh/orangepi_automation}
restore_linux=$repo_root/competition/ivc/orangepi/restore-linux.sh
serial_command_runner=$repo_root/competition/ivc/orangepi/serial-command.sh
power_tool=$repo_root/.claude/skills/board-power-control/scripts/board_power.py
power_config=${TGOS_BOARD_POWER_CONFIG:-$repo_root/.board-power.toml}
power_python=${ORANGEPI_POWER_PYTHON:-}
run_timeout_seconds=120
serial_settle_seconds=35

if [[ "$mode" == -h || "$mode" == --help ]]; then
    usage
    exit 0
fi
if [[ -z "$output_root" ]]; then
    usage >&2
    exit 2
fi
if [[ "$output_root" != /* ]]; then
    output_root=$repo_root/$output_root
fi
if [[ -e "$output_root" ]]; then
    echo "refusing to overwrite native RK3588 evidence: $output_root" >&2
    exit 2
fi

case "$mode" in
    idle)
        workload=idle
        profile=short
        extra_conf=
        ;;
    cpu-stress)
        workload=cpu-stress
        profile=short
        extra_conf=$script_dir/stress.conf
        ;;
    soak)
        workload=cpu-stress
        profile=soak
        extra_conf=$script_dir/soak.conf
        run_timeout_seconds=2100
        serial_settle_seconds=1860
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

if [[ ! -r "$power_config" ]]; then
    git_common_dir=$(git -C "$repo_root" rev-parse --path-format=absolute --git-common-dir)
    common_power_config=$(dirname -- "$git_common_dir")/.board-power.toml
    if [[ -r "$common_power_config" ]]; then
        power_config=$common_power_config
    fi
fi
if [[ -z "$power_python" ]]; then
    user_power_python=${HOME}/.local/share/tgos-board-power-venv/bin/python
    if [[ -x "$user_power_python" ]] \
        && "$user_power_python" -c 'import miio, tomllib' >/dev/null 2>&1; then
        power_python=$user_power_python
    elif command -v python.exe >/dev/null 2>&1 \
        && python.exe -c 'import miio, tomllib' >/dev/null 2>&1; then
        power_python=$(command -v python.exe)
    else
        echo "a Python 3.11+ interpreter with python-miio is required" >&2
        exit 2
    fi
fi

for input_path in \
    "$zephyr_base/VERSION" \
    "$west_workspace/.west/config" \
    "$west" \
    "$ssh_identity" \
    "$restore_linux" \
    "$serial_command_runner" \
    "$power_tool" \
    "$power_config"; do
    if [[ ! -r "$input_path" ]]; then
        echo "missing native RK3588 input: $input_path" >&2
        exit 2
    fi
done
for command_name in cargo git gzip mkfifo python3 rsync sha256sum ssh tee timeout \
    "${cross_compile}gcc"; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "missing native RK3588 command: $command_name" >&2
        exit 2
    fi
done
if [[ $(git -C "$zephyr_base" describe --tags --exact-match) != v4.3.0 ]]; then
    echo "Zephyr source is not checked out at the exact v4.3.0 tag" >&2
    exit 2
fi

mkdir -p -- "$output_root"
build_dir=$output_root/build
build_log=$output_root/build.log
board_service_log=$output_root/board-service.log
post_board_service_log=$output_root/post-board-service.log
console_log=$output_root/console.log
stage_log=$output_root/stage.log
pre_health=$output_root/pre-run-linux-health.log
post_health=$output_root/post-run-linux-health.log
restore_log=$output_root/restore-linux.log
power_before=$output_root/power-before.json
power_pre_cycle=$output_root/power-pre-cycle.json
power_after=$output_root/power-after.json
serial_status_file=$output_root/serial-status.txt
source_provenance=$output_root/source-provenance.json
summary=$output_root/summary.json
run_env=$output_root/run.env
remote_dir=/home/orangepi/tgos-native-zephyr/$mode
remote_binary=$remote_dir/zephyr.bin

ssh_options=(
    -i "$ssh_identity"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o StrictHostKeyChecking=accept-new
    -o ConnectTimeout=8
)

run_power_tool() {
    local tool_path=$power_tool
    local config_path=$power_config

    if [[ "$power_python" == *.exe ]]; then
        tool_path=$(wslpath -w "$power_tool")
        config_path=$(wslpath -w "$power_config")
    fi
    "$power_python" "$tool_path" --config "$config_path" "$@"
}

lease_pid=
lease_fifo=
lease_fifo_dir=
cleanup_lease() {
    exec 9>&- 2>/dev/null || true
    if [[ -n "$lease_pid" ]] && kill -0 "$lease_pid" 2>/dev/null; then
        kill -TERM "$lease_pid" 2>/dev/null || true
        wait "$lease_pid" 2>/dev/null || true
    fi
    lease_pid=
    if [[ -n "$lease_fifo_dir" ]]; then
        rm -rf -- "$lease_fifo_dir"
    fi
    lease_fifo=
    lease_fifo_dir=
}
trap cleanup_lease EXIT HUP INT TERM

start_lease() {
    local log_path=$1
    local deadline

    lease_fifo_dir=$(mktemp -d "${TMPDIR:-/tmp}/native-zephyr-input.XXXXXX")
    lease_fifo=$lease_fifo_dir/input
    mkfifo "$lease_fifo"
    exec 9<>"$lease_fifo"
    cargo xtask board connect -b "$board_type" <"$lease_fifo" >"$log_path" 2>&1 &
    lease_pid=$!
    deadline=$((SECONDS + 90))
    while ! grep -q '^Allocated board session:' "$log_path"; do
        if ! kill -0 "$lease_pid" 2>/dev/null; then
            echo "board lease ended before allocation" >&2
            sed -n '1,160p' "$log_path" >&2
            return 1
        fi
        if ((SECONDS >= deadline)); then
            echo "timed out while acquiring the $board_type lease" >&2
            return 1
        fi
        sleep 0.25
    done
}

capture_linux_health() {
    local marker=$1
    ssh "${ssh_options[@]}" "$ssh_target" sh -s -- "$marker" <<'REMOTE'
set -eu
marker=$1
test "$(hostname)" = orangepi5plus
root_mount=$(findmnt -n -o SOURCE,FSTYPE,OPTIONS /)
root_fstype=$(findmnt -n -o FSTYPE /)
root_options=$(findmnt -n -o OPTIONS /)
printf 'root_mount=%s\n' "$root_mount"
test "$root_fstype" = ext4
case "$root_options" in
    rw|rw,*) ;;
    *) echo "root filesystem is not writable: $root_options" >&2; exit 1 ;;
esac
kernel_log=$(journalctl -k -b --no-pager 2>/dev/null)
if [ -z "$kernel_log" ]; then
    echo 'current Linux kernel log is unavailable to the automation user' >&2
    exit 1
fi
printf '%s\n' "$kernel_log" | tail -n 160
if printf '%s\n' "$kernel_log" | grep -Eiq \
    'EXT4-fs error|Buffer I/O error|end_request: I/O error|corrupt|run fsck manually|Remounting filesystem read-only'; then
    echo 'current Linux boot reports a filesystem or block-device fault' >&2
    exit 1
fi
printf '%s\n' "$marker"
REMOTE
}

export ZEPHYR_BASE="$zephyr_base"
export ZEPHYR_TOOLCHAIN_VARIANT=cross-compile
export CROSS_COMPILE="$cross_compile"
build_command=(
    "$west" build -p always -b roc_rk3588_pc
    -d "$build_dir" "$script_dir"
)
if [[ -n "$extra_conf" ]]; then
    build_command+=(-- "-DEXTRA_CONF_FILE=$extra_conf")
fi
(
    cd -- "$west_workspace"
    "${build_command[@]}"
) 2>&1 | tee "$build_log"

run_power_tool status --json >"$power_before"
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
start_lease "$board_service_log"

ssh "${ssh_options[@]}" "$ssh_target" mkdir -p -- "$remote_dir" \
    >"$stage_log" 2>&1
rsync -a -e "ssh -i $ssh_identity -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8" \
    "$build_dir/zephyr/zephyr.bin" "$ssh_target:$remote_binary.new" \
    >>"$stage_log" 2>&1
ssh "${ssh_options[@]}" "$ssh_target" sh -s -- "$remote_dir" "$remote_binary" \
    >>"$stage_log" 2>&1 <<'REMOTE'
set -eu
remote_dir=$1
remote_binary=$2
mkdir -p -- "$remote_dir"
mv -f -- "$remote_binary.new" "$remote_binary"
sync
sha256sum "$remote_binary"
findmnt -n -o SOURCE,FSTYPE,OPTIONS /
echo NATIVE_ZEPHYR_STAGE_PASS
REMOTE
capture_linux_health PRE_NATIVE_LINUX_HEALTH_PASS >"$pre_health" 2>&1

ssh "${ssh_options[@]}" "$ssh_target" \
    'sudo -n /usr/bin/sync; echo NATIVE_ZEPHYR_REBOOT_ARMED; sudo -n /usr/sbin/reboot' \
    >>"$stage_log" 2>&1 || true
cleanup_lease
sleep 20
uboot_command="if ext4load mmc 1:2 0x50000000 $remote_binary; then echo NATIVE_ZEPHYR_UBOOT_LOADED; echo NATIVE_ZEPHYR_GO; go 0x50000000; else echo NATIVE_ZEPHYR_UBOOT_LOAD_FAILED; fi"
set +e
ORANGEPI_SERIAL_COMMAND_SETTLE_SECONDS=$serial_settle_seconds \
ORANGEPI_SERIAL_COMMAND_TIMEOUT=$run_timeout_seconds \
    bash "$serial_command_runner" "$uboot_command" >"$console_log" 2>&1
serial_status=$?
set -e
printf 'serial_status=%s\n' "$serial_status" >"$serial_status_file"
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if grep -aEq \
    '^RTOS_BASELINE_FATAL([[:space:]]|$)|^NATIVE_ZEPHYR_UBOOT_LOAD_FAILED[[:space:]]*$' \
    "$console_log"; then
    echo "native Zephyr reported a fatal marker" >&2
    exit 1
fi
if ! grep -aEq 'RTOS_BASELINE_CONFIG schema=1 .*platform=orange-pi-5-plus-rk3588' \
    "$console_log"; then
    echo "native Zephyr configuration marker is missing" >&2
    exit 1
fi
if ! grep -aFq \
    "RTOS_BASELINE_COMPLETE schema=1 workload=$workload status=pass" \
    "$console_log"; then
    echo "native Zephyr completion marker is missing (serial status $serial_status)" >&2
    exit 1
fi

run_power_tool status --json >"$power_pre_cycle"
ORANGEPI_AXVISOR_NO_HOST_FS=1 \
ORANGEPI_POWER_PYTHON="$power_python" \
ORANGEPI_SSH_TARGET="$ssh_target" \
ORANGEPI_SSH_IDENTITY="$ssh_identity" \
    bash "$restore_linux" >"$restore_log" 2>&1

start_lease "$post_board_service_log"
capture_linux_health POST_NATIVE_LINUX_HEALTH_PASS >"$post_health" 2>&1
ssh "${ssh_options[@]}" "$ssh_target" sh -s -- "$remote_dir" <<'REMOTE'
set -eu
remote_dir=$1
case "$remote_dir" in
    /home/orangepi/tgos-native-zephyr/*) ;;
    *) echo "refusing to remove unexpected staging path: $remote_dir" >&2; exit 1 ;;
esac
rm -rf -- "$remote_dir"
sync
REMOTE
cleanup_lease
run_power_tool status --json >"$power_after"

python3 "$script_dir/capture_source.py" \
    --zephyr-base "$zephyr_base" \
    --output "$source_provenance"
python3 "$script_dir/analyze_board.py" "$console_log" \
    --build-log "$build_log" \
    --build-dir "$build_dir" \
    --zephyr-base "$zephyr_base" \
    --source-provenance "$source_provenance" \
    --workload "$workload" \
    --profile "$profile" \
    --stage-log "$stage_log" \
    --pre-health "$pre_health" \
    --post-health "$post_health" \
    --board-service-log "$board_service_log" \
    --power-before "$power_before" \
    --power-after "$power_after" \
    --serial-status "$serial_status_file" \
    --output "$summary"

printf '%s\n' \
    "mode=$mode" \
    "profile=$profile" \
    "workload=$workload" \
    "board_type=$board_type" \
    "started_at_utc=$started_at" \
    "finished_at_utc=$finished_at" \
    "serial_status=$serial_status" \
    "source_commit=$(git -C "$repo_root" rev-parse HEAD)" \
    "zephyr_commit=$(git -C "$zephyr_base" rev-parse 'v4.3.0^{}')" \
    >"$run_env"
gzip -n -c -- "$console_log" >"$console_log.gz"
(
    cd -- "$output_root"
    sha256sum \
        board-service.log \
        build.log \
        console.log \
        console.log.gz \
        post-board-service.log \
        post-run-linux-health.log \
        power-after.json \
        power-before.json \
        power-pre-cycle.json \
        pre-run-linux-health.log \
        restore-linux.log \
        run.env \
        serial-status.txt \
        source-provenance.json \
        stage.log \
        summary.json \
        >checksums.sha256
)

echo "NATIVE_ZEPHYR_BOARD_COMPLETE mode=$mode result_dir=$output_root"
