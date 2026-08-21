#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repository=$(cd -- "$script_dir/../.." && pwd)
python_command=${PYTHON:-python3}
compiler=${CC:-cc}

for command in "$python_command" "$compiler" git; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "missing competition host-validation command: $command" >&2
        exit 2
    fi
done

cd -- "$repository"

"$python_command" -m unittest \
    competition.ivc.tests.test_rtos_guest_contract \
    competition.ivc.tests.test_qemu_config \
    competition.ivc.tests.test_validate_guest_elf \
    competition.ivc.tests.test_analyze_qemu
bash competition/ivc/common/run-host-tests.sh
bash competition/ivc/zephyr/run-host-tests.sh
bash competition/rt-baseline/common/tests/run.sh
"$python_command" -m unittest discover \
    -s competition/rt-baseline/rtthread/tests -p 'test_*.py'
"$python_command" -m unittest discover \
    -s competition/evidence/tests -p 'test_*.py'
"$python_command" -m unittest discover \
    -s competition/vision/tests -p 'test_*.py'
"$python_command" competition/evidence/verify_delivery.py

echo "COMPETITION_HOST_VALIDATION_PASS rtos_guest_tests=36 vision_contract=pass evidence_sets=3 qemu_logs=5 archive_files=113"
