#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
libusb_url=https://github.com/libusb/libusb.git
libusb_commit=4239bc3a50014b8e6a5a2a59df1fff3b7469543b
output_root=${1:-$repo_root/tmp/competition/vision/libusb-aarch64-${libusb_commit:0:12}}
cross_prefix=${CROSS_COMPILE:-aarch64-linux-gnu-}

if [[ -e "$output_root" ]]; then
    echo "refusing to overwrite libusb build evidence: $output_root" >&2
    exit 2
fi
for command_name in \
    "${cross_prefix}gcc" \
    "${cross_prefix}readelf" \
    autoconf automake git libtoolize make sha256sum; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "missing libusb cross-build command: $command_name" >&2
        exit 2
    }
done

source_dir=$output_root/source
install_dir=$output_root/install
mkdir -p -- "$output_root"
git clone --filter=blob:none --no-checkout "$libusb_url" "$source_dir"
git -C "$source_dir" fetch --depth=1 origin "$libusb_commit"
git -C "$source_dir" checkout --detach "$libusb_commit"
[[ $(git -C "$source_dir" rev-parse HEAD) == "$libusb_commit" ]] || {
    echo "libusb source checkout does not match the pinned commit" >&2
    exit 1
}
[[ -z $(git -C "$source_dir" status --porcelain --untracked-files=normal) ]] || {
    echo "libusb source checkout is not clean" >&2
    exit 1
}

(
    cd -- "$source_dir"
    ./autogen.sh \
        --host=aarch64-linux-gnu \
        --prefix="$install_dir" \
        --disable-udev \
        --disable-static \
        --enable-shared
) 2>&1 | tee "$output_root/configure.log"
make -C "$source_dir" -j2 2>&1 | tee "$output_root/build.log"
make -C "$source_dir" install 2>&1 | tee "$output_root/install.log"

libusb_real=$(readlink -f "$install_dir/lib/libusb-1.0.so")
[[ -r "$libusb_real" ]] || {
    echo "cross-build did not produce libusb-1.0.so" >&2
    exit 1
}
"${cross_prefix}readelf" -h "$libusb_real" >"$output_root/libusb-elf-header.txt"
"${cross_prefix}readelf" -d "$libusb_real" >"$output_root/libusb-dynamic.txt"
grep -Eq 'Machine:[[:space:]]+AArch64' "$output_root/libusb-elf-header.txt"
grep -Fq 'Library soname: [libusb-1.0.so.0]' "$output_root/libusb-dynamic.txt"

while IFS= read -r dependency; do
    case "$dependency" in
        libc.so.6|libpthread.so.0|libdl.so.2|ld-linux-aarch64.so.1) ;;
        *)
            echo "unexpected libusb runtime dependency: $dependency" >&2
            exit 1
            ;;
    esac
done < <(
    sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p' \
        "$output_root/libusb-dynamic.txt"
)

printf '%s\n' \
    "libusb_url=$libusb_url" \
    "libusb_commit=$libusb_commit" \
    "libusb_path=$libusb_real" \
    "cross_compiler=$("${cross_prefix}gcc" --version | head -n 1)" \
    "udev_support=disabled-starry-uses-usbfs" \
    >"$output_root/provenance.env"
(
    cd -- "$output_root"
    sha256sum \
        build.log \
        configure.log \
        install.log \
        install/lib/libusb-1.0.so.0.3.0 \
        libusb-dynamic.txt \
        libusb-elf-header.txt \
        provenance.env \
        >manifest.sha256
)
echo "LIBUSB_AARCH64_BUILD_PASS libusb=$libusb_real udev=disabled"
