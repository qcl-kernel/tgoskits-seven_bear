#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../../.." && pwd)
output_dir=$workspace/tmp/competition/ivc/starry
output_image=${1:-$output_dir/starry-ivc-rootfs-vision.img}
runner_dir=$workspace/apps/starry/orangepi-5-plus-uvc-rknn/rknn-yolov8-image/install/rk3588_linux_aarch64/rknn_yolov8_image
target_dir=$output_dir/vision-controller-target
controller=$target_dir/aarch64-unknown-linux-gnu/release/ivc-vision-controller
actuator=$target_dir/aarch64-unknown-linux-gnu/release/ivc-vision-actuator
toolchain=nightly-2026-07-15
rustup_bin=${RUSTUP:-/home/seven_wsl/.cargo/bin/rustup}
cargo_bin=${CARGO:-/home/seven_wsl/.cargo/bin/cargo}
base_image=${IVC_VISION_BASE_IMAGE:-$workspace/tmp/axbuild/rootfs/rootfs-aarch64-busybox.img/rootfs-aarch64-busybox.img}
sysroot=${IVC_VISION_SYSROOT:-/usr/aarch64-linux-gnu}
vision_mode=${IVC_VISION_MODE:-fixed-images}
autorun_script=${IVC_VISION_AUTORUN_SCRIPT:-$script_dir/autorun-vision.sh}
libuvc=${IVC_VISION_LIBUVC:-}
libusb=${IVC_VISION_LIBUSB:-}
cross_readelf=${CROSS_READELF:-aarch64-linux-gnu-readelf}

audit_runtime_dependencies() {
    local component=$1
    local library=$2
    shift 2
    local dependency
    local allowed
    local matched

    while IFS= read -r dependency; do
        matched=false
        for allowed in "$@"; do
            if [[ "$dependency" == "$allowed" ]]; then
                matched=true
                break
            fi
        done
        if [[ "$matched" != true ]]; then
            echo "unexpected $component runtime dependency: $dependency" >&2
            exit 2
        fi
    done < <(
        "$cross_readelf" -d "$library" | \
            sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p'
    )
}

case "$vision_mode" in
    fixed-images|so100-prep) ;;
    *)
        echo "IVC_VISION_MODE must be fixed-images or so100-prep: $vision_mode" >&2
        exit 2
        ;;
esac

runner=$runner_dir/rknn_yolov8_bench
if [[ "$vision_mode" == so100-prep ]]; then
    runner=$runner_dir/rknn_yolov8_stream
    [[ -r "$libuvc" ]] || {
        echo "SO-100 preparation requires readable IVC_VISION_LIBUVC" >&2
        exit 2
    }
    [[ -r "$libusb" ]] || {
        echo "SO-100 preparation requires readable IVC_VISION_LIBUSB" >&2
        exit 2
    }
    command -v "$cross_readelf" >/dev/null 2>&1 || {
        echo "SO-100 preparation requires AArch64 readelf: $cross_readelf" >&2
        exit 2
    }
    for library in "$libuvc" "$libusb"; do
        "$cross_readelf" -h "$library" | grep -Eq 'Machine:[[:space:]]+AArch64' || {
            echo "SO-100 preparation runtime is not AArch64: $library" >&2
            exit 2
        }
    done
    audit_runtime_dependencies libusb "$libusb" \
        libc.so.6 libpthread.so.0 libdl.so.2 ld-linux-aarch64.so.1
    audit_runtime_dependencies libuvc "$libuvc" \
        libusb-1.0.so.0 libc.so.6 libpthread.so.0 ld-linux-aarch64.so.1
fi

bash "$workspace/apps/starry/orangepi-5-plus-uvc-rknn/build-image-runner.sh"

cd "$workspace"
"$rustup_bin" "+$toolchain" target add aarch64-unknown-linux-gnu
bins=(--bin ivc-vision-controller)
if [[ "$vision_mode" == so100-prep ]]; then
    bins+=(--bin ivc-vision-actuator)
fi
CARGO_TARGET_DIR="$target_dir" \
CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    "$cargo_bin" "+$toolchain" build --release --target aarch64-unknown-linux-gnu \
        --package ivcproto "${bins[@]}"

[[ -r "$base_image" ]] || { echo "Missing managed AArch64 rootfs: $base_image" >&2; exit 1; }
mkdir -p "$output_dir" "$(dirname -- "$output_image")"
cp --reflink=auto --sparse=always "$base_image" "$output_image"

required_inputs=(
    "$controller"
    "$runner"
    "$runner_dir/lib/librknnrt.so"
    "$runner_dir/model/yolov8.rknn"
    "$runner_dir/model/coco_80_labels_list.txt"
    "$autorun_script"
)
if [[ "$vision_mode" == fixed-images ]]; then
    required_inputs+=(
        "$runner_dir/validation/images.txt"
        "$runner_dir/validation/expected.txt"
        "$runner_dir/validation/tennis-ball-close.jpg"
        "$runner_dir/validation/tennis-ball-black-box.jpg"
        "$runner_dir/validation/tennis-ball-plant.jpg"
    )
fi
if [[ "$vision_mode" == so100-prep ]]; then
    required_inputs+=("$actuator" "$libuvc" "$libusb")
fi
for path in "${required_inputs[@]}"; do
    [[ -r "$path" ]] || { echo "Missing vision rootfs input: $path" >&2; exit 1; }
done

