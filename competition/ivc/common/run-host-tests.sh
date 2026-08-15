#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build_dir=${IVC_COMMON_TEST_BUILD_DIR:-"$script_dir/../../../tmp/ivc-common-tests"}
compiler=${CC:-cc}

mkdir -p -- "$build_dir"
"$compiler" -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
    -I"$script_dir" \
    "$script_dir/virtio_net_mmio.c" \
    "$script_dir/tests/virtio_net_mmio_test.c" \
    -o "$build_dir/virtio-net-mmio-test"
"$build_dir/virtio-net-mmio-test"

"$compiler" -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
    -I"$script_dir" \
    -I"$script_dir/../zephyr/src" \
    "$script_dir/../zephyr/src/protocol.c" \
    "$script_dir/../zephyr/src/endpoint.c" \
    "$script_dir/ivc_rtos_server.c" \
    "$script_dir/tests/ivc_rtos_server_test.c" \
    -o "$build_dir/ivc-rtos-server-test"
"$build_dir/ivc-rtos-server-test"
