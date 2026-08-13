#!/usr/bin/env bash

set -euo pipefail

expected_source=598b357f92c848e669c12cca830a4d08d0a50e36
result_root=${RESULT_ROOT:?set RESULT_ROOT to a new directory on a Linux filesystem}

test "$(git rev-parse HEAD)" = "$expected_source"
test -z "$(git status --porcelain=v1)"
test ! -e "$result_root"

env \
  ORANGEPI_AXVISOR_HOST_ROOT="${ORANGEPI_AXVISOR_HOST_ROOT:?}" \
  ORANGEPI_SSH_TARGET="${ORANGEPI_SSH_TARGET:?}" \
  ORANGEPI_SSH_IDENTITY="${ORANGEPI_SSH_IDENTITY:?}" \
  TGOS_BOARD_POWER_CONFIG="${TGOS_BOARD_POWER_CONFIG:?}" \
  ORANGEPI_POWER_PYTHON="${ORANGEPI_POWER_PYTHON:?}" \
  bash competition/ivc/run-orangepi-5-plus.sh fault-restart \
    --result-dir "$result_root" \
    --timeout 900 \
    --restore-linux \
    --require-clean
