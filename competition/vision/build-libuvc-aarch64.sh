#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
libuvc_url=https://github.com/libuvc/libuvc.git
libuvc_commit=047920bcdfb1dac42424c90de5cc77dfc9fba04d
libusb_runtime=${1:-}
output_root=${2:-$repo_root/tmp/competition/vision/libuvc-aarch64-${libuvc_commit:0:12}}
libusb_header=${LIBUSB_HEADER:-/usr/include/libusb-1.0/libusb.h}
cross_prefix=${CROSS_COMPILE:-aarch64-linux-gnu-}

if [[ -z "$libusb_runtime" ]]; then
    echo "usage: build-libuvc-aarch64.sh <AArch64-libusb-1.0.so.0> [new-output-directory]" >&2
    exit 2
fi
if [[ ! -r "$libusb_runtime" || ! -r "$libusb_header" ]]; then
    echo "libusb runtime or architecture-independent header is not readable" >&2
    exit 2
fi
if [[ -e "$output_root" ]]; then
    echo "refusing to overwrite libuvc build evidence: $output_root" >&2
    exit 2
fi
for command_name in \
    "${cross_prefix}gcc" \
    "${cross_prefix}readelf" \
    cmake git pkg-config sha256sum; do
    command -v "$command_name" >/dev/null 2>&1 || {
        echo "missing libuvc cross-build command: $command_name" >&2
        exit 2
    }
done
if ! "${cross_prefix}readelf" -h "$libusb_runtime" | \
    grep -Eq 'Machine:[[:space:]]+AArch64'; then
    echo "libusb runtime is not an AArch64 ELF object" >&2
    exit 2
fi
if ! "${cross_prefix}readelf" -d "$libusb_runtime" | \
    grep -Fq 'Library soname: [libusb-1.0.so.0]'; then
    echo "libusb runtime does not provide SONAME libusb-1.0.so.0" >&2
    exit 2
fi

source_dir=$output_root/source
sysroot=$output_root/sysroot
build_dir=$output_root/build
install_dir=$output_root/install
mkdir -p -- "$output_root"
git clone --filter=blob:none --no-checkout "$libuvc_url" "$source_dir"
git -C "$source_dir" fetch --depth=1 origin "$libuvc_commit"
git -C "$source_dir" checkout --detach "$libuvc_commit"
[[ $(git -C "$source_dir" rev-parse HEAD) == "$libuvc_commit" ]] || {
    echo "libuvc source checkout does not match the pinned commit" >&2
    exit 1
}
[[ -z $(git -C "$source_dir" status --porcelain --untracked-files=normal) ]] || {
    echo "libuvc source checkout is not clean" >&2
    exit 1
}

mkdir -p -- "$sysroot/include/libusb-1.0" "$sysroot/lib/pkgconfig"
cp -- "$libusb_header" "$sysroot/include/libusb-1.0/libusb.h"
cp -- "$libusb_runtime" "$sysroot/lib/libusb-1.0.so.0"
ln -s libusb-1.0.so.0 "$sysroot/lib/libusb-1.0.so"
{
    printf 'prefix=%s\n' "$sysroot"
    cat <<'PKGCONFIG'
exec_prefix=${prefix}
libdir=${prefix}/lib
includedir=${prefix}/include

Name: libusb-1.0
Description: userspace USB programming library
Version: 1.0.26
Libs: -L${libdir} -lusb-1.0
Cflags: -I${includedir}/libusb-1.0
PKGCONFIG
} >"$sysroot/lib/pkgconfig/libusb-1.0.pc"

PKG_CONFIG_LIBDIR="$sysroot/lib/pkgconfig" cmake \
    -S "$source_dir" -B "$build_dir" \
    -DCMAKE_SYSTEM_NAME=Linux \
    -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
    -DCMAKE_C_COMPILER="${cross_prefix}gcc" \
    -DCMAKE_INSTALL_PREFIX="$install_dir" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_BUILD_TARGET=Shared \
    -DBUILD_EXAMPLE=OFF \
    -DBUILD_TEST=OFF \
    -DCMAKE_DISABLE_FIND_PACKAGE_JpegPkg=TRUE \
    2>&1 | tee "$output_root/configure.log"
cmake --build "$build_dir" --parallel 2>&1 | tee "$output_root/build.log"
cmake --install "$build_dir" 2>&1 | tee "$output_root/install.log"

libuvc_real=$(readlink -f "$install_dir/lib/libuvc.so")
[[ -r "$libuvc_real" ]] || {
    echo "cross-build did not produce libuvc.so" >&2
    exit 1
}
"${cross_prefix}readelf" -h "$libuvc_real" >"$output_root/libuvc-elf-header.txt"
"${cross_prefix}readelf" -d "$libuvc_real" >"$output_root/libuvc-dynamic.txt"
grep -Eq 'Machine:[[:space:]]+AArch64' "$output_root/libuvc-elf-header.txt"
grep -Fq 'Shared library: [libusb-1.0.so.0]' "$output_root/libuvc-dynamic.txt"
grep -Fq 'Library soname: [libuvc.so.0]' "$output_root/libuvc-dynamic.txt"

printf '%s\n' \
    "libuvc_url=$libuvc_url" \
    "libuvc_commit=$libuvc_commit" \
    "libuvc_path=$libuvc_real" \
    "libusb_runtime=$libusb_runtime" \
    "cross_compiler=$("${cross_prefix}gcc" --version | head -n 1)" \
    "jpeg_support=disabled-runner-decodes-mjpeg" \
    >"$output_root/provenance.env"
(
    cd -- "$output_root"
    sha256sum \
        build.log \
        configure.log \
        install.log \
        install/lib/libuvc.so.0.0.7 \
        libuvc-dynamic.txt \
        libuvc-elf-header.txt \
        provenance.env \
        sysroot/include/libusb-1.0/libusb.h \
        sysroot/lib/libusb-1.0.so.0 \
        >manifest.sha256
)
echo "LIBUVC_AARCH64_BUILD_PASS libuvc=$libuvc_real libusb=$libusb_runtime"
