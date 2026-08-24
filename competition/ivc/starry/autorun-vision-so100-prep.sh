#!/bin/sh

set -u

BB=/bin/busybox
PROFILE=/etc/ivc-vision-profile
RUNNER_LOG=/var/lib/ivc/vision-runner.log
CONTROLLER_LOG=/var/lib/ivc/vision-controller.log
ACTUATOR_LOG=/var/lib/ivc/vision-actuator.log
RUNNER_STATUS=/var/lib/ivc/vision-runner.status
RUNNER_TEE_STATUS=/var/lib/ivc/vision-runner-tee.status
CONTROLLER_STATUS=/var/lib/ivc/vision-controller.status
CONTROLLER_TEE_STATUS=/var/lib/ivc/vision-controller-tee.status
ACTUATOR_STATUS=/var/lib/ivc/vision-actuator.status
ACTUATOR_TEE_STATUS=/var/lib/ivc/vision-actuator-tee.status

exec >/dev/console 2>&1

replay_failure_tail() {
    component=$1
    log_path=$2
    [ -x "$BB" ] || return 0
    [ -r "$log_path" ] || return 0
    echo "IVC-STARRY-SO100-FAILURE-BEGIN component=$component"
    "$BB" tail -n 80 "$log_path"
    echo "IVC-STARRY-SO100-FAILURE-END component=$component"
}

fatal() {
    replay_failure_tail runner "$RUNNER_LOG"
    replay_failure_tail controller "$CONTROLLER_LOG"
    replay_failure_tail actuator "$ACTUATOR_LOG"
    echo "IVC-STARRY-SO100-PREP-FAIL reason=$1"
    "$BB" sync
    "$BB" poweroff -f
    while true; do
        "$BB" sleep 60
    done
}

positive_decimal() {
    case "$1" in
        ''|*[!0-9]*|0) return 1 ;;
        *) return 0 ;;
    esac
}

nonnegative_decimal() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}

[ -x "$BB" ] || fatal busybox-not-found
[ -r "$PROFILE" ] || fatal profile-not-found
# The generated profile is the only source of these immutable run values.
vision_device=
vision_width=
vision_height=
vision_fps=
vision_infer_every=
vision_max_inferences=
vision_decision_ttl_us=
vision_min_confidence=
vision_decision_split_permille=
vision_serial_fps=
vision_session_id=
vision_actuator_mode=
vision_usb_controller=
vision_camera_usb_id=
vision_arm_usb_id=
vision_runner_sha256=
vision_model_sha256=
vision_controller_sha256=
vision_actuator_sha256=
vision_libuvc_sha256=
vision_libusb_sha256=
# shellcheck disable=SC1090
. "$PROFILE"

for value in "$vision_device" "$vision_width" "$vision_height" "$vision_fps" \
    "$vision_infer_every" "$vision_max_inferences" "$vision_decision_ttl_us" \
    "$vision_min_confidence" "$vision_decision_split_permille" \
    "$vision_serial_fps" "$vision_session_id"; do
    nonnegative_decimal "$value" || fatal invalid-profile-number
done
positive_decimal "$vision_width" || fatal invalid-width
positive_decimal "$vision_height" || fatal invalid-height
positive_decimal "$vision_fps" || fatal invalid-fps
positive_decimal "$vision_infer_every" || fatal invalid-infer-every
positive_decimal "$vision_max_inferences" || fatal invalid-inference-count
positive_decimal "$vision_decision_ttl_us" || fatal invalid-decision-ttl
positive_decimal "$vision_min_confidence" || fatal invalid-min-confidence
positive_decimal "$vision_decision_split_permille" || fatal invalid-decision-split
positive_decimal "$vision_serial_fps" || fatal invalid-serial-fps
positive_decimal "$vision_session_id" || fatal invalid-session-id
[ "$vision_max_inferences" -eq 180 ] || fatal inference-count-profile-drift
[ "$vision_decision_ttl_us" -le 5000000 ] || fatal decision-ttl-too-large
[ "$vision_min_confidence" -le 99 ] || fatal min-confidence-too-large
[ "$vision_decision_split_permille" -lt 1000 ] || fatal decision-split-too-large
[ "$vision_actuator_mode" = dry-run ] || fatal physical-actuator-must-remain-locked
[ "$vision_usb_controller" = /usb@fc880000 ] || fatal unexpected-usb-controller
[ "$vision_camera_usb_id" = 4c4a:4a55 ] || fatal unexpected-camera-identity
[ "$vision_arm_usb_id" = 1a86:55d3 ] || fatal unexpected-arm-identity

