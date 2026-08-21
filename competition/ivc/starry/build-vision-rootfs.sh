#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../../.." && pwd)
output_dir=$workspace/tmp/competition/ivc/starry
output_image=${1:-$output_dir/starry-ivc-rootfs-vision.img}
runner_dir=$workspace/apps/starry/orangepi-5-plus-uvc-rknn/rknn-yolov8-image/install/rk3588_linux_aarch64/rknn_yolov8_image
target_dir=$output_dir/vision-controller-target
controller=$target_dir/aarch64-unknown-linux-gnu/release/ivc-vision-controller
toolchain=nightly-2026-07-15
rustup_bin=${RUSTUP:-/home/seven_wsl/.cargo/bin/rustup}
cargo_bin=${CARGO:-/home/seven_wsl/.cargo/bin/cargo}
base_image=$workspace/tmp/axbuild/rootfs/rootfs-aarch64-busybox.img/rootfs-aarch64-busybox.img
sysroot=${IVC_VISION_SYSROOT:-/usr/aarch64-linux-gnu}

bash "$workspace/apps/starry/orangepi-5-plus-uvc-rknn/build-image-runner.sh"

cd "$workspace"
"$rustup_bin" "+$toolchain" target add aarch64-unknown-linux-gnu
CARGO_TARGET_DIR="$target_dir" \
CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc \
    "$cargo_bin" "+$toolchain" build --release --target aarch64-unknown-linux-gnu \
        --package ivcproto --bin ivc-vision-controller

[[ -r "$base_image" ]] || { echo "Missing managed AArch64 rootfs: $base_image" >&2; exit 1; }
mkdir -p "$output_dir" "$(dirname -- "$output_image")"
cp --reflink=auto --sparse=always "$base_image" "$output_image"

for path in \
    "$controller" \
    "$runner_dir/rknn_yolov8_bench" \
    "$runner_dir/lib/librknnrt.so" \
    "$runner_dir/model/yolov8.rknn" \
    "$runner_dir/model/coco_80_labels_list.txt" \
    "$runner_dir/validation/images.txt" \
    "$runner_dir/validation/expected.txt" \
    "$runner_dir/validation/tennis-ball-close.jpg" \
    "$runner_dir/validation/tennis-ball-black-box.jpg" \
    "$runner_dir/validation/tennis-ball-plant.jpg" \
    "$script_dir/autorun-vision.sh"; do
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
install_file "$runner_dir/rknn_yolov8_bench" /opt/vision/rknn_yolov8_bench 0100755
install_file "$runner_dir/lib/librknnrt.so" /opt/vision/lib/librknnrt.so 0100755
install_file "$runner_dir/model/yolov8.rknn" /opt/vision/model/yolov8.rknn 0100644
install_file "$runner_dir/model/coco_80_labels_list.txt" \
    /opt/vision/model/coco_80_labels_list.txt 0100644
for name in images.txt expected.txt tennis-ball-close.jpg tennis-ball-black-box.jpg \
    tennis-ball-plant.jpg; do
    install_file "$runner_dir/validation/$name" "/opt/vision/validation/$name" 0100644
done
install_file "$script_dir/autorun-vision.sh" /usr/bin/starry-run-case-tests 0100755

profile_file=$(mktemp "$output_dir/vision-profile.XXXXXX")
trap 'rm -f -- "$profile_file"' EXIT HUP INT TERM
runner_sha256=$(sha256sum "$runner_dir/rknn_yolov8_bench" | cut -d ' ' -f 1)
model_sha256=$(sha256sum "$runner_dir/model/yolov8.rknn" | cut -d ' ' -f 1)
controller_sha256=$(sha256sum "$controller" | cut -d ' ' -f 1)
printf 'vision_runner_sha256=%s\nvision_model_sha256=%s\nvision_controller_sha256=%s\n' \
    "$runner_sha256" "$model_sha256" "$controller_sha256" >"$profile_file"
install_file "$profile_file" /etc/ivc-vision-profile 0100644

set +e
e2fsck -fy "$output_image"
fsck_status=$?
set -e
((fsck_status <= 1)) || exit "$fsck_status"
debugfs -R 'cat /etc/ivc-vision-profile' "$output_image"
sha256sum "$controller" "$runner_dir/rknn_yolov8_bench" \
    "$runner_dir/model/yolov8.rknn" "$output_image"
echo "STARRY_VISION_ROOTFS_PASS image=$output_image frames=3"
