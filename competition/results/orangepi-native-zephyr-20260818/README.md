# Orange Pi 5 Plus 原生 Zephyr 实时基线（2026-08-18）

本目录保存 Zephyr 4.3.0 直接运行在 Orange Pi 5 Plus（RK3588）上的
idle、CPU stress 和约 30 分钟 soak 实测。测量 CPU 为 Cortex-A55 CPU0，时钟源为
24 MHz AArch64 architected counter；该链路不经过 AxVisor，用作同板原生 RTOS
补充对照，而不是虚拟化数据。

| 场景 | 样本 / 周期 | CPU 负载 | wake lateness p99 / max | timer→task p99 / max | miss |
| --- | --- | --- | ---: | ---: | ---: |
| idle | 10,000 / 1 ms | idle 999‰ | 2,875 / 4,000 ns | 1,458 / 2,625 ns | 0 |
| CPU stress | 10,000 / 1 ms | non-idle 1000‰；stress 999‰；131,716 blocks/s | 2,875 / 4,208 ns | 1,458 / 2,916 ns | 0 |
| CPU stress soak | 10,000 / 180 ms；采集窗 1,817.822 s | non-idle 1000‰；stress 999‰；132,282 blocks/s | 3,291 / 4,291 ns | 2,041 / 2,916 ns | 0 |

每个子目录均保留原始串口日志、压缩日志、构建日志、运行参数、源码溯源、板卡电源状态、
Linux 运行前后健康检查、恢复日志、机器可读 `summary.json` 和逐文件
`checksums.sha256`。测量阶段不输出串口；统计值由板端对 10,000 个样本按
nearest-rank 计算，结束后重复发送三份记录。这里没有把 20,000 个逐样本数值另存为
CSV，因此应把 `console.log` 称为原始串口证据，而不是逐样本数据集。

CPU-stress 短测中，串口复播的一份 wake-result 记录受字符交错影响；分析器仍从完整且
一致的记录得到结果，并在 `summary.json` 的 `serial_replays` 中保留该事实。idle 与 soak
的两类指标均有三份完整复播。

复核：

```sh
for run in idle cpu-stress soak; do
  (cd "competition/results/orangepi-native-zephyr-20260818/$run" && \
    sha256sum -c checksums.sha256)
done
```