[ -c /dev/dri/card1 ] || fatal rknpu-device-not-found
[ -c /dev/ttyUSB0 ] || fatal usb-serial-node-not-found
[ -x /opt/vision/rknn_yolov8_stream ] || fatal runner-not-found
[ -x /usr/local/bin/ivc-vision-controller ] || fatal controller-not-found
[ -x /usr/local/bin/ivc-vision-actuator ] || fatal actuator-not-found
[ -r /opt/vision/lib/libuvc.so.0 ] || fatal libuvc-not-found
[ -r /lib/aarch64-linux-gnu/libusb-1.0.so.0 ] || fatal libusb-not-found

verify_hash() {
    path=$1
    expected=$2
    actual=$($BB sha256sum "$path") || fatal hash-command-failed
    actual=${actual%% *}
    [ "$actual" = "$expected" ] || fatal artifact-hash-mismatch
}

verify_hash /opt/vision/rknn_yolov8_stream "$vision_runner_sha256"
verify_hash /opt/vision/model/yolov8.rknn "$vision_model_sha256"
verify_hash /usr/local/bin/ivc-vision-controller "$vision_controller_sha256"
verify_hash /usr/local/bin/ivc-vision-actuator "$vision_actuator_sha256"
verify_hash /opt/vision/lib/libuvc.so.0 "$vision_libuvc_sha256"
verify_hash /lib/aarch64-linux-gnu/libusb-1.0.so.0 "$vision_libusb_sha256"

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

echo "IVC-STARRY-SO100-PREP-BOOT source=live-usb-camera backend=rknn-npu actuator=dry-run"
echo "IVC-STARRY-SO100-PREP-IDENTITY camera=$vision_camera_usb_id arm=$vision_arm_usb_id controller=$vision_usb_controller"
echo "IVC-STARRY-SO100-PREP-NET ip=10.0.0.1/24 peer=10.0.0.2:5500 segment=1"
echo "IVC-STARRY-SO100-PREP-POLICY id1_left=2042 id1_right=2074 stable_frames=3 physical_applied=0 physical_verified=0"

LD_LIBRARY_PATH=/opt/vision/lib:/lib/aarch64-linux-gnu
export LD_LIBRARY_PATH
"$BB" rm -f "$RUNNER_LOG" "$CONTROLLER_LOG" "$ACTUATOR_LOG" \
    "$RUNNER_STATUS" "$RUNNER_TEE_STATUS" "$CONTROLLER_STATUS" \
    "$CONTROLLER_TEE_STATUS" "$ACTUATOR_STATUS" "$ACTUATOR_TEE_STATUS"

(
    cd /opt/vision || exit 125
    ./rknn_yolov8_stream \
        --device "$vision_device" \
        --width "$vision_width" \
        --height "$vision_height" \
        --fps "$vision_fps" \
        --infer-every "$vision_infer_every" \
        --max-inferences "$vision_max_inferences" \
        --http-port 0 \
        --serial-fps "$vision_serial_fps" \
        --log-every 10 \
        --min-confidence "$vision_min_confidence" \
        --closed-loop \
        --decision-split-permille "$vision_decision_split_permille" \
        --decision-ttl-us "$vision_decision_ttl_us" \
        --jpeg-quality 75
    status=$?
    printf '%s\n' "$status" >"$RUNNER_STATUS"
    exit "$status"
) 2>&1 | (
    "$BB" tee "$RUNNER_LOG" /dev/console
    status=$?
    printf '%s\n' "$status" >"$RUNNER_TEE_STATUS"
    exit "$status"
) | (
    /usr/local/bin/ivc-vision-controller \
        10.0.0.2:5500 - "$vision_session_id"
    status=$?
    printf '%s\n' "$status" >"$CONTROLLER_STATUS"
    exit "$status"
) 2>&1 | (
    "$BB" tee "$CONTROLLER_LOG" /dev/console
    status=$?
    printf '%s\n' "$status" >"$CONTROLLER_TEE_STATUS"
    exit "$status"
) | (
    /usr/local/bin/ivc-vision-actuator --dry-run -
    status=$?
    printf '%s\n' "$status" >"$ACTUATOR_STATUS"
    exit "$status"
) 2>&1 | (
    "$BB" tee "$ACTUATOR_LOG" /dev/console
    status=$?
    printf '%s\n' "$status" >"$ACTUATOR_TEE_STATUS"
    exit "$status"
)
pipeline_status=$?

