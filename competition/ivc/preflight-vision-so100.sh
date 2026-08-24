#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../.." && pwd)
board_type=${ORANGEPI_BOARD_TYPE:-OrangePi-5-Plus}
ssh_target=${ORANGEPI_SSH_TARGET:-orangepi@192.168.31.33}
: "${ORANGEPI_SSH_IDENTITY:?set ORANGEPI_SSH_IDENTITY to the board SSH private key}"
camera_usb_id=${ORANGEPI_VISION_CAMERA_USB_ID:-4c4a:4a55}
arm_usb_id=${ORANGEPI_SO100_USB_ID:-1a86:55d3}
expected_controller=/usb@fc880000
lease_log=$(mktemp "${TMPDIR:-/tmp}/orangepi-so100-preflight.XXXXXX.log")
lease_pid=

cleanup() {
    if [[ -n "$lease_pid" ]] && kill -0 "$lease_pid" 2>/dev/null; then
        kill -TERM "$lease_pid" 2>/dev/null || true
        wait "$lease_pid" 2>/dev/null || true
    fi
    rm -f -- "$lease_log"
}
trap cleanup EXIT HUP INT TERM

for usb_id in "$camera_usb_id" "$arm_usb_id"; do
    case "$usb_id" in
        [0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]) ;;
        *)
            echo "USB identity must be a VID:PID pair: $usb_id" >&2
            exit 2
            ;;
    esac
done
camera_usb_id=${camera_usb_id,,}
arm_usb_id=${arm_usb_id,,}
[[ -r "$ORANGEPI_SSH_IDENTITY" ]] || {
    echo "Board SSH identity is not readable: $ORANGEPI_SSH_IDENTITY" >&2
    exit 2
}

cd "$workspace"
cargo xtask board connect -b "$board_type" >"$lease_log" 2>&1 &
lease_pid=$!
lease_deadline=$((SECONDS + 60))
while ! grep -q '^Allocated board session:' "$lease_log"; do
    if ! kill -0 "$lease_pid" 2>/dev/null; then
        echo "Board lease ended before SO-100 preflight allocation" >&2
        sed -n '1,160p' "$lease_log" >&2
        exit 1
    fi
    if ((SECONDS >= lease_deadline)); then
        echo "Timed out acquiring the $board_type preflight lease" >&2
        sed -n '1,160p' "$lease_log" >&2
        exit 1
    fi
    sleep 0.2
done

ssh_options=(
    -i "$ORANGEPI_SSH_IDENTITY"
    -o IdentitiesOnly=yes
    -o BatchMode=yes
    -o StrictHostKeyChecking=accept-new
    -o ConnectTimeout=8
)
ssh "${ssh_options[@]}" "$ssh_target" sh -s -- \
    "$camera_usb_id" "$arm_usb_id" "$expected_controller" <<'REMOTE'
set -eu
camera_usb_id=$1
arm_usb_id=$2
expected_controller=$3

inspect_usb_identity() {
    expected_id=$1
    expected_driver=$2
    count=0
    selected=
    controller=
    driver_found=0

    for usb_device in /sys/bus/usb/devices/*; do
        [ -r "$usb_device/idVendor" ] || continue
        [ -r "$usb_device/idProduct" ] || continue
        vendor=$(tr 'A-F' 'a-f' <"$usb_device/idVendor")
        product=$(tr 'A-F' 'a-f' <"$usb_device/idProduct")
        [ "$vendor:$product" = "$expected_id" ] || continue
        count=$((count + 1))
        selected=$(readlink -f "$usb_device")
        cursor=$selected
        controller=
        while [ "$cursor" != / ]; do
            if [ -e "$cursor/of_node" ]; then
                of_node=$(readlink -f "$cursor/of_node")
                controller=${of_node#*/base}
                break
            fi
            cursor=${cursor%/*}
            [ -n "$cursor" ] || cursor=/
        done
        for interface in "$usb_device":*; do
            [ -L "$interface/driver" ] || continue
            driver=$(basename "$(readlink -f "$interface/driver")")
            [ "$driver" = "$expected_driver" ] && driver_found=1
        done
    done
    [ "$count" -eq 1 ] || {
        echo "Expected one $expected_id device, found $count" >&2
        return 1
    }
    [ "$controller" = "$expected_controller" ] || {
        echo "$expected_id is on $controller, expected $expected_controller" >&2
        return 1
    }
    [ "$driver_found" -eq 1 ] || {
        echo "$expected_id has no $expected_driver interface" >&2
        return 1
    }
    printf 'SO100_PREFLIGHT_DEVICE usb_id=%s controller=%s driver=%s sysfs=%s\n' \
        "$expected_id" "$controller" "$expected_driver" "$selected"
}

inspect_usb_identity "$camera_usb_id" uvcvideo
inspect_usb_identity "$arm_usb_id" cdc_acm
[ -c /dev/ttyACM0 ] || {
    echo "SO-100 CDC ACM node /dev/ttyACM0 is missing" >&2
    exit 1
}
echo "SO100_PREFLIGHT_PASS controller=$expected_controller topology=exclusive-shared-ehci motion_attempted=0"
REMOTE
