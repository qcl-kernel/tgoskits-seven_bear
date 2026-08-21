#!/bin/sh

set -u

BB=/bin/busybox
PROFILE=/etc/ivc-vision-profile
RUNNER_LOG=/var/lib/ivc/vision-runner.log
CONTROLLER_LOG=/var/lib/ivc/vision-controller.log

exec >/dev/console 2>&1

fatal() {
    echo "IVC-STARRY-VISION-FAIL reason=$1"
    "$BB" sync
    "$BB" poweroff -f
    while true; do
        "$BB" sleep 60
    done
}

[ -x "$BB" ] || fatal busybox-not-found
[ -r "$PROFILE" ] || fatal profile-not-found
. "$PROFILE"
[ -c /dev/dri/card1 ] || fatal rknpu-device-not-found
[ -x /opt/vision/rknn_yolov8_bench ] || fatal runner-not-found
[ -x /usr/local/bin/ivc-vision-controller ] || fatal controller-not-found

verify_hash() {
    path=$1
    expected=$2
    actual=$($BB sha256sum "$path") || fatal hash-command-failed
    actual=${actual%% *}
    [ "$actual" = "$expected" ] || fatal artifact-hash-mismatch
}

verify_hash /opt/vision/rknn_yolov8_bench "$vision_runner_sha256"
verify_hash /opt/vision/model/yolov8.rknn "$vision_model_sha256"
verify_hash /usr/local/bin/ivc-vision-controller "$vision_controller_sha256"

attempt=0
while [ "$attempt" -lt 60 ]; do
    if "$BB" ip link show dev eth0 >/dev/null 2>&1; then
        break
    fi
    attempt=$((attempt + 1))
    "$BB" sleep 1
done
[ "$attempt" -lt 60 ] || fatal eth0-not-found
"$BB" ip addr flush dev eth0 >/dev/null 2>&1 || true
"$BB" ip addr add 10.0.0.1/24 dev eth0 || fatal eth0-address-failed

vision_boot_record='IVC-STARRY-VISION-BOOT source=fixed-images backend=rknn-npu frames=3 target_class=32 calibration_x=625'
vision_net_record='IVC-STARRY-VISION-NET ip=10.0.0.1/24 peer=10.0.0.2:5500 segment=1'
echo "$vision_boot_record"
echo "$vision_net_record"
"$BB" sleep 2

LD_LIBRARY_PATH=/opt/vision/lib:/lib/aarch64-linux-gnu
export LD_LIBRARY_PATH
"$BB" rm -f "$RUNNER_LOG" "$CONTROLLER_LOG"
if ! (
    cd /opt/vision
    ./rknn_yolov8_bench \
        --validate-list validation/images.txt \
        --expected validation/expected.txt \
        --min-confidence 25 \
        --core-mask all \
        --profile
) >"$RUNNER_LOG" 2>&1; then
    "$BB" cat "$RUNNER_LOG"
    fatal rknn-runner-failed
fi
record_count=$($BB grep -c '^VISION_DECISION_RECORD ' "$RUNNER_LOG") \
    || fatal record-count-failed
[ "$record_count" -eq 3 ] || fatal record-count-mismatch
$BB grep -q '^UVC_RKNN_VALIDATE_PASS images=3$' "$RUNNER_LOG" \
    || fatal detection-validation-missing

if ! /usr/local/bin/ivc-vision-controller \
    10.0.0.2:5500 "$RUNNER_LOG" 1447646030 >"$CONTROLLER_LOG" 2>&1; then
    "$BB" cat "$CONTROLLER_LOG"
    fatal controller-failed
fi
$BB grep -q '^VISION_CLOSED_LOOP_DONE frames=3 applied=3 errors=0$' \
    "$CONTROLLER_LOG" || fatal completion-record-missing

runner_hash=$($BB sha256sum "$RUNNER_LOG") || fatal runner-log-hash-failed
runner_hash=${runner_hash%% *}
controller_hash=$($BB sha256sum "$CONTROLLER_LOG") || fatal controller-log-hash-failed
controller_hash=${controller_hash%% *}
"$BB" sync || fatal final-sync-failed

evidence_quiet_seconds=2
evidence_line_interval_seconds=0.25
evidence_copy_interval_seconds=1
evidence_copy=0
"$BB" sleep "$evidence_quiet_seconds"
while [ "$evidence_copy" -lt 3 ]; do
    echo "$vision_boot_record"
    "$BB" sleep "$evidence_line_interval_seconds"
    echo "$vision_net_record"
    "$BB" sleep "$evidence_line_interval_seconds"
    "$BB" grep '^VISION_DECISION_RECORD ' "$RUNNER_LOG" |
        while IFS= read -r record; do
            echo "$record"
            "$BB" sleep "$evidence_line_interval_seconds"
        done
    "$BB" grep '^UVC_RKNN_VALIDATE_PASS ' "$RUNNER_LOG"
    "$BB" sleep "$evidence_line_interval_seconds"
    while IFS= read -r record; do
        echo "$record"
        "$BB" sleep "$evidence_line_interval_seconds"
    done <"$CONTROLLER_LOG"
    echo "IVC-STARRY-VISION-RUNNER-SHA256 sha256=$runner_hash"
    "$BB" sleep "$evidence_line_interval_seconds"
    echo "IVC-STARRY-VISION-CONTROLLER-SHA256 sha256=$controller_hash"
    "$BB" sleep "$evidence_line_interval_seconds"
    evidence_copy=$((evidence_copy + 1))
    "$BB" sleep "$evidence_copy_interval_seconds"
done

done_copy=0
while [ "$done_copy" -lt 3 ]; do
    echo "IVC-STARRY-VISION-DONE exit=0"
    done_copy=$((done_copy + 1))
    "$BB" sleep "$evidence_line_interval_seconds"
done
"$BB" poweroff -f
"$BB" sleep 5
fatal poweroff-returned
