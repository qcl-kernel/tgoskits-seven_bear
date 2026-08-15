# Native RT-Thread real-time reference

This directory retains one idle and one sustained CPU-stress run of the native
RT-Thread v5.2.2 baseline on QEMU `virt`. It is a level-1 native baseline: no
AxVisor, guest boot, virtual network, or IVC/1 endpoint is involved.

Both cases use one Cortex-A53, a 1 kHz RT-Thread tick, a 1 ms periodic
workload, 100 discarded warm-up expirations, and exactly 10,000 retained
deadlines. Values below are nanoseconds, except for duration.

| Workload | Metric | p50 | p90 | p99 | p99.9 | Max | Actual duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| idle | periodic wake lateness | 67,472 | 106,208 | 179,792 | 254,896 | 441,824 | 10,477,395 us |
| idle | timer-to-task dispatch | 10,256 | 26,768 | 43,696 | 85,024 | 143,984 | 10,477,395 us |
| CPU stress | periodic wake lateness | 60,320 | 98,496 | 190,784 | 348,912 | 4,848,912 | 10,421,582 us |
| CPU stress | timer-to-task dispatch | 10,272 | 24,736 | 45,408 | 111,216 | 199,312 | 10,421,582 us |

Both cases reported zero measured and warm-up timer misses and zero early
wakes. Tick-hook accounting observed 1,000 permille idle time in the idle case
and 1,000 permille stress time in the CPU-stress case; the stress task
completed 1,643,799 work blocks (156,184/s). RT-Thread's 1 ms tick granularity
rounds the short periodic task's own share to zero, so that field is retained
as measured rather than replaced with an estimate.

## Reproduction and provenance

The source attestation pins RT-Thread tag `v5.2.2` at commit
`ddf52e2cdd977f14fc04035c88672ac204aec713`. The runner uses the upstream
`qemu-virt64-aarch64` BSP and the SHA-256-pinned Arm GNU Toolchain 13.2.Rel1.

```sh
bash competition/rt-baseline/rtthread/prepare.sh
bash competition/rt-baseline/rtthread/run.sh all \
  tmp/competition/rt-baseline/rtthread/reproduction-1
```

[`idle-summary.json`](idle-summary.json),
[`stress-summary.json`](stress-summary.json), and
[`source-provenance.json`](source-provenance.json) contain the validated
configuration, aggregate results, build/binary hashes, tool versions, and
post-run clean-source attestation. The exact console and build logs are
retained as deterministic `gzip -n -9` streams:

| Workload | Artifact | Gzip bytes | Gzip SHA-256 | Original bytes | Original SHA-256 |
| --- | --- | ---: | --- | ---: | --- |
| idle | [`idle-qemu.log.gz`](idle-qemu.log.gz) | 972 | `34cf4ee3b7dfd06f6f14b5b3a15f0fa40e7861161128d621eaf5c44fedb8201c` | 2,575 | `5a662b9327e1844c18291b2c485af0fc76b0653fc313580d376334d26101000c` |
| idle | [`idle-build.log.gz`](idle-build.log.gz) | 1,903 | `25833c8e63120f6361d5d3a07901e459343b062941b4ffeeff095571b88d46c1` | 12,147 | `5e3f801870df17088e2d6d3867da9c9767865749b99f16d52237dff6efeadde6` |
| CPU stress | [`stress-qemu.log.gz`](stress-qemu.log.gz) | 999 | `49d7ef4b196ea4051d7a1189fb92efae267e402ff6f6d1f38e4b120aee8ccfe9` | 2,646 | `a34aaebb94160ce97a5ee6d4a7c8a3d7072046393802765fc7aef8f079cbed75` |
| CPU stress | [`stress-build.log.gz`](stress-build.log.gz) | 1,907 | `74f6dfe28ced22ad8f9cea4e7034c62adc17070debd0eca53f3b8bc559ad195b` | 12,225 | `81dadfd5ac0a9cfe73fc97dd0fdac3b683940b83eb75fe8333d15ba9cc572a97` |

Verify retained file bytes with `(cd competition/results/native-rtthread-reference && sha256sum -c checksums.sha256)`.

This is a single QEMU/WSL2 capture per workload, not an RK3588 result, a
long-duration soak, or a hardware worst-case bound.
