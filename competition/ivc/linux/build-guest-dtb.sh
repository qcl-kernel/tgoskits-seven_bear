#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
workspace=$(cd -- "$script_dir/../../.." && pwd)
output_dir="$workspace/tmp/competition/ivc/linux"
output_dtb="$output_dir/orangepi-5-plus.dtb"

mkdir -p "$output_dir"
dtc -I dts -O dtb -o "$output_dtb" "$script_dir/orangepi-5-plus.dts"

test "$(fdtget -t s "$output_dtb" /interrupt-controller@8000000 compatible)" = \
    "arm,gic-v3"
test "$(fdtget -t s "$output_dtb" /timer compatible)" = "arm,armv8-timer"
test "$(fdtget -t s "$output_dtb" /serial@9000000 compatible)" = \
    "arm,pl011 arm,primecell"
if fdtget -l "$output_dtb" / | grep -q '^[[:space:]]*virtio_mmio@'; then
    echo "Guest DTB template must not predeclare graph-owned virtio-mmio nodes" >&2
    exit 1
fi

sha256sum "$output_dtb"
echo "IVC Linux guest DTB ready at $output_dtb"
