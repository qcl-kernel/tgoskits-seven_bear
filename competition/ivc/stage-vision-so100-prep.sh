#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../.." && pwd)
artifact_dir=$workspace/tmp/competition/ivc/starry

IVC_VISION_KERNEL="$artifact_dir/starryos-rknpu-usb.bin" \
IVC_VISION_DTB="$artifact_dir/starry-orangepi-5-plus-rknpu-usb.dtb" \
IVC_VISION_ROOTFS="$artifact_dir/starry-ivc-rootfs-vision-so100-prep.img" \
IVC_VISION_REMOTE_KERNEL_NAME=starryos-rknpu-usb.bin \
IVC_VISION_REMOTE_DTB_NAME=starry-orangepi-5-plus-rknpu-usb.dtb \
IVC_VISION_REMOTE_ROOTFS_NAME=starry-ivc-rootfs-vision-so100-prep.img \
    bash "$script_dir/stage-vision.sh"
