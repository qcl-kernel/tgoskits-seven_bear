#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../.." && pwd)
toolchain=nightly-2026-07-15
output_dir=$workspace/tmp/competition/ivc/starry
built_kernel=$workspace/target/aarch64-unknown-none-softfloat/release/starryos.bin
kernel=$output_dir/starryos-rknpu-usb.bin
guest_dtb=$output_dir/starry-orangepi-5-plus-rknpu-usb.dtb
rootfs=$output_dir/starry-ivc-rootfs-vision-so100-prep.img
zephyr_dir=$workspace/competition/ivc/zephyr
zephyr_build=$zephyr_dir/build-board-vision-so100-prep
linux_cross_compile=${IVC_LINUX_CROSS_COMPILE:-aarch64-linux-gnu-}
zephyr_cross_compile=${IVC_ZEPHYR_CROSS_COMPILE:-${CROSS_COMPILE:-}}

: "${IVC_VISION_LIBUVC:?set IVC_VISION_LIBUVC to an AArch64 libuvc shared object}"
: "${IVC_VISION_LIBUSB:?set IVC_VISION_LIBUSB to its AArch64 libusb-1.0.so.0 dependency}"

for command_name in cargo cmake ctest debugfs dtc e2fsck fdtget resize2fs sha256sum west; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "Required SO-100 preparation build command not found: $command_name" >&2
        exit 1
    }
done

cd "$workspace"
cargo "+$toolchain" xtask starry build \
    -c competition/ivc/config/starry-aarch64-rknpu-usb.toml \
    --smp 2
[[ -s "$built_kernel" ]] || {
    echo "StarryOS USB/RKNPU build did not produce $built_kernel" >&2
    exit 1
}

mkdir -p "$output_dir"
install -m 0644 "$built_kernel" "$kernel"
dtc -I dts -O dtb -o "$guest_dtb" \
    "$script_dir/starry/orangepi-5-plus-rknpu.dts"
dtc -I dtb -O dts -o /dev/null "$guest_dtb"
if fdtget -l "$guest_dtb" / | grep -q '^[[:space:]]*virtio_mmio@'; then
    echo "Guest DTB template must not predeclare graph-owned virtio-mmio nodes" >&2
    exit 1
fi

IVC_LINUX_CROSS_COMPILE="$linux_cross_compile" \
    bash "$script_dir/starry/build-vision-so100-prep-rootfs.sh" "$rootfs"
zephyr_env=(env -u CROSS_COMPILE)
if [[ -n "$zephyr_cross_compile" ]]; then
    zephyr_env=(env "CROSS_COMPILE=$zephyr_cross_compile")
fi
"${zephyr_env[@]}" west build -p always -b qemu_cortex_a53 \
    -d "$zephyr_build" "$zephyr_dir" -- \
    -DEXTRA_CONF_FILE=board-vision-so100-prep.conf

zephyr_bin=$zephyr_build/zephyr/zephyr.bin
[[ -s "$zephyr_bin" ]] || {
    echo "Zephyr SO-100 preparation build did not produce $zephyr_bin" >&2
    exit 1
}
sha256sum "$kernel" "$guest_dtb" "$rootfs" "$zephyr_bin"
echo "VISION_SO100_PREP_BUILD_PASS mode=dry-run inferences=180 output_dir=$output_dir"
