# Orange Pi 5 Plus RT-Thread / FreeRTOS Guest IVC（2026-08-18）

本目录保存两次真实 RK3588/AxVisor 板测：双 vCPU StarryOS 控制器分别与
RT-Thread、FreeRTOS 客体通过隔离的 VirtIO Ethernet + UDP/IPv4 运行 IVC/1。
每次发送 20 条神经网络控制命令；RTOS 执行动作并回传 STATUS/ACK，随后通过
PSCI `SYSTEM_OFF` 停止。AxVisor 在两个证据客体停止后快照 StarryOS 块设备，Linux
恢复后再做 fsck、CSV 三方哈希和 ext4 读写挂载检查。

| RTOS 客体 | IVC 结果 | transport p50 / p99 / max | full-loop p50 / p99 / max | 生命周期 |
| --- | --- | ---: | ---: | --- |
| RT-Thread | 20/20；0 error/timeout/retry/duplicate | 2,265 / 16,672 / 36,924 µs | 2,285 / 16,693 / 50,406 µs | PSCI off、Starry done、snapshot fsck clean、Linux rw restored |
| FreeRTOS | 20/20；0 error/timeout/retry/duplicate | 1,910 / 16,627 / 37,588 µs | 1,929 / 16,647 / 50,663 µs | PSCI off、Starry done、snapshot fsck clean、Linux rw restored |

两次运行都使用板卡 `bf61f4d4a1d994ad`，物理 Linux root 以稳定 PARTUUID 传入；
`summary.json` 中的 `rtos.name` 分别为 `rt-thread` 和 `freertos`，不能由通用
Zephyr marker 代替。`metadata.json` 记录客体二进制、StarryOS、DTB、rootfs、模型、
原始日志和 CSV 的 SHA-256。该批次是当前工作树的移植 smoke，不冒充此前 clean commit
上的正式长时性能活动；它补足的是两种 RTOS 在 Orange Pi 5 Plus 上的真实 Guest/IVC
可运行性和完整收割链路。

复核：

```sh
for run in rtthread freertos; do
  (cd "competition/results/orangepi-rtos-ivc-20260818/$run" && \
    sha256sum -c checksums.sha256)
done
```
