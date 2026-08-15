# Native FreeRTOS baseline

This application runs FreeRTOS directly on Bao's `qemu-aarch64-virt`
bare-metal runtime. It implements the competition's native RTOS control, not an
AxVisor guest or IVC/1 endpoint.

The benchmark uses FreeRTOS's 1 kHz virtual-timer tick as its absolute 1 ms
period. The application tick hook records the architected-counter timestamp in
interrupt context and notifies priority-7 `rtperiod`; the task records its
observation before doing other work. After 100 warm-up expirations it retains
10,000 wake-lateness and timer-to-task-dispatch samples. The stress build adds
continuously runnable priority-1 `rtstress`. FreeRTOS 64-bit run-time counters
independently verify the idle and stress CPU shares.

## Prepare and run

Required host tools are Git, Make, Python 3, QEMU AArch64, `curl`, `tar`, and
`xz`. Preparation pins `freertos-over-bao`, FreeRTOS-Kernel, and Bao's
bare-metal runtime, then verifies the SHA-256-pinned Arm GNU Toolchain
13.2.Rel1.

```sh
bash competition/rt-baseline/freertos/prepare.sh
bash competition/rt-baseline/freertos/run.sh all \
  tmp/competition/rt-baseline/freertos/run-1
```

The runner copies the owned application into a fresh evidence directory,
builds both workloads without patching upstream source, runs them on one
Cortex-A53, captures exact commands and artifacts, performs a post-run
clean-source attestation, and invokes the shared analyzer. Existing evidence
is never overwritten.

The retained result and limitations are documented in
[`results/native-freertos-reference`](../../results/native-freertos-reference/).
