#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
source_root=${FREERTOS_BAO_SOURCE_ROOT:-"$workspace/freertos-over-bao"}
source_commit=cb9112f982c2768872536b811e013254d0184811
kernel_commit=f1043c49d59944353291654c175852bd17b34f99
runtime_commit=c50068084212ef33115a4c05f9f714cc637f30bc

for command in git make python3 qemu-system-aarch64; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing FreeRTOS baseline prerequisite: $command" >&2
        exit 2
    fi
done

bash "$script_dir/../common/prepare_toolchain.sh"
mkdir -p -- "$workspace"
if [[ ! -d "$source_root/.git" ]]; then
    git -c core.autocrlf=false clone \
        https://github.com/bao-project/freertos-over-bao.git "$source_root"
    git -C "$source_root" config core.autocrlf false
    git -C "$source_root" config core.filemode false
    git -C "$source_root" checkout --detach "$source_commit"
fi
git -C "$source_root" submodule update --init --recursive
git -C "$source_root" submodule foreach --quiet --recursive \
    'git config core.autocrlf false && git config core.filemode false'

if [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]] ||
    [[ $(git -C "$source_root/src/freertos" rev-parse HEAD) != "$kernel_commit" ]] ||
    [[ $(git -C "$source_root/src/baremetal-runtime" rev-parse HEAD) != "$runtime_commit" ]] ||
    [[ -n $(git -C "$source_root" status --porcelain=v1 --untracked-files=all --ignore-submodules=none) ]]; then
    echo "freertos-over-bao or a pinned submodule has source drift" >&2
    exit 2
fi

echo "native FreeRTOS baseline environment ready"
echo "  source: $source_root"
