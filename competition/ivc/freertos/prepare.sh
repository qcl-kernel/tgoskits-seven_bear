#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
tcp_source=${FREERTOS_PLUS_TCP_SOURCE_ROOT:-"$workspace/freertos-plus-tcp-v4.4.1"}
tcp_commit=c12361095aca68aeed858f45d14395fbffa92c0d

bash "$repo_root/competition/rt-baseline/freertos/prepare.sh"
if [[ ! -d "$tcp_source/.git" ]]; then
    git -c core.autocrlf=false clone \
        https://github.com/FreeRTOS/FreeRTOS-Plus-TCP.git "$tcp_source"
    git -C "$tcp_source" config core.autocrlf false
    git -C "$tcp_source" config core.filemode false
    git -C "$tcp_source" checkout --detach "$tcp_commit"
fi
if [[ $(git -C "$tcp_source" rev-parse HEAD) != "$tcp_commit" ]] ||
    [[ $(git -C "$tcp_source" describe --tags --exact-match) != V4.4.1 ]] ||
    [[ -n $(git -C "$tcp_source" status --porcelain=v1 --untracked-files=all) ]]; then
    echo "FreeRTOS-Plus-TCP is not the clean pinned V4.4.1 source" >&2
    exit 2
fi

echo "FreeRTOS AxVisor IVC build environment ready"
echo "  FreeRTOS-Plus-TCP: $tcp_source"
