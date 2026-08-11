#!/usr/bin/env bash

set -euo pipefail

workspace=/mnt/c/Users/10469/Workspace/starryos_t/tgoskits-rt-ivc
expected_source=069c911c1de02cecdc0c1fe891f5d5a288065ef0
result_root=$workspace/tmp/competition/current-source-069c911c1

cd "$workspace"
actual_source=$(git rev-parse HEAD)
if [[ "$actual_source" != "$expected_source" ]]; then
    echo "Source changed before IVC board run: expected=$expected_source actual=$actual_source" >&2
    exit 1
fi
mkdir -p "$result_root"
export ORANGEPI_AXVISOR_HOST_ROOT=PARTUUID=5874edd8-1582-a144-a298-b139acd7b0e6
export ORANGEPI_SSH_TARGET=orangepi@192.168.31.33
export ORANGEPI_SSH_IDENTITY=$HOME/.ssh/orangepi_automation

bash competition/ivc/run-orangepi-5-plus.sh fault-restart \
    --result-dir "$result_root/ivc" \
    --timeout 900 \
    --restore-linux \
    2>&1 | tee "$result_root/run-ivc-wrapper.log"
