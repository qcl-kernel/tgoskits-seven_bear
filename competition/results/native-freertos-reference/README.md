# Native FreeRTOS real-time reference

This directory retains one idle and one sustained CPU-stress run of the native
FreeRTOS AArch64 baseline on QEMU `virt`. It is a level-1 native baseline: no
AxVisor, guest boot, virtual network, or IVC/1 endpoint is involved.

Both cases use one Cortex-A53, a 1 kHz FreeRTOS tick, a 1 ms periodic
workload, 100 discarded warm-up expirations, and exactly 10,000 retained
deadlines. Values below are nanoseconds, except for duration.

| Workload | Metric | p50 | p90 | p99 | p99.9 | Max | Actual duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle | periodic wake lateness | 67,904 | 107,408 | 209,136 | 556,112 | 4,370,096 | 10,477,549 us |
| idle | timer-to-task dispatch | 16,736 | 26,880 | 62,480 | 160,448 | 642,816 | 10,477,549 us |
| CPU stress | periodic wake lateness | 66,208 | 103,872 | 201,888 | 519,664 | 3,483,376 | 10,479,159 us |
| CPU stress | timer-to-task dispatch | 15,360 | 25,488 | 58,144 | 133,488 | 475,872 | 10,479,159 us |

Both cases reported zero measured and warm-up timer misses and zero early
wakes. FreeRTOS 64-bit run-time counters observed 983 permille idle time in the
idle case and 984 permille stress time in the CPU-stress case; the stress task
completed 8,384,858 work blocks (792,283/s).

## Reproduction and provenance

The source attestation pins `freertos-over-bao` at
`cb9112f982c2768872536b811e013254d0184811`, FreeRTOS-Kernel at
`f1043c49d59944353291654c175852bd17b34f99`, and Bao's bare-metal runtime at
`c50068084212ef33115a4c05f9f714cc637f30bc`. The runner uses the Bao
`qemu-aarch64-virt` platform and the SHA-256-pinned Arm GNU Toolchain
13.2.Rel1.

```sh
bash competition/rt-baseline/freertos/prepare.sh
bash competition/rt-baseline/freertos/run.sh all \
  tmp/competition/rt-baseline/freertos/reproduction-1
```

[`idle-summary.json`](idle-summary.json),
[`stress-summary.json`](stress-summary.json), and
[`source-provenance.json`](source-provenance.json) contain the validated
configuration, aggregate results, build/binary hashes, tool versions, and
post-run clean-source attestation. The exact console and build logs are
retained as deterministic `gzip -n -9` streams:

| Workload | Artifact | Gzip bytes | Gzip SHA-256 | Original bytes | Original SHA-256 |
| --- | --- | ---: | --- | ---: | --- |
| idle | [`idle-qemu.log.gz`](idle-qemu.log.gz) | 628 | `249f592dc7c42684a7ef612c2c90bd918532e91bc63813c784ae953913edf12a` | 1,337 | `4faf4178c251ab49203737fc8ded93fc4778d8c3fdd8d7d853ed23272e3a97d5` |
| idle | [`idle-build.log.gz`](idle-build.log.gz) | 1,955 | `f6dc178aac1e4d909e529f2676408df597afa5d6ffa6a3d1aef5c4715a287f42` | 61,788 | `ff3b7e013d24cf7cfe22d87dd97b7031b4addc1a6dd41310e8caf36aacd765f1` |
| CPU stress | [`stress-qemu.log.gz`](stress-qemu.log.gz) | 656 | `77f08f1b33c9ce5599b93182bc0cf6bc2456799906eef65d15c9636a7e308bc5` | 1,407 | `cf684b33aaf17176c214118ab2c4c6dea488c605b3d809b32eacc486ba9f1b41` |
| CPU stress | [`stress-build.log.gz`](stress-build.log.gz) | 2,036 | `9e6c4919ac6fac7359df3ae860496bdc9a79b8b9a080dbc166c585da15ac2c99` | 63,189 | `9abaf9eb922a160ffe70eae7f0bf34f0bbcc4ae41f6a245d7e4b4bcbf42b3645` |

Verify retained file bytes with `(cd competition/results/native-freertos-reference && sha256sum -c checksums.sha256)`.

This is a single QEMU/WSL2 capture per workload, not an RK3588 result, a
long-duration soak, or a hardware worst-case bound.