truncate -s "${IVC_STARRY_VISION_ROOTFS_SIZE:-256M}" "$output_image"
set +e
e2fsck -fy "$output_image"
fsck_status=$?
set -e
((fsck_status <= 1)) || exit "$fsck_status"
resize2fs "$output_image"

for directory in /opt /opt/vision /opt/vision/lib /opt/vision/model \
    /opt/vision/validation /usr /usr/local /usr/local/bin /var /var/lib /var/lib/ivc \
    /lib /lib/aarch64-linux-gnu /etc; do
    debugfs -w -R "mkdir $directory" "$output_image" >/dev/null 2>&1 || true
done

install_file() {
    local source=$1
    local destination=$2
    local mode=$3
    debugfs -w -R "rm $destination" "$output_image" >/dev/null 2>&1 || true
    debugfs -w -R "write $source $destination" "$output_image" >/dev/null
    debugfs -w -R "set_inode_field $destination mode $mode" "$output_image" >/dev/null
}

install_file "$sysroot/lib/ld-linux-aarch64.so.1" /lib/ld-linux-aarch64.so.1 0100755
for soname in libc.so.6 libpthread.so.0 libdl.so.2 libm.so.6 libstdc++.so.6 \
    libgcc_s.so.1; do
    [[ -r "$sysroot/lib/$soname" ]] || {
        echo "Missing AArch64 runtime library: $sysroot/lib/$soname" >&2
        exit 1
    }
    install_file "$sysroot/lib/$soname" "/lib/aarch64-linux-gnu/$soname" 0100755
done

install_file "$controller" /usr/local/bin/ivc-vision-controller 0100755
if [[ "$vision_mode" == fixed-images ]]; then
    install_file "$runner" /opt/vision/rknn_yolov8_bench 0100755
else
    install_file "$runner" /opt/vision/rknn_yolov8_stream 0100755
    install_file "$actuator" /usr/local/bin/ivc-vision-actuator 0100755
    install_file "$libuvc" /opt/vision/lib/libuvc.so.0 0100755
    install_file "$libusb" /lib/aarch64-linux-gnu/libusb-1.0.so.0 0100755
fi
install_file "$runner_dir/lib/librknnrt.so" /opt/vision/lib/librknnrt.so 0100755
install_file "$runner_dir/model/yolov8.rknn" /opt/vision/model/yolov8.rknn 0100644
install_file "$runner_dir/model/coco_80_labels_list.txt" \
    /opt/vision/model/coco_80_labels_list.txt 0100644
if [[ "$vision_mode" == fixed-images ]]; then
    for name in images.txt expected.txt tennis-ball-close.jpg tennis-ball-black-box.jpg \
        tennis-ball-plant.jpg; do
        install_file "$runner_dir/validation/$name" "/opt/vision/validation/$name" 0100644
    done
fi
install_file "$autorun_script" /usr/bin/starry-run-case-tests 0100755

profile_file=$(mktemp "$output_dir/vision-profile.XXXXXX")
trap 'rm -f -- "$profile_file"' EXIT HUP INT TERM
runner_sha256=$(sha256sum "$runner" | cut -d ' ' -f 1)
model_sha256=$(sha256sum "$runner_dir/model/yolov8.rknn" | cut -d ' ' -f 1)
controller_sha256=$(sha256sum "$controller" | cut -d ' ' -f 1)
printf 'vision_runner_sha256=%s\nvision_model_sha256=%s\nvision_controller_sha256=%s\n' \
    "$runner_sha256" "$model_sha256" "$controller_sha256" >"$profile_file"
if [[ "$vision_mode" == so100-prep ]]; then
    actuator_sha256=$(sha256sum "$actuator" | cut -d ' ' -f 1)
    libuvc_sha256=$(sha256sum "$libuvc" | cut -d ' ' -f 1)
    libusb_sha256=$(sha256sum "$libusb" | cut -d ' ' -f 1)
    printf '%s\n' \
        "vision_actuator_sha256=$actuator_sha256" \
        "vision_libuvc_sha256=$libuvc_sha256" \
        "vision_libusb_sha256=$libusb_sha256" \
        "vision_device=0" \
        "vision_width=320" \
        "vision_height=240" \
        "vision_fps=10" \
        "vision_infer_every=3" \
        "vision_max_inferences=180" \
        "vision_decision_ttl_us=1000000" \
        "vision_min_confidence=25" \
        "vision_decision_split_permille=500" \
        "vision_serial_fps=4" \
        "vision_session_id=1447646040" \
        "vision_actuator_mode=dry-run" \
        "vision_usb_controller=/usb@fc880000" \
        "vision_camera_usb_id=4c4a:4a55" \
        "vision_arm_usb_id=1a86:55d3" >>"$profile_file"
fi
install_file "$profile_file" /etc/ivc-vision-profile 0100644

set +e
e2fsck -fy "$output_image"
fsck_status=$?
set -e
((fsck_status <= 1)) || exit "$fsck_status"
debugfs -R 'cat /etc/ivc-vision-profile' "$output_image"
sha256sum "$controller" "$runner" "$runner_dir/model/yolov8.rknn" "$output_image"
if [[ "$vision_mode" == fixed-images ]]; then
    echo "STARRY_VISION_ROOTFS_PASS image=$output_image frames=3 mode=fixed-images"
else
    echo "STARRY_VISION_ROOTFS_PASS image=$output_image inferences=180 mode=so100-prep actuator=dry-run"
fi
