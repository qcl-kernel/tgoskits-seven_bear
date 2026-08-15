# RT-Thread/FreeRTOS Guest/IVC QEMU validation

This directory records the compact, machine-readable result of four validation
campaigns run on 2026-08-15 (Asia/Shanghai). The campaigns used AxVisor on
QEMU/AArch64 TCG, a two-vCPU Linux controller, and one single-vCPU RTOS
endpoint. The tracked worktree was clean at commit `ec3c363b1a61956069365a06c262091ce847b335`.

All four strict analyzers returned success:

| Endpoint | Profile | Applied | Duplicate / dropped ACK | Controller ACK | Retransmit / recovery |
| --- | --- | ---: | ---: | ---: | ---: |
| RT-Thread v5.2.2 | normal | 100 | 0 / 0 | 100 | 0 / 0 |
| RT-Thread v5.2.2 | ACK-loss | 100 | 20 / 20 | 100 | 20 / 20 |
| FreeRTOS | normal | 100 | 0 / 0 | 100 | 0 / 0 |
| FreeRTOS | ACK-loss | 100 | 20 / 20 | 100 | 20 / 20 |

The four `*-qemu.log.gz` files are deterministic `gzip -n -9` copies of the
complete console/build logs. [`validation.json`](validation.json) binds each
compressed artifact to its uncompressed SHA-256, analyzer summary, guest
binary, source pins, controller rootfs, and exact run directory.
[`SHA256SUMS`](SHA256SUMS) covers every tracked file in this directory except
the checksum list itself.

This is clean-commit QEMU evidence for RT-Thread/FreeRTOS Guest boot,
VirtIO/IP, IVC/1 normal operation, and deterministic ACK-loss recovery. It is
not an RK3588 latency result, a physical-board result, or a StarryOS + RTOS
combination result. Reproduction commands and the full support boundary are in
[`../../ivc/README.md`](../../ivc/README.md).