for status_path in "$RUNNER_STATUS" "$RUNNER_TEE_STATUS" "$CONTROLLER_STATUS" \
    "$CONTROLLER_TEE_STATUS" "$ACTUATOR_STATUS" "$ACTUATOR_TEE_STATUS"; do
    [ -r "$status_path" ] || fatal component-status-missing
    status_value=$("$BB" cat "$status_path") || fatal component-status-read-failed
    [ "$status_value" -eq 0 ] || fatal component-failed
done
[ "$pipeline_status" -eq 0 ] || fatal pipeline-failed

decision_count=$($BB grep -c '^VISION_DECISION_RECORD ' "$RUNNER_LOG") || fatal decision-count-failed
capture_count=$($BB grep -c '^VISION_CAPTURE_IDENTITY ' "$RUNNER_LOG") || fatal capture-count-failed
jpeg_begin_count=$($BB grep -c '^STARRY_JPEG_BEGIN ' "$RUNNER_LOG") || fatal jpeg-count-failed
authorization_count=$($BB grep -c '^VISION_RTOS_AUTH_RECORD ' "$CONTROLLER_LOG") || fatal authorization-count-failed
actuator_count=$($BB grep -c '^VISION_ACTUATOR_RECORD ' "$ACTUATOR_LOG") || fatal actuator-count-failed
for count in "$decision_count" "$capture_count" "$jpeg_begin_count" \
    "$authorization_count" "$actuator_count"; do
    [ "$count" -eq "$vision_max_inferences" ] || fatal exact-record-count-mismatch
done
"$BB" grep -q "^VISION_CLOSED_LOOP_DONE frames=$vision_max_inferences applied=$vision_max_inferences errors=0$" \
    "$CONTROLLER_LOG" || fatal controller-completion-missing
"$BB" grep -q "^VISION_ACTUATOR_DONE authorizations=$vision_max_inferences physical_applied=0 physical_verified=0 device_io_attempted=0$" \
    "$ACTUATOR_LOG" || fatal actuator-completion-missing
"$BB" grep -q '^stream-rknn: done .*inference_errors=0 ' "$RUNNER_LOG" || fatal runner-completion-missing

runner_hash=$($BB sha256sum "$RUNNER_LOG") || fatal runner-log-hash-failed
runner_hash=${runner_hash%% *}
controller_hash=$($BB sha256sum "$CONTROLLER_LOG") || fatal controller-log-hash-failed
controller_hash=${controller_hash%% *}
actuator_hash=$($BB sha256sum "$ACTUATOR_LOG") || fatal actuator-log-hash-failed
actuator_hash=${actuator_hash%% *}
"$BB" sync || fatal final-sync-failed

echo "IVC-STARRY-SO100-PREP-HASH component=runner sha256=$runner_hash"
echo "IVC-STARRY-SO100-PREP-HASH component=controller sha256=$controller_hash"
echo "IVC-STARRY-SO100-PREP-HASH component=actuator sha256=$actuator_hash"
echo "IVC-STARRY-SO100-PREP-DONE inferences=$vision_max_inferences physical_applied=0 physical_verified=0 exit=0"
"$BB" poweroff -f
"$BB" sleep 5
fatal poweroff-returned
