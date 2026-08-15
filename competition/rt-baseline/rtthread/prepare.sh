#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../../.." && pwd)
workspace=${RT_BASELINE_WORKSPACE:-"$repo_root/tmp"}
source_root=${RTTHREAD_SOURCE_ROOT:-"$workspace/rt-thread-v5.2.2"}
python_packages=${RTTHREAD_PYTHON_PACKAGES:-"$workspace/rtthread-python"}
source_commit=ddf52e2cdd977f14fc04035c88672ac204aec713

for command in git python3 qemu-system-aarch64; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing RT-Thread baseline prerequisite: $command" >&2
        exit 2
    fi
done

"$script_dir/../common/prepare_toolchain.sh"
mkdir -p -- "$workspace"
if [[ ! -d "$source_root/.git" ]]; then
    git clone --branch v5.2.2 --depth 1 --filter=blob:none --no-checkout \
        https://github.com/RT-Thread/rt-thread.git "$source_root"
    git -C "$source_root" sparse-checkout init --cone
    git -C "$source_root" sparse-checkout set \
        bsp/qemu-virt64-aarch64 components examples/utest include libcpu src tools
    git -C "$source_root" checkout --detach "$source_commit"
fi

if [[ $(git -C "$source_root" rev-parse HEAD) != "$source_commit" ]] ||
    [[ $(git -C "$source_root" describe --tags --exact-match) != v5.2.2 ]] ||
    [[ -n $(git -C "$source_root" status --porcelain=v1 --untracked-files=all) ]]; then
    echo "RT-Thread source is not the clean pinned v5.2.2 release" >&2
    exit 2
fi
for required in \
    "$source_root/bsp/qemu-virt64-aarch64/.config" \
    "$source_root/components/SConscript" \
    "$source_root/examples/utest/testcases/mm/Kconfig"; do
    if [[ ! -f "$required" ]]; then
        echo "RT-Thread sparse checkout is incomplete: $required" >&2
        exit 2
    fi
done

mkdir -p -- "$python_packages"
python3 -m pip install --disable-pip-version-check --upgrade \
    --target "$python_packages" 'scons==4.10.1' 'kconfiglib==14.1.0'

echo "native RT-Thread baseline environment ready"
echo "  source: $source_root"
echo "  scons: $python_packages/bin/scons"
