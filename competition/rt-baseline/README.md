# Native RTOS baselines

This directory contains three reproducible native/equivalent RTOS controls for
the competition real-time comparison. Each control runs directly on QEMU,
without AxVisor, and measures a 1 ms periodic path under both idle and sustained
lower-priority CPU load.

| RTOS | Native baseline | AxVisor guest boot in this competition path | IVC/1 endpoint |
| --- | --- | --- | --- |
| Zephyr v4.3.0 | validated | validated | validated |
| RT-Thread v5.2.2 | validated | validated separately on QEMU/AArch64 | validated separately |
| FreeRTOS Kernel `f1043c49…` | validated | validated separately on QEMU/AArch64 | validated separately |

“Native baseline” is deliberately narrower than general guest support. Old VM
TOML files or a native QEMU image do not prove that the owned benchmark boots
under AxVisor, and neither proves IP/virtio-net or IVC/1 interoperability.
The independent Guest/IVC implementation and its four strict campaigns are
documented in [`../ivc/README.md`](../ivc/README.md); those results are not
derived from the measurements in this directory.

The three implementations share statistics and miss-accounting code from
[`common`](common/), but each analyzer preserves its actual RTOS priority,
timer, load-accounting, platform, source, and toolchain boundary.

## Commands

```sh
# Zephyr
bash competition/rt-baseline/zephyr/prepare.sh
bash competition/rt-baseline/zephyr/run.sh all

# RT-Thread
bash competition/rt-baseline/rtthread/prepare.sh
bash competition/rt-baseline/rtthread/run.sh all

# FreeRTOS
bash competition/rt-baseline/freertos/prepare.sh
bash competition/rt-baseline/freertos/run.sh all
```

Each runner refuses to overwrite evidence. Use a distinct output directory for
every campaign. The retained reference captures are under
[`results/native-zephyr-reference`](../results/native-zephyr-reference/),
[`results/native-rtthread-reference`](../results/native-rtthread-reference/),
and
[`results/native-freertos-reference`](../results/native-freertos-reference/).

Run the shared contract and negative-analyzer tests with:

```sh
bash competition/rt-baseline/common/tests/run.sh
```

All three are equivalent QEMU/AArch64 controls, not Orange Pi 5 Plus bare-metal
results. Their CPU model, RTOS mechanisms, timer paths, and host environment
must remain visible when comparing numerical results.
