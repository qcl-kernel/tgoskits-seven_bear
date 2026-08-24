#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../../.." && pwd)
output_image=${1:-$workspace/tmp/competition/ivc/starry/starry-ivc-rootfs-vision-so100-prep.img}

: "${IVC_VISION_LIBUVC:?set IVC_VISION_LIBUVC to an AArch64 libuvc shared object}"
: "${IVC_VISION_LIBUSB:?set IVC_VISION_LIBUSB to its AArch64 libusb-1.0.so.0 dependency}"

IVC_VISION_MODE=so100-prep \
IVC_VISION_AUTORUN_SCRIPT="$script_dir/autorun-vision-so100-prep.sh" \
    bash "$script_dir/build-vision-rootfs.sh" "$output_image"
