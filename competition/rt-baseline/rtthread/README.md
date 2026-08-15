# Native RT-Thread baseline

This application runs RT-Thread v5.2.2 directly on the upstream
`qemu-virt64-aarch64` BSP. It implements the competition's native RTOS control,
not an AxVisor guest or IVC/1 endpoint.

The benchmark uses the 1 kHz RT-Thread tick as its absolute 1 ms period. A tick
hook records the architected-counter timestamp in interrupt context and wakes
priority-1 `rtperiod`; the task records its observation before doing other
work. After 100 warm-up expirations it retains 10,000 wake-lateness and
timer-to-task-dispatch samples. The stress build adds continuously runnable
priority-20 `rtstress`; lower numeric RT-Thread priority is higher urgency.

RT-Thread v5.2.2's generic CPU tracer does not classify kernel idle time on
this BSP, so the benchmark's tick hook accounts the currently scheduled thread
instead. This has 1 ms resolution: the short periodic task may round to zero
permille, while idle versus sustained stress remains directly verified.

## Prepare and run

Required host tools are Git, Python 3, QEMU AArch64, `curl`, `tar`, `xz`, and a
working Python `pip`. Preparation pins the upstream commit, installs pinned
SCons/Kconfiglib under ignored `tmp/`, and verifies the SHA-256-pinned Arm GNU
Toolchain 13.2.Rel1.

```sh
bash competition/rt-baseline/rtthread/prepare.sh
bash competition/rt-baseline/rtthread/run.sh all \
  tmp/competition/rt-baseline/rtthread/run-1
```

The runner stages a copy of the clean upstream source, overlays only the owned
application/configuration, builds both workloads, runs them on one Cortex-A53,
captures exact commands and artifacts, performs a post-run clean-source
attestation, and invokes the shared analyzer. Existing evidence is never
overwritten.

The retained result and limitations are documented in
[`results/native-rtthread-reference`](../../results/native-rtthread-reference/).
